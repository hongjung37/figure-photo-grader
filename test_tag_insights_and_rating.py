import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from photo_dashboard import ensure_db_columns, get_all_analyses, get_tag_stats
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
                        "light_expression": ["자연광", "확산광"],
                        "composition_space": ["삼분할 구도", "클로즈업"],
                        "mood": ["화사함"]
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
                        "light_expression": ["자연광"],
                        "composition_space": ["중앙 구도"],
                        "mood": ["청량함"]
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
                        "light_expression": ["저조도"],
                        "composition_space": ["중앙 구도"],
                        "mood": ["다크·누아르"]
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
            conn.execute("INSERT INTO photo_analysis_tags VALUES (1, 'light_expression', '자연광')")
            conn.execute("INSERT INTO photo_analysis_tags VALUES (1, 'light_expression', '확산광')")
            conn.execute("INSERT INTO photo_analysis_tags VALUES (1, 'composition_space', '삼분할 구도')")
            conn.execute("INSERT INTO photo_analysis_tags VALUES (1, 'composition_space', '클로즈업')")
            conn.execute("INSERT INTO photo_analysis_tags VALUES (1, 'mood', '화사함')")

            conn.execute("INSERT INTO photo_analysis_tags VALUES (2, 'light_expression', '자연광')")
            conn.execute("INSERT INTO photo_analysis_tags VALUES (2, 'composition_space', '중앙 구도')")
            conn.execute("INSERT INTO photo_analysis_tags VALUES (2, 'mood', '청량함')")

            conn.execute("INSERT INTO photo_analysis_tags VALUES (3, 'light_expression', '저조도')")
            conn.execute("INSERT INTO photo_analysis_tags VALUES (3, 'composition_space', '중앙 구도')")
            conn.execute("INSERT INTO photo_analysis_tags VALUES (3, 'mood', '다크·누아르')")

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

        # min_count=2: only '자연광' (count=2) and '중앙 구도' (count=2) should appear
        stats_min2 = get_tag_stats(self.db_path, min_count=2)
        self.assertEqual(stats_min2["total_photos"], 3)
        self.assertEqual(stats_min2["user_rated_photos"], 1)

        tags_min2 = {t["tag"]: t for t in stats_min2["all_tags"]}
        self.assertIn("자연광", tags_min2)
        self.assertIn("중앙 구도", tags_min2)
        self.assertNotIn("저조도", tags_min2)  # count is 1

        # Check '자연광' average: (9.2 + 8.0) / 2 = 8.6
        self.assertAlmostEqual(tags_min2["자연광"]["avg_ai_score"], 8.6, places=1)
        self.assertEqual(tags_min2["자연광"]["count"], 2)
        self.assertEqual(tags_min2["자연광"]["user_rated_count"], 1)
        self.assertEqual(tags_min2["자연광"]["avg_user_score"], 9.5)
        # diff = 9.5 - 8.6 = +0.9
        self.assertAlmostEqual(tags_min2["자연광"]["score_diff"], 0.9, places=1)

        # min_count=1: all tags appear
        stats_min1 = get_tag_stats(self.db_path, min_count=1)
        tags_min1 = {t["tag"]: t for t in stats_min1["all_tags"]}
        self.assertIn("저조도", tags_min1)
        self.assertAlmostEqual(tags_min1["저조도"]["avg_ai_score"], 6.5, places=1)

        # Check Top and Bottom AI tags
        self.assertEqual(stats_min1["top_ai_tags"][0]["tag"], "확산광")  # score 9.2 (along with 삼분할 구도, 클로즈업, 화사함)
        self.assertEqual(stats_min1["bottom_ai_tags"][0]["tag"], "저조도")  # score 6.5

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
                self.assertEqual(tags["자연광"]["avg_user_score"], 8.8)

            # 3. Test POST /api/rate to clear score
            req_data_clear = json.dumps({"id": 1, "user_score": None}).encode("utf-8")
            req_clear = urllib.request.Request(
                f"{base_url}/api/rate",
                data=req_data_clear,
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req_clear) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(res["success"])
                self.assertIsNone(res["user_score"])
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()

