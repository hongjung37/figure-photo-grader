// static/dashboard.js - Core State, Gallery Progressive Renderer, Detail Inspector & Reanalyze

// --- HTML Escaping Utility ---
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// --- Darkroom Theme Management ---
function initTheme() {
  try {
    const saved = localStorage.getItem('theme');
    const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    const isDark = saved === 'dark' || (!saved && prefersDark);
    if (isDark) {
      document.body.classList.add('darkroom');
      document.documentElement.classList.add('darkroom');
      updateThemeButton(true);
    } else {
      document.body.classList.remove('darkroom');
      document.documentElement.classList.remove('darkroom');
      updateThemeButton(false);
    }
  } catch (e) {}
}

function toggleTheme() {
  const isDark = document.body.classList.toggle('darkroom');
  document.documentElement.classList.toggle('darkroom', isDark);
  try {
    localStorage.setItem('theme', isDark ? 'dark' : 'light');
  } catch (e) {}
  updateThemeButton(isDark);
}

function updateThemeButton(isDark) {
  const btn = document.getElementById('theme-toggle-btn');
  if (!btn) return;
  if (isDark) {
    btn.innerHTML = '☀️ 라이트룸';
    btn.style.background = '#475569';
    btn.title = '라이트 모드로 전환';
  } else {
    btn.innerHTML = '🌙 다크룸';
    btn.style.background = '#334155';
    btn.title = '다크룸 모드로 전환';
  }
}

// --- Core State ---
let allData = (typeof window !== 'undefined' && window.allData) || [];
let currentFilter = 'all';
let currentCatFilter = 'all';
let currentSort = 'score_desc';
let currentDetailId = null;
let currentBurstDist = 15;
let currentBurstFilter = 'all'; // 'all', 'best_only', 'stack'
let expandedBurstGroups = new Set();
let selectedScoreBin = null; // 0.5-point or 0.1-point bin key (e.g., '8.0' or 'p_7.8')
let scoreDistMetric = 'ai'; // 'ai' | 'user' | 'overlay'
let scoreDistStep = '0.5'; // '0.5' | '0.1'
let scoreDistCollapsed = false;

// --- 0.5-Point & 0.1-Point Score Bins Definition ---
const SCORE_BINS_05 = [
  { key: 'le_5.0', label: '≤5.0', sub: '하위', min: -Infinity, max: 5.5, color: '#94a3b8' },
  { key: '5.5',    label: '5.5',  sub: '5.5~5.9', min: 5.5, max: 6.0, color: '#64748b' },
  { key: '6.0',    label: '6.0',  sub: '6.0~6.4', min: 6.0, max: 6.5, color: '#f97316' },
  { key: '6.5',    label: '6.5',  sub: '6.5~6.9', min: 6.5, max: 7.0, color: '#f59e0b' },
  { key: '7.0',    label: '7.0',  sub: '7.0~7.4', min: 7.0, max: 7.5, color: '#eab308' },
  { key: '7.5',    label: '7.5',  sub: '7.5~7.9', min: 7.5, max: 8.0, color: '#10b981' },
  { key: '8.0',    label: '8.0',  sub: '8.0~8.4', min: 8.0, max: 8.5, color: '#0d9488' },
  { key: '8.5',    label: '8.5',  sub: '8.5~8.9', min: 8.5, max: 9.0, color: '#3b82f6' },
  { key: 'ge_9.0', label: '9.0+', sub: '마스터피스', min: 9.0, max: Infinity, color: '#8b5cf6' }
];
window.SCORE_BINS_05 = SCORE_BINS_05;

function getScoreTierColor(val) {
  if (val >= 9.0) return '#8b5cf6';
  if (val >= 8.5) return '#3b82f6';
  if (val >= 8.0) return '#0d9488';
  if (val >= 7.5) return '#10b981';
  if (val >= 7.0) return '#eab308';
  if (val >= 6.5) return '#f59e0b';
  if (val >= 6.0) return '#f97316';
  if (val >= 5.5) return '#64748b';
  return '#94a3b8';
}

