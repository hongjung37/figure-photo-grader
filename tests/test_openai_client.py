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
        o_res = self._sample_analysis(8.4, "OpenAI")
        o_cross = OpenAICrossCheck(
            score=8.4,
            reason="OpenAI",
            strengths=["디테일"],
            improvements=["각도"],
            composition_critique="[장점] 구도 좋음",
            lighting_critique="[장점] 자연스러움",
        )

        with patch("app.services.multi_llm.analyze_with_gemini", return_value=g_res) as mock_g, \
             patch("app.services.multi_llm.cross_check_with_openai", return_value=o_cross) as mock_cross, \
             patch("app.services.multi_llm.analyze_with_openai", return_value=o_res) as mock_o:

            # Provider: gemini
            res1 = analyze_photo(self.sample_photo, provider="gemini")
            self.assertEqual(res1.final_reason, "Gemini")
            mock_g.assert_called_once()
            mock_cross.assert_not_called()
            mock_o.assert_not_called()

            # Provider: openai -> routes to analyze_with_openai (Luna standalone supported)
            mock_g.reset_mock()
            mock_cross.reset_mock()
            mock_o.reset_mock()
            res2 = analyze_photo(self.sample_photo, provider="openai")
            self.assertEqual(res2.final_reason, "OpenAI")
            mock_g.assert_not_called()
            mock_o.assert_called_once()

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

    def test_ensemble_with_median_sampling(self) -> None:
        from app.models.analysis import OpenAICrossCheck
        from app.services.multi_llm import analyze_photo, get_last_sampled_scores

        g1 = self._sample_analysis(6.0, "Gemini sample 1")
        g2 = self._sample_analysis(7.0, "Gemini sample 2")
        g3 = self._sample_analysis(6.5, "Gemini sample 3")
        o_cross = OpenAICrossCheck(
            score=7.8,
            reason="OpenAI Luna 단독 평가",
            strengths=["디테일 우수"],
            improvements=["조명"],
            composition_critique="[장점] 안정적",
            lighting_critique="[장점] 자연광",
        )

        with patch("app.services.multi_llm.analyze_with_gemini", side_effect=[g1, g2, g3]) as mock_g, \
             patch("app.services.multi_llm.cross_check_with_openai", return_value=o_cross) as mock_cross:

            res = analyze_photo(
                self.sample_photo,
                provider="ensemble",
                model="ensemble(gemini-3.5-flash-lite+gpt-6-luna)",
                sample_count=3,
            )

            # Gemini sampled 3 times for median
            self.assertEqual(mock_g.call_count, 3)
            # Luna called exactly ONCE
            self.assertEqual(mock_cross.call_count, 1)

            # Median of [6.0, 6.5, 7.0] is 6.5
            self.assertEqual(res.final_score, 6.5)
            self.assertEqual(res.final_reason, "Gemini sample 3")
            self.assertIsNotNone(res.cross_check_opinion)
            self.assertEqual(res.cross_check_opinion.score, 7.8)

            # Sampled scores retrieved via get_last_sampled_scores
            sampled = get_last_sampled_scores()
            self.assertIsNotNone(sampled)
            self.assertEqual(sorted(sampled), [6.0, 6.5, 7.0])

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

    def test_cross_check_score_scaling(self) -> None:
        from app.models.analysis import CrossCheckOpinion, OpenAICrossCheck

        # 100-point scale should automatically rescale by dividing by 10
        critique = OpenAICrossCheck(
            score=78.0,
            reason="Good",
            strengths=["A"],
            improvements=["B"],
            composition_critique="Good",
            lighting_critique="Good",
        )
        self.assertEqual(critique.score, 7.8)

        # Clamping above 100 or below 0
        opinion = CrossCheckOpinion(
            score=105.0,
            reason="Great",
        )
        self.assertEqual(opinion.score, 10.0)

        opinion_low = CrossCheckOpinion(
            score=-5.0,
            reason="Poor",
        )
        self.assertEqual(opinion_low.score, 0.0)

    def test_heal_choice_keyword_mapping(self) -> None:
        from app.models.analysis import FOCUS_STATUS_OPTIONS, FIGURE_CATEGORY_CHOICES, _heal_choice

        # '초점 완벽' should map to '완벽 칼초점' and not mistakenly misclassify
        healed_focus = _heal_choice("초점 완벽", FOCUS_STATUS_OPTIONS, field_name="focus_status")
        self.assertEqual(healed_focus, "완벽 칼초점")

        # '매크로 접사 사진' should map to '접사/디테일'
        healed_cat = _heal_choice("매크로 접사 사진", FIGURE_CATEGORY_CHOICES, field_name="figure_category")
        self.assertEqual(healed_cat, "접사/디테일")

    def test_single_sns_crop_endpoint_patch_preserves_other_ratios(self) -> None:
        """Verify that ?force=true on a specific ratio key only patches that ratio and does not overwrite all crops."""
        from io import BytesIO
        import json
        import tempfile
        from PIL import Image
        from unittest.mock import MagicMock, patch
        from app.db import ensure_db_columns, save_analysis, update_sns_advice
        from app.models.analysis import PhotoAnalysis
        from app.models.crop import CropBox
        from app.services.image_processor import prepare_photo_from_bytes
        from app.web.handlers import DashboardRequestHandler

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "test_crop.sqlite3"
            img = Image.new("RGB", (32, 24), (100, 150, 200))
            bio = BytesIO()
            img.save(bio, format="JPEG")
            valid_photo = prepare_photo_from_bytes(bio.getvalue(), filename="crop_test.jpg")

            sample_analysis = PhotoAnalysis(
                composition_score=8.0,
                composition_notes="좋음",
                lighting_score=8.0,
                lighting_notes="좋음",
                color_score=8.0,
                color_notes="좋음",
                technique_score=8.0,
                technique_notes="좋음",
                final_score=8.0,
                final_reason="전체적으로 균형 잡힘",
                strengths=["장점"],
                improvements=["단점"],
                focus_status="완벽 칼초점",
                figure_category="일반 피규어 촬영",
            )
            rec_id = save_analysis(db_path, valid_photo, "test-model", sample_analysis)
            ensure_db_columns(db_path)

            initial_advice = {
                "best_ratio_key": "instagram_crop_4_5",
                "best_ratio_reason": "피규어의 전신이 가장 균형 있게 들어옴",
                "original_tip": "배경 여백을 살려보세요",
                "instagram_crop_4_5": {"ymin": 0.05, "xmin": 0.1, "ymax": 0.95, "xmax": 0.9, "ratio_label": "4:5", "composition_tip": "세로 전신"},
                "instagram_crop_1_1": {"ymin": 0.1, "xmin": 0.1, "ymax": 0.9, "xmax": 0.9, "ratio_label": "1:1", "composition_tip": "구버전 정사각형"},
                "x_crop_16_9": {"ymin": 0.2, "xmin": 0.05, "ymax": 0.8, "xmax": 0.95, "ratio_label": "16:9", "composition_tip": "와이드"},
                "x_crop_3_4": {"ymin": 0.1, "xmin": 0.15, "ymax": 0.9, "xmax": 0.85, "ratio_label": "3:4", "composition_tip": "피드"},
            }
            update_sns_advice(db_path, rec_id, json.dumps(initial_advice))

            handler = DashboardRequestHandler.__new__(DashboardRequestHandler)
            handler.db_path = db_path
            handler.wfile = BytesIO()
            handler.send_response = MagicMock()
            handler.send_header = MagicMock()
            handler.end_headers = MagicMock()

            # Mock single crop returned by LLM
            patched_box = CropBox(
                ymin=0.15,
                xmin=0.15,
                ymax=0.85,
                xmax=0.85,
                ratio_label="1:1",
                composition_tip="새로 제안된 1:1 크롭",
            )

            handler.path = f"/api/sns-crop/instagram_crop_1_1/{rec_id}?force=true&model=luna"

            with patch("app.web.handlers.suggest_single_sns_crop", return_value=patched_box) as mock_single, \
                 patch("app.web.handlers.suggest_all_sns_crops") as mock_all:
                handler.do_POST()

                mock_single.assert_called_once()
                self.assertEqual(mock_single.call_args.kwargs.get("ratio_key"), "instagram_crop_1_1")
                # suggest_all_sns_crops must NOT be called, saving tokens and preserving other crops!
                mock_all.assert_not_called()

            resp = json.loads(handler.wfile.getvalue().decode("utf-8"))
            self.assertTrue(resp["success"])
            self.assertFalse(resp["cached"])
            # instagram_crop_1_1 should be updated
            self.assertEqual(resp["crop_box"]["composition_tip"], "새로 제안된 1:1 크롭")
            # Other ratios must remain completely intact!
            self.assertEqual(resp["advice"]["instagram_crop_4_5"]["composition_tip"], "세로 전신")
            self.assertEqual(resp["advice"]["x_crop_16_9"]["composition_tip"], "와이드")
            self.assertEqual(resp["advice"]["best_ratio_key"], "instagram_crop_4_5")

    def test_cli_and_batch_pipeline_multi_llm_connection(self) -> None:
        """Verify that CLI parser and batch_service accept luna and ensemble and route to multi_llm."""
        from app.cli import build_parser, _dispatch_analyze
        from app.config import ALL_MODEL_PRESETS
        from app.services.batch_service import _dispatch_analyze as batch_dispatch_analyze

        # 1. CLI parser choices include all multi-LLM models
        parser = build_parser()
        tier_action = next(a for a in parser._actions if "--tier" in a.option_strings)
        self.assertIn("luna", tier_action.choices)
        self.assertIn("ensemble", tier_action.choices)
        self.assertEqual(set(tier_action.choices), set(ALL_MODEL_PRESETS.keys()))

        # 2. CLI dispatch calls multi_llm.analyze_photo
        with patch("app.cli.analyze_photo") as mock_analyze:
            mock_analyze.return_value = MagicMock()
            _dispatch_analyze(self.sample_photo, model="luna", category=None)
            mock_analyze.assert_called_once_with(self.sample_photo, provider="openai", model="gpt-6-luna", category_hint=None)

        # 3. Batch dispatch calls multi_llm.analyze_photo
        with patch("app.services.multi_llm.analyze_photo") as mock_batch_analyze:
            mock_batch_analyze.return_value = MagicMock()
            batch_dispatch_analyze(self.sample_photo, model="ensemble")
            mock_batch_analyze.assert_called_once_with(self.sample_photo, provider="ensemble", model=ALL_MODEL_PRESETS["ensemble"], category_hint=None)

    def test_multi_llm_analyze_photo_non_gemini_model_fallback(self) -> None:
        """Verify that when an unsupported non-Gemini model is passed to provider=gemini, it safely falls back to DEFAULT_MODEL."""
        from app.config import DEFAULT_MODEL
        from app.services.multi_llm import analyze_photo

        sample_res = self._sample_analysis(8.0, "Good")

        # Unsupported non-gemini model string to provider=gemini: safely falls back to DEFAULT_MODEL avoiding 404
        with patch("app.services.multi_llm.analyze_with_gemini", return_value=sample_res) as mock_gemini:
            res = analyze_photo(self.sample_photo, provider="gemini", model="unsupported-claude-model")
            self.assertEqual(res.final_score, 8.0)
            mock_gemini.assert_called_once_with(
                photo=self.sample_photo,
                model=DEFAULT_MODEL,
                category_hint=None,
            )

        # Provider: openai with luna: routes to analyze_with_openai
        with patch("app.services.multi_llm.analyze_with_openai", return_value=sample_res) as mock_openai:
            res2 = analyze_photo(self.sample_photo, provider="openai", model="gpt-6-luna")
            self.assertEqual(res2.final_score, 8.0)
            mock_openai.assert_called_once_with(
                photo=self.sample_photo,
                model="gpt-6-luna",
                category_hint=None,
                api_key=None,
            )


if __name__ == "__main__":
    unittest.main()

