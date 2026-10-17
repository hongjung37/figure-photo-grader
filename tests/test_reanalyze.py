import json
import socketserver
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import (
    get_analysis_by_id,
    save_analysis,
    update_analysis,
    update_cross_check_opinion,
)
import io
from PIL import Image

from app.models.analysis import (
    AestheticTags,
    CrossCheckOpinion,
    OpenAICrossCheck,
    PhotoAnalysis,
)
from app.services.image_processor import PreparedPhoto
from app.web.handlers import DashboardRequestHandler


def _get_dummy_image_bytes() -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", (64, 64), color=(120, 160, 220))
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_dummy_photo() -> PreparedPhoto:
    img_bytes = _get_dummy_image_bytes()
    return PreparedPhoto(
        source_filename="test_figure.jpg",
        sha256="abc1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
        width=64,
        height=64,
        image_format="JPEG",
        safe_exif={"Model": "Alpha 7 IV"},
        upload_bytes=img_bytes,
        upload_mime_type="image/jpeg",
        thumbnail_bytes=img_bytes,
        dhash=123456789,
    )


def _make_dummy_analysis(score: float = 8.5) -> PhotoAnalysis:
    return PhotoAnalysis(
        figure_category="일반 피규어 촬영",
        focus_status="완벽 칼초점",
        focus_notes="얼굴과 눈동자에 핀이 완벽함",
        composition_score=8.5,
        composition_notes="삼분할 구도",
        lighting_score=8.0,
        lighting_notes="측면 부드러운 확산광",
        color_score=8.5,
        color_notes="자연스러운 피부톤",
        technique_score=9.0,
        technique_notes="낮은 노이즈와 선명한 핀",
        final_score=score,
        final_reason="우수한 조형 디테일",
        strengths=["선명한 디테일", "안정된 노출"],
        improvements=["배경 분리 강화"],
        aesthetic_tags=AestheticTags.empty().model_copy(
            update={"viewpoint": ["아이레벨"], "mood": ["화사함"]}
        ),
    )


class ReanalyzeFeatureTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_reanalyze.sqlite3"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_repository_update_analysis_and_tags(self):
        photo = _make_dummy_photo()
        base_analysis = _make_dummy_analysis(score=7.5)
        record_id = save_analysis(self.db_path, photo, "gemini-2.5-flash-lite", base_analysis)

        # Verify initial state
        initial = get_analysis_by_id(self.db_path, record_id)
        self.assertIsNotNone(initial)
        self.assertEqual(initial["final_score"], 7.5)
        self.assertEqual(initial["model"], "gemini-2.5-flash-lite")
        self.assertIsNone(initial["cross_check_opinion"])

        # Update full analysis with new score and model
        updated_analysis = _make_dummy_analysis(score=9.2)
        updated_analysis.strengths = ["향상된 조명", "역동적 구도"]
        res = update_analysis(self.db_path, record_id, "gemini-3.0-flash", updated_analysis)

        self.assertIsNotNone(res)
        self.assertEqual(res["id"], record_id)
        self.assertEqual(res["final_score"], 9.2)
        self.assertEqual(res["model"], "gemini-3.0-flash")
        self.assertEqual(res["strengths"], ["향상된 조명", "역동적 구도"])

    def test_repository_update_cross_check_opinion_preserves_base(self):
        photo = _make_dummy_photo()
        base_analysis = _make_dummy_analysis(score=8.0)
        record_id = save_analysis(self.db_path, photo, "gemini-3.5-flash-lite", base_analysis)

        opinion = CrossCheckOpinion(
            model="gpt-6-luna",
            score=8.7,
            reason="Luna: 음영 묘사와 디테일이 돋보입니다.",
            strengths=["얼굴 데칼 정밀도"],
            improvements=["하단 베이스 그림자 완화"],
            composition_critique="중앙 집중형으로 시선 유도가 좋음",
            lighting_critique="입체감을 살리는 측면광",
        )

        res = update_cross_check_opinion(self.db_path, record_id, opinion)
        self.assertIsNotNone(res)
        self.assertEqual(res["final_score"], 8.0)  # Preserves base Gemini score
        self.assertEqual(res["model"], "gemini-3.5-flash-lite")
        self.assertIsNotNone(res["cross_check_opinion"])
        self.assertEqual(res["cross_check_opinion"]["model"], "gpt-6-luna")
        self.assertEqual(res["cross_check_opinion"]["score"], 8.7)
        self.assertEqual(res["cross_check_opinion"]["composition_critique"], "중앙 집중형으로 시선 유도가 좋음")

    def test_api_reanalyze_http_endpoints(self):
        photo = _make_dummy_photo()
        base_analysis = _make_dummy_analysis(score=7.0)
        record_id = save_analysis(self.db_path, photo, "gemini-3.5-flash-lite", base_analysis)

        # Set up a local test HTTP server
        handler_class = DashboardRequestHandler
        handler_class.db_path = self.db_path

        server = socketserver.TCPServer(("127.0.0.1", 0), handler_class)
        port = server.server_address[1]
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()

        try:
            # 1. Test mode="cross_check_only"
            mock_cross_check = OpenAICrossCheck(
                score=8.4,
                reason="Luna 크로스체크 피드백",
                strengths=["풍부한 질감"],
                improvements=["배경 대비 조절"],
                composition_critique="안정적인 수평 구도",
                lighting_critique="피사체 강조가 뛰어남",
            )
            with patch("app.services.openai_client.cross_check_with_openai", return_value=mock_cross_check):
                req_data = json.dumps({
                    "id": record_id,
                    "mode": "cross_check_only",
                    "category": "auto",
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/reanalyze",
                    data=req_data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(body["success"])
                    analysis = body["analysis"]
                    self.assertEqual(analysis["final_score"], 7.0)  # Gemini score maintained
                    self.assertIsNotNone(analysis["cross_check_opinion"])
                    self.assertEqual(analysis["cross_check_opinion"]["score"], 8.4)
                    self.assertEqual(analysis["cross_check_opinion"]["reason"], "Luna 크로스체크 피드백")

            # 2. Test mode="full" with new model
            new_gemini_analysis = _make_dummy_analysis(score=9.5)
            with patch("app.web.handlers.analyze_photo", return_value=new_gemini_analysis):
                req_data = json.dumps({
                    "id": record_id,
                    "mode": "full",
                    "tier": "pro",
                    "category": "macro",
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/reanalyze",
                    data=req_data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req) as resp:
                    self.assertEqual(resp.status, 200)
                    body = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(body["success"])
                    analysis = body["analysis"]
                    self.assertEqual(analysis["final_score"], 9.5)
                    self.assertEqual(analysis["model"], "gemini-3.8-flash")
        finally:
            server.shutdown()
            server.server_close()

    def test_ui_and_css_integrity(self):
        js_path = PROJECT_ROOT / "static/dashboard.js"
        reanalyze_path = PROJECT_ROOT / "static/js/reanalyze.js"
        detail_path = PROJECT_ROOT / "static/js/detail_modal.js"
        css_path = PROJECT_ROOT / "static/dashboard.css"
        api_path = PROJECT_ROOT / "static/js/api.js"

        js = js_path.read_text(encoding="utf-8")
        reanalyze_js = reanalyze_path.read_text(encoding="utf-8") if reanalyze_path.is_file() else ""
        detail_js = detail_path.read_text(encoding="utf-8") if detail_path.is_file() else ""
        all_ui_js = js + "\n" + reanalyze_js + "\n" + detail_js
        css = css_path.read_text(encoding="utf-8")
        api = api_path.read_text(encoding="utf-8")

        # Check button label in UI is strictly '🔄 재평가'
        self.assertIn(">🔄 재평가</button>", all_ui_js)

        # Check supporting JS functions
        self.assertIn("function toggleReanalyzePanel", all_ui_js)
        self.assertIn("function renderReanalyzePanel", all_ui_js)
        self.assertIn("function executeReanalyze", all_ui_js)
        self.assertIn("function selectReanalyzeMode", all_ui_js)

        # Check API client method
        self.assertIn("reanalyzePhoto(id", api)

        # Check CSS rules and darkroom adaptation
        self.assertIn(".reanalyze-btn", css)
        self.assertIn("body.darkroom .reanalyze-btn", css)
        self.assertIn(".reanalyze-panel", css)
        self.assertIn("body.darkroom .reanalyze-panel", css)
        self.assertIn("body.darkroom .reanalyze-mode-card", css)


if __name__ == "__main__":
    unittest.main()