function buildScoreBins01(items) {
  const vals = [];
  (items || []).forEach(it => {
    if (it && it.final_score !== null && it.final_score !== undefined && !Number.isNaN(Number(it.final_score))) {
      vals.push(Math.round(Number(it.final_score) * 10));
    }
    if (it && it.user_score !== null && it.user_score !== undefined && !Number.isNaN(Number(it.user_score))) {
      vals.push(Math.round(Number(it.user_score) * 10));
    }
  });
  let minTenth = vals.length ? Math.min(...vals) : 60;
  let maxTenth = vals.length ? Math.max(...vals) : 90;
  // Pad by 1 step and clamp to [0, 100], ensuring a clean visual range
  minTenth = Math.max(0, Math.min(minTenth, 60));
  maxTenth = Math.min(100, Math.max(maxTenth, 85));

  const bins = [];
  for (let t = minTenth; t <= maxTenth; t++) {
    const exact = t / 10;
    const label = exact.toFixed(1);
    bins.push({
      key: `p_${label}`,
      label: label,
      sub: `${label}점`,
      min: exact - 0.05,
      max: exact + 0.05,
      color: getScoreTierColor(exact)
    });
  }
  return bins;
}
window.buildScoreBins01 = buildScoreBins01;

function getActiveScoreBins(items, stepMode) {
  const mode = stepMode || scoreDistStep;
  if (mode === '0.1') {
    return buildScoreBins01(items && items.length ? items : allData);
  }
  return SCORE_BINS_05;
}

function matchScoreBin(score, binKey) {
  if (score === null || score === undefined || Number.isNaN(Number(score))) return false;
  const val = Number(score);
  if (binKey && binKey.startsWith('p_')) {
    const target = parseFloat(binKey.slice(2));
    return Math.round(val * 10) === Math.round(target * 10);
  }
  const bin = SCORE_BINS_05.find(b => b.key === binKey);
  if (!bin) return true;
  return val >= bin.min && val < bin.max;
}

function computeScoreDistribution(items, scoreGetter, customBins) {
  const templateBins = customBins || SCORE_BINS_05;
  const counts = templateBins.map(b => ({ ...b, count: 0, pct: 0 }));
  const validScores = [];
  (items || []).forEach(it => {
    const s = scoreGetter(it);
    if (s === null || s === undefined || Number.isNaN(Number(s))) return;
    const val = Number(s);
    validScores.push(val);
    for (let i = 0; i < counts.length; i++) {
      if (counts[i].key.startsWith('p_')) {
        const target = parseFloat(counts[i].key.slice(2));
        if (Math.round(val * 10) === Math.round(target * 10)) {
          counts[i].count += 1;
          break;
        }
      } else if (val >= counts[i].min && val < counts[i].max) {
        counts[i].count += 1;
        break;
      }
    }
  });
  const total = validScores.length;
  let maxCount = 0;
  counts.forEach(c => {
    c.pct = total ? Math.round((c.count / total) * 100) : 0;
    if (c.count > maxCount) maxCount = c.count;
  });
  validScores.sort((a, b) => a - b);
  const mean = total ? (validScores.reduce((a, b) => a + b, 0) / total) : 0;
  const median = total
    ? (total % 2 === 1
      ? validScores[Math.floor(total / 2)]
      : (validScores[total / 2 - 1] + validScores[total / 2]) / 2)
    : 0;
  const top10Idx = total ? Math.max(0, Math.ceil(total * 0.9) - 1) : 0;
  const top10Cutoff = total ? validScores[top10Idx] : 0;
  const minScore = total ? validScores[0] : 0;
  const maxScore = total ? validScores[total - 1] : 0;
  return { bins: counts, total, maxCount, mean, median, top10Cutoff, minScore, maxScore };
}
window.computeScoreDistribution = computeScoreDistribution;

function toggleScoreDistPanel() {
  scoreDistCollapsed = !scoreDistCollapsed;
  const panel = document.getElementById('score-dist-panel');
  const btn = document.getElementById('btn-toggle-score-dist');
  const arrow = document.getElementById('score-dist-toggle-arrow');
  if (panel) panel.style.display = scoreDistCollapsed ? 'none' : 'block';
  if (btn) btn.classList.toggle('active', !scoreDistCollapsed);
  if (arrow) arrow.textContent = scoreDistCollapsed ? '▾' : '▴';
}

function setScoreDistStep(step) {
  if (scoreDistStep !== step) {
    scoreDistStep = step;
    selectedScoreBin = null;
    updateScoreBinFilterBadge();
  }
  renderScoreDistPanel();
  renderGallery();
  if (typeof currentView !== 'undefined' && currentView === 'insights' && typeof renderTagInsights === 'function') {
    renderTagInsights();
  }
}
window.setScoreDistStep = setScoreDistStep;

function setScoreDistMetric(mode) {
  scoreDistMetric = mode;
  renderScoreDistPanel();
  if (selectedScoreBin) renderGallery();
}

function selectScoreBin(binKey) {
  if (selectedScoreBin === binKey) {
    selectedScoreBin = null;
  } else {
    selectedScoreBin = binKey;
  }
  updateScoreBinFilterBadge();
  renderScoreDistPanel();
  renderGallery();
}

