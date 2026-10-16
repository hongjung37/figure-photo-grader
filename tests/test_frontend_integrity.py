from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class FrontendIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.html = (PROJECT_ROOT / "templates/index.html").read_text(encoding="utf-8")
        js_files = [
            PROJECT_ROOT / "static/js/api.js",
            PROJECT_ROOT / "static/js/tag_filter.js",
            PROJECT_ROOT / "static/js/crop_viewer.js",
            PROJECT_ROOT / "static/js/tournament.js",
            PROJECT_ROOT / "static/js/tag_insights.js",
            PROJECT_ROOT / "static/js/modals.js",
            PROJECT_ROOT / "static/dashboard.js",
        ]
        self.js = "\n".join(p.read_text(encoding="utf-8") for p in js_files if p.is_file())

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

    def test_scripts_syntax_and_runtime_integrity(self):
        """Verify that all scripts load and evaluate in sequential order without SyntaxError (e.g., redeclared let/const)."""
        import shutil
        import subprocess

        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("node binary not found on system")

        eval_script = r"""
const vm = require('vm');
const fs = require('fs');

const files = [
  'static/js/api.js',
  'static/js/tag_filter.js',
  'static/js/crop_viewer.js',
  'static/js/tournament.js',
  'static/js/tag_insights.js',
  'static/js/modals.js',
  'static/dashboard.js'
];

const mockElements = {
  'gallery-grid': { style: {} },
  'compare-view': { style: {} },
  'insights-view': { style: {}, innerHTML: '' },
  'tab-gallery': { classList: { toggle: () => {} } },
  'tab-compare': { classList: { toggle: () => {} } },
  'tab-insights': { classList: { toggle: () => {} } },
  'comp-a-select': { options: [], innerHTML: '', value: '1' },
  'comp-b-select': { options: [], innerHTML: '', value: '2' },
  'compare-content': { innerHTML: '' }
};

const windowObj = { addEventListener: () => {} };
const ctx = vm.createContext({
  window: windowObj,
  document: {
    getElementById: (id) => mockElements[id] || null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {}
  },
  navigator: {},
  fetch: () => Promise.resolve({ json: () => Promise.resolve([]) }),
  console: console
});

for (const file of files) {
  const code = fs.readFileSync(file, 'utf8');
  vm.runInContext(code, ctx);
}

// Verify switchView works for all view modes
if (typeof ctx.switchView !== 'function' && typeof windowObj.switchView !== 'function') {
  throw new Error('switchView is not a function');
}

const switchFn = ctx.switchView || windowObj.switchView;
switchFn('compare');
if (mockElements['compare-view'].style.display !== 'block') {
  throw new Error('compare-view did not display block');
}

switchFn('insights');
if (mockElements['insights-view'].style.display !== 'block') {
  throw new Error('insights-view did not display block');
}

switchFn('gallery');
if (mockElements['gallery-grid'].style.display !== 'grid') {
  throw new Error('gallery-grid did not display grid');
}

process.stdout.write('OK');
"""
        res = subprocess.run(
            [node_bin, "-e", eval_script],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        self.assertEqual(res.returncode, 0, f"Script evaluation failed: {res.stderr}\n{res.stdout}")
        self.assertIn("OK", res.stdout)


if __name__ == "__main__":
    unittest.main()

