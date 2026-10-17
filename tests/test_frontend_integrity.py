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
            PROJECT_ROOT / "static/js/rating_advice.js",
            PROJECT_ROOT / "static/js/reanalyze.js",
            PROJECT_ROOT / "static/js/detail_modal.js",
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
  'static/js/rating_advice.js',
  'static/js/reanalyze.js',
  'static/js/detail_modal.js',
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
  'compare-content': { innerHTML: '' },
  'sort-select': { value: 'score_desc' },
  'score-dist-panel': { style: {}, innerHTML: '' },
  'active-bin-filter-badge': { style: {} },
  'active-bin-filter-text': { textContent: '' },
  'btn-toggle-score-dist': { classList: { toggle: () => {} } },
  'score-dist-toggle-arrow': { textContent: '' }
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

// Verify tournament odd-bracket pairing does not lose bye candidate
if (typeof ctx.makeMatchesFromList === 'function') {
  const r3 = ctx.makeMatchesFromList([1, 2, 3]);
  if (!r3.matches || r3.matches.length !== 1 || !r3.byes || r3.byes.length !== 1 || r3.byes[0] !== 3) {
    throw new Error('makeMatchesFromList(3 items) failed to preserve bye candidate');
  }
}

// Verify compare selection persistence across populateCompareSelects
const popFn = ctx.populateCompareSelects || windowObj.populateCompareSelects;
if (typeof popFn === 'function') {
  ctx.allData = [
    { id: 101, filename: 'fig1.jpg', final_score: 8.5, grade: 'S' },
    { id: 102, filename: 'fig2.jpg', final_score: 7.9, grade: 'A' },
    { id: 103, filename: 'fig3.jpg', final_score: 9.1, grade: 'EX' }
  ];
  mockElements['comp-a-select'].value = '102';
  mockElements['comp-b-select'].value = '103';
  popFn();
  if (mockElements['comp-a-select'].value !== '102' || mockElements['comp-b-select'].value !== '103') {
    throw new Error('populateCompareSelects failed to preserve user selection');
  }
}

// Verify filterList with object aesthetic_tags, AND/OR tagLogic, and burst filter modes
const sampleItems = [
  {
    id: 1, filename: 'b_item.jpg', final_score: 8.8, user_score: 7.0,
    created_at: '2026-10-15T10:00:00+00:00', captured_at: '2026-10-10T10:00:00',
    figure_category: '접사/디테일', is_burst: true, is_best_pick: true, burst_group_id: 'g1', burst_total: 2,
    aesthetic_tags: { viewpoint: ['정면'], mood: ['고요함'] },
    composition_score: 8.5, lighting_score: 8.5, color_score: 8.5, technique_score: 8.5,
    review_status: '토너먼트 1위', sns_advice: { best_ratio_key: 'original' }
  },
  {
    id: 2, filename: 'a_item.jpg', final_score: 7.5, user_score: 9.5,
    created_at: '2026-10-17T10:00:00+00:00', captured_at: '2024-01-01T10:00:00',
    figure_category: '접사/디테일', is_burst: true, is_best_pick: false, burst_group_id: 'g1', burst_total: 2, drop_reason: '초점 열세',
    aesthetic_tags: { viewpoint: ['로우앵글'], mood: ['고요함'] },
    composition_score: 7.5, lighting_score: 7.5, color_score: 7.5, technique_score: 7.5
  }
];

// 1) Burst filter 'all' must keep B-cut, while 'stack' hides unexpanded B-cut
const resAll = vm.runInContext('currentBurstFilter = "all"; filterList(' + JSON.stringify(sampleItems) + ')', ctx);
if (resAll.length !== 2) {
  throw new Error('currentBurstFilter="all" should keep B-cuts, got ' + resAll.length);
}
const resStack = vm.runInContext('currentBurstFilter = "stack"; filterList(' + JSON.stringify(sampleItems) + ')', ctx);
if (resStack.length !== 1 || resStack[0].id !== 1) {
  throw new Error('currentBurstFilter="stack" should hide unexpanded B-cuts');
}
vm.runInContext('currentBurstFilter = "all";', ctx);