function clearScoreBinFilter() {
  selectedScoreBin = null;
  updateScoreBinFilterBadge();
  renderScoreDistPanel();
  renderGallery();
}

function updateScoreBinFilterBadge() {
  const badge = document.getElementById('active-bin-filter-badge');
  const text = document.getElementById('active-bin-filter-text');
  if (!badge || !text) return;
  if (!selectedScoreBin) {
    badge.style.display = 'none';
    return;
  }
  const modeLabel = scoreDistMetric === 'user' ? '내 점수' : 'AI 점수';
  if (selectedScoreBin.startsWith('p_')) {
    const exactLabel = selectedScoreBin.slice(2);
    text.textContent = `📊 ${modeLabel} ${exactLabel}점`;
  } else {
    const bin = SCORE_BINS_05.find(b => b.key === selectedScoreBin);
    text.textContent = `📊 ${modeLabel} ${bin ? bin.label : selectedScoreBin} 구간 (${bin ? bin.sub : ''})`;
  }
  badge.style.display = 'inline-flex';
}

function renderScoreDistPanel() {
  const panel = document.getElementById('score-dist-panel');
  if (!panel) return;
  if (typeof currentView !== 'undefined' && currentView !== 'gallery') {
    panel.style.display = 'none';
    return;
  }
  panel.style.display = scoreDistCollapsed ? 'none' : 'block';
  if (!allData || !allData.length) {
    panel.innerHTML = '';
    return;
  }

  // Filter items by current category/tag/burst (excluding grade & bin filter so full distribution is visible)
  const baseList = allData.filter(item => {
    if (currentCatFilter !== 'all' && item.figure_category !== currentCatFilter) return false;
    if (currentBurstFilter === 'burst_only' && !item.is_burst) return false;
    if (currentBurstFilter === 'best_only' && item.is_burst && !item.is_best_pick) return false;
    if (typeof selectedTags !== 'undefined' && selectedTags && selectedTags.size > 0 && typeof getAllTagsFromItem === 'function') {
      const itemTags = getAllTagsFromItem(item);
      if (typeof tagLogic !== 'undefined' && tagLogic === 'OR') {
        if (!Array.from(selectedTags).some(t => itemTags.has(t))) return false;
      } else {
        if (!Array.from(selectedTags).every(t => itemTags.has(t))) return false;
      }
    }
    return true;
  });

  const activeBins = getActiveScoreBins(baseList, scoreDistStep);
  const aiDist = computeScoreDistribution(baseList, d => d.final_score, activeBins);
  const userDist = computeScoreDistribution(baseList, d => d.user_score, activeBins);
  const activeDist = scoreDistMetric === 'user' ? userDist : aiDist;
  const maxBar = scoreDistMetric === 'overlay'
    ? Math.max(aiDist.maxCount, userDist.maxCount, 1)
    : Math.max(activeDist.maxCount, 1);
  const isStep01 = scoreDistStep === '0.1';

  panel.innerHTML = `
    <div class="score-dist-header">
      <div class="score-dist-title-group">
        <span style="font-size:0.95rem;font-weight:800;color:var(--navy);display:flex;align-items:center;gap:6px;">
          📊 ${isStep01 ? '0.1점 정밀' : '0.5점 단위'} 점수 분포표
        </span>
        <div style="display:inline-flex;background:var(--filter-btn-bg);border:1px solid var(--line);border-radius:8px;padding:2px;gap:2px;">
          <button type="button" class="toggle-logic-btn ${!isStep01 ? 'active' : ''}" onclick="setScoreDistStep('0.5')">0.5점 단위</button>
          <button type="button" class="toggle-logic-btn ${isStep01 ? 'active' : ''}" onclick="setScoreDistStep('0.1')">0.1점 단위 (정밀)</button>
        </div>
        <span style="font-size:0.74rem;color:var(--muted);">막대를 클릭하면 해당 점수대 사진만 즉시 필터링됩니다</span>
      </div>

      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
        <div class="score-dist-kpis">
          <span class="score-dist-kpi-pill">표본 <strong>${activeDist.total}장</strong></span>
          <span class="score-dist-kpi-pill">평균 <strong>${activeDist.mean.toFixed(2)}점</strong></span>
          <span class="score-dist-kpi-pill">중앙값 <strong>${activeDist.median.toFixed(1)}점</strong></span>
          <span class="score-dist-kpi-pill">상위 10% 컷 <strong>${activeDist.top10Cutoff.toFixed(1)}점+</strong></span>
        </div>

        <div style="display:inline-flex;background:var(--filter-btn-bg);border:1px solid var(--line);border-radius:9px;padding:2px;gap:2px;">
          <button type="button" class="toggle-logic-btn ${scoreDistMetric === 'ai' ? 'active' : ''}" onclick="setScoreDistMetric('ai')">🤖 AI 점수</button>
          <button type="button" class="toggle-logic-btn ${scoreDistMetric === 'user' ? 'active' : ''}" onclick="setScoreDistMetric('user')">👤 내 점수 (${userDist.total})</button>
          <button type="button" class="toggle-logic-btn ${scoreDistMetric === 'overlay' ? 'active' : ''}" onclick="setScoreDistMetric('overlay')">⚖️ AI vs 내 점수 겹쳐보기</button>
        </div>
      </div>
    </div>

    <div class="score-dist-scroll-wrap">
      <div class="score-dist-bars ${isStep01 ? 'step-01' : 'step-05'}" style="--bin-count:${activeBins.length};">
        ${activeBins.map((bin, idx) => {
          const aiBin = aiDist.bins[idx];
          const uBin = userDist.bins[idx];
          const primaryBin = scoreDistMetric === 'user' ? uBin : aiBin;
          const hPct = primaryBin.count > 0 ? Math.max(8, Math.round((primaryBin.count / maxBar) * 100)) : 4;
          const uPct = uBin.count > 0 ? Math.max(8, Math.round((uBin.count / maxBar) * 100)) : 4;
          const isSelected = selectedScoreBin === bin.key;
          const isEmpty = scoreDistMetric === 'overlay' ? (aiBin.count === 0 && uBin.count === 0) : (primaryBin.count === 0);

          return `
            <div class="score-dist-col ${isSelected ? 'active' : ''} ${isEmpty ? 'empty' : ''}"
                 onclick="selectScoreBin('${bin.key}')"
                 title="${bin.label}점 (${bin.sub}) — AI: ${aiBin.count}장 (${aiBin.pct}%) / 내 점수: ${uBin.count}장 (${uBin.pct}%) | 클릭하여 필터링">
              <div class="score-dist-count">
                ${scoreDistMetric === 'overlay'
                  ? `<span style="color:${bin.color};">${aiBin.count}</span><span style="color:var(--muted);font-weight:500;">/</span><span style="color:#4f46e5;">${uBin.count}</span>`
                  : (isStep01
                      ? `<span>${primaryBin.count > 0 ? primaryBin.count : '0'}</span><span class="score-dist-pct">${primaryBin.count > 0 ? primaryBin.pct + '%' : ''}</span>`
                      : `${primaryBin.count}장 <span class="score-dist-pct">${primaryBin.pct}%</span>`
                    )
                }
              </div>
              <div class="score-dist-bar-wrap">
                <div class="score-dist-bar" style="height:${hPct}%;background:${bin.color};opacity:${primaryBin.count > 0 ? 1 : 0.22};"></div>
                ${scoreDistMetric === 'overlay' ? `
                  <div class="score-dist-bar user-overlay-bar" style="height:${uPct}%;opacity:${uBin.count > 0 ? 0.95 : 0.18};"></div>
                ` : ''}
              </div>
              <div class="score-dist-label">${bin.label}</div>
              ${!isStep01 ? `<div class="score-dist-sublabel">${bin.sub}</div>` : ''}
            </div>
          `;
        }).join('')}
      </div>
    </div>
  `;
}

