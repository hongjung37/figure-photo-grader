from __future__ import annotations

import base64
import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import ExifTags, Image
from PIL.TiffImagePlugin import IFDRational
from pydantic import ValidationError

import photo_analyzer
import photo_dashboard
from photo_analyzer import PhotoAnalysis, analyze_with_gemini, prepare_photo, save_analysis
from photo_tag_schema import AESTHETIC_TAG_OPTIONS, AestheticTags, get_score_grade


class PhotoAnalyzerTests(unittest.TestCase):
    def _make_jpeg(self, path: Path, *, with_exif: bool = False) -> None:
        image = Image.new("RGB", (16, 12), (90, 120, 150))
        save_options = {"format": "JPEG"}
        if with_exif:
            exif = Image.Exif()
            exif[271] = "Example Camera"  # Make
            exif[272] = "Model X"  # Model
            exif[306] = "2026:01:02 03:04:05"  # DateTime; must be omitted
            exif[315] = "Private Owner"  # Artist; must be omitted
            exif[34853] = {
                1: "N",
                2: (IFDRational(37, 1), IFDRational(30, 1), IFDRational(0, 1)),
                3: "E",
                4: (IFDRational(127, 1), IFDRational(0, 1), IFDRational(0, 1)),
            }  # GPS IFD; must be omitted
            exif[34665] = {
                33434: IFDRational(1, 125),  # ExposureTime
                33437: IFDRational(56, 10),  # FNumber
                34855: 400,  # ISOSpeedRatings
            }
            save_options["exif"] = exif
        image.save(path, **save_options)

    def _valid_analysis(self) -> PhotoAnalysis:
        return PhotoAnalysis(
            composition_score=8,
            composition_notes="주제가 잘 배치되었습니다.",
            lighting_score=7.5,
            lighting_notes="부드러운 빛이 사용되었습니다.",
            color_score=8,
            color_notes="색 조화가 자연스럽습니다.",
            technique_score=7,
            technique_notes="초점이 안정적입니다.",
            final_score=7.8,
            final_reason="전체 완성도가 좋습니다.",
            strengths=["안정된 구도"],
            improvements=["배경을 단순화해 보세요."],
            aesthetic_tags=AestheticTags.empty().model_copy(
                update={
                    "viewpoint": ["정면"],
                    "composition_space": ["삼분할 구도"],
                    "mood": ["고요함"],
                }
            ),
        )

    def test_exif_allowlist_is_embedded_but_private_metadata_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "sample.jpg"
            self._make_jpeg(image_path, with_exif=True)
            photo = prepare_photo(image_path)

            self.assertEqual(photo.safe_exif["Make"], "Example Camera")
            self.assertEqual(photo.safe_exif["Model"], "Model X")
            self.assertAlmostEqual(photo.safe_exif["ExposureTime"], 1 / 125)
            self.assertAlmostEqual(photo.safe_exif["FNumber"], 5.6)
            self.assertEqual(photo.safe_exif["ISOSpeedRatings"], 400)
            self.assertNotIn("DateTime", photo.safe_exif)
            self.assertNotIn("Artist", photo.safe_exif)

            with Image.open(BytesIO(photo.upload_bytes)) as uploaded_image:
                uploaded_exif = uploaded_image.getexif()
                self.assertNotIn(34853, uploaded_exif)
                self.assertNotIn(306, uploaded_exif)
                self.assertNotIn(315, uploaded_exif)
                uploaded_ifd = uploaded_exif.get_ifd(photo_analyzer.EXIF_IFD_ID)
                uploaded_fields = {
                    ExifTags.TAGS.get(tag_id): value
                    for tag_id, value in uploaded_ifd.items()
                }
                self.assertAlmostEqual(float(uploaded_fields["ExposureTime"]), 1 / 125)
                self.assertAlmostEqual(float(uploaded_fields["FNumber"]), 5.6)
                self.assertEqual(uploaded_fields["ISOSpeedRatings"], 400)

    def test_gemini_request_includes_safe_settings_and_loads_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            image_path = directory / "sample.jpg"
            env_path = directory / ".env"
            env_path.write_text("GEMINI_API_KEY=unit-test-key\n", encoding="utf-8")
            self._make_jpeg(image_path, with_exif=True)
            photo = prepare_photo(image_path)

            with patch.object(photo_analyzer, "ENV_FILE_PATH", env_path), patch.dict(os.environ):
                os.environ.pop("GEMINI_API_KEY", None)
                with patch.object(photo_analyzer.genai, "Client") as client_factory:
                    client = client_factory.return_value
                    client.interactions.create.return_value.output_text = (
                        self._valid_analysis().model_dump_json()
                    )
                    result = analyze_with_gemini(photo)

                self.assertEqual(result.final_score, 7.8)
                client_factory.assert_called_once_with(api_key="unit-test-key")
                request = client.interactions.create.call_args.kwargs
                prompt = request["input"][0]["text"]
                self.assertIn('"ExposureTime": 0.008', prompt)
                self.assertIn('"FNumber": 5.6', prompt)
                self.assertIn('"ISOSpeedRatings": 400', prompt)
                self.assertNotIn("2026:01:02 03:04:05", prompt)
                self.assertIn("aesthetic_tags", prompt)
                self.assertIn("정면, 측면, 후면", prompt)
                self.assertIn("0~3개 선택하세요", prompt)
                schema = request["response_format"]["schema"]
                self.assertIn("aesthetic_tags", schema["required"])
                self.assertEqual(
                    set(schema["$defs"]["AestheticTags"]["required"]),
                    set(AestheticTags.model_fields),
                )
                tag_properties = schema["$defs"]["AestheticTags"]["properties"]
                for category_key, allowed_tags in AESTHETIC_TAG_OPTIONS.items():
                    self.assertEqual(
                        tag_properties[category_key]["items"]["enum"],
                        list(allowed_tags),
                    )

                sent_image = base64.b64decode(request["input"][1]["data"])
                with Image.open(BytesIO(sent_image)) as uploaded_image:
                    uploaded_exif = uploaded_image.getexif()
                    self.assertNotIn(34853, uploaded_exif)
                    sent_ifd = uploaded_exif.get_ifd(photo_analyzer.EXIF_IFD_ID)
                sent_names = {ExifTags.TAGS.get(tag_id) for tag_id in sent_ifd}
                self.assertTrue(
                    {"ExposureTime", "FNumber", "ISOSpeedRatings"} <= sent_names
                )

    def test_mpo_input_is_reencoded_as_jpeg(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "sample.mpo"
            self._make_jpeg(image_path)
            with Image.open(image_path) as source:
                source.format = "MPO"
                with patch.object(photo_analyzer.Image, "open", return_value=source):
                    photo = prepare_photo(image_path)

            self.assertEqual(photo.image_format, "MPO")
            self.assertEqual(photo.upload_mime_type, "image/jpeg")
            with Image.open(BytesIO(photo.upload_bytes)) as uploaded_image:
                self.assertEqual(uploaded_image.format, "JPEG")

    def test_scores_outside_zero_to_ten_are_rejected(self) -> None:
        payload = self._valid_analysis().model_dump()
        payload["final_score"] = 10.1
        with self.assertRaises(ValidationError):
            PhotoAnalysis.model_validate(payload)

    def test_unknown_or_excessive_aesthetic_tags_are_rejected(self) -> None:
        payload = self._valid_analysis().model_dump()
        payload["aesthetic_tags"]["viewpoint"] = ["정면", "측면", "후면", "사선"]
        with self.assertRaises(ValidationError):
            PhotoAnalysis.model_validate(payload)

        payload["aesthetic_tags"]["viewpoint"] = ["파노라마 시점"]
        with self.assertRaises(ValidationError):
            PhotoAnalysis.model_validate(payload)

    def test_legacy_analysis_without_tag_field_uses_empty_tag_defaults(self) -> None:
        payload = self._valid_analysis().model_dump(exclude={"aesthetic_tags"})
        restored = PhotoAnalysis.model_validate(payload)
        self.assertEqual(restored.aesthetic_tags.viewpoint, [])
        self.assertEqual(restored.aesthetic_tags.narrative_implication, [])

    def test_validated_analysis_and_safe_exif_are_saved_to_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            image_path = directory / "sample.jpg"
            database_path = directory / "analysis.sqlite3"
            self._make_jpeg(image_path, with_exif=True)
            photo = prepare_photo(image_path)

            record_id = save_analysis(database_path, photo, "test-model", self._valid_analysis())
            self.assertGreater(record_id, 0)

            with closing(sqlite3.connect(database_path)) as connection:
                row = connection.execute(
                    "SELECT exif_json, analysis_json FROM photo_analyses WHERE id = ?",
                    (record_id,),
                ).fetchone()
                stored_tags = connection.execute(
                    "SELECT category_key, tag FROM photo_analysis_tags WHERE analysis_id = ? ORDER BY category_key",
                    (record_id,),
                ).fetchall()
                catalog_count = connection.execute(
                    "SELECT COUNT(*) FROM photo_tag_catalog"
                ).fetchone()[0]
            self.assertIsNotNone(row)
            exif_data = json.loads(row[0])
            analysis_data = json.loads(row[1])
            self.assertNotIn("GPSInfo", exif_data)
            self.assertNotIn("DateTime", exif_data)
            self.assertEqual(analysis_data["final_score"], 7.8)
            self.assertEqual(
                stored_tags,
                [("composition_space", "삼분할 구도"), ("mood", "고요함"), ("viewpoint", "정면")],
            )
            self.assertGreater(catalog_count, 0)


    def test_score_grading_benchmark_tiers(self) -> None:
        self.assertEqual(get_score_grade(9.5), "프로사진작가 및 전문가급")
        self.assertEqual(get_score_grade(9.0), "프로사진작가 및 전문가급")
        self.assertEqual(get_score_grade(8.9), "매우 우수")
        self.assertEqual(get_score_grade(8.0), "매우 우수")
        self.assertEqual(get_score_grade(7.5), "우수")
        self.assertEqual(get_score_grade(7.0), "우수")
        self.assertEqual(get_score_grade(6.8), "보통 (일반 스냅)")
        self.assertEqual(get_score_grade(5.0), "보통 (일반 스냅)")
        self.assertEqual(get_score_grade(4.9), "개선 필요 (기초 미흡)")
        self.assertEqual(get_score_grade(0.0), "개선 필요 (기초 미흡)")

    def test_prompt_enforces_pros_cons_and_grading_benchmarks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "sample.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)
            prompt = photo_analyzer._build_prompt(photo)

            self.assertIn("7.0 ~ 7.9: [우수]", prompt)
            self.assertIn("8.0 ~ 8.9: [매우 우수]", prompt)
            self.assertIn("9.0 ~ 10.0: [프로사진작가 및 전문가급]", prompt)
            self.assertIn("[장점]", prompt)
            self.assertIn("[단점]", prompt)
            self.assertIn("과도하게 칭찬하거나 호의적으로만 평가하지 마세요", prompt)


    def test_model_presets_tiers(self) -> None:
        self.assertIn("lite", photo_analyzer.MODEL_PRESETS)
        self.assertIn("standard", photo_analyzer.MODEL_PRESETS)
        self.assertIn("pro", photo_analyzer.MODEL_PRESETS)
        self.assertEqual(photo_analyzer.MODEL_PRESETS["lite"], "gemini-3.1-flash-lite")
        self.assertEqual(photo_analyzer.MODEL_PRESETS["standard"], "gemini-3.5-flash-lite")
        self.assertEqual(photo_analyzer.MODEL_PRESETS["pro"], "gemini-3.8-flash")
        self.assertIn("Flash-Lite 3.1", photo_dashboard.DASHBOARD_HTML)
        self.assertIn("Flash-Lite 3.5", photo_dashboard.DASHBOARD_HTML)
        self.assertIn("Flash 3.8", photo_dashboard.DASHBOARD_HTML)

    def test_aesthetic_mood_tags_registered(self) -> None:
        self.assertIn("차가움", AESTHETIC_TAG_OPTIONS["mood"])
        self.assertIn("따뜻함", AESTHETIC_TAG_OPTIONS["mood"])
        self.assertIn("쿨톤(차가움)", AESTHETIC_TAG_OPTIONS["color_impression"])
        self.assertIn("웜톤(따뜻함)", AESTHETIC_TAG_OPTIONS["color_impression"])

        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "test.sqlite3"
            with closing(sqlite3.connect(db_path)) as conn, conn:
                conn.execute("CREATE TABLE photo_analyses (id INTEGER PRIMARY KEY)")
            photo_dashboard.ensure_db_columns(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                tags = [r[0] for r in conn.execute("SELECT tag FROM photo_tag_catalog WHERE category_key = 'mood'").fetchall()]
                self.assertIn("차가움", tags)
                self.assertIn("따뜻함", tags)
                self.assertIn("청량함", tags)

    def test_blind_tournament_ui_and_status_update(self) -> None:
        self.assertIn("tournament-modal", photo_dashboard.DASHBOARD_HTML)
        self.assertIn("openTournamentModal", photo_dashboard.DASHBOARD_HTML)
        self.assertIn("startTournament", photo_dashboard.DASHBOARD_HTML)
        self.assertIn("selectTournamentWinner", photo_dashboard.DASHBOARD_HTML)
        self.assertIn("블라인드 토너먼트", photo_dashboard.DASHBOARD_HTML)

        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "test.sqlite3"
            with closing(sqlite3.connect(db_path)) as conn, conn:
                conn.execute("CREATE TABLE photo_analyses (id INTEGER PRIMARY KEY, review_status TEXT)")
                conn.execute("INSERT INTO photo_analyses (id, review_status) VALUES (1, '미검토')")
            # Simulate update status
            with closing(sqlite3.connect(db_path)) as conn, conn:
                conn.execute("UPDATE photo_analyses SET review_status = ? WHERE id = ?", ("토너먼트 1위", 1))
            with closing(sqlite3.connect(db_path)) as conn:
                status = conn.execute("SELECT review_status FROM photo_analyses WHERE id = 1").fetchone()[0]
                self.assertEqual(status, "토너먼트 1위")

    def test_hybrid_burst_grouping_and_sensitivity(self) -> None:
        self.assertTrue(photo_dashboard.are_filenames_sequential("SG_01089.webp", "SG_01089-2.webp"))
        self.assertTrue(photo_dashboard.are_filenames_sequential("SG_03607.webp", "SG_03607 (1).webp"))
        self.assertTrue(photo_dashboard.are_filenames_sequential("IMG_0123.jpg", "IMG_0124.jpg"))
        self.assertFalse(photo_dashboard.are_filenames_sequential("SG_07953.jpg", "SG_03607.webp"))

        item1 = {
            "id": 1,
            "filename": "SG_01089.webp",
            "dhash": 0x1111111111111111,
            "created_at": "2026-10-14T10:00:00+00:00",
            "figure_category": "접사/디테일",
        }
        # Item 2 has distance 17 from item1, but same stem and same time!
        # Base threshold is 15. Without bonus, 17 > 15 (False).
        # With bonus (+3 for filename, +2 for time), allowed is 20, so 17 <= 20 (True).
        diff_bits = 17
        diff_val = (1 << diff_bits) - 1
        item2 = {
            "id": 2,
            "filename": "SG_01089-2.webp",
            "dhash": 0x1111111111111111 ^ diff_val,
            "created_at": "2026-10-14T10:00:30+00:00",
            "figure_category": "접사/디테일",
        }
        self.assertTrue(photo_dashboard.are_burst_pair(item1, item2, base_max_dist=15))

        # Different files with distance 17 and no bonus should not cluster under base 15
        item3 = {
            "id": 3,
            "filename": "OTHER_001.webp",
            "dhash": 0x1111111111111111 ^ diff_val,
            "created_at": "2026-10-14T12:00:00+00:00",
            "figure_category": "일상/야외 스냅",
        }
        self.assertFalse(photo_dashboard.are_burst_pair(item1, item3, base_max_dist=15))
        # But under relaxed threshold 18, it should cluster
        self.assertTrue(photo_dashboard.are_burst_pair(item1, item3, base_max_dist=18))

        self.assertIn("burst-dist-select", photo_dashboard.DASHBOARD_HTML)
        self.assertIn("changeBurstSensitivity", photo_dashboard.DASHBOARD_HTML)

    def test_figure_prompt_includes_figure_photography_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "sample.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)
            prompt = photo_analyzer._build_prompt(photo)
            self.assertIn("피규어 및 캐릭터 모델 사진(Figure Photography)", prompt)
            self.assertIn("접사/디테일", prompt)
            self.assertIn("일상/야외 스냅", prompt)
            self.assertIn("스튜디오 연출/디오라마", prompt)

    def test_run_batch_pipeline_creates_reports_and_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            dir_path = Path(temporary_directory)
            photo1 = dir_path / "fig1.jpg"
            photo2 = dir_path / "fig2.jpg"
            self._make_jpeg(photo1)
            self._make_jpeg(photo2)

            db_path = dir_path / "batch_test.sqlite3"
            report_dir = dir_path / "reports"
            summary_html = dir_path / "comparison.html"

            with patch.object(photo_analyzer, "analyze_with_gemini") as mock_analyze:
                mock_analyze.return_value = self._valid_analysis()
                exit_code = photo_analyzer.run_batch_pipeline(
                    photo_paths=[photo1, photo2],
                    model="test-model",
                    db_path=db_path,
                    report_dir=report_dir,
                    summary_html_path=summary_html,
                    max_workers=2,
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue(db_path.is_file())
            self.assertTrue(summary_html.is_file())
            self.assertTrue((report_dir / "fig1.html").is_file())
            self.assertTrue((report_dir / "fig2.html").is_file())

            comparison_text = summary_html.read_text(encoding="utf-8")
            self.assertIn("피규어 사진 일괄 평가 결과", comparison_text)
            self.assertIn("fig1.jpg", comparison_text)
            self.assertIn("fig2.jpg", comparison_text)

    def test_dashboard_get_all_analyses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            dir_path = Path(temporary_directory)
            db_path = dir_path / "dash_test.sqlite3"
            image_path = dir_path / "sample.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)
            record_id = save_analysis(db_path, photo, "test-model", self._valid_analysis())

            items = photo_dashboard.get_all_analyses(db_path)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["id"], record_id)
            self.assertEqual(items[0]["filename"], "sample.jpg")
            self.assertEqual(items[0]["final_score"], 7.8)
            self.assertEqual(items[0]["grade"], "우수")

    def test_dashboard_delete_analysis_removes_record_and_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            dir_path = Path(temporary_directory)
            db_path = dir_path / "dash_delete_test.sqlite3"
            image_path = dir_path / "sample.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)
            record_id = save_analysis(db_path, photo, "test-model", self._valid_analysis())

            # Verify tag exists
            with closing(sqlite3.connect(db_path)) as conn:
                tag_count = conn.execute("SELECT COUNT(*) FROM photo_analysis_tags WHERE analysis_id = ?", (record_id,)).fetchone()[0]
                self.assertGreater(tag_count, 0)

            # Delete record
            with closing(sqlite3.connect(db_path)) as conn, conn:
                conn.execute("DELETE FROM photo_analysis_tags WHERE analysis_id = ?", (record_id,))
                conn.execute("DELETE FROM photo_analyses WHERE id = ?", (record_id,))

            items = photo_dashboard.get_all_analyses(db_path)
            self.assertEqual(len(items), 0)
            with closing(sqlite3.connect(db_path)) as conn:
                tag_count = conn.execute("SELECT COUNT(*) FROM photo_analysis_tags WHERE analysis_id = ?", (record_id,)).fetchone()[0]
                self.assertEqual(tag_count, 0)


    def test_figure_categories_defined(self) -> None:
        from photo_tag_schema import FIGURE_CATEGORIES
        self.assertIn("macro", FIGURE_CATEGORIES)
        self.assertIn("snap", FIGURE_CATEGORIES)
        self.assertIn("staging", FIGURE_CATEGORIES)
        self.assertIn("general", FIGURE_CATEGORIES)
        self.assertEqual(FIGURE_CATEGORIES["macro"]["label"], "접사/디테일")
        self.assertEqual(FIGURE_CATEGORIES["snap"]["label"], "일상/야외 스냅")
        self.assertEqual(FIGURE_CATEGORIES["staging"]["label"], "스튜디오 연출/디오라마")

    def test_prompt_branching_for_macro_snap_and_auto(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "sample.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)

            # Auto mode
            auto_prompt = photo_analyzer._build_prompt(photo, category_hint=None)
            self.assertIn("피규어 촬영 세부 유형 자동 판별 및 분기 심사", auto_prompt)
            self.assertIn("접사/디테일", auto_prompt)
            self.assertIn("일상/야외 스냅", auto_prompt)
            self.assertIn("스튜디오 연출/디오라마", auto_prompt)

            # Macro explicit hint
            macro_prompt = photo_analyzer._build_prompt(photo, category_hint="macro")
            self.assertIn("[지정된 피규어 촬영 유형: 접사/디테일]", macro_prompt)
            self.assertIn("눈동자 데칼", macro_prompt)

            # Snap explicit hint
            snap_prompt = photo_analyzer._build_prompt(photo, category_hint="snap")
            self.assertIn("[지정된 피규어 촬영 유형: 일상/야외 스냅]", snap_prompt)
            self.assertIn("자연광", snap_prompt)

    def test_photo_analysis_figure_category_default(self) -> None:
        analysis = self._valid_analysis()
        self.assertEqual(analysis.figure_category, "일반 피규어 촬영")
        self.assertIn("figure_category", PhotoAnalysis.model_fields)

    def test_photo_analysis_detected_camera_settings(self) -> None:
        analysis = self._valid_analysis()
        self.assertIsNone(analysis.detected_camera_settings)

        analysis_with_settings = analysis.model_copy(
            update={"detected_camera_settings": {"Camera": "SONY A7M4", "FNumber": "F/1.4", "ISO": "100"}}
        )
        self.assertEqual(analysis_with_settings.detected_camera_settings["Camera"], "SONY A7M4")
        self.assertEqual(analysis_with_settings.detected_camera_settings["FNumber"], "F/1.4")

    def test_prompt_includes_watermark_detection_guidelines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "sample.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)
            prompt = photo_analyzer._build_prompt(photo)
            self.assertIn("시각적 워터마크/하단 프레임 촬영 설정 감지 지침", prompt)
            self.assertIn("detected_camera_settings", prompt)

    def test_focus_status_and_notes_schema_and_prompt(self) -> None:
        analysis = self._valid_analysis()
        self.assertEqual(analysis.focus_status, "완벽 칼초점")
        self.assertEqual(analysis.focus_notes, "")

        custom_analysis = analysis.model_copy(
            update={"focus_status": "미세 앞핀", "focus_notes": "눈동자 대신 앞머리 끝에 초점 맺힘"}
        )
        self.assertEqual(custom_analysis.focus_status, "미세 앞핀")
        self.assertIn("앞머리", custom_analysis.focus_notes)

        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "sample.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)
            prompt = photo_analyzer._build_prompt(photo)
            self.assertIn("focus_status", prompt)
            self.assertIn("완벽 칼초점", prompt)
            self.assertIn("아이 데칼", prompt)

    def test_lightroom_advice_schema_and_model(self) -> None:
        from photo_analyzer import LightroomAdvice

        advice = LightroomAdvice(
            exposure=0.35,
            contrast=10,
            highlights=-25,
            shadows=20,
            whites=5,
            blacks=-10,
            texture=-5,
            clarity=8,
            dehaze=5,
            vibrance=15,
            saturation=0,
            temp_tint_notes="5200K 유지, 마젠타 +4 추천",
            retouching_guide="눈동자 반사광에 원형 마스크 노출 +0.3 부여",
        )
        self.assertEqual(advice.exposure, 0.35)
        self.assertEqual(advice.highlights, -25)
        self.assertIn("마젠타", advice.temp_tint_notes)

    def test_dashboard_lr_advice_caching_and_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "test_dash.sqlite3"
            image_path = Path(temporary_directory) / "test.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)
            analysis = self._valid_analysis()
            rec_id = save_analysis(db_path, photo, "test-model", analysis)

            # Check columns
            photo_dashboard.ensure_db_columns(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(photo_analyses)").fetchall()]
                self.assertIn("lr_advice_json", cols)

                # Update with sample advice
                advice_json = json.dumps({"exposure": 0.5, "contrast": 5})
                conn.execute("UPDATE photo_analyses SET lr_advice_json = ? WHERE id = ?", (advice_json, rec_id))
                conn.commit()

            items = photo_dashboard.get_all_analyses(db_path)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["focus_status"], "완벽 칼초점")
            self.assertIsNotNone(items[0]["lr_advice"])
            self.assertEqual(items[0]["lr_advice"]["exposure"], 0.5)

    def test_sns_advice_schema_and_model(self) -> None:
        from photo_analyzer import CropBox, SNSAdvice

        crop_4_5 = CropBox(
            ymin=0.05,
            xmin=0.10,
            ymax=0.95,
            xmax=0.82,
            ratio_label="4:5 (인스타 세로)",
            composition_tip="피규어 시선 방향 여백 확보 및 상반신 집중 프레이밍",
        )
        crop_1_1 = CropBox(
            ymin=0.10,
            xmin=0.15,
            ymax=0.85,
            xmax=0.90,
            ratio_label="1:1 (정방형)",
            composition_tip="얼굴과 가슴 디테일 중심",
        )
        crop_16_9 = CropBox(
            ymin=0.20,
            xmin=0.00,
            ymax=0.76,
            xmax=1.00,
            ratio_label="16:9 (X 가로)",
            composition_tip="X 타임라인 썸네일 잘림 방지",
        )
        crop_3_4 = CropBox(
            ymin=0.05,
            xmin=0.12,
            ymax=0.95,
            xmax=0.80,
            ratio_label="3:4 (X 세로)",
            composition_tip="모바일 X 앱 피드 최적화",
        )

        advice = SNSAdvice(
            instagram_crop_4_5=crop_4_5,
            instagram_crop_1_1=crop_1_1,
            x_crop_16_9=crop_16_9,
            x_crop_3_4=crop_3_4,
            social_caption="빛과 조형의 완벽한 조화 ✨ 피규어 컬렉션",
            hashtags=["#피규어", "#figurephotography", "#toyphotography", "#フィギュア"],
        )
        self.assertEqual(advice.instagram_crop_4_5.ymin, 0.05)
        self.assertEqual(advice.x_crop_16_9.ratio_label, "16:9 (X 가로)")
        self.assertIn("#figurephotography", advice.hashtags)

    def test_dashboard_sns_advice_caching_and_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "test_dash_sns.sqlite3"
            image_path = Path(temporary_directory) / "test.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)
            analysis = self._valid_analysis()
            rec_id = save_analysis(db_path, photo, "test-model", analysis)

            photo_dashboard.ensure_db_columns(db_path)
            with closing(sqlite3.connect(db_path)) as conn:
                cols = [r[1] for r in conn.execute("PRAGMA table_info(photo_analyses)").fetchall()]
                self.assertIn("sns_advice_json", cols)

                sample_sns = {
                    "instagram_crop_4_5": {
                        "ymin": 0.1, "xmin": 0.1, "ymax": 0.9, "xmax": 0.74,
                        "ratio_label": "4:5 (인스타 세로)", "composition_tip": "테스트 팁"
                    },
                    "social_caption": "테스트 캡션입니다",
                    "hashtags": ["#피규어"]
                }
                conn.execute("UPDATE photo_analyses SET sns_advice_json = ? WHERE id = ?", (json.dumps(sample_sns), rec_id))
                conn.commit()

            items = photo_dashboard.get_all_analyses(db_path)
            self.assertEqual(len(items), 1)
            self.assertIsNotNone(items[0]["sns_advice"])
            self.assertEqual(items[0]["sns_advice"]["social_caption"], "테스트 캡션입니다")

    def test_single_sns_crop_ratio_config_and_caption_schema(self) -> None:
        from photo_analyzer import SNS_CROP_RATIO_CONFIGS, SNSCaptionAndTags, CropBox

        for ratio_key in ("instagram_crop_4_5", "instagram_crop_1_1", "x_crop_16_9", "x_crop_3_4"):
            self.assertIn(ratio_key, SNS_CROP_RATIO_CONFIGS)
            cfg = SNS_CROP_RATIO_CONFIGS[ratio_key]
            self.assertIn("name", cfg)
            self.assertIn("guide", cfg)
            self.assertGreater(cfg["w"], 0)
            self.assertGreater(cfg["h"], 0)

        caption_model = SNSCaptionAndTags(
            social_caption="단독 캡션 생성 테스트 ✨",
            hashtags=["#피규어", "#키덜트", "#figurephotography"]
        )
        self.assertEqual(caption_model.social_caption, "단독 캡션 생성 테스트 ✨")
        self.assertEqual(len(caption_model.hashtags), 3)

    def test_dhash_calculation_and_hamming_distance(self) -> None:
        from io import BytesIO
        from PIL import Image
        from photo_analyzer import compute_dhash_from_bytes, hamming_distance

        img1 = Image.new("RGB", (100, 100), (200, 100, 50))
        buf1 = BytesIO()
        img1.save(buf1, format="WEBP")
        h1 = compute_dhash_from_bytes(buf1.getvalue())

        # Identical image -> distance 0
        h1_same = compute_dhash_from_bytes(buf1.getvalue())
        self.assertEqual(hamming_distance(h1, h1_same), 0)

        # Very similar image (small noise)
        img2 = Image.new("RGB", (100, 100), (202, 101, 52))
        buf2 = BytesIO()
        img2.save(buf2, format="WEBP")
        h2 = compute_dhash_from_bytes(buf2.getvalue())
        self.assertLessEqual(hamming_distance(h1, h2), 2)

    def test_dhash_sqlite_signed_conversion_large_int(self) -> None:
        from photo_analyzer import dhash_to_sqlite, dhash_from_sqlite, save_analysis, prepare_photo
        import photo_dashboard

        large_val = 0xFEDCBA0987654321  # > 2**63 - 1 (overflows signed 64-bit int)
        signed_val = dhash_to_sqlite(large_val)
        self.assertLess(signed_val, 0)
        self.assertEqual(dhash_from_sqlite(signed_val), large_val)

        # Ensure SQLite insert and retrieval works without OverflowError
        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "test_overflow.sqlite3"
            image_path = Path(temporary_directory) / "test_overflow.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)
            # Inject large dhash
            object.__setattr__(photo, "dhash", large_val)
            analysis = self._valid_analysis()
            rec_id = save_analysis(db_path, photo, "test-model", analysis)

            photo_dashboard.ensure_db_columns(db_path)
            items = photo_dashboard.get_all_analyses(db_path)
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0]["dhash"], large_val)

    def test_cluster_burst_groups_ranking_and_drop_reasons(self) -> None:
        from photo_dashboard import cluster_burst_groups

        analyses = [
            {
                "id": 1,
                "filename": "fig_burst_01.jpg",
                "final_score": 9.2,
                "focus_status": "완벽 칼초점",
                "composition_score": 9.0,
                "lighting_score": 9.0,
                "technique_score": 9.2,
                "dhash": 0x1234567890ABCDEF,
            },
            {
                "id": 2,
                "filename": "fig_burst_02.jpg",
                "final_score": 7.5,
                "focus_status": "미세 앞핀",
                "composition_score": 8.0,
                "lighting_score": 7.5,
                "technique_score": 7.0,
                "dhash": 0x1234567890ABCDFF,  # distance 2 from id 1
            },
            {
                "id": 3,
                "filename": "fig_burst_03.jpg",
                "final_score": 8.1,
                "focus_status": "완벽 칼초점",
                "composition_score": 7.5,
                "lighting_score": 8.0,
                "technique_score": 8.0,
                "dhash": 0x1234567890ABCDEE,  # distance 1 from id 1
            },
            {
                "id": 4,
                "filename": "other_photo.jpg",
                "final_score": 8.5,
                "focus_status": "완벽 칼초점",
                "composition_score": 8.5,
                "lighting_score": 8.5,
                "technique_score": 8.5,
                "dhash": 0xFEDCBA0987654321,  # completely distinct hash
            },
        ]

        clustered = cluster_burst_groups(analyses, max_hamming_dist=12)

        # ID 1, 2, 3 should form a burst group of size 3
        b1 = next(item for item in clustered if item["id"] == 1)
        b2 = next(item for item in clustered if item["id"] == 2)
        b3 = next(item for item in clustered if item["id"] == 3)
        single = next(item for item in clustered if item["id"] == 4)

        # Check Best Pick (ID 1 had highest score 9.2)
        self.assertTrue(b1["is_burst"])
        self.assertTrue(b1["is_best_pick"])
        self.assertEqual(b1["burst_rank"], 1)
        self.assertEqual(b1["burst_total"], 3)
        self.assertEqual(b1["drop_reason"], "")

        # Check B-cut #2 (ID 3 had score 8.1)
        self.assertTrue(b3["is_burst"])
        self.assertFalse(b3["is_best_pick"])
        self.assertEqual(b3["burst_rank"], 2)
        self.assertEqual(b3["burst_total"], 3)

        # Check B-cut #3 (ID 2 had focus issue '미세 앞핀')
        self.assertTrue(b2["is_burst"])
        self.assertFalse(b2["is_best_pick"])
        self.assertEqual(b2["burst_rank"], 3)
        self.assertIn("초점 핀 열세", b2["drop_reason"])

        # Check Singleton photo
        self.assertFalse(single["is_burst"])
        self.assertFalse(single["is_best_pick"])
        self.assertIsNone(single["burst_group_id"])
        self.assertEqual(single["burst_total"], 1)

    def test_sns_crop_framing_headroom_and_prompt(self) -> None:
        import subprocess
        import photo_analyzer
        import photo_dashboard

        # 1. Verify prompt guidelines in photo_analyzer
        cfg = photo_analyzer.SNS_CROP_RATIO_CONFIGS["instagram_crop_1_1"]
        self.assertEqual(cfg["w"], 1)
        self.assertEqual(cfg["h"], 1)

        # 2. Test calculateExactCrop in node against tall portrait photo
        with open("photo_dashboard.py", encoding="utf-8") as f:
            code = f.read()
        func_body = "function calculateExactCrop" + code.split("function calculateExactCrop")[1].split("function selectCropRatio")[0]
        node_script = """
        const TARGET_CROP_RATIOS = {
          instagram_crop_1_1: { name: '1:1', tag: '1:1', w: 1, h: 1, ratio: 1.0 },
          x_crop_16_9: { name: '16:9', tag: '16:9', w: 16, h: 9, ratio: 16/9 }
        };
        """ + func_body
        full_script = f"""
        {node_script}
        // Test vertical portrait photo (4672 x 7008), figure head at ymin = 0.12
        const box = {{ ymin: 0.12, xmin: 0.10, ymax: 0.88, xmax: 0.86 }};
        const crop1 = calculateExactCrop('instagram_crop_1_1', box, 4672, 7008);
        const crop169 = calculateExactCrop('x_crop_16_9', box, 4672, 7008);
        console.log(JSON.stringify({{ crop1, crop169 }}));
        """
        res = subprocess.run(["node", "-e", full_script], capture_output=True, text=True, check=True)
        data = json.loads(res.stdout.strip())
        
        # In 1:1 crop, sy must be <= box.ymin * naturalH (head is inside crop with headroom)
        self.assertLessEqual(data["crop1"]["sy"], 0.12 * 7008)
        self.assertGreater(data["crop1"]["sy"], 0)
        self.assertEqual(data["crop1"]["sw"], 4672)
        self.assertEqual(data["crop1"]["sh"], 4672)

        # In 16:9 crop, sy must also be <= box.ymin * naturalH (head is not cut off)
        self.assertLessEqual(data["crop169"]["sy"], 0.12 * 7008)
        self.assertGreater(data["crop169"]["sy"], 0)
        self.assertEqual(data["crop169"]["sw"], 4672)
        self.assertEqual(data["crop169"]["sh"], 2628)


    def test_usage_logging_fallback_and_stats(self) -> None:
        import photo_analyzer
        from types import SimpleNamespace

        class FakeInteractions:
            def __init__(self) -> None:
                self.models: list[str] = []

            def create(self, model, **kwargs):
                self.models.append(model)
                if model != photo_analyzer.FALLBACK_MODEL:
                    raise RuntimeError("503 UNAVAILABLE high demand")
                return SimpleNamespace(
                    output_text="{}",
                    usage=SimpleNamespace(total_input_tokens=120, total_output_tokens=30),
                )

        fake = SimpleNamespace(interactions=FakeInteractions())
        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "usage.sqlite3"
            photo_analyzer.set_usage_log_db(db_path)
            try:
                out = photo_analyzer._call_gemini_interaction(
                    client=fake, model="primary-model", input_payload=[], schema={}, task_desc="테스트 호출"
                )
            finally:
                photo_analyzer.set_usage_log_db(None)
            self.assertEqual(out, "{}")
            stats = photo_analyzer.get_usage_stats(db_path)
            self.assertEqual(stats["total_calls"], 1)
            row = stats["by_task"][0]
            self.assertEqual(row["task"], "테스트 호출")
            self.assertEqual(row["fallbacks"], 1)
            self.assertEqual(row["retries"], 1)
            self.assertEqual(row["input_tokens"], 120)
            self.assertEqual(row["output_tokens"], 30)

    def test_get_client_is_reused_per_key(self) -> None:
        import photo_analyzer

        photo_analyzer._CLIENT_CACHE.clear()
        c1 = photo_analyzer._get_client("test-key-a")
        c2 = photo_analyzer._get_client("test-key-a")
        c3 = photo_analyzer._get_client("test-key-b")
        photo_analyzer._CLIENT_CACHE.clear()
        self.assertIs(c1, c2)
        self.assertIsNot(c1, c3)

    def test_find_existing_analysis_by_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "dup.sqlite3"
            self.assertIsNone(photo_dashboard.find_existing_analysis(db_path, "x"))
            image_path = Path(temporary_directory) / "dup.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)
            rec_id = save_analysis(db_path, photo, "test-model", self._valid_analysis())
            found = photo_dashboard.find_existing_analysis(db_path, photo.sha256)
            self.assertIsNotNone(found)
            self.assertEqual(found[0], rec_id)
            self.assertIn("final_score", found[1])
            self.assertIsNone(photo_dashboard.find_existing_analysis(db_path, "missing"))


    def test_generate_all_sns_crops_uses_single_call(self) -> None:
        import os
        from unittest import mock

        import photo_analyzer

        box = {"ymin": 0.1, "xmin": 0.1, "ymax": 0.9, "xmax": 0.9, "ratio_label": "r", "composition_tip": "t"}
        payload = json.dumps({key: box for key in photo_analyzer.SNS_CROP_RATIO_CONFIGS})

        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "batch.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                    mock.patch.object(photo_analyzer, "_get_client", return_value=object()), \
                    mock.patch.object(photo_analyzer, "_call_gemini_interaction", return_value=payload) as call:
                crops = photo_analyzer.generate_all_sns_crops(photo)

        self.assertEqual(call.call_count, 1)
        self.assertEqual(set(crops.model_dump()), set(photo_analyzer.SNS_CROP_RATIO_CONFIGS))
        prompt_text = call.call_args.kwargs["input_payload"][0]["text"]
        for key in photo_analyzer.SNS_CROP_RATIO_CONFIGS:
            self.assertIn(key, prompt_text)


if __name__ == "__main__":
    unittest.main()
