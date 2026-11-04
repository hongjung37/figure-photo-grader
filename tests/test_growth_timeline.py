import shutil
import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class GrowthTimelineTests(unittest.TestCase):
    def setUp(self):
        self.node_bin = shutil.which("node")
        if not self.node_bin:
            self.skipTest("node binary not found on system")

    def run_node_eval(self, js_code: str) -> str:
        cmd = [self.node_bin, "-e", js_code]
        proc = subprocess.run(cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True, encoding="utf-8")
        if proc.returncode != 0:
            self.fail(f"Node execution failed (code {proc.returncode}):\n{proc.stderr}\nCode:\n{js_code}")
        return proc.stdout.strip()

    def test_timeline_grouping_and_aggregation(self):
        js = r"""
const fs = require('fs');
const vm = require('vm');

const mockWindow = {};
const mockElements = {
  'timeline-view': { style: {}, innerHTML: '' },
  'timeline-tooltip': { style: {}, innerHTML: '' },
  'timeline-chart-wrap': { getBoundingClientRect: () => ({ left: 0, top: 0, width: 900, height: 400 }) }
};

const ctx = vm.createContext({
  window: mockWindow,
  document: {
    getElementById: (id) => mockElements[id] || null,
    querySelector: () => null,
    querySelectorAll: () => []
  },
  console: console,
  setTimeout: setTimeout,
  clearTimeout: clearTimeout,
  allData: [
    {
      id: 1, filename: 'shot1_day1.jpg', final_score: 6.0, user_score: 5.5,
      composition_score: 7.0, lighting_score: 6.5, color_score: 7.5, technique_score: 7.0,
      captured_at: '2026-03-01T10:00:00'
    },
    {
      id: 2, filename: 'shot2_day1.jpg', final_score: 7.0, user_score: 6.5,
      composition_score: 7.0, lighting_score: 7.0, color_score: 7.0, technique_score: 7.0,
      captured_at: '2026-03-01T10:30:00'
    },
    {
      id: 3, filename: 'shot3_day1.jpg', final_score: 8.0, user_score: 7.5,
      composition_score: 8.0, lighting_score: 7.5, color_score: 8.5, technique_score: 8.0,
      captured_at: '2026-03-01T11:00:00'
    },
    {
      id: 4, filename: 'shot4_day1.jpg', final_score: 9.0, user_score: 8.5,
      composition_score: 8.5, lighting_score: 9.0, color_score: 8.0, technique_score: 8.5,
      captured_at: '2026-03-01T11:30:00'
    },
    {
      id: 5, filename: 'shot5_day2.jpg', final_score: 8.5, user_score: 8.0,
      composition_score: 8.5, lighting_score: 9.0, color_score: 8.0, technique_score: 8.5,
      captured_at: '2026-03-15T14:00:00'
    },
    {
      id: 6, filename: 'shot6_month2.jpg', final_score: 9.2, user_score: 9.0,
      composition_score: 9.0, lighting_score: 9.5, color_score: 9.0, technique_score: 9.3,
      captured_at: '2026-04-10T15:00:00'
    }
  ]
});

// Load growth_timeline.js
const code = fs.readFileSync('static/js/growth_timeline.js', 'utf8');
vm.runInContext(code, ctx);

// 1. Session Grouping Test
const sessionPoints = ctx.computeGrowthTimelineData('session');
if (sessionPoints.length !== 3) {
  throw new Error(`Expected 3 sessions, got ${sessionPoints.length}`);
}

// First session (2026-03-01): 4 photos: [6.0, 7.0, 8.0, 9.0]
// Overall AI avg = 30.0 / 4 = 7.5
// Top 25% (k=1) = 9.0
// User avg = (5.5 + 6.5 + 7.5 + 8.5) / 4 = 7.0
const p1 = sessionPoints[0];
if (p1.key !== '2026-03-01' || p1.count !== 4 || p1.avgFinal !== 7.5 || p1.bestFinal !== 9.0) {
  throw new Error(`Day 1 mismatch: ${JSON.stringify(p1)}`);
}
if (p1.top25Avg !== 9.0) {
  throw new Error(`Day 1 top25Avg expected 9.0, got ${p1.top25Avg}`);
}
if (p1.userAvg !== 7.0) {
  throw new Error(`Day 1 userAvg expected 7.0, got ${p1.userAvg}`);
}

// 2. KPI Computation Test
const kpis = ctx.computeTimelineKPIs(sessionPoints);
if (kpis.totalSessions !== 3 || kpis.totalPhotos !== 6) {
  throw new Error(`KPI totals mismatch: ${JSON.stringify(kpis)}`);
}
// AI Delta: 7.5 -> 9.2 = +1.7
if (kpis.delta !== 1.7) {
  throw new Error(`Expected AI growth delta 1.7, got ${kpis.delta}`);
}
// Top 25% Delta: 9.0 -> 9.2 = +0.2
if (kpis.top25Delta !== 0.2) {
  throw new Error(`Expected top25Delta 0.2, got ${kpis.top25Delta}`);
}
// User overall average: (28.0 + 8.0 + 9.0) / 6 = 45.0 / 6 = 7.5
if (kpis.overallUserAvg !== 7.5) {
  throw new Error(`Expected overallUserAvg 7.5, got ${kpis.overallUserAvg}`);
}

console.log('SUCCESS');
        """
        output = self.run_node_eval(js)
        self.assertEqual(output, "SUCCESS")

    def test_timeline_empty_and_single_edge_cases(self):
        js = r"""
const fs = require('fs');
const vm = require('vm');

const mockElements = {
  'timeline-view': { style: {}, innerHTML: '' },
  'timeline-tooltip': { style: {}, innerHTML: '' },
  'timeline-chart-wrap': { getBoundingClientRect: () => ({ left: 0, top: 0, width: 900, height: 400 }) }
};

const ctx = vm.createContext({
  window: {},
  document: {
    getElementById: (id) => mockElements[id] || null,
    querySelector: () => null,
    querySelectorAll: () => []
  },
  console: console,
  setTimeout: (fn) => fn(),
  clearTimeout: () => {},
  allData: []
});

const code = fs.readFileSync('static/js/growth_timeline.js', 'utf8');
vm.runInContext(code, ctx);

// Empty test
const emptyPoints = ctx.computeGrowthTimelineData('session');
if (emptyPoints.length !== 0) throw new Error('Empty allData should yield 0 points');
const emptyKpi = ctx.computeTimelineKPIs(emptyPoints);
if (emptyKpi !== null) throw new Error('Empty points should yield null KPIs');

// Render empty state
ctx.renderGrowthTimeline();
if (!mockElements['timeline-view'].innerHTML.includes('타임라인을 표시할 촬영 데이터가 없습니다')) {
  throw new Error('Empty render did not show empty notice');
}

// Single photo test (with user score)
ctx.allData = [
  { id: 99, filename: 'single.jpg', final_score: 8.0, user_score: 8.5, captured_at: '2026-05-01T12:00:00' }
];
const singlePoints = ctx.computeGrowthTimelineData('session');
if (singlePoints.length !== 1) throw new Error('Single item should yield 1 point');
if (singlePoints[0].top25Avg !== 8.0) throw new Error('Single item top25Avg should match final_score');
if (singlePoints[0].userAvg !== 8.5) throw new Error('Single item userAvg should match user_score');

const singleKpi = ctx.computeTimelineKPIs(singlePoints);
if (singleKpi.delta !== 0) throw new Error(`Single item delta should be 0, got ${singleKpi.delta}`);
if (singleKpi.overallUserAvg !== 8.5) throw new Error(`Single item overallUserAvg should be 8.5, got ${singleKpi.overallUserAvg}`);

ctx.renderGrowthTimeline();
if (!mockElements['timeline-view'].innerHTML.includes('single.jpg')) {
  throw new Error('Single item render missing filename');
}

console.log('EDGE_CASES_SUCCESS');
        """
        output = self.run_node_eval(js)
        self.assertEqual(output, "EDGE_CASES_SUCCESS")

    def test_timeline_jump_to_gallery_filter(self):
        js = r"""
const fs = require('fs');
const vm = require('vm');

let selectedDate = null;
let customFrom = null;
let customTo = null;
let currentViewMode = null;

const mockWindow = {};
const mockElements = {
  'timeline-view': { style: {}, innerHTML: '' },
  'timeline-tooltip': { style: {}, innerHTML: '' },
  'gallery-grid': { style: {}, scrollIntoView: () => {} },
  'date-scope-from': { value: '' },
  'date-scope-to': { value: '' },
  'timeline-chart-wrap': { getBoundingClientRect: () => ({ left: 0, top: 0, width: 900, height: 400 }) }
};

const ctx = vm.createContext({
  window: mockWindow,
  document: {
    getElementById: (id) => mockElements[id] || null,
    querySelector: () => null,
    querySelectorAll: () => []
  },
  console: console,
  setTimeout: (fn) => fn(),
  clearTimeout: () => {},
  applySessionDateJump: (d) => { selectedDate = d; },
  applyCustomDateJump: (f, t) => { customFrom = f; customTo = t; },
  selectDateSession: (d) => { selectedDate = d; },
  switchView: (v) => { currentViewMode = v; },
  allData: []
});

const code = fs.readFileSync('static/js/growth_timeline.js', 'utf8');
vm.runInContext(code, ctx);

// Jump daily session
ctx.jumpToTimelineDate('2026-03-15', false);
if (selectedDate !== '2026-03-15') throw new Error(`Expected selectedDate 2026-03-15, got ${selectedDate}`);
if (currentViewMode !== 'gallery') throw new Error(`Expected switchView to gallery, got ${currentViewMode}`);

// Jump monthly
ctx.jumpToTimelineDate('2026-03', true);
if (customFrom !== '2026-03-01' || customTo !== '2026-03-31') {
  throw new Error(`Monthly range wrong: ${customFrom} ~ ${customTo}`);
}
if (currentViewMode !== 'gallery') throw new Error(`Expected gallery mode after monthly jump`);

console.log('JUMP_TEST_SUCCESS');
        """
        output = self.run_node_eval(js)
        self.assertEqual(output, "JUMP_TEST_SUCCESS")


if __name__ == "__main__":
    unittest.main()