// --- Progressive Gallery Chunk Rendering ---
const GALLERY_PAGE_SIZE = 40;
let currentGalleryRenderCount = GALLERY_PAGE_SIZE;
let galleryObserver = null;

function setCatFilter(cat, btn) {
  currentCatFilter = cat;
  document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderScoreDistPanel();
  renderGallery();
}

async function loadData() {
  const data = await API.fetchAnalyses(currentBurstDist);
  allData = Array.isArray(data) ? data : [];
  window.allData = allData;
  updateStats();
  if (typeof populateCompareSelects === 'function') populateCompareSelects();
  if (typeof populateTagSelectorAndQuickTags === 'function') populateTagSelectorAndQuickTags();
  if (typeof updateTagFilterUI === 'function') updateTagFilterUI();
  renderScoreDistPanel();
  renderGallery();
  if (typeof currentView !== 'undefined' && currentView === 'insights' && typeof renderTagInsights === 'function') {
    renderTagInsights();
  }
}

const loadAnalyses = loadData;

async function changeBurstSensitivity(val) {
  currentBurstDist = parseInt(val, 10) || 15;
  await loadData();
}

function updateStats() {
  const totalEl = document.getElementById('total-count');
  const avgEl = document.getElementById('avg-score');
  const goodEl = document.getElementById('good-count');
  if (totalEl) totalEl.textContent = allData.length;
  if (!allData.length) {
    if (avgEl) avgEl.textContent = '0.0';
    if (goodEl) goodEl.textContent = '0';
    return;
  }
  const avg = (allData.reduce((acc, cur) => acc + cur.final_score, 0) / allData.length).toFixed(1);
  const good = allData.filter(d => d.final_score >= 7.0).length;
  if (avgEl) avgEl.textContent = avg;
  if (goodEl) goodEl.textContent = good;
}

