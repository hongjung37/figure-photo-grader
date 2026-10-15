from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class FrontendIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.html = (PROJECT_ROOT / "templates/index.html").read_text(encoding="utf-8")
        self.js = (
            (PROJECT_ROOT / "static/js/api.js").read_text(encoding="utf-8")
            + "\n"
            + (PROJECT_ROOT / "static/js/tag_filter.js").read_text(encoding="utf-8")
            + "\n"
            + (PROJECT_ROOT / "static/js/crop_viewer.js").read_text(encoding="utf-8")
            + "\n"
            + (PROJECT_ROOT / "static/dashboard.js").read_text(encoding="utf-8")
        )

    def test_dom_ids_exist(self):
        ids = set(re.findall(r"document\.getElementById\(['\"]([a-zA-Z0-9_-]+)['\"]\)", self.js))
        self.assertGreater(len(ids), 30)

        missing = []
        for el_id in sorted(ids):
            in_html = f'id="{el_id}"' in self.html or f"id='{el_id}'" in self.html
            in_js = f'id="{el_id}"' in self.js or f"id='{el_id}'" in self.js
            if not in_html and not in_js:
                missing.append(el_id)
        self.assertEqual(missing, [], f"DOM IDs referenced in JS but missing in HTML: {missing}")

    def test_html_event_handlers_exist(self):
        handlers = set(re.findall(r'on(?:click|change|dragover|dragleave|drop)=["\']([a-zA-Z0-9_]+)\(', self.html))
        self.assertGreater(len(handlers), 15)

        missing = []
        for h in sorted(handlers):
            fn_def1 = f"function {h}" in self.js
            fn_def2 = f"{h} = function" in self.js
            fn_def3 = f"const {h} =" in self.js or f"let {h} =" in self.js or f"var {h} =" in self.js
            if not (fn_def1 or fn_def2 or fn_def3):
                missing.append(h)
        self.assertEqual(missing, [], f"HTML event handlers missing in JS: {missing}")


if __name__ == "__main__":
    unittest.main()
