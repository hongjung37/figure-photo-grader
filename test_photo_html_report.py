from __future__ import annotations

import base64
import tempfile
import unittest
from pathlib import Path

from photo_analyzer import PhotoAnalysis, PreparedPhoto
from photo_tag_schema import AestheticTags
from photo_html_report import render_html_report, save_html_report


class PhotoHtmlReportTests(unittest.TestCase):
    def _sample(self) -> tuple[PreparedPhoto, PhotoAnalysis]:
        photo = PreparedPhoto(
            source_filename="<script>alert('photo')</script>.jpg",
            sha256="b" * 64,
            width=1200,
            height=800,
            image_format="JPEG",
            safe_exif={},
            upload_bytes=b"safe-preview-bytes",
            upload_mime_type="image/jpeg",
        )
        analysis = PhotoAnalysis(
            composition_score=8.2,
            composition_notes="구도가 균형 잡혔습니다.",
            lighting_score=7.1,
            lighting_notes="<강한> 빛",
            color_score=9,
            color_notes="색이 조화롭습니다.",
            technique_score=6.5,
            technique_notes="초점을 확인해 보세요.",
            final_score=8.0,
            final_reason="전체적으로 <좋은> 사진입니다.",
            strengths=["선명한 피사체", "자연스러운 색"],
            improvements=["배경을 단순화해 보세요."],
            aesthetic_tags=AestheticTags.empty().model_copy(
                update={"viewpoint": ["측면"], "mood": ["고요함"]}
            ),
        )
        return photo, analysis

    def test_report_contains_scores_commentary_and_escaped_text(self) -> None:
        photo, analysis = self._sample()
        report = render_html_report(photo, analysis, record_id=17, model="test-model")

        self.assertIn("8.0", report)
        self.assertIn("구도", report)
        self.assertIn("7.1", report)
        self.assertIn("&lt;강한&gt; 빛", report)
        self.assertIn("&lt;좋은&gt; 사진입니다.", report)
        self.assertIn("&lt;script&gt;alert(&#x27;photo&#x27;)&lt;/script&gt;.jpg", report)
        self.assertNotIn("<script>alert('photo')</script>", report)
        self.assertIn(base64.b64encode(b"safe-preview-bytes").decode("ascii"), report)
        self.assertIn('role="meter"', report)
        self.assertIn("미학 태그", report)
        self.assertIn("시점", report)
        self.assertIn("측면", report)
        self.assertIn("분위기", report)
        self.assertIn("고요함", report)
        self.assertIn("매우 우수", report)
        self.assertIn("주요 장점", report)
        self.assertIn("단점 및 개선점", report)
        self.assertIn("점수 평가 기준", report)
        self.assertIn("프로사진작가 및 전문가급", report)

    def test_report_explains_when_legacy_record_has_no_tags(self) -> None:
        photo, analysis = self._sample()
        analysis.aesthetic_tags = AestheticTags.empty()
        report = render_html_report(photo, analysis, record_id=18, model="test-model")
        self.assertIn("이 기록에는 태그가 없습니다", report)
        self.assertIn("관찰된 태그 없음", report)

    def test_report_is_saved_as_a_standalone_html_file(self) -> None:
        photo, analysis = self._sample()
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = save_html_report(
                photo,
                analysis,
                record_id=3,
                model="test-model",
                output_path=Path(temporary_directory) / "result.html",
            )
            self.assertTrue(path.is_file())
            saved = path.read_text(encoding="utf-8")
            self.assertIn("PHOTO REVIEW", saved)
            self.assertIn("사진 분석 결과", saved)
            self.assertIn("data:image/jpeg;base64,", saved)

    def test_non_html_extension_is_rejected(self) -> None:
        photo, analysis = self._sample()
        with tempfile.TemporaryDirectory() as temporary_directory:
            with self.assertRaises(ValueError):
                save_html_report(photo, analysis, 1, "test-model", Path(temporary_directory) / "result.txt")


if __name__ == "__main__":
    unittest.main()