function setBurstFilter(mode, btn) {
  currentBurstFilter = mode;
  document.querySelectorAll('.burst-btn, .burst-filter-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderScoreDistPanel();
  renderGallery();
}

function toggleExpandBurstGroup(groupId, e) {
  if (e) e.stopPropagation();
  if (expandedBurstGroups.has(groupId)) {
    expandedBurstGroups.delete(groupId);
  } else {
    expandedBurstGroups.add(groupId);
  }
  renderGallery(false);
}

function setFilter(filter, btn) {
  currentFilter = filter;
  if (selectedScoreBin) {
    selectedScoreBin = null;
    updateScoreBinFilterBadge();
    renderScoreDistPanel();
  }
  document.querySelectorAll('.filter-btn:not(.burst-btn):not(.cat-btn):not(#btn-toggle-score-dist)').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderGallery();
}

function filterList(list) {
  return list.filter(item => {
    // 1. Grade filter
    if (currentFilter === 'pro' && item.final_score < 9.0) return false;
    if (currentFilter === 'very_good' && (item.final_score < 8.0 || item.final_score >= 9.0)) return false;
    if (currentFilter === 'good' && (item.final_score < 7.0 || item.final_score >= 8.0)) return false;
    if (currentFilter === 'normal' && (item.final_score < 5.0 || item.final_score >= 7.0)) return false;

    // 1-b. Interactive 0.5-point Score Bin filter
    if (selectedScoreBin) {
      const targetScore = scoreDistMetric === 'user' ? item.user_score : item.final_score;
      if (!matchScoreBin(targetScore, selectedScoreBin)) return false;
    }

    // 2. Category filter
    if (currentCatFilter !== 'all' && item.figure_category !== currentCatFilter) return false;

    // 3. Burst filter
    if (currentBurstFilter === 'burst_only' && !item.is_burst) return false;
    if (currentBurstFilter === 'best_only' && item.is_burst && !item.is_best_pick) return false;

    // 4. Tag filter
    if (typeof selectedTags !== 'undefined' && selectedTags && selectedTags.size > 0 && typeof getAllTagsFromItem === 'function') {
      const itemTags = getAllTagsFromItem(item);
      if (typeof tagLogic !== 'undefined' && tagLogic === 'OR') {
        if (!Array.from(selectedTags).some(t => itemTags.has(t))) return false;
      } else {
        if (!Array.from(selectedTags).every(t => itemTags.has(t))) return false;
      }
    }

    // 5. Burst group collapse logic (only in 'stack' mode)
    if (currentBurstFilter === 'stack') {
      if (item.is_burst && !item.is_best_pick && !expandedBurstGroups.has(item.burst_group_id)) {
        return false;
      }
    }

    return true;
  });
}

function sortList(list) {
  const sortSelect = document.getElementById('sort-select');
  const sort = sortSelect ? sortSelect.value : currentSort;
  return [...list].sort((a, b) => {
    if (sort === 'score_desc' || sort === 'score-desc') return b.final_score - a.final_score;
    if (sort === 'score_asc' || sort === 'score-asc') return a.final_score - b.final_score;
    if (sort === 'user_score_desc') {
      const sa = (a.user_score !== null && a.user_score !== undefined) ? a.user_score : -1;
      const sb = (b.user_score !== null && b.user_score !== undefined) ? b.user_score : -1;
      return sb - sa;
    }
    if (sort === 'user_score_asc') {
      const sa = (a.user_score !== null && a.user_score !== undefined) ? a.user_score : 999;
      const sb = (b.user_score !== null && b.user_score !== undefined) ? b.user_score : 999;
      return sa - sb;
    }
    if (sort === 'gap_desc' || sort === 'diff-desc') {
      const ga = (a.user_score !== null && a.user_score !== undefined) ? Math.abs(a.user_score - a.final_score) : -1;
      const gb = (b.user_score !== null && b.user_score !== undefined) ? Math.abs(b.user_score - b.final_score) : -1;
      return gb - ga;
    }
    if (sort === 'newest' || sort === 'date-desc') {
      const timeA = a.created_at ? new Date(a.created_at).getTime() : 0;
      const timeB = b.created_at ? new Date(b.created_at).getTime() : 0;
      const validA = Number.isNaN(timeA) ? 0 : timeA;
      const validB = Number.isNaN(timeB) ? 0 : timeB;
      return (validB - validA) || (b.id - a.id);
    }
    if (sort === 'captured_desc') {
      const timeA = a.captured_at ? new Date(a.captured_at).getTime() : -1;
      const timeB = b.captured_at ? new Date(b.captured_at).getTime() : -1;
      const validA = Number.isNaN(timeA) ? -1 : timeA;
      const validB = Number.isNaN(timeB) ? -1 : timeB;
      return (validB - validA) || (b.id - a.id);
    }
    if (sort === 'name') return a.filename.localeCompare(b.filename);
    return 0;
  });
}

function formatCapturedAt(value) {
  if (!value) return '촬영 시각 정보 없음';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return `촬영 ${value}`;
  return `촬영 ${date.toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'medium' })}`;
}

function renderGalleryCard(item) {
  const modelBadgeText = (window.ModelSettings && item.model)
    ? window.ModelSettings.formatBadge(item.model)
    : (item.model || '');
  return `
    <article class="card" onclick="openDetailModal(${item.id})">
      <button class="card-delete-btn" title="이 분석 기록 삭제" onclick="event.stopPropagation(); deleteAnalysisRecord(${item.id})">🗑️</button>
      <img class="card-thumb" src="/api/image/${item.id}" alt="${escapeHtml(item.filename)}" loading="lazy">
      <div class="card-body">
        <div class="card-header">
          <div>
            <h3 class="card-title">${escapeHtml(item.filename)}</h3>
            <div style="margin-top:4px;font-size:0.72rem;color:var(--muted);">📷 ${escapeHtml(formatCapturedAt(item.captured_at))}</div>
            <span style="display:inline-block;margin-top:4px;font-size:0.75rem;font-weight:700;color:#4f46e5;background:#eef2ff;padding:2px 7px;border-radius:6px;">${escapeHtml(item.figure_category)}</span>
            <span style="display:inline-block;margin-top:4px;margin-left:4px;font-size:0.75rem;font-weight:700;color:#0d9488;background:#f0fdfa;padding:2px 7px;border-radius:6px;">🎯 ${escapeHtml(item.focus_status || '완벽 칼초점')}</span>
            ${modelBadgeText ? `<span style="display:inline-block;margin-top:4px;margin-left:4px;font-size:0.73rem;font-weight:700;color:#334155;background:rgba(148,163,184,0.16);border:1px solid rgba(148,163,184,0.35);padding:1px 7px;border-radius:6px;" title="평가 모델: ${escapeHtml(item.model)}">🤖 ${escapeHtml(modelBadgeText)}</span>` : ''}
            ${item.is_burst ? (item.is_best_pick ?
              `<span class="badge-best-pick" style="display:inline-block;margin-top:4px;margin-left:4px;">👑 Best Pick (${item.burst_total}장 1위)</span>` :
              `<span class="badge-b-cut" style="display:inline-block;margin-top:4px;margin-left:4px;" title="${escapeHtml(item.drop_reason)}">⚠️ B컷 (${escapeHtml(item.drop_reason)})</span>`
            ) : ''}
            ${item.review_status === '토너먼트 1위' ? '<span class="badge-best-pick" style="background:#fef3c7;color:#b45309;border:1px solid #fde68a;display:inline-block;margin-top:4px;margin-left:4px;">🏆 토너먼트 1위</span>' : ''}
            ${item.sns_advice ? '<span style="display:inline-block;margin-top:4px;margin-left:4px;font-size:0.75rem;font-weight:700;color:#0284c7;background:#e0f2fe;padding:2px 7px;border-radius:6px;">📱 SNS크롭</span>' : ''}
            ${item.user_score !== null && item.user_score !== undefined ? `
              <span class="badge-user-score" style="display:inline-block;margin-top:4px;margin-left:4px;" title="사용자 직접 평점: ${item.user_score.toFixed(1)}점 (AI: ${item.final_score.toFixed(1)}점)">👤 내 점수 ${item.user_score.toFixed(1)}</span>
            ` : ''}
            ${item.cross_check_opinion ? `
              <span class="cross-check-badge" title="OpenAI(${escapeHtml(item.cross_check_opinion.model || 'GPT-6 Luna')}) 보조 의견: ${Number(item.cross_check_opinion.score).toFixed(1)}점">🤝 OpenAI ${Number(item.cross_check_opinion.score).toFixed(1)}</span>
            ` : ''}
          </div>
          <div class="score-badge">
            <span class="score-num">${item.final_score.toFixed(1)}</span>
            <span class="score-grade">${escapeHtml(item.grade)}</span>
            ${item.user_score !== null && item.user_score !== undefined ? `
              <span style="font-size:0.74rem;font-weight:800;color:#1d4ed8;margin-top:3px;">👤 ${item.user_score.toFixed(1)}점</span>
            ` : ''}
          </div>
        </div>
        <div class="mini-scores">
          <div><span>구도</span><strong>${item.composition_score.toFixed(1)}</strong></div>
          <div><span>조명</span><strong>${item.lighting_score.toFixed(1)}</strong></div>
          <div><span>색감</span><strong>${item.color_score.toFixed(1)}</strong></div>
          <div><span>기술</span><strong>${item.technique_score.toFixed(1)}</strong></div>
        </div>
        <div class="reason-box">${escapeHtml(item.final_reason)}</div>
        <div class="tag-pills">
          ${typeof renderTagPills === 'function' ? renderTagPills(item.aesthetic_tags) : ''}
        </div>
        ${currentBurstFilter === 'stack' && item.is_burst && item.is_best_pick ? `
          <div style="margin-top:8px;padding-top:8px;border-top:1px dashed var(--line);display:flex;justify-content:space-between;align-items:center;" onclick="event.stopPropagation()">
            <span style="font-size:0.74rem;color:var(--muted);font-weight:600;">🗂️ 연사 묶음 (${item.burst_total}장)</span>
            <button class="filter-btn" style="padding:2px 8px;font-size:0.72rem;background:#f0f9ff;border-color:#bae6fd;color:#0369a1;" onclick="toggleExpandBurstGroup('${escapeHtml(item.burst_group_id)}', event)">
              ${expandedBurstGroups.has(item.burst_group_id) ? '▲ B컷 접기' : `▼ B컷 ${item.burst_total - 1}장 펼치기`}
            </button>
          </div>
        ` : ''}
      </div>
    </article>
  `;
}

function renderGallery(resetPaging = true) {
  if (resetPaging) {
    currentGalleryRenderCount = GALLERY_PAGE_SIZE;
  }
  const container = document.getElementById('gallery-grid');
  if (!container) return;

  const filtered = sortList(filterList(allData));
  if (!filtered.length) {
    container.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:60px;color:var(--muted)">해당 조건의 분석 사진이 없습니다.</div>';
    return;
  }

  const itemsToRender = filtered.slice(0, currentGalleryRenderCount);
  const hasMore = filtered.length > currentGalleryRenderCount;

  let html = itemsToRender.map(item => renderGalleryCard(item)).join('');

  if (hasMore) {
    html += `
      <div id="gallery-sentinel" style="grid-column:1/-1;text-align:center;padding:24px;color:var(--muted);font-size:0.86rem;cursor:pointer;" onclick="loadMoreGalleryItems()">
        <span>⏳ 더 많은 사진 로딩 중... (${currentGalleryRenderCount} / ${filtered.length}장 표시됨, 클릭 시 즉시 더 보기)</span>
      </div>
    `;
  }

  container.innerHTML = html;
  setupGalleryObserver(filtered.length);
}

function loadMoreGalleryItems() {
  const filtered = sortList(filterList(allData));
  if (currentGalleryRenderCount >= filtered.length) return;
  currentGalleryRenderCount += GALLERY_PAGE_SIZE;
  renderGallery(false);
}

function setupGalleryObserver(totalCount) {
  if (galleryObserver) {
    galleryObserver.disconnect();
    galleryObserver = null;
  }

  const sentinel = document.getElementById('gallery-sentinel');
  if (!sentinel) return;

  if ('IntersectionObserver' in window) {
    galleryObserver = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          loadMoreGalleryItems();
        }
      });
    }, {
      rootMargin: '300px 0px',
      threshold: 0.01
    });
    galleryObserver.observe(sentinel);
  }
}

