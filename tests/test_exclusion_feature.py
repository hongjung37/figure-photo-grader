# -*- coding: utf-8 -*-
"""Unit tests for prompt test and statistical exclusion feature."""

import shutil
import tempfile
import unittest
from pathlib import Path
import hashlib

from app.db import (
    ensure_db_columns,
    get_all_analyses,
    get_focal_stats,
    get_tag_stats,
    save_analysis,
    update_analysis_excluded,
    batch_update_excluded,
)
from app.models.analysis import AestheticTags, PhotoAnalysis
from app.services.image_processor import PreparedPhoto


class TestExclusionFeature(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_photos.sqlite3"
        ensure_db_columns(self.db_path, force=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_mock_photo(self, filename: str, final_score: float, tags: list[str]) -> int:
        sha256 = hashlib.sha256(filename.encode("utf-8")).hexdigest()
        photo = PreparedPhoto(
            source_filename=filename,
            sha256=sha256,
            width=1000,
            height=1000,
            image_format="JPEG",
            safe_exif={},
            upload_bytes=b"dummy_bytes",
            upload_mime_type="image/jpeg",
            thumbnail_bytes=b"thumb_bytes",
        )
        analysis = PhotoAnalysis(
            figure_category="일반 피규어 촬영",
            focus_status="완벽 칼초점",
            focus_notes="선명함",
            composition_score=8.0,
            composition_notes="",
            lighting_score=8.5,
            lighting_notes="",
            color_score=8.0,
            color_notes="",
            technique_score=8.0,
            technique_notes="",
            final_score=final_score,
            final_reason="테스트",
            strengths=["선명한 조명"],
            improvements=[],
            aesthetic_tags=AestheticTags(
                viewpoint=[],
                composition_space=[],
                pose_gaze=[],
                mood=[],
                subject_background=[],
                light_expression=tags,
                color_impression=[],
                narrative_implication=[],
            ),
        )
        return save_analysis(self.db_path, photo, "gemini-2.5-flash", analysis)

    def test_exclude_photo_from_tag_and_focal_stats(self):
        # 1. Insert 3 photos (2 real, 1 prompt test photo)
        id1 = self._create_mock_photo("real_1.jpg", 9.0, ["자연광"])
        id2 = self._create_mock_photo("real_2.jpg", 8.0, ["자연광"])
        id3 = self._create_mock_photo("prompt_test.jpg", 3.0, ["역광"])

        # Check initial stats (3 photos)
        initial_stats = get_tag_stats(self.db_path)
        self.assertEqual(initial_stats["total_photos"], 3)
        self.assertEqual(initial_stats["excluded_photos"], 0)

        # 2. Exclude prompt_test.jpg
        ok = update_analysis_excluded(self.db_path, id3, True)
        self.assertTrue(ok)

        # Check tag stats (should exclude id3)
        filtered_stats = get_tag_stats(self.db_path)
        self.assertEqual(filtered_stats["total_photos"], 2)
        self.assertEqual(filtered_stats["excluded_photos"], 1)

        # Check focal stats (should also exclude id3)
        focal_stats = get_focal_stats(self.db_path)
        self.assertEqual(focal_stats["total_photos"], 2)
        self.assertEqual(focal_stats["excluded_photos"], 1)

        # 3. Test get_all_analyses flag
        all_items = get_all_analyses(self.db_path)
        item3 = next(i for i in all_items if i["id"] == id3)
        self.assertTrue(item3["is_excluded"])
        item1 = next(i for i in all_items if i["id"] == id1)
        self.assertFalse(item1["is_excluded"])

        # 4. Batch update test: include back
        batch_count = batch_update_excluded(self.db_path, [id3], False)
        self.assertEqual(batch_count, 1)

        restored_stats = get_tag_stats(self.db_path)
        self.assertEqual(restored_stats["total_photos"], 3)
        self.assertEqual(restored_stats["excluded_photos"], 0)


if __name__ == "__main__":
    unittest.main()
