from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.models.analysis import AestheticTags, PhotoAnalysis
from app.models.lightroom import LightroomAdvice
from app.services.image_processor import PreparedPhoto
from app.services.multi_llm import _merge_analyses, analyze_photo
from app.services.openai_client import (
    analyze_with_openai,
    suggest_lightroom_advice_with_openai,
)


class OpenAIClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sample_photo = PreparedPhoto(
            source_filename="test.jpg",
            sha256="abcdef1234567890" * 4,
            width=800,
            height=600,
            image_format="JPEG",
            safe_exif={"Make": "Sony"},
            upload_bytes=b"\xFF\xD8\xFF\xE0dummy_jpeg_data",
            upload_mime_type="image/jpeg",
        )

    def _sample_analysis(self, score: float = 8.0, reason: str = "Good") -> PhotoAnalysis:
        return PhotoAnalysis(
            composition_score=score,
            composition_notes="구도 분석",
            lighting_score=score,
            lighting_notes="조명 분석",
            color_score=score,
            color_notes="색감 분석",
            technique_score=score,
            technique_notes="기술 분석",
            final_score=score,
            final_reason=reason,
            strengths=["구도가 좋음"],
            improvements=["조명 각도 개선"],
            figure_category="일반 피규어 촬영",
            focus_status="완벽 칼초점",
            focus_notes="얼굴에 초점 맞음",
            aesthetic_tags=AestheticTags.empty().model_copy(
                update={"mood": ["고요함"], "viewpoint": ["정면"]}
            ),
        )

    def test_missing_api_key_raises_runtime_error(self) -> None:
        with patch.dict("os.environ", {}, clear=True), patch("app.services.openai_client.load_dotenv"):
            with self.assertRaises(RuntimeError) as ctx:
                analyze_with_openai(self.sample_photo, api_key=None)
            self.assertIn("OPENAI_API_KEY", str(ctx.exception))

    def test_analyze_with_openai_success(self) -> None:
        expected = self._sample_analysis(8.5, "훌륭한 피규어 사진")

        mock_choice = MagicMock()
        mock_choice.message.refusal = None
        mock_choice.message.parsed = expected

        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]
        mock_completion.usage.prompt_tokens = 150
        mock_completion.usage.completion_tokens = 50

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.return_value = mock_completion

        with patch("app.services.openai_client._get_client", return_value=mock_client):
            result = analyze_with_openai(
                self.sample_photo,
                model="gpt-4o-mini",
                api_key="sk-test-fake-key",
            )

        self.assertEqual(result.final_score, 8.5)
        mock_client.beta.chat.completions.parse.assert_called_once()
        call_kwargs = mock_client.beta.chat.completions.parse.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "gpt-4o-mini")
        self.assertEqual(call_kwargs["response_format"], PhotoAnalysis)

    def test_suggest_lightroom_advice_with_openai_success(self) -> None:
        expected_advice = LightroomAdvice(
            exposure=0.3,
            contrast=10,
            highlights=-15,
            shadows=20,
            whites=5,
            blacks=-5,
            texture=10,
            clarity=10,
            dehaze=5,
            vibrance=15,
            saturation=0,
            temp_tint_notes="5200K 유지, 틴트 +2",
            retouching_guide="얼굴 부분 암부를 살리고 채도를 보정합니다.",
        )

        mock_choice = MagicMock()
        mock_choice.message.refusal = None
        mock_choice.message.parsed = expected_advice

        mock_completion = MagicMock()
        mock_completion.choices = [mock_choice]
        mock_completion.usage.prompt_tokens = 100
        mock_completion.usage.completion_tokens = 30

        mock_client = MagicMock()
        mock_client.beta.chat.completions.parse.return_value = mock_completion

        with patch("app.services.openai_client._get_client", return_value=mock_client):
            advice = suggest_lightroom_advice_with_openai(
                self.sample_photo,
                self._sample_analysis(),
                model="gpt-4o-mini",
                api_key="sk-test-fake-key",
            )

        self.assertEqual(advice.exposure, 0.3)
        self.assertEqual(advice.shadows, 20)
        self.assertEqual(advice.retouching_guide, "얼굴 부분 암부를 살리고 채도를 보정합니다.")

    def test_multi_llm_ensemble_attaches_cross_check_without_averaging(self) -> None:
        from app.models.analysis import OpenAICrossCheck
        g_analysis = self._sample_analysis(7.0, "Gemini 평가: 노출 부족")
        o_cross = OpenAICrossCheck(
            score=9.0,
            reason="OpenAI 의견: 구도 우수",
            strengths=["안정적인 구도"],
            improvements=["조명 각도 개선"],
            composition_critique="[장점] 3분할 안정적 [단점] 여백 약간 부족",
            lighting_critique="[장점] 부드러운 빛 [단점] 암부 디테일 소실",
        )

        merged = _merge_analyses(g_analysis, o_cross)

        # Gemini score (7.0) is authoritatively preserved without averaging
        self.assertEqual(merged.final_score, 7.0)
        self.assertIsNotNone(merged.cross_check_opinion)
        self.assertEqual(merged.cross_check_opinion.score, 9.0)
        self.assertEqual(merged.cross_check_opinion.reason, "OpenAI 의견: 구도 우수")
        self.assertEqual(merged.cross_check_opinion.strengths, ["안정적인 구도"])

    def test_analyze_photo_router_provider_dispatch(self) -> None:
        from app.models.analysis import OpenAICrossCheck
        g_res = self._sample_analysis(8.0, "Gemini")
        o_cross = OpenAICrossCheck(
            score=8.4,
            reason="OpenAI",
            strengths=["디테일"],
            improvements=["각도"],
            composition_critique="[장점] 구도 좋음",
            lighting_critique="[장점] 자연스러움",
        )

        with patch("app.services.multi_llm.analyze_with_gemini", return_value=g_res) as mock_g, \
             patch("app.services.multi_llm.cross_check_with_openai", return_value=o_cross) as mock_cross:

            # Provider: gemini
            res1 = analyze_photo(self.sample_photo, provider="gemini")
            self.assertEqual(res1.final_reason, "Gemini")
            mock_g.assert_called_once()
            mock_cross.assert_not_called()

            # Provider: openai -> routes to Gemini because solo OpenAI is removed
            mock_g.reset_mock()
            mock_cross.reset_mock()
            res2 = analyze_photo(self.sample_photo, provider="openai")
            self.assertEqual(res2.final_reason, "Gemini")
            mock_g.assert_called_once()
            mock_cross.assert_not_called()

            # Provider: ensemble -> preserves Gemini 8.0, attaches OpenAI 8.4 cross-check
            mock_g.reset_mock()
            mock_cross.reset_mock()
            res3 = analyze_photo(self.sample_photo, provider="ensemble")
            self.assertEqual(res3.final_score, 8.0)
            self.assertIsNotNone(res3.cross_check_opinion)
            self.assertEqual(res3.cross_check_opinion.score, 8.4)
            mock_g.assert_called_once()
            self.assertEqual(mock_g.call_args.kwargs.get("model"), "gemini-3.5-flash-lite")
            mock_cross.assert_called_once()
            self.assertEqual(mock_cross.call_args.kwargs.get("model"), "gpt-6-luna")

            # Provider: ensemble with wrapper string
            mock_g.reset_mock()
            mock_cross.reset_mock()
            res4 = analyze_photo(
                self.sample_photo,
                provider="ensemble",
                model="ensemble(gemini-3.5-flash-lite+gpt-6-luna)",
            )
            self.assertEqual(res4.final_score, 8.0)
            mock_g.assert_called_once()
            self.assertEqual(mock_g.call_args.kwargs.get("model"), "gemini-3.5-flash-lite")
            mock_cross.assert_called_once()
            self.assertEqual(mock_cross.call_args.kwargs.get("model"), "gpt-6-luna")

    def test_resolve_task_model(self) -> None:
        from app.services.multi_llm import resolve_task_model

        self.assertEqual(resolve_task_model("lite"), ("gemini", "gemini-3.1-flash-lite"))
        self.assertEqual(resolve_task_model("standard"), ("gemini", "gemini-3.5-flash-lite"))
        self.assertEqual(resolve_task_model("flash-3.6"), ("gemini", "gemini-3.6-flash"))
        self.assertEqual(resolve_task_model("flash-3.7"), ("gemini", "gemini-3.7-flash"))
        self.assertEqual(resolve_task_model("pro"), ("gemini", "gemini-3.8-flash"))
        self.assertEqual(resolve_task_model("luna"), ("openai", "gpt-6-luna"))
        self.assertEqual(resolve_task_model("gpt-6-luna"), ("openai", "gpt-6-luna"))
        self.assertEqual(resolve_task_model("gpt-4o-mini"), ("openai", "gpt-4o-mini"))
        self.assertEqual(resolve_task_model(""), ("gemini", "gemini-3.1-flash-lite"))

    def test_multi_llm_task_routing_lightroom_and_sns(self) -> None:
        from app.models.crop import CropBox, CropSet, SNSCaptionAndTags
        from app.services.multi_llm import (
            suggest_all_sns_crops,
            suggest_lightroom_advice,
            suggest_sns_caption_and_tags,
        )

        dummy_lr = LightroomAdvice(
            exposure=0.1,
            contrast=5,
            highlights=-10,
            shadows=15,
            whites=0,
            blacks=0,
            texture=5,
            clarity=5,
            dehaze=0,
            vibrance=10,
            saturation=0,
            temp_tint_notes="5000K",
            retouching_guide="가이드",
        )
        dummy_box = CropBox(ymin=0.1, xmin=0.1, ymax=0.9, xmax=0.9, ratio_label="4:5", composition_tip="팁")
        dummy_crops = CropSet(
            best_ratio_key="instagram_crop_4_5",
            best_ratio_reason="최적",
            original_tip="원본 팁",
            instagram_crop_4_5=dummy_box,
            instagram_crop_1_1=dummy_box,
            x_crop_16_9=dummy_box,
            x_crop_3_4=dummy_box,
        )
        dummy_caption = SNSCaptionAndTags(
            social_caption="멋진 피규어 스냅",
            hashtags=["#피규어", "#토이포토"],
        )

        with patch("app.services.multi_llm.generate_lightroom_advice_with_gemini", return_value=dummy_lr) as mock_g_lr, \
             patch("app.services.multi_llm.suggest_lightroom_advice_with_openai", return_value=dummy_lr) as mock_o_lr:
            res_lr_g = suggest_lightroom_advice(self.sample_photo, model="pro")
            self.assertEqual(res_lr_g.exposure, 0.1)
            mock_g_lr.assert_called_once_with(photo=self.sample_photo, model="gemini-3.8-flash")

            res_lr_o = suggest_lightroom_advice(self.sample_photo, model="luna")
            self.assertEqual(res_lr_o.exposure, 0.1)
            mock_o_lr.assert_called_once()
            self.assertEqual(mock_o_lr.call_args.kwargs.get("model"), "gpt-6-luna")

        with patch("app.services.multi_llm.generate_all_sns_crops_with_gemini", return_value=dummy_crops) as mock_g_crop, \
             patch("app.services.multi_llm.generate_all_sns_crops_with_openai", return_value=dummy_crops) as mock_o_crop:
            res_crop_g = suggest_all_sns_crops(self.sample_photo, model="standard")
            self.assertEqual(res_crop_g.best_ratio_key, "instagram_crop_4_5")
            mock_g_crop.assert_called_once_with(photo=self.sample_photo, model="gemini-3.5-flash-lite")

            res_crop_o = suggest_all_sns_crops(self.sample_photo, model="luna")
            self.assertEqual(res_crop_o.best_ratio_key, "instagram_crop_4_5")
            mock_o_crop.assert_called_once_with(photo=self.sample_photo, model="gpt-6-luna", api_key=None)

        with patch("app.services.multi_llm.generate_sns_caption_and_tags_with_gemini", return_value=dummy_caption) as mock_g_cap, \
             patch("app.services.multi_llm.generate_sns_caption_and_tags_with_openai", return_value=dummy_caption) as mock_o_cap:
            res_cap_o = suggest_sns_caption_and_tags(self.sample_photo, model="luna")
            self.assertEqual(res_cap_o.social_caption, "멋진 피규어 스냅")
            mock_o_cap.assert_called_once_with(photo=self.sample_photo, model="gpt-6-luna", api_key=None)
            mock_g_cap.assert_not_called()


if __name__ == "__main__":
    unittest.main()