function renderBurstThumbnails(groupId, currentId) {
  if (!groupId) return '';
  const groupItems = allData.filter(d => d.burst_group_id === groupId).sort((a, b) => a.burst_rank - b.burst_rank);
  return groupItems.map(m => `
    <img src="/api/image/${m.id}"
         class="burst-thumb-link ${m.id === currentId ? 'current' : ''} ${m.is_best_pick ? 'is-best' : ''}"
         title="${m.is_best_pick ? '👑 1위 Best Pick' : `${m.burst_rank}위 B컷 (${escapeHtml(m.drop_reason)})`}"
         onclick="event.stopPropagation(); openDetailModal(${m.id})">
  `).join('');
}

async function deleteAnalysisRecord(id) {
  const item = allData.find(d => d.id === id);
  const name = item ? `"${item.filename}"` : `ID ${id}`;
  if (!confirm(`${name} 사진의 분석 기록을 삭제하시겠습니까?\n이 사진의 분석 데이터는 DB에서 영구히 삭제됩니다.`)) {
    return;
  }
  try {
    const result = await API.deleteAnalyses(id);
    if (result.success) {
      const detailId = (typeof currentDetailId !== 'undefined' && currentDetailId !== null) ? currentDetailId : window.currentDetailId;
      if (detailId === id) {
        if (typeof closeDetailModal === 'function') closeDetailModal();
      }
      await loadData();
    } else {
      alert(`삭제 실패: ${result.error || '알 수 없는 오류'}`);
    }
  } catch (err) {
    alert(`삭제 통신 오류: ${err.message}`);
  }
}

