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
            PROJECT_ROOT / "static/js/blind_rating.js",
            PROJECT_ROOT / "static/js/tag_insights.js",
            PROJECT_ROOT / "static/js/modals.js",
            PROJECT_ROOT / "static/js/rating_advice.js",
            PROJECT_ROOT / "static/js/reanalyze.js",
            PROJECT_ROOT / "static/js/growth_timeline.js",
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
  'static/js/blind_rating.js',
  'static/js/tag_insights.js',
  'static/js/modals.js',
  'static/js/rating_advice.js',
  'static/js/reanalyze.js',
  'static/js/growth_timeline.js',
  'static/js/detail_modal.js',
  'static/dashboard.js'
];

const mockElements = {
  'gallery-grid': { style: {} },
  'compare-view': { style: {} },
  'insights-view': { style: {}, innerHTML: '' },
  'timeline-view': { style: {}, innerHTML: '' },
  'timeline-tooltip': { style: {}, innerHTML: '' },
  'timeline-chart-wrap': { getBoundingClientRect: () => ({ left: 0, top: 0, width: 900, height: 400 }) },
  'tab-gallery': { classList: { toggle: () => {} } },
  'tab-compare': { classList: { toggle: () => {} } },
  'tab-insights': { classList: { toggle: () => {} } },
  'tab-timeline': { classList: { toggle: () => {} } },
  'comp-a-select': { options: [], innerHTML: '', value: '1' },
  'comp-b-select': { options: [], innerHTML: '', value: '2' },
  'compare-content': { innerHTML: '' },
  'sort-select': { value: 'score_desc' },
  'score-dist-panel': { style: {}, innerHTML: '' },
  'active-bin-filter-badge': { style: {} },
  'active-bin-filter-text': { textContent: '' },
  'btn-toggle-score-dist': { classList: { toggle: () => {} } },
  'score-dist-toggle-arrow': { textContent: '' },
  'upload-analysis-mode': { value: 'full' },
  'upload-mode-full-btn': { style: {} },
  'upload-mode-fast-btn': { style: {} },
  'upload-mode-hint': { innerHTML: '' },
  'date-scope-panel': { style: {} },
  'date-scope-from': { value: '' },
  'date-scope-to': { value: '' },
  'btn-clear-date-scope': { style: {} },
  'date-session-chips': { innerHTML: '' },
  'active-date-scope-summary': { style: {}, textContent: '' },
  'date-basis-smart': { classList: { toggle: () => {} } },
  'date-basis-captured': { classList: { toggle: () => {} } },
  'date-basis-created': { classList: { toggle: () => {} } },
  'collection-scope-chips': { innerHTML: '' },
  'collection-manage-btns': { style: {} },
  'batch-select-bar': { style: {} },
  'batch-selected-count': { textContent: '' },
  'batch-target-collection': { innerHTML: '', value: '' },
  'btn-batch-remove-from-col': { style: {} },
  'btn-toggle-batch-select': { style: {}, textContent: '' },
  'upload-collection-select': { innerHTML: '', value: '' },
  'upload-new-collection-name': { style: {}, value: '', focus: () => {} },
  'upload-auto-folder-collection': { checked: true },
  'btn-toggle-date-drawer': { classList: { toggle: () => {} } },
  'date-drawer-label': { textContent: '' },
  'date-drawer-arrow': { textContent: '' },
  'date-scope-drawer': { style: {} },
  'btn-toggle-adv-filters': { classList: { toggle: () => {} } },
  'adv-filter-count-badge': { style: {}, textContent: '' },
  'adv-filter-arrow': { textContent: '' },
  'adv-filter-drawer': { style: {} },
  'active-adv-filter-pills': { innerHTML: '' }
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

switchFn('timeline');
if (mockElements['timeline-view'].style.display !== 'block') {
  throw new Error('timeline-view did not display block');
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
    review_status: '토너먼트 1위', sns_advice: { best_ratio_key: 'original' },
    exif: { FocalLengthIn35mmFilm: 85, LensModel: '85mm F1.4' },
    strengths: ['눈동자 초점이 선명함'], improvements: ['림라이트를 더해 입체감을 보강하기']
  },
  {
    id: 2, filename: 'a_item.jpg', final_score: 7.5, user_score: 9.5,
    created_at: '2026-10-17T10:00:00+00:00', captured_at: '2024-01-01T10:00:00',
    figure_category: '접사/디테일', is_burst: true, is_best_pick: false, burst_group_id: 'g1', burst_total: 2, drop_reason: '초점 열세',
    aesthetic_tags: { viewpoint: ['로우앵글'], mood: ['고요함'] },
    composition_score: 7.5, lighting_score: 7.5, color_score: 7.5, technique_score: 7.5,
    exif: { FocalLength: 50 },
    strengths: ['자연스러운 배경 공간감'], improvements: ['가장자리 여백과 하단 잘림 확보']
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

// 5) 0.5-point & 0.1-point Score Distribution & Interactive Bin Filtering (Option C)
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
// Verify 0.1-point mode
const bins01 = vm.runInContext('setScoreDistStep("0.1"); getActiveScoreBins(' + JSON.stringify(sampleItems) + ', "0.1")', ctx);
if (!bins01.some(b => b.key === 'p_8.8') || !bins01.some(b => b.key === 'p_7.5')) {
  throw new Error('0.1-point bins missing p_8.8 or p_7.5');
}
const filteredByBin01 = vm.runInContext('selectScoreBin("p_8.8"); filterList(' + JSON.stringify(sampleItems) + ')', ctx);
if (filteredByBin01.length !== 1 || filteredByBin01[0].id !== 1) {
  throw new Error('selectScoreBin("p_8.8") failed to filter 8.8 item');
}
vm.runInContext('setScoreDistStep("0.5"); clearScoreBinFilter();', ctx);
const insightsDistHtml = vm.runInContext('renderInsightsScoreDistSection(' + JSON.stringify(sampleItems) + ')', ctx);
if (!insightsDistHtml.includes('종합 점수 분포') || !insightsDistHtml.includes('구도 (Composition)')) {
  throw new Error('renderInsightsScoreDistSection missing expected sections');
}

// 6) Focal Length Insights & Focal Band/Exact mm Filtering
vm.runInContext('allData = ' + JSON.stringify(sampleItems) + '; window.allData = allData; insightsMinCount = 1;', ctx);
const fStats = vm.runInContext('computeClientFocalStats(1)', ctx);
if (fStats.identifiedPhotos !== 2 || !fStats.bestBand || fStats.bestBand.band_key !== 'portrait_85') {
  throw new Error('computeClientFocalStats failed to compute focal bands properly');
}
vm.runInContext('setInsightsDimension("focal");', ctx);
if (!mockElements['insights-view'].innerHTML.includes('화각 구간별 종합 성적표') || !mockElements['insights-view'].innerHTML.includes('85mm')) {
  throw new Error('Focal insights view did not render expected focal table and mm pills');
}
const filteredByFocalBand = vm.runInContext('setFocalFilter("standard_50"); filterList(' + JSON.stringify(sampleItems) + ')', ctx);
if (filteredByFocalBand.length !== 1 || filteredByFocalBand[0].id !== 2) {
  throw new Error('setFocalFilter("standard_50") failed to filter 50mm item');
}
const filteredByExactMm = vm.runInContext('setFocalFilter("mm:85"); filterList(' + JSON.stringify(sampleItems) + ')', ctx);
if (filteredByExactMm.length !== 1 || filteredByExactMm[0].id !== 1) {
  throw new Error('setFocalFilter("mm:85") failed to filter exact 85mm item');
}
vm.runInContext('clearFocalFilter(); setInsightsDimension("tag");', ctx);

// 7) Fast Mode (경량 분석) UI toggle & card/detail detection
vm.runInContext('selectUploadAnalysisMode("fast");', ctx);
if (mockElements['upload-analysis-mode'].value !== 'fast' || !mockElements['upload-mode-hint'].innerHTML.includes('경량 분석')) {
  throw new Error('selectUploadAnalysisMode("fast") failed to update mode input and hint');
}
vm.runInContext('selectUploadAnalysisMode("full");', ctx);
if (mockElements['upload-analysis-mode'].value !== 'full') {
  throw new Error('selectUploadAnalysisMode("full") failed to reset mode input');
}
const fastItem = {
  id: 99, filename: 'fast_shot.jpg', final_score: 8.4, grade: '매우 우수',
  figure_category: '일반 피규어 촬영', focus_status: '완벽 칼초점', analysis_mode: 'fast',
  composition_score: 8.5, lighting_score: 8.2, color_score: 8.4, technique_score: 8.5,
  composition_notes: '', lighting_notes: '', color_notes: '', technique_notes: '',
  final_reason: '눈동자 칼핀이 선명하나 배경 여백이 다소 좁음.',
  strengths: [], improvements: [], aesthetic_tags: {}
};
const isFastDetected = vm.runInContext('isFastAnalysisItem(' + JSON.stringify(fastItem) + ')', ctx);
if (!isFastDetected) {
  throw new Error('isFastAnalysisItem failed to identify fast analysis item');
}
const fastCardHtml = vm.runInContext('renderGalleryCard(' + JSON.stringify(fastItem) + ')', ctx);
if (!fastCardHtml.includes('⚡ 경량')) {
  throw new Error('renderGalleryCard did not render ⚡ 경량 badge for fast item');
}

// 8) Date Scope (Phase 1) filtering & Scoped Insights
vm.runInContext('allData = ' + JSON.stringify(sampleItems) + '; window.allData = allData;', ctx);
vm.runInContext('setDateBasis("captured"); selectDateSession("2026-10-10");', ctx);
const scopedCaptured = vm.runInContext('getScopedData()', ctx);
if (scopedCaptured.length !== 1 || scopedCaptured[0].id !== 1) {
  throw new Error('selectDateSession("2026-10-10") with captured basis failed to scope to item 1');
}
const scopedFocalStats = vm.runInContext('computeClientFocalStats(1)', ctx);
if (scopedFocalStats.totalPhotos !== 1 || !scopedFocalStats.bestBand || scopedFocalStats.bestBand.band_key !== 'portrait_85') {
  throw new Error('computeClientFocalStats failed to respect active date scope');
}
vm.runInContext('clearDateScope(); setDateBasis("smart");', ctx);
if (vm.runInContext('getScopedData().length', ctx) !== 2) {
  throw new Error('clearDateScope() failed to restore full dataset');
}

// 9) Phase 2: Virtual Collections (Many-to-Many Albums) & Scoped Stats
const itemsWithCols = sampleItems.map((it, idx) => Object.assign({}, it, { collection_ids: idx === 0 ? [10] : [] }));
vm.runInContext('allData = ' + JSON.stringify(itemsWithCols) + '; window.allData = allData;', ctx);
vm.runInContext('allCollections = [{id: 10, name: "아키하바라 출사", count: 1}]; window.allCollections = allCollections;', ctx);
vm.runInContext('renderCollectionChips(); setCollectionFilter("10");', ctx);
const scopedCol10 = vm.runInContext('getScopedData()', ctx);
if (scopedCol10.length !== 1 || scopedCol10[0].id !== 1) {
  throw new Error('setCollectionFilter("10") failed to scope to collection #10');
}
vm.runInContext('setCollectionFilter("uncollected");', ctx);
const scopedUncollected = vm.runInContext('getScopedData()', ctx);
if (scopedUncollected.length !== 1 || scopedUncollected[0].id !== 2) {
  throw new Error('setCollectionFilter("uncollected") failed to scope to uncollected item #2');
}
vm.runInContext('setCollectionFilter("all");', ctx);

// 10) Option A Slim Toolbar & Collapsible Drawers
vm.runInContext('toggleDateScopeDrawer(true);', ctx);
if (mockElements['date-scope-drawer'].style.display !== 'block') {
  throw new Error('toggleDateScopeDrawer(true) failed to open date drawer');
}
vm.runInContext('toggleDateScopeDrawer(false);', ctx);
vm.runInContext('toggleAdvFilterDrawer(true);', ctx);
if (mockElements['adv-filter-drawer'].style.display !== 'block') {
  throw new Error('toggleAdvFilterDrawer(true) failed to open adv filter drawer');
}
vm.runInContext('setCatFilter("접사/디테일"); setFocalFilter("portrait_85");', ctx);
if (mockElements['adv-filter-count-badge'].textContent !== '2' || !mockElements['active-adv-filter-pills'].innerHTML.includes('접사/디테일')) {
  throw new Error('updateAdvFilterSummaryUI failed to render active filter count badge and pills');
}
vm.runInContext('setCatFilter("all"); clearFocalFilter(); toggleAdvFilterDrawer(false);', ctx);

// 11) Verify safeBlindEscape and blind rating XSS defense
const fnEscape = ctx.safeBlindEscape || windowObj.safeBlindEscape;
if (typeof fnEscape !== 'function') {
  throw new Error('safeBlindEscape is not exported on ctx or windowObj');
}
const testDangerous = '<script>alert(1)</script>&' + '"' + '\'';
const escaped = fnEscape(testDangerous);
if (escaped !== '&lt;script&gt;alert(1)&lt;/script&gt;&amp;&quot;&#39;') {
  throw new Error('safeBlindEscape did not escape dangerous characters properly: ' + escaped);
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


    def test_blind_rating_xss_and_filename_escaping(self):
        blind_code = (PROJECT_ROOT / "static/js/blind_rating.js").read_text(encoding="utf-8")
        self.assertIn("function safeBlindEscape", blind_code)
        self.assertIn("safeBlindEscape(item.filename || item.photo_filename || '사진')", blind_code)
        self.assertIn("safeBlindEscape(metaStr)", blind_code)
        self.assertIn("safeBlindEscape(item.figure_category", blind_code)
        self.assertIn("safeBlindEscape(item.final_reason)", blind_code)
        self.assertNotIn("${item.photo_filename || '사진'}", blind_code)


if __name__ == "__main__":
    unittest.main()

