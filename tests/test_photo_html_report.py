from __future__ import annotations

import base64
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from photo_analyzer import CrossCheckOpinion, PhotoAnalysis, PreparedPhoto
from photo_tag_schema import AestheticTags
from photo_html_report import render_batch_comparison_html, render_html_report, save_html_report


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

    def test_report_renders_watermark_settings_when_present(self) -> None:
        photo, analysis = self._sample()
        analysis.detected_camera_settings = {"Camera": "SONY A7M4", "FNumber": "F/1.4"}
        report = render_html_report(photo, analysis, record_id=19, model="test-model")
        self.assertIn("사진 내 워터마크 감지", report)
        self.assertIn("SONY A7M4", report)
        self.assertIn("F/1.4", report)

    def test_report_renders_cross_check_opinion(self) -> None:
        photo, analysis = self._sample()
        analysis.cross_check_opinion = CrossCheckOpinion(
            model="gpt-6-luna",
            score=8.7,
            reason="종합 총평: <안정적> 구도와 자연스러운 색감",
            strengths=["<우수한> 칼초점", "안정된 3분할"],
            improvements=["<배경> 단순화 필요"],
            composition_critique="중앙 집중형으로 시선 유도가 좋음",
            lighting_critique="림라이트 효과가 피규어 윤곽을 잘 살림",
        )
        report = render_html_report(photo, analysis, record_id=20, model="ensemble(flash-3.5+gpt-6-luna)")

        self.assertIn("Gemini + OpenAI 앙상블 분석", report)
        self.assertIn("🤝 앙상블 크로스체크", report)
        self.assertIn("OpenAI 크로스 체크 의견", report)
        self.assertIn("gpt-6-luna", report)
        self.assertIn("8.7", report)
        self.assertIn("매우 우수", report)
        self.assertIn("종합 총평: &lt;안정적&gt; 구도와 자연스러운 색감", report)
        self.assertIn("&lt;우수한&gt; 칼초점", report)
        self.assertIn("&lt;배경&gt; 단순화 필요", report)
        self.assertIn("중앙 집중형으로 시선 유도가 좋음", report)
        self.assertIn("림라이트 효과가 피규어 윤곽을 잘 살림", report)

    def test_report_without_cross_check_omits_section(self) -> None:
        photo, analysis = self._sample()
        analysis.cross_check_opinion = None
        report = render_html_report(photo, analysis, record_id=21, model="gemini-3.5-flash-lite")

        self.assertIn("Gemini 사진 분석", report)
        self.assertNotIn("🤝 앙상블 크로스체크", report)
        self.assertNotIn("OpenAI 크로스 체크 의견", report)

    def test_batch_comparison_renders_cross_check_badge(self) -> None:
        photo, analysis = self._sample()
        analysis.cross_check_opinion = CrossCheckOpinion(
            model="gpt-6-luna",
            score=8.7,
            reason="우수함",
            strengths=[],
            improvements=[],
        )
        results = [{
            "filename": "fig1.jpg",
            "analysis": analysis,
            "relative_report": "reports/fig1.html",
        }]
        html = render_batch_comparison_html(results, model="ensemble", db_path=Path("dummy.sqlite3"))
        self.assertIn("🤝 gpt-6-luna 8.7", html)


if __name__ == "__main__":
    unittest.main()

