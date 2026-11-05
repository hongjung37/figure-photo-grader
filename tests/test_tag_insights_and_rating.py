import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from photo_dashboard import (
    classify_focal_band,
    ensure_db_columns,
    extract_focal_length_mm,
    get_all_analyses,
    get_focal_stats,
    get_tag_stats,
)
from photo_tag_schema import AestheticTags


class TestTagInsightsAndUserRating(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_photos.sqlite3"
        self._init_mock_db()

    def tearDown(self):
        import gc
        gc.collect()
        try:
            self.tmp_dir.cleanup()
        except Exception:
            pass

    def _init_mock_db(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                """CREATE TABLE photo_analyses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sha256 TEXT NOT NULL,
                    source_filename TEXT NOT NULL,
                    width INTEGER NOT NULL,
                    height INTEGER NOT NULL,
                    image_format TEXT NOT NULL,
                    model TEXT NOT NULL,
                    exif_json TEXT NOT NULL,
                    analysis_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    thumbnail BLOB
                )"""
            )
            # Insert 3 test photos
            analyses = [
                {
                    "final_score": 9.2,
                    "lighting_score": 9.5,
                    "composition_score": 9.0,
                    "color_score": 9.0,
                    "technique_score": 9.3,
                    "figure_category": "접사/디테일",
                    "focus_status": "완벽 칼초점",
                    "final_reason": "자연광과 삼분할 구도가 돋보이는 컷",
                    "aesthetic_tags": {
                        "light_direction": "순광(정면광)",
                        "light_quality": "소프트(부드러운 확산광)",
                        "camera_angle": "아이레벨(눈높이)",
                        "shot_scale": "접사(페이스/디테일)",
                        "depth_of_field": "극얕은심도(배경완전흐림)",
                        "color_tone": "하이키/쿨톤"
                    }
                },
                {
                    "final_score": 8.0,
                    "lighting_score": 8.0,
                    "composition_score": 8.5,
                    "color_score": 8.0,
                    "technique_score": 7.5,
                    "figure_category": "일상/야외 스냅",
                    "focus_status": "완벽 칼초점",
                    "final_reason": "자연광 야외 스냅 컷",
                    "aesthetic_tags": {
                        "light_direction": "순광(정면광)",
                        "light_quality": "소프트(부드러운 확산광)",
                        "camera_angle": "로우앵글(앙각)",
                        "shot_scale": "바스트샷(상반신)",
                        "depth_of_field": "중간심도(배경형태인식)",
                        "color_tone": "하이키/쿨톤"
                    }
                },
                {
                    "final_score": 6.5,
                    "lighting_score": 6.0,
                    "composition_score": 6.5,
                    "color_score": 7.0,
                    "technique_score": 6.5,
                    "figure_category": "스튜디오 연출/디오라마",
                    "focus_status": "미세 앞핀",
                    "final_reason": "저조도 환경 노이즈 발생",
                    "aesthetic_tags": {
                        "light_direction": "탑라이트(상단광)",
                        "light_quality": "하드(강한 직사광/대비)",
                        "camera_angle": "로우앵글(앙각)",
                        "shot_scale": "풀샷(전신)",
                        "depth_of_field": "깊은심도(팬포커스)",
                        "color_tone": "로우키/쿨톤"
                    }
                }
            ]

            for idx, a in enumerate(analyses, 1):
                conn.execute(
                    """INSERT INTO photo_analyses (
                        sha256, source_filename, width, height, image_format,
                        model, exif_json, analysis_json, created_at, thumbnail
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        f"hash_{idx}",
                        f"fig_{idx}.jpg",
                        1920,
                        1080,
                        "JPEG",
                        "gemini-flash",
                        "{}",
                        json.dumps(a),
                        "2026-10-15T00:00:00",
                        None
                    )
                )

        ensure_db_columns(self.db_path)

        # Populate normalized photo_analysis_tags
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("INSERT INTO photo_analysis_tags VALUES (1, 'light_direction', '순광(정면광)')")
            conn.execute("INSERT INTO photo_analysis_tags VALUES (1, 'light_quality', '소프트(부드러운 확산광)')")
            conn.execute("INSERT INTO photo_analysis_tags VALUES (1, 'camera_angle', '아이레벨(눈높이)')")
            conn.execute("INSERT INTO photo_analysis_tags VALUES (1, 'shot_scale', '접사(페이스/디테일)')")
            conn.execute("INSERT INTO photo_analysis_tags VALUES (1, 'color_tone', '하이키/쿨톤')")

            conn.execute("INSERT INTO photo_analysis_tags VALUES (2, 'light_direction', '순광(정면광)')")
            conn.execute("INSERT INTO photo_analysis_tags VALUES (2, 'camera_angle', '로우앵글(앙각)')")
            conn.execute("INSERT INTO photo_analysis_tags VALUES (2, 'color_tone', '하이키/쿨톤')")

            conn.execute("INSERT INTO photo_analysis_tags VALUES (3, 'light_direction', '탑라이트(상단광)')")
            conn.execute("INSERT INTO photo_analysis_tags VALUES (3, 'camera_angle', '로우앵글(앙각)')")
            conn.execute("INSERT INTO photo_analysis_tags VALUES (3, 'color_tone', '로우키/쿨톤')")

    def test_ensure_db_columns_adds_user_score(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(photo_analyses)").fetchall()]
            self.assertIn("user_score", cols)

    def test_update_and_load_user_score(self):
        # Update user rating for photo 1 and photo 2
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("UPDATE photo_analyses SET user_score = ? WHERE id = ?", (9.5, 1))
            conn.execute("UPDATE photo_analyses SET user_score = ? WHERE id = ?", (7.0, 2))

        analyses = get_all_analyses(self.db_path)
        self.assertEqual(len(analyses), 3)

        p1 = next(p for p in analyses if p["id"] == 1)
        p2 = next(p for p in analyses if p["id"] == 2)
        p3 = next(p for p in analyses if p["id"] == 3)

        self.assertEqual(p1["user_score"], 9.5)
        self.assertEqual(p2["user_score"], 7.0)
        self.assertIsNone(p3["user_score"])

    def test_get_tag_stats_aggregation(self):
        # Update user score for photo 1
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("UPDATE photo_analyses SET user_score = ? WHERE id = ?", (9.5, 1))

        # min_count=2: only '순광(정면광)', '하이키/쿨톤', '로우앵글(앙각)' should appear
        stats_min2 = get_tag_stats(self.db_path, min_count=2)
        self.assertEqual(stats_min2["total_photos"], 3)
        self.assertEqual(stats_min2["user_rated_photos"], 1)

        tags_min2 = {t["tag"]: t for t in stats_min2["all_tags"]}
        self.assertIn("순광(정면광)", tags_min2)
        self.assertIn("로우앵글(앙각)", tags_min2)
        self.assertNotIn("탑라이트(상단광)", tags_min2)  # count is 1

        # Check '순광(정면광)' average: (9.2 + 8.0) / 2 = 8.6
        self.assertAlmostEqual(tags_min2["순광(정면광)"]["avg_ai_score"], 8.6, places=1)
        self.assertEqual(tags_min2["순광(정면광)"]["count"], 2)
        self.assertEqual(tags_min2["순광(정면광)"]["user_rated_count"], 1)
        self.assertEqual(tags_min2["순광(정면광)"]["avg_user_score"], 9.5)
        # diff = 9.5 - 8.6 = +0.9
        self.assertAlmostEqual(tags_min2["순광(정면광)"]["score_diff"], 0.9, places=1)

        # min_count=1: all tags appear
        stats_min1 = get_tag_stats(self.db_path, min_count=1)
        tags_min1 = {t["tag"]: t for t in stats_min1["all_tags"]}
        self.assertIn("탑라이트(상단광)", tags_min1)
        self.assertAlmostEqual(tags_min1["탑라이트(상단광)"]["avg_ai_score"], 6.5, places=1)

        # Check Top and Bottom AI tags
        self.assertEqual(stats_min1["top_ai_tags"][0]["tag"], "소프트(부드러운 확산광)")  # score 9.2
        self.assertEqual(stats_min1["bottom_ai_tags"][0]["tag"], "탑라이트(상단광)")  # score 6.5

    def test_http_rate_and_tag_stats_endpoints(self):
        import threading
        import urllib.request
        from http.server import HTTPServer
        from photo_dashboard import DashboardRequestHandler

        class TestHandler(DashboardRequestHandler):
            db_path = self.db_path

        server = HTTPServer(("127.0.0.1", 0), TestHandler)
        port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        base_url = f"http://127.0.0.1:{port}"
        try:
            # 1. Test POST /api/rate
            req_data = json.dumps({"id": 1, "user_score": 8.8}).encode("utf-8")
            req = urllib.request.Request(
                f"{base_url}/api/rate",
                data=req_data,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(res["success"])
                self.assertEqual(res["user_score"], 8.8)

            # Check DB updated
            analyses = get_all_analyses(self.db_path)
            p1 = next(p for p in analyses if p["id"] == 1)
            self.assertEqual(p1["user_score"], 8.8)

            # 2. Test GET /api/tag-stats
            with urllib.request.urlopen(f"{base_url}/api/tag-stats?min_count=1") as resp:
                stats = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(stats["total_photos"], 3)
                self.assertEqual(stats["user_rated_photos"], 1)
                tags = {t["tag"]: t for t in stats["all_tags"]}
                self.assertEqual(tags["순광(정면광)"]["avg_user_score"], 8.8)

            # 3. Test POST /api/rate to clear score
            req_data_clear = json.dumps({"id": 1, "user_score": None}).encode("utf-8")
            req_clear = urllib.request.Request(
                f"{base_url}/api/rate",
                data=req_data_clear,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req_clear) as resp:
                res = json.loads(resp.read().decode("utf-8"))
            # 4. Test POST /api/rate with nonexistent ID
            req_data_missing = json.dumps({"id": 9999, "user_score": 5.0}).encode("utf-8")
            req_missing = urllib.request.Request(
                f"{base_url}/api/rate",
                data=req_data_missing,
                headers={"Content-Type": "application/json"}
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req_missing)
            err_body = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertFalse(err_body["success"])
            self.assertIn("9999", err_body["error"])

            # 5. Test POST /api/update-status with nonexistent ID
            req_status_missing = json.dumps({"id": 9999, "status": "검토 완료"}).encode("utf-8")
            req_st = urllib.request.Request(
                f"{base_url}/api/update-status",
                data=req_status_missing,
                headers={"Content-Type": "application/json"}
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req_st)
            err_body = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertFalse(err_body["success"])
            self.assertIn("9999", err_body["error"])

            # 6. Test POST /api/delete-analysis with nonexistent ID
            req_del_missing = json.dumps({"ids": [9999]}).encode("utf-8")
            req_del = urllib.request.Request(
                f"{base_url}/api/delete-analysis",
                data=req_del_missing,
                headers={"Content-Type": "application/json"}
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(req_del)
            err_body = json.loads(ctx.exception.read().decode("utf-8"))
            self.assertFalse(err_body["success"])
            self.assertIn("9999", err_body["error"])

            # 7. Test GET /api/focal-stats
            with urllib.request.urlopen(f"{base_url}/api/focal-stats?min_count=1") as resp:
                fstats = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(fstats["total_photos"], 3)
                self.assertIn("bands", fstats)
        finally:
            server.shutdown()
            server.server_close()

    def test_focal_length_extraction_and_focal_stats(self):
        # Verify extract_focal_length_mm priority
        self.assertEqual(
            extract_focal_length_mm({"FocalLengthIn35mmFilm": 85, "FocalLength": 56.0}, {}),
            85.0,
        )
        self.assertEqual(
            extract_focal_length_mm({"FocalLength": [50, 1]}, {}),
            50.0,
        )
        self.assertEqual(
            extract_focal_length_mm({}, {"focal_length": "24mm"}),
            24.0,
        )
        self.assertEqual(
            extract_focal_length_mm({}, {"lens": "180mm macro f/3.5"}),
            180.0,
        )
        self.assertIsNone(
            extract_focal_length_mm({"LensModel": "24-70mm F2.8 DG DN II"}, {})
        )

        # Verify classify_focal_band
        self.assertEqual(classify_focal_band(24.0)["key"], "wide_24")
        self.assertEqual(classify_focal_band(35.0)["key"], "semi_wide_35")
        self.assertEqual(classify_focal_band(50.0)["key"], "standard_50")
        self.assertEqual(classify_focal_band(70.0)["key"], "portrait_85")
        self.assertEqual(classify_focal_band(105.0)["key"], "tele_100")
        self.assertEqual(classify_focal_band(None)["key"], "unknown")

        # Update mock DB rows with EXIF / detected_camera_settings and strengths/improvements
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE photo_analyses SET exif_json = ?, analysis_json = ? WHERE id = 1",
                (
                    json.dumps({"FocalLengthIn35mmFilm": 85, "LensModel": "85mm F1.4"}),
                    json.dumps({
                        "final_score": 9.2,
                        "lighting_score": 9.5,
                        "composition_score": 9.0,
                        "color_score": 9.0,
                        "technique_score": 9.3,
                        "strengths": ["눈동자 초점이 매우 선명함", "아름다운 배경 흐림과 보케 분리"],
                        "improvements": ["약한 림라이트를 더해 입체감을 보강하기"],
                    }),
                ),
            )
            conn.execute(
                "UPDATE photo_analyses SET exif_json = ?, analysis_json = ? WHERE id = 2",
                (
                    json.dumps({"FocalLength": 50.0, "LensModel": "24-70mm F2.8"}),
                    json.dumps({
                        "final_score": 8.0,
                        "lighting_score": 8.0,
                        "composition_score": 8.5,
                        "color_score": 8.0,
                        "technique_score": 7.5,
                        "strengths": ["자연스러운 야외 공간감 연출"],
                        "improvements": ["하단 여백과 가장자리 잘림 확보 필요"],
                    }),
                ),
            )
            conn.execute(
                "UPDATE photo_analyses SET exif_json = ?, analysis_json = ? WHERE id = 3",
                (
                    json.dumps({}),
                    json.dumps({
                        "final_score": 6.5,
                        "lighting_score": 6.0,
                        "composition_score": 6.5,
                        "color_score": 7.0,
                        "technique_score": 6.5,
                        "detected_camera_settings": {"focal_length": "24mm"},
                        "strengths": ["자연광 활용"],
                        "improvements": ["배경의 시선 분산 요소를 덜어내고 정리하기"],
                    }),
                ),
            )

        fstats = get_focal_stats(self.db_path, min_count=1)
        self.assertEqual(fstats["total_photos"], 3)
        self.assertEqual(fstats["identified_photos"], 3)
        self.assertEqual(fstats["unknown_photos"], 0)
        self.assertEqual(fstats["best_band"]["band_key"], "portrait_85")
        self.assertEqual(fstats["weakest_band"]["band_key"], "wide_24")

        bands_by_key = {b["band_key"]: b for b in fstats["bands"]}
        self.assertIn("portrait_85", bands_by_key)
        self.assertIn("standard_50", bands_by_key)
        self.assertIn("wide_24", bands_by_key)
        self.assertTrue(len(bands_by_key["portrait_85"]["top_strengths"]) >= 1)
        self.assertTrue(len(bands_by_key["wide_24"]["top_improvements"]) >= 1)


if __name__ == "__main__":
    unittest.main()

