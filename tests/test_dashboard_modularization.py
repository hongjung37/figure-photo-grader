import unittest
import sys
from pathlib import Path
from http import HTTPStatus
import socketserver
import threading
import urllib.request

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import burst_clustering
import photo_dashboard


class DashboardModularizationTests(unittest.TestCase):
    def test_burst_clustering_standalone(self):
        # 1. are_filenames_sequential
        self.assertTrue(burst_clustering.are_filenames_sequential("IMG_0100.jpg", "IMG_0101.jpg"))
        self.assertTrue(burst_clustering.are_filenames_sequential("sample (1).png", "sample.png"))
        self.assertFalse(burst_clustering.are_filenames_sequential("foo.jpg", "bar.jpg"))

        # 2. re-export in photo_dashboard
        self.assertIs(photo_dashboard.are_filenames_sequential, burst_clustering.are_filenames_sequential)
        self.assertIs(photo_dashboard.cluster_burst_groups, burst_clustering.cluster_burst_groups)
        self.assertIs(photo_dashboard.are_burst_pair, burst_clustering.are_burst_pair)
        self.assertIs(photo_dashboard.parse_photo_time, burst_clustering.parse_photo_time)

    def test_darkroom_theme_and_static_files(self):
        css_path = PROJECT_ROOT / "static/dashboard.css"
        js_path = PROJECT_ROOT / "static/dashboard.js"
        crop_js_path = PROJECT_ROOT / "static/js/crop_viewer.js"
        detail_js_path = PROJECT_ROOT / "static/js/detail_modal.js"
        tmpl_path = PROJECT_ROOT / "templates/index.html"

        self.assertTrue(css_path.is_file(), "static/dashboard.css should exist")
        self.assertTrue(js_path.is_file(), "static/dashboard.js should exist")
        self.assertTrue(crop_js_path.is_file(), "static/js/crop_viewer.js should exist")
        self.assertTrue(detail_js_path.is_file(), "static/js/detail_modal.js should exist")
        self.assertTrue(tmpl_path.is_file(), "templates/index.html should exist")

        css = css_path.read_text(encoding="utf-8")
        js = js_path.read_text(encoding="utf-8")
        detail_js = detail_js_path.read_text(encoding="utf-8")
        js_all = js + "\n" + detail_js
        tmpl = tmpl_path.read_text(encoding="utf-8")

        # Verify darkroom rules in CSS
        self.assertIn("body.darkroom", css)
        self.assertIn("--paper", css)
        self.assertIn("--card", css)
        self.assertIn("--ink", css)
        self.assertIn("body.darkroom .strengths-box", css)
        self.assertIn("body.darkroom .improvements-box", css)
        self.assertIn("body.darkroom .lr-advice-box", css)
        self.assertIn("body.darkroom .user-score-section", css)

        # Verify theme functions and classes in JS
        self.assertIn("function toggleTheme", js)
        self.assertIn("function initTheme", js)
        self.assertIn("localStorage.setItem('theme'", js)
        self.assertIn('class="strengths-box"', js_all)
        self.assertIn('class="improvements-box"', js_all)
        self.assertIn('class="user-score-section"', js_all)
        self.assertIn('class="lr-advice-box"', js_all)

        # Verify template links and theme button
        self.assertIn('href="/static/dashboard.css"', tmpl)
        self.assertIn('src="/static/js/crop_viewer.js"', tmpl)
        self.assertIn('src="/static/dashboard.js"', tmpl)
        self.assertIn('id="theme-toggle-btn"', tmpl)
        self.assertIn('onclick="toggleTheme()"', tmpl)

    def test_http_static_and_template_routing(self):
        class EphemeralServer(socketserver.TCPServer):
            allow_reuse_address = True

        handler = photo_dashboard.DashboardRequestHandler
        httpd = EphemeralServer(("127.0.0.1", 0), handler)
        port = httpd.server_address[1]

        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()

        try:
            # 1. Root /
            req = urllib.request.urlopen(f"http://127.0.0.1:{port}/")
            self.assertEqual(req.status, HTTPStatus.OK)
            self.assertIn("text/html", req.headers.get("Content-Type"))
            html_body = req.read().decode("utf-8")
            self.assertIn("피규어 포토 그레이더", html_body)
            self.assertIn("theme-toggle-btn", html_body)

            # 2. Static CSS
            req_css = urllib.request.urlopen(f"http://127.0.0.1:{port}/static/dashboard.css")
            self.assertEqual(req_css.status, HTTPStatus.OK)
            self.assertIn("text/css", req_css.headers.get("Content-Type"))
            css_body = req_css.read().decode("utf-8")
            self.assertIn("body.darkroom", css_body)

            # 3. Static JS
            req_js = urllib.request.urlopen(f"http://127.0.0.1:{port}/static/dashboard.js")
            self.assertEqual(req_js.status, HTTPStatus.OK)
            self.assertIn("application/javascript", req_js.headers.get("Content-Type"))
            js_body = req_js.read().decode("utf-8")
            self.assertIn("toggleTheme", js_body)

            # 4. Modular Crop Viewer JS
            req_crop_js = urllib.request.urlopen(f"http://127.0.0.1:{port}/static/js/crop_viewer.js")
            self.assertEqual(req_crop_js.status, HTTPStatus.OK)
            self.assertIn("application/javascript", req_crop_js.headers.get("Content-Type"))
            crop_js_body = req_crop_js.read().decode("utf-8")
            self.assertIn("calculateExactCrop", crop_js_body)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_ai_best_pick_and_original_no_crop(self):
        import json
        import subprocess

        css_path = PROJECT_ROOT / "static/dashboard.css"
        crop_js_path = PROJECT_ROOT / "static/js/crop_viewer.js"
        css = css_path.read_text(encoding="utf-8")
        crop_js = crop_js_path.read_text(encoding="utf-8")

        # 1. Verify CSS classes for AI Best Pick banner and badges
        self.assertIn(".best-ratio-banner", css)
        self.assertIn(".best-ratio-badge-pill", css)
        self.assertIn(".best-ratio-badge", css)
        self.assertIn(".is-best-ratio-btn", css)
        self.assertIn("body.darkroom .best-ratio-banner", css)

        # 2. Verify JS components and No Crop options in crop_viewer.js
        self.assertIn("원본 유지 (No Crop)", crop_js)
        self.assertIn("best_ratio_key", crop_js)
        self.assertIn("best_ratio_reason", crop_js)
        self.assertIn("original_tip", crop_js)
        self.assertIn("원본 구도에 대한 AI 분석", crop_js)
        self.assertIn("AI 제안과의 비교", crop_js)
        self.assertIn("best-ratio-banner", crop_js)
        self.assertIn("👑 AI Best Pick", crop_js)
        self.assertIn("👑 AI 추천", crop_js)
        self.assertIn("downloadCroppedImage", crop_js)

        # 3. Test calculateExactCrop in node with 'original' returning null
        func_body = "function calculateExactCrop" + crop_js.split("function calculateExactCrop")[1].split("function selectCropRatio")[0]
        node_script = """
        const TARGET_CROP_RATIOS = {
          original: { name: 'Original', tag: '원본 유지 (No Crop)', w: 0, h: 0, ratio: 0 },
          instagram_crop_1_1: { name: '1:1', tag: '1:1', w: 1, h: 1, ratio: 1.0 },
          x_crop_16_9: { name: '16:9', tag: '16:9', w: 16, h: 9, ratio: 16/9 }
        };
        """ + func_body + """
        const box = { ymin: 0.1, xmin: 0.1, ymax: 0.9, xmax: 0.9 };
        const cropOriginal = calculateExactCrop('original', box, 4000, 3000);
        const crop11 = calculateExactCrop('instagram_crop_1_1', box, 4000, 3000);
        console.log(JSON.stringify({ cropOriginal, crop11 }));
        """
        res = subprocess.run(["node", "-e", node_script], capture_output=True, text=True, check=True)
        data = json.loads(res.stdout.strip())
        self.assertIsNone(data["cropOriginal"], "calculateExactCrop on 'original' must return null")
        self.assertIsNotNone(data["crop11"], "calculateExactCrop on valid ratio must return crop data")

        # 4. Test renderCropRatioDetailArea and renderSnsAdviceContent execution in Node
        # Verifies that 'item' is defined and no ReferenceError occurs, and XSS is escaped.
        exec_script = """
        const allData = [{
            id: 42,
            filename: 'fig.jpg',
            composition_notes: '피규어 전신과 베이스 배치가 균형 잡힘',
            sns_advice: {
                best_ratio_key: 'instagram_crop_4_5',
                best_ratio_reason: '얼굴 집중 클로즈업 <script>alert("xss")</script>',
                original_tip: '배경 공간감 보존',
                instagram_crop_4_5: { ratio_label: '4:5', composition_tip: '헤드룸 확보' }
            }
        }];
        """ + crop_js + """
        currentCropRatioKey = 'original';
        // Test 1: render original when best_ratio_key is instagram_crop_4_5 (must not throw ReferenceError)
        const htmlCropOther = renderCropRatioDetailArea('original', allData[0].sns_advice, 42);

        // Test 2: render original when best_ratio_key is original
        const advOriginal = {
            best_ratio_key: 'original',
            best_ratio_reason: '원본 구도가 완벽함 <b>굵게</b>',
            original_tip: '원본 여백 최적'
        };
        const htmlCropOrig = renderCropRatioDetailArea('original', advOriginal, 42);

        // Test 3: render full advice container
        const htmlFull = renderSnsAdviceContent(allData[0].sns_advice, 42);

        console.log(JSON.stringify({ htmlCropOther, htmlCropOrig, htmlFull }));
        """
        res_exec = subprocess.run(["node"], input=exec_script, capture_output=True, text=True, encoding="utf-8", check=True)
        exec_data = json.loads(res_exec.stdout.strip())
        self.assertIn("원본 구도에 대한 AI 분석", exec_data["htmlCropOther"])
        self.assertIn("&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;", exec_data["htmlCropOther"])
        self.assertNotIn("<script>", exec_data["htmlCropOther"])
        self.assertIn("👑 AI Best Pick", exec_data["htmlCropOrig"])
        self.assertIn("&lt;b&gt;굵게&lt;/b&gt;", exec_data["htmlCropOrig"])
        self.assertNotIn("<b>굵게</b>", exec_data["htmlCropOrig"])


if __name__ == "__main__":
    unittest.main()