// 2) Tag filter with object aesthetic_tags must not crash and must honor AND / OR
const resTagAnd = vm.runInContext('selectedTags.clear(); selectedTags.add("정면"); selectedTags.add("고요함"); tagLogic = "AND"; filterList(' + JSON.stringify(sampleItems) + ')', ctx);
if (resTagAnd.length !== 1 || resTagAnd[0].id !== 1) {
  throw new Error('Tag filter AND failed');
}
const resTagOr = vm.runInContext('selectedTags.clear(); selectedTags.add("정면"); selectedTags.add("로우앵글"); tagLogic = "OR"; filterList(' + JSON.stringify(sampleItems) + ')', ctx);
if (resTagOr.length !== 2) {
  throw new Error('Tag filter OR failed');
}
vm.runInContext('selectedTags.clear();', ctx);

// 3) Sort dropdown (#sort-select) must sort properly
mockElements['sort-select'].value = 'score_asc';
const sortedScoreAsc = vm.runInContext('sortList(' + JSON.stringify(sampleItems) + ')', ctx);
if (sortedScoreAsc[0].id !== 2) {
  throw new Error('sortList score_asc failed');
}
mockElements['sort-select'].value = 'user_score_desc';
const sortedUserDesc = vm.runInContext('sortList(' + JSON.stringify(sampleItems) + ')', ctx);
if (sortedUserDesc[0].id !== 2) {
  throw new Error('sortList user_score_desc failed');
}
mockElements['sort-select'].value = 'newest';
const sortedNewest = vm.runInContext('sortList(' + JSON.stringify(sampleItems) + ')', ctx);
if (sortedNewest[0].id !== 2) {
  throw new Error('sortList newest (by created_at) failed');
}
mockElements['sort-select'].value = 'captured_desc';
const sortedCaptured = vm.runInContext('sortList(' + JSON.stringify(sampleItems) + ')', ctx);
if (sortedCaptured[0].id !== 1) {
  throw new Error('sortList captured_desc (by captured_at) failed');
}
mockElements['sort-select'].value = 'name';
const sortedName = vm.runInContext('sortList(' + JSON.stringify(sampleItems) + ')', ctx);
if (sortedName[0].filename !== 'a_item.jpg') {
  throw new Error('sortList name failed');
}

// 4) renderGalleryCard must include delete button, tournament winner badge, and SNS crop badge
const cardHtml = vm.runInContext('renderGalleryCard(' + JSON.stringify(sampleItems[0]) + ')', ctx);
if (!cardHtml.includes('card-delete-btn') || !cardHtml.includes('토너먼트 1위') || !cardHtml.includes('SNS크롭')) {
  throw new Error('renderGalleryCard missing delete button or badges');
}

// 5) 0.5-point Score Distribution & Interactive Bin Filtering (Option C)
const distRes = vm.runInContext('computeScoreDistribution(' + JSON.stringify(sampleItems) + ', d => d.final_score)', ctx);
if (distRes.total !== 2 || distRes.bins.length !== 9) {
  throw new Error('computeScoreDistribution failed to compute 9 bins for 2 items');
}
const bin75 = distRes.bins.find(b => b.key === '7.5');
const bin85 = distRes.bins.find(b => b.key === '8.5');
if (!bin75 || bin75.count !== 1 || !bin85 || bin85.count !== 1) {
  throw new Error('0.5-point bin counts mismatch');
}
const filteredByBin85 = vm.runInContext('selectScoreBin("8.5"); filterList(' + JSON.stringify(sampleItems) + ')', ctx);
if (filteredByBin85.length !== 1 || filteredByBin85[0].id !== 1) {
  throw new Error('selectScoreBin("8.5") failed to filter gallery items');
}
vm.runInContext('clearScoreBinFilter();', ctx);
const insightsDistHtml = vm.runInContext('renderInsightsScoreDistSection(' + JSON.stringify(sampleItems) + ')', ctx);
if (!insightsDistHtml.includes('0.5점 단위 종합 점수 분포') || !insightsDistHtml.includes('구도 (Composition)')) {
  throw new Error('renderInsightsScoreDistSection missing expected sections');
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

