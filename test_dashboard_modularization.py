import unittest
from pathlib import Path
from http import HTTPStatus
import socketserver
import threading
import urllib.request

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
        css_path = Path("static/dashboard.css")
        js_path = Path("static/dashboard.js")
        tmpl_path = Path("templates/index.html")

        self.assertTrue(css_path.is_file(), "static/dashboard.css should exist")
        self.assertTrue(js_path.is_file(), "static/dashboard.js should exist")
        self.assertTrue(tmpl_path.is_file(), "templates/index.html should exist")

        css = css_path.read_text(encoding="utf-8")
        js = js_path.read_text(encoding="utf-8")
        tmpl = tmpl_path.read_text(encoding="utf-8")

        # Verify darkroom rules in CSS
        self.assertIn("body.darkroom", css)
        self.assertIn("--paper", css)
        self.assertIn("--card", css)
        self.assertIn("--ink", css)

        # Verify theme functions in JS
        self.assertIn("function toggleTheme", js)
        self.assertIn("function initTheme", js)
        self.assertIn("localStorage.setItem('theme'", js)

        # Verify template links and theme button
        self.assertIn('href="/static/dashboard.css"', tmpl)
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
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == "__main__":
    unittest.main()