async function exportAllXmp(btn) {
  const origText = btn ? btn.textContent : '';
  if (btn) {
    btn.textContent = 'XMP 생성 중...';
    btn.disabled = true;
  }
  try {
    const data = await API.exportXmp();
    if (data.success) {
      let msg = `총 ${data.count}개 사진의 Lightroom / Capture One 호환 XMP 사이드카 생성이 완료되었습니다!`;
      if (data.skipped && data.skipped.length > 0) {
        msg += `\n\n⚠️ 로컬 원본 사진을 찾지 못해 ${data.skipped.length}개 파일은 건너뛰었습니다. (웹 업로드 전용이거나 원본 파일 이동됨)`;
      }
      if (data.errors && data.errors.length > 0) {
        msg += `\n\n❌ 생성 중 오류 발생: ${data.errors.length}건`;
      }
      alert(msg + '\n\n라이트룸에서 폴더를 동기화하면 별점(1~5)과 색상 라벨이 즉시 표시됩니다.');
    } else {
      alert(`XMP 내보내기 실패: ${data.error}`);
    }
  } catch (err) {
    alert(`오류: ${err.message}`);
  } finally {
    if (btn) {
      btn.textContent = origText;
      btn.disabled = false;
    }
  }
}

// --- Global Keyboard Shortcuts ---
window.addEventListener('keydown', (e) => {
  if (['input', 'textarea', 'select'].includes(document.activeElement?.tagName?.toLowerCase())) return;
  const tourModal = document.getElementById('tournament-modal');
  if (tourModal && tourModal.style.display === 'flex') {
    if (typeof handleTournamentKey === 'function') {
      handleTournamentKey(e);
    }
    return;
  }
  if (e.key === 'Escape') {
    if (typeof closeDetailModal === 'function') closeDetailModal();
    if (typeof closeUsageModal === 'function') closeUsageModal();
    if (typeof closeUploadModal === 'function') closeUploadModal();
    if (typeof closeModelSettingsModal === 'function') closeModelSettingsModal();
    if (typeof closeTournamentModal === 'function') closeTournamentModal();
  } else if (e.key === 'ArrowRight' || e.key === 'k') {
    if (typeof navigateDetail === 'function') navigateDetail(1);
  } else if (e.key === 'ArrowLeft' || e.key === 'j') {
    if (typeof navigateDetail === 'function') navigateDetail(-1);
  } else if (e.key === ' ' || e.code === 'Space') {
    const modal = document.getElementById('detail-modal');
    if (modal && modal.style.display === 'flex') {
      e.preventDefault();
      if (typeof toggleZoom === 'function') toggleZoom();
    }
  }
});

window.addEventListener('DOMContentLoaded', () => {
  initTheme();
  loadData();
});

// Global scope export
window.escapeHtml = escapeHtml;
window.formatCapturedAt = formatCapturedAt;
window.renderBurstThumbnails = renderBurstThumbnails;
window.loadData = loadData;
window.loadAnalyses = loadAnalyses;
window.renderGallery = renderGallery;
window.filterList = filterList;
window.sortList = sortList;
window.deleteAnalysisRecord = deleteAnalysisRecord;
window.exportAllXmp = exportAllXmp;
window.changeBurstSensitivity = changeBurstSensitivity;
window.setFilter = setFilter;
window.setCatFilter = setCatFilter;
window.setBurstFilter = setBurstFilter;
window.toggleExpandBurstGroup = toggleExpandBurstGroup;
window.initTheme = initTheme;
window.toggleTheme = toggleTheme;
