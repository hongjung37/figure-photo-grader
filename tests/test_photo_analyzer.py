from __future__ import annotations

import base64
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from io import BytesIO
from http import HTTPStatus
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
            stored_originals = list((directory / photo_analyzer.ORIGINALS_DIR_NAME).iterdir())
            self.assertEqual(len(stored_originals), 1)
            self.assertEqual(stored_originals[0].read_bytes(), photo.upload_bytes)

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

    def test_run_batch_pipeline_avoids_duplicate_report_stems(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            first_dir = root / "first"
            second_dir = root / "second"
            first_dir.mkdir()
            second_dir.mkdir()
            first_photo = first_dir / "same.jpg"
            second_photo = second_dir / "same.jpg"
            self._make_jpeg(first_photo)
            self._make_jpeg(second_photo)

            report_dir = root / "reports"
            with patch.object(photo_analyzer, "analyze_with_gemini", return_value=self._valid_analysis()):
                exit_code = photo_analyzer.run_batch_pipeline(
                    photo_paths=[first_photo, second_photo],
                    model="test-model",
                    db_path=root / "batch.sqlite3",
                    report_dir=report_dir,
                    summary_html_path=None,
                    max_workers=2,
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(len(list(report_dir.glob("same__*.html"))), 2)

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

    def test_unknown_record_updates_and_delete_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "missing_record.sqlite3"
            image_path = Path(temporary_directory) / "sample.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)
            record_id = save_analysis(db_path, photo, "test-model", self._valid_analysis())

            self.assertTrue(photo_dashboard.update_review_status(db_path, record_id, "검토 완료"))
            self.assertTrue(photo_dashboard.update_user_score(db_path, record_id, 9.0))
            self.assertFalse(photo_dashboard.update_review_status(db_path, 9999, "검토 완료"))
            self.assertFalse(photo_dashboard.update_user_score(db_path, 9999, 9.0))
            self.assertEqual(photo_dashboard.delete_analyses(db_path, [9999]), [])

    def test_local_photo_lookup_rejects_absolute_and_parent_paths(self) -> None:
        from app.web.handlers import _find_local_photo_path

        with tempfile.TemporaryDirectory() as temporary_directory:
            external_photo = Path(temporary_directory) / "outside.jpg"
            external_photo.write_bytes(b"not a project photo")
            self.assertIsNone(_find_local_photo_path(str(external_photo)))
            self.assertIsNone(_find_local_photo_path(f"..\\{external_photo.name}"))

    def test_legacy_db_without_dhash_backfills_and_clusters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "legacy_test.sqlite3"
            image_path = Path(temporary_directory) / "sample.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)
            record_id = save_analysis(db_path, photo, "test-model", self._valid_analysis())

            # Simulate legacy database record where dhash is NULL
            with closing(sqlite3.connect(db_path)) as conn, conn:
                conn.execute("UPDATE photo_analyses SET dhash = NULL WHERE id = ?", (record_id,))
                dhash_before = conn.execute("SELECT dhash FROM photo_analyses WHERE id = ?", (record_id,)).fetchone()[0]
                self.assertIsNone(dhash_before)

            # Retrieve analyses should compute dHash from thumbnail and backfill
            analyses = photo_dashboard.get_all_analyses(db_path)
            self.assertEqual(len(analyses), 1)
            self.assertIsNotNone(analyses[0].get("dhash"))

            with closing(sqlite3.connect(db_path)) as conn:
                dhash_after = conn.execute("SELECT dhash FROM photo_analyses WHERE id = ?", (record_id,)).fetchone()[0]
                self.assertIsNotNone(dhash_after)

    def test_local_photo_lookup_sha256_verification(self) -> None:
        from app.web.handlers import _find_local_photo_path
        with tempfile.TemporaryDirectory() as temporary_directory:
            # Place photo in test_photo
            test_dir = PROJECT_ROOT / "test_photo"
            test_dir.mkdir(exist_ok=True)
            probe_file = test_dir / "_probe_test_sample.jpg"
            self._make_jpeg(probe_file)
            try:
                import hashlib
                valid_sha = hashlib.sha256(probe_file.read_bytes()).hexdigest()
                # Should find when sha256 matches
                found = _find_local_photo_path(probe_file.name, expected_sha256=valid_sha)
                self.assertIsNotNone(found)
                # Should NOT match when sha256 is different (even if filename matches)
                wrong_sha = "0" * 64
                not_found = _find_local_photo_path(probe_file.name, expected_sha256=wrong_sha)
                self.assertIsNone(not_found)
            finally:
                probe_file.unlink(missing_ok=True)

    def test_batch_pipeline_reuses_existing_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            photo_file = root / "item.jpg"
            self._make_jpeg(photo_file)
            db_path = root / "batch_idempotent.sqlite3"

            with patch.object(photo_analyzer, "analyze_with_gemini", return_value=self._valid_analysis()) as mock_ai:
                # First run
                code1 = photo_analyzer.run_batch_pipeline(
                    photo_paths=[photo_file],
                    model="test-model",
                    db_path=db_path,
                    report_dir=None,
                    summary_html_path=None,
                )
                self.assertEqual(code1, 0)
                self.assertEqual(mock_ai.call_count, 1)

                # Second run with same photo should reuse existing analysis and NOT call AI again
                code2 = photo_analyzer.run_batch_pipeline(
                    photo_paths=[photo_file],
                    model="test-model",
                    db_path=db_path,
                    report_dir=None,
                    summary_html_path=None,
                )
                self.assertEqual(code2, 0)
                # Call count should still be 1!
                self.assertEqual(mock_ai.call_count, 1)

            # DB should have exactly 1 record, not 2
            analyses = photo_dashboard.get_all_analyses(db_path)
            self.assertEqual(len(analyses), 1)

    def test_find_existing_analysis_by_model(self) -> None:
        from app.db.repository import find_existing_analysis
        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "model_check.sqlite3"
            image_path = Path(temporary_directory) / "sample.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)

            record_id = save_analysis(db_path, photo, "gemini-2.5-flash-lite", self._valid_analysis())

            # Query with same model -> returns existing record
            match_same = find_existing_analysis(db_path, photo.sha256, model="gemini-2.5-flash-lite")
            self.assertIsNotNone(match_same)
            self.assertEqual(match_same[0], record_id)

            # Query with different model -> returns None so new analysis runs
            match_diff = find_existing_analysis(db_path, photo.sha256, model="gemini-3.1-pro")
            self.assertIsNone(match_diff)

            # Query without model -> backwards-compatible match by hash
            match_any = find_existing_analysis(db_path, photo.sha256)
            self.assertIsNotNone(match_any)
            self.assertEqual(match_any[0], record_id)


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
            best_ratio_key="original",
            best_ratio_reason="원본의 와이드 공간감이 안정적",
            social_caption="빛과 조형의 완벽한 조화 ✨ 피규어 컬렉션",
            hashtags=["#피규어", "#figurephotography", "#toyphotography", "#フィギュア"],
        )
        self.assertEqual(advice.instagram_crop_4_5.ymin, 0.05)
        self.assertEqual(advice.x_crop_16_9.ratio_label, "16:9 (X 가로)")
        self.assertEqual(advice.best_ratio_key, "original")
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
                    "best_ratio_key": "original",
                    "best_ratio_reason": "원본 구도 안정적",
                    "original_tip": "배경과 조화 우수",
                    "social_caption": "테스트 캡션입니다",
                    "hashtags": ["#피규어"]
                }
                conn.execute("UPDATE photo_analyses SET sns_advice_json = ? WHERE id = ?", (json.dumps(sample_sns), rec_id))
                conn.commit()

            items = photo_dashboard.get_all_analyses(db_path)
            self.assertEqual(len(items), 1)
            self.assertIsNotNone(items[0]["sns_advice"])
            self.assertEqual(items[0]["sns_advice"]["social_caption"], "테스트 캡션입니다")
            self.assertEqual(items[0]["sns_advice"]["best_ratio_key"], "original")
            self.assertEqual(items[0]["sns_advice"]["original_tip"], "배경과 조화 우수")

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
        crop_js_file = PROJECT_ROOT / "static/js/crop_viewer.js"
        js_file = crop_js_file if crop_js_file.is_file() else (PROJECT_ROOT / "static/dashboard.js")
        code = js_file.read_text(encoding="utf-8") if js_file.is_file() else (PROJECT_ROOT / "photo_dashboard.py").read_text(encoding="utf-8")
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

    def test_missing_model_falls_back_to_stable_model(self) -> None:
        import photo_analyzer
        from types import SimpleNamespace

        class FakeInteractions:
            def __init__(self) -> None:
                self.models: list[str] = []

            def create(self, model, **kwargs):
                self.models.append(model)
                if model != photo_analyzer.FALLBACK_MODEL:
                    raise RuntimeError("404 NOT_FOUND model not found")
                return SimpleNamespace(
                    output_text="{}",
                    usage=SimpleNamespace(total_input_tokens=10, total_output_tokens=5),
                )

        fake = SimpleNamespace(interactions=FakeInteractions())
        out = photo_analyzer._call_gemini_interaction(
            client=fake, model="unsupported-model", input_payload=[], schema={}, task_desc="404 폴백 테스트"
        )

        self.assertEqual(out, "{}")
        self.assertEqual(fake.interactions.models, ["unsupported-model", photo_analyzer.FALLBACK_MODEL])

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
        crop_data = {key: box for key in photo_analyzer.SNS_CROP_RATIO_CONFIGS}
        crop_data["best_ratio_key"] = "original"
        crop_data["best_ratio_reason"] = "원본 프레이밍이 피규어 공간감에 가장 이상적임"
        crop_data["original_tip"] = "피규어의 좌우 여백과 시선 처리가 안정적임"
        payload = json.dumps(crop_data)

        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "batch.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)
            with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                    mock.patch.object(photo_analyzer, "_get_client", return_value=object()), \
                    mock.patch.object(photo_analyzer, "_call_gemini_interaction", return_value=payload) as call:
                crops = photo_analyzer.generate_all_sns_crops(photo)

        self.assertEqual(call.call_count, 1)
        self.assertEqual(set(crops.model_dump()), set(photo_analyzer.SNS_CROP_RATIO_CONFIGS) | {"best_ratio_key", "best_ratio_reason", "original_tip"})
        self.assertEqual(crops.best_ratio_key, "original")
        self.assertEqual(crops.best_ratio_reason, "원본 프레이밍이 피규어 공간감에 가장 이상적임")
        self.assertEqual(crops.original_tip, "피규어의 좌우 여백과 시선 처리가 안정적임")
        prompt_text = call.call_args.kwargs["input_payload"][0]["text"]
        for key in photo_analyzer.SNS_CROP_RATIO_CONFIGS:
            self.assertIn(key, prompt_text)
        self.assertIn("best_ratio_key", prompt_text)
        self.assertIn("original_tip", prompt_text)
        self.assertIn("original", prompt_text)

    def test_prompts_package_modularization(self) -> None:
        import prompts

        # Verify all prompt builders exist in prompts package
        self.assertTrue(callable(prompts.build_grader_prompt))
        self.assertTrue(callable(prompts.build_lightroom_prompt))
        self.assertTrue(callable(prompts.build_all_sns_crops_prompt))
        self.assertTrue(callable(prompts.build_single_crop_prompt))
        self.assertTrue(callable(prompts.build_sns_advice_prompt))
        self.assertTrue(callable(prompts.build_caption_and_tags_prompt))

        # Test Lightroom prompt builder
        lr_prompt = prompts.build_lightroom_prompt()
        self.assertIn("Adobe Lightroom 마스터", lr_prompt)
        self.assertIn("exposure:", lr_prompt)

        # Test photo-based prompt builders
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "test_prompt.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)

            grader_p = prompts.build_grader_prompt(photo)
            self.assertIn("피규어 및 캐릭터 모델 사진(Figure Photography)", grader_p)

            sns_adv_p = prompts.build_sns_advice_prompt(photo)
            self.assertIn("갤러리 큐레이터이자 사진 예술 감독", sns_adv_p)
            self.assertIn("best_ratio_key", sns_adv_p)

            caption_p = prompts.build_caption_and_tags_prompt(photo)
            self.assertIn("social_caption", caption_p)
            self.assertIn("hashtags", caption_p)

    def test_db_repository_modularization(self) -> None:
        import db
        from db import repository

        # 1. Verify re-exports and module identity
        self.assertIs(photo_dashboard.find_existing_analysis, repository.find_existing_analysis)
        self.assertIs(photo_dashboard.ensure_db_columns, repository.ensure_db_columns)
        self.assertIs(photo_dashboard.get_all_analyses, repository.get_all_analyses)
        self.assertIs(photo_dashboard.get_tag_stats, repository.get_tag_stats)

        # 2. Test CRUD workflow using db.repository
        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "test_repo.sqlite3"
            image_path = Path(temporary_directory) / "repo_img.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)
            rec_id = save_analysis(db_path, photo, "test-model", self._valid_analysis())

            # get_analysis_row_by_id
            row = db.get_analysis_row_by_id(db_path, rec_id)
            self.assertIsNotNone(row)
            self.assertEqual(row["source_filename"], "repo_img.jpg")

            # get_photo_thumbnail_and_hash
            thumb_info = db.get_photo_thumbnail_and_hash(db_path, rec_id)
            self.assertIsNotNone(thumb_info)
            self.assertEqual(thumb_info[1], "repo_img.jpg")
            self.assertEqual(thumb_info[2], photo.sha256)

            # update_review_status
            db.update_review_status(db_path, rec_id, "선택완료")
            updated_row = db.get_analysis_row_by_id(db_path, rec_id)
            self.assertEqual(updated_row["review_status"], "선택완료")

            # update_user_score
            db.update_user_score(db_path, rec_id, 9.5)
            updated_row = db.get_analysis_row_by_id(db_path, rec_id)
            self.assertEqual(updated_row["user_score"], 9.5)

            # update_lr_advice & update_sns_advice
            db.update_lr_advice(db_path, rec_id, '{"preset": "vivid"}')
            db.update_sns_advice(db_path, rec_id, '{"best_ratio_key": "original"}')
            updated_row = db.get_analysis_row_by_id(db_path, rec_id)
            self.assertEqual(updated_row["lr_advice_json"], '{"preset": "vivid"}')
            self.assertEqual(updated_row["sns_advice_json"], '{"best_ratio_key": "original"}')

            # get_analyses_and_tags_for_export
            export_rows, export_tags = db.get_analyses_and_tags_for_export(db_path)
            self.assertEqual(len(export_rows), 1)

            # delete_analyses
            deleted = db.delete_analyses(db_path, [rec_id])
            self.assertEqual(deleted, [rec_id])
            self.assertIsNone(db.get_analysis_row_by_id(db_path, rec_id))

    def test_pydantic_figure_category_and_focus_status_constraints(self) -> None:
        valid_dict = self._valid_analysis().model_dump()

        # Valid options should work
        PhotoAnalysis(**{**valid_dict, "figure_category": "스튜디오 연출/디오라마", "focus_status": "초점 이탈"})

        # Invalid figure_category
        with self.assertRaises(ValidationError):
            PhotoAnalysis(**{**valid_dict, "figure_category": "존재하지않는카테고리"})

        # Invalid focus_status
        with self.assertRaises(ValidationError):
            PhotoAnalysis(**{**valid_dict, "focus_status": "완전흔들림"})

    def test_pydantic_crop_box_coordinates_constraints(self) -> None:
        from app.models.crop import CropBox

        # Valid box
        box = CropBox(
            ymin=0.1,
            xmin=0.1,
            ymax=0.9,
            xmax=0.9,
            ratio_label="1:1",
            composition_tip="test tip",
        )
        self.assertEqual(box.ymin, 0.1)

        # Inverted Y
        with self.assertRaises(ValidationError):
            CropBox(
                ymin=0.8,
                xmin=0.1,
                ymax=0.2,
                xmax=0.9,
                ratio_label="1:1",
                composition_tip="test",
            )

        # Inverted X
        with self.assertRaises(ValidationError):
            CropBox(
                ymin=0.1,
                xmin=0.9,
                ymax=0.8,
                xmax=0.1,
                ratio_label="1:1",
                composition_tip="test",
            )

        # Out of bounds
        with self.assertRaises(ValidationError):
            CropBox(
                ymin=-0.1,
                xmin=0.1,
                ymax=0.8,
                xmax=0.9,
                ratio_label="1:1",
                composition_tip="test",
            )

    def test_pydantic_lightroom_advice_slider_constraints(self) -> None:
        from app.models.lightroom import LightroomAdvice

        base_advice = {
            "exposure": 0.5,
            "contrast": 10,
            "highlights": -20,
            "shadows": 15,
            "whites": 5,
            "blacks": -10,
            "texture": 15,
            "clarity": 10,
            "dehaze": 5,
            "vibrance": 10,
            "saturation": -5,
            "temp_tint_notes": "5200K",
            "retouching_guide": "아이 데칼 마스킹",
        }
        # Valid should succeed
        LightroomAdvice(**base_advice)

        # Out of range exposure (> 5.0)
        with self.assertRaises(ValidationError):
            LightroomAdvice(**{**base_advice, "exposure": 5.5})

        # Out of range slider (> 100)
        with self.assertRaises(ValidationError):
            LightroomAdvice(**{**base_advice, "contrast": 105})

        # Out of range slider (< -100)
        with self.assertRaises(ValidationError):
            LightroomAdvice(**{**base_advice, "shadows": -110})

    def test_load_prepared_photo_for_record_prioritizes_originals(self) -> None:
        from app.services.image_processor import save_original_photo
        from app.web.handlers import _load_prepared_photo_for_record

        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "test.sqlite3"
            orig_img_path = Path(temporary_directory) / "source_shot.jpg"
            self._make_jpeg(orig_img_path)
            photo = prepare_photo(orig_img_path)

            # 1. Save original to photo_originals
            save_original_photo(db_path, photo)

            row = {
                "sha256": photo.sha256,
                "source_filename": "source_shot.jpg",
                "width": 16,
                "height": 12,
                "thumbnail": b"fake_thumb",
            }

            # Should load from photo_originals
            loaded = _load_prepared_photo_for_record(db_path, row)
            self.assertEqual(loaded.sha256, photo.sha256)
            self.assertEqual(loaded.upload_mime_type, "image/jpeg")

            # 2. Thumbnail fallback when no file exists
            row_thumb_only = {
                "sha256": "nonexistent_hash",
                "source_filename": "missing.jpg",
                "width": 100,
                "height": 100,
                "thumbnail": b"dummy_thumb_bytes",
            }
            loaded_fallback = _load_prepared_photo_for_record(db_path, row_thumb_only)
            self.assertEqual(loaded_fallback.upload_bytes, b"dummy_thumb_bytes")
            self.assertEqual(loaded_fallback.image_format, "WEBP")

            # 3. Raise ValueError when neither original nor thumbnail exists
            row_empty = {
                "sha256": "missing_hash",
                "source_filename": "missing.jpg",
                "width": 100,
                "height": 100,
                "thumbnail": None,
            }
            with self.assertRaises(ValueError):
                _load_prepared_photo_for_record(db_path, row_empty)

    def test_analyze_rejects_oversized_request_before_reading_body(self) -> None:
        from app.config import MAX_UPLOAD_SIZE
        from app.web.handlers import DashboardRequestHandler

        handler = DashboardRequestHandler.__new__(DashboardRequestHandler)
        handler.path = "/api/analyze"
        handler.headers = {
            "Content-Type": "multipart/form-data; boundary=test",
            "Content-Length": str(MAX_UPLOAD_SIZE + 1),
        }
        handler.rfile = BytesIO(b"request body must not be read")
        handler.wfile = BytesIO()
        handler.send_error = MagicMock()

        handler.do_POST()

        handler.send_error.assert_called_once()
        self.assertEqual(handler.send_error.call_args.args[0], HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        self.assertEqual(handler.rfile.tell(), 0)

    def test_post_process_advice_endpoint_force_flag(self) -> None:
        from app.models.lightroom import LightroomAdvice
        from app.web.handlers import DashboardRequestHandler
        from unittest.mock import MagicMock, patch

        with tempfile.TemporaryDirectory() as temporary_directory:
            db_path = Path(temporary_directory) / "test.sqlite3"
            image_path = Path(temporary_directory) / "test.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)
            rec_id = save_analysis(db_path, photo, "test-model", self._valid_analysis())

            # Seed existing cache
            seed_advice = LightroomAdvice(
                exposure=0.1,
                contrast=5,
                highlights=-10,
                shadows=10,
                whites=0,
                blacks=0,
                texture=5,
                clarity=5,
                dehaze=0,
                vibrance=5,
                saturation=0,
                temp_tint_notes="5000K",
                retouching_guide="guide1",
            )
            from app.db import update_lr_advice
            update_lr_advice(db_path, rec_id, json.dumps(seed_advice.model_dump()))

            # Handler setup
            handler = DashboardRequestHandler.__new__(DashboardRequestHandler)
            handler.db_path = db_path
            handler.wfile = BytesIO()
            handler.send_response = MagicMock()
            handler.send_header = MagicMock()
            handler.end_headers = MagicMock()

            # 1. Without force (force=false): returns cached advice
            handler.path = f"/api/post-process-advice/{rec_id}"
            handler.do_POST()
            resp = json.loads(handler.wfile.getvalue().decode("utf-8"))
            self.assertTrue(resp["success"])
            self.assertTrue(resp["cached"])
            self.assertEqual(resp["advice"]["temp_tint_notes"], "5000K")

            # 2. With force=true: regenerates advice and returns cached=False
            new_advice = LightroomAdvice(
                exposure=0.5,
                contrast=20,
                highlights=-30,
                shadows=20,
                whites=10,
                blacks=-5,
                texture=15,
                clarity=10,
                dehaze=5,
                vibrance=10,
                saturation=5,
                temp_tint_notes="5400K (Regenerated)",
                retouching_guide="guide2",
            )
            handler.wfile = BytesIO()
            handler.path = f"/api/post-process-advice/{rec_id}?force=true"
            with patch("app.web.handlers.generate_lightroom_advice", return_value=new_advice):
                handler.do_POST()

            resp_force = json.loads(handler.wfile.getvalue().decode("utf-8"))
            self.assertTrue(resp_force["success"])
            self.assertFalse(resp_force["cached"])
            self.assertEqual(resp_force["advice"]["temp_tint_notes"], "5400K (Regenerated)")

    def test_self_healing_from_llm_json_and_model_validate_json(self) -> None:
        """Test defensive normalization on LLM JSON output with typos, markdown, out-of-range scores."""
        raw_llm_output = """```json
        {
            "composition_score": 10.5,
            "composition_notes": "[장점] 구도 좋음 [단점] 없음",
            "lighting_score": 8.0,
            "lighting_notes": "[장점] 조명 자연스러움 [단점] 없음",
            "color_score": -1.0,
            "color_notes": "[장점] 색감 좋음 [단점] 없음",
            "technique_score": "8.5",
            "technique_notes": "[장점] 선명함 [단점] 없음",
            "final_score": 9.2,
            "final_reason": "전체적으로 우수함",
            "strengths": ["선명한 디테일"],
            "improvements": ["배경 정리"],
            "figure_category": "접사",
            "focus_status": "완벽 칼초plet",
            "focus_notes": "눈동자에 핀이 완벽히 맞음",
            "aesthetic_tags": {
                "viewpoint": ["정면", "정면"],
                "composition_space": ["중앙구도", "클로즈업", "얕은 심도", "깊은 심도"],
                "pose_gaze": ["정면 응시"],
                "mood": ["존재하지않는이상한태그", "따뜻함"],
                "subject_background": [],
                "light_expression": [],
                "color_impression": [],
                "narrative_implication": []
            }
        }
        ```"""
        analysis = PhotoAnalysis.from_llm_json(raw_llm_output)

        # 1. focus_status healed from '완벽 칼초plet' to '완벽 칼초점'
        self.assertEqual(analysis.focus_status, "완벽 칼초점")

        # 2. figure_category healed from '접사' to '접사/디테일'
        self.assertEqual(analysis.figure_category, "접사/디테일")

        # 3. scores clamped to 0.0 - 10.0
        self.assertEqual(analysis.composition_score, 10.0)
        self.assertEqual(analysis.color_score, 0.0)
        self.assertEqual(analysis.technique_score, 8.5)

        # 4. aesthetic_tags healed, deduplicated, and limited to 3
        self.assertEqual(analysis.aesthetic_tags.viewpoint, ["정면"])
        self.assertIn("중앙 구도", analysis.aesthetic_tags.composition_space)
        self.assertLessEqual(len(analysis.aesthetic_tags.composition_space), 3)
        self.assertEqual(analysis.aesthetic_tags.mood, ["따뜻함"])

        # 5. Unknown focus_status falls back to '판별 불가'
        unknown_output = raw_llm_output.replace("완벽 칼초plet", "완전알수없는말")
        unknown_analysis = PhotoAnalysis.from_llm_json(unknown_output)
        self.assertEqual(unknown_analysis.focus_status, "판별 불가")

        # 6. Strict model_validate_json raises ValidationError on invalid scores
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            PhotoAnalysis.model_validate_json('{"composition_score": 15.0}')

    def test_do_get_blocks_arbitrary_file_exposure_p0(self) -> None:
        from app.web.handlers import DashboardRequestHandler

        for forbidden_path in ("/.env", "/photo_analyses.sqlite3", "/app/config.py", "/static/../.env"):
            handler = DashboardRequestHandler.__new__(DashboardRequestHandler)
            handler.path = forbidden_path
            handler.wfile = BytesIO()
            handler.send_error = MagicMock()
            handler.do_GET()
            handler.send_error.assert_called_once()
            self.assertEqual(handler.send_error.call_args.args[0], HTTPStatus.NOT_FOUND)
            self.assertEqual(handler.wfile.getvalue(), b"")

    def test_are_burst_pair_excludes_same_sha256_multi_model_records(self) -> None:
        from app.services.burst_detector import are_burst_pair, cluster_burst_groups

        rec_lite = {
            "id": 10,
            "sha256": "same_photo_hash_123",
            "filename": "figure.jpg",
            "model": "gemini-3.1-flash-lite-preview",
            "final_score": 8.2,
            "focus_status": "완벽 칼초점",
            "dhash": 0x1122334455667788,
        }
        rec_pro = {
            "id": 11,
            "sha256": "same_photo_hash_123",
            "filename": "figure.jpg",
            "model": "gemini-3.1-pro-preview",
            "final_score": 9.1,
            "focus_status": "완벽 칼초점",
            "dhash": 0x1122334455667788,
        }
        self.assertFalse(are_burst_pair(rec_lite, rec_pro))
        clustered = cluster_burst_groups([rec_lite, rec_pro])
        for item in clustered:
            self.assertFalse(item["is_burst"])
            self.assertIsNone(item["burst_group_id"])

    def test_json_post_endpoints_reject_missing_or_oversized_content_length(self) -> None:
        from app.web.handlers import DashboardRequestHandler

        for endpoint in ("/api/reanalyze", "/api/update-status", "/api/rate", "/api/delete-analysis"):
            # Oversized Content-Length (> 1MB) must be rejected without reading rfile
            handler = DashboardRequestHandler.__new__(DashboardRequestHandler)
            handler.path = endpoint
            handler.headers = {"Content-Length": str(2 * 1024 * 1024)}
            handler.rfile = BytesIO(b'{"id": 1}')
            handler.wfile = BytesIO()
            handler.send_response = MagicMock()
            handler.send_header = MagicMock()
            handler.end_headers = MagicMock()
            handler.do_POST()
            handler.send_response.assert_called_once_with(HTTPStatus.BAD_REQUEST)
            self.assertEqual(handler.rfile.tell(), 0)

    def test_render_html_report_includes_cross_check_opinion(self) -> None:
        from app.exporters.html_exporter import render_html_report
        from app.models.analysis import CrossCheckOpinion

        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "cc.jpg"
            self._make_jpeg(image_path)
            photo = prepare_photo(image_path)
            analysis = self._valid_analysis().model_copy(
                update={
                    "cross_check_opinion": CrossCheckOpinion(
                        model="gpt-5.4-mini",
                        score=8.7,
                        reason="세컨드 오피니언 테스트 총평",
                        strengths=["독립 강점 1"],
                        improvements=["독립 개선점 1"],
                        composition_critique="구도 비평 내용",
                        lighting_critique="조명 비평 내용",
                    )
                }
            )
            html = render_html_report(photo, analysis, record_id=7, model="ensemble")
            self.assertIn("교차 검증 소견 (gpt-5.4-mini)", html)
            self.assertIn("세컨드 오피니언 테스트 총평", html)
            self.assertIn("구도 비평 내용", html)


if __name__ == "__main__":
    unittest.main()


