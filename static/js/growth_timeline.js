/**
 * static/js/growth_timeline.js
 * Photo Score Growth & Progression Timeline Chart
 * Visualizes score progression, Top-25% percentile, user ratings, and subscore evolution
 * across Multiple Scales: Session, Weekly, Monthly, Quarterly, and Cumulative Mileage.
 */

function safeEscapeHtml(str) {
  if (typeof escapeHtml === 'function') return escapeHtml(str);
  if (typeof window !== 'undefined' && typeof window.escapeHtml === 'function') return window.escapeHtml(str);
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function safeSetTimeout(fn, ms) {
  if (typeof setTimeout !== 'undefined') return setTimeout(fn, ms);
  if (typeof window !== 'undefined' && typeof window.setTimeout !== 'undefined') return window.setTimeout(fn, ms);
  try { fn(); } catch (e) {}
  return null;
}

function safeClearTimeout(id) {
  if (!id) return;
  if (typeof clearTimeout !== 'undefined') return clearTimeout(id);
  if (typeof window !== 'undefined' && typeof window.clearTimeout !== 'undefined') return window.clearTimeout(id);
}

// Timeline View State
// 'session' | 'weekly' | 'monthly' | 'quarterly' | 'mileage'
let timelineGrouping = 'session'; 

let timelineActiveMetrics = {
  avg: true,     // AI 종합 평균 (Overall AI Average)
  top25: true,   // 🎯 상위 25% 평균 (Top 25% / A컷 풀)
  best: true,    // 👑 AI 최고점 (Peak Score)
  userAvg: true, // 👤 내 점수 평균 (User Rating Average)
  comp: false,   // 구도 (Composition)
  light: false,  // 조명 (Lighting)
  color: false,  // 색감 (Color)
  tech: false    // 기술 (Technique)
};

const TIMELINE_METRIC_CONFIG = {
  avg: { key: 'avg', label: 'AI 종합 평균', color: '#4f46e5', darkColor: '#60a5fa', strokeWidth: 3.2 },
  top25: { key: 'top25', label: '🎯 상위 25%(A컷)', color: '#0d9488', darkColor: '#2dd4bf', strokeWidth: 2.8, dash: '5 3' },
  best: { key: 'best', label: '👑 AI 최고점', color: '#f59e0b', darkColor: '#fbbf24', strokeWidth: 2.2, dash: '3 2' },
  userAvg: { key: 'userAvg', label: '👤 내 점수 평균', color: '#e11d48', darkColor: '#fb7185', strokeWidth: 3.0 },
  comp: { key: 'comp', label: '구도', color: '#10b981', darkColor: '#34d399', strokeWidth: 2 },
  light: { key: 'light', label: '조명', color: '#f97316', darkColor: '#fb923c', strokeWidth: 2 },
  color: { key: 'color', label: '색감', color: '#ec4899', darkColor: '#f472b6', strokeWidth: 2 },
  tech: { key: 'tech', label: '기술', color: '#8b5cf6', darkColor: '#a78bfa', strokeWidth: 2 }
};

let timelineTooltipTimer = null;

function scheduleHideTimelineTooltip() {
  timelineTooltipTimer = safeSetTimeout(() => {
    hideTimelineTooltip();
  }, 180);
}
window.scheduleHideTimelineTooltip = scheduleHideTimelineTooltip;

function cancelHideTimelineTooltip() {
  if (timelineTooltipTimer) {
    safeClearTimeout(timelineTooltipTimer);
    timelineTooltipTimer = null;
  }
}
window.cancelHideTimelineTooltip = cancelHideTimelineTooltip;

function hideTimelineTooltip() {
  cancelHideTimelineTooltip();
  const tooltip = document.getElementById('timeline-tooltip');
  if (tooltip) tooltip.style.display = 'none';
}
window.hideTimelineTooltip = hideTimelineTooltip;

/**
 * Extract item date string (YYYY-MM-DD) using smart basis (EXIF captured_at first, fallback created_at)
 */
function extractTimelineItemDate(item) {
  if (!item) return null;
  if (typeof getItemDateStr === 'function') {
    const s = getItemDateStr(item, 'smart');
    if (s && s.length >= 10) return s.slice(0, 10);
  }
  const cap = item.captured_at ? String(item.captured_at).trim().slice(0, 10).replace(/[:/]/g, '-') : null;
  const cre = item.created_at ? String(item.created_at).trim().slice(0, 10).replace(/[:/]/g, '-') : null;
  return cap || cre;
}

/**
 * ISO Week calculation helpers (Pure Math, zero external library)
 */
function getIsoWeekInfo(dateStr) {
  const parts = dateStr.split('-').map(Number);
  const y = parts[0], m = parts[1], d = parts[2];
  const target = new Date(y, m - 1, d);
  const dayNr = (target.getDay() + 6) % 7;
  target.setDate(target.getDate() - dayNr + 3);
  const firstThursday = target.getTime();
  const year = target.getFullYear();
  target.setMonth(0, 1);
  if (target.getDay() !== 4) {
    target.setMonth(0, 1 + ((4 - target.getDay()) + 7) % 7);
  }
  const weekNr = 1 + Math.ceil((firstThursday - target.getTime()) / 604800000);
  const weekKey = `${year}-W${String(weekNr).padStart(2, '0')}`;
  const label = `${m}월 ${weekNr}주차`;
  return { weekKey, weekNr, year, label };
}

function getIsoWeekRange(year, week) {
  const jan4 = new Date(year, 0, 4);
  const dayOfWeek = jan4.getDay() || 7;
  const monWeek1 = new Date(jan4.getTime() - (dayOfWeek - 1) * 86400000);
  const targetMon = new Date(monWeek1.getTime() + (week - 1) * 7 * 86400000);
  const targetSun = new Date(targetMon.getTime() + 6 * 86400000);
  const fmt = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  return { fromStr: fmt(targetMon), toStr: fmt(targetSun) };
}

/**
 * Quarterly calculation helpers
 */
function getQuarterInfo(dateStr) {
  const parts = dateStr.split('-').map(Number);
  const y = parts[0], m = parts[1];
  const q = Math.ceil(m / 3);
  const seasonLabels = { 1: '1분기 (겨울·초봄)', 2: '2분기 (봄·초여름)', 3: '3분기 (여름·초가을)', 4: '4분기 (가을·초겨울)' };
  const quarterKey = `${y}-Q${q}`;
  const label = `${y}년 ${q}분기`;
  const seasonTitle = `${y}년 ${seasonLabels[q]}`;
  return { quarterKey, year: y, quarter: q, label, seasonTitle };
}

function getQuarterRange(year, quarter) {
  const startMonth = (quarter - 1) * 3 + 1;
  const endMonth = quarter * 3;
  const lastDay = new Date(year, endMonth, 0).getDate();
  const fromStr = `${year}-${String(startMonth).padStart(2, '0')}-01`;
  const toStr = `${year}-${String(endMonth).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`;
  return { fromStr, toStr };
}

/**
 * Get active filter subtitle/badge for timeline
 */
function getTimelineActiveFiltersInfo() {
  const parts = [];
  if (typeof currentCatFilter !== 'undefined' && currentCatFilter !== 'all') {
    parts.push(`🎬 ${currentCatFilter}`);
  }
  if (typeof currentFocalFilter !== 'undefined' && currentFocalFilter !== 'all') {
    const fLabel = (typeof getFocalBandLabel === 'function') ? getFocalBandLabel(currentFocalFilter) : currentFocalFilter;
    parts.push(`🔭 ${fLabel}`);
  }
  if (typeof currentCollectionFilter !== 'undefined' && currentCollectionFilter !== 'all') {
    const colName = (typeof getCollectionNameById === 'function') ? getCollectionNameById(currentCollectionFilter) : currentCollectionFilter;
    parts.push(`📁 ${colName}`);
  }
  return parts.length ? parts.join(' · ') : null;
}

function resetTimelineSubFilters() {
  if (typeof setCatFilter === 'function') setCatFilter('all');
  if (typeof setFocalFilter === 'function') setFocalFilter('all');
  renderGrowthTimeline();
}
window.resetTimelineSubFilters = resetTimelineSubFilters;

/**
 * Group photos across all 5 dimensions (session, weekly, monthly, quarterly, mileage)
 * Automatically respects active category, focal length, collection, and tag filters!
 */
function computeGrowthTimelineData(grouping = timelineGrouping) {
  const rawAll = (typeof allData !== 'undefined' && Array.isArray(allData)) ? allData : [];
  
  // Filter source items respecting Category, Focal Length, Collection, and Tags
  const sourceItems = rawAll.filter(item => {
    if (!item) return false;
    if (typeof matchCollectionScope === 'function' && !matchCollectionScope(item)) return false;
    if (typeof currentCatFilter !== 'undefined' && currentCatFilter !== 'all' && item.figure_category !== currentCatFilter) return false;
    if (typeof currentFocalFilter !== 'undefined' && currentFocalFilter !== 'all' && typeof matchFocalFilter === 'function' && !matchFocalFilter(item, currentFocalFilter)) return false;
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

  if (!sourceItems.length) return [];

  // Sort items chronologically ascending
  const sortedItems = [...sourceItems].sort((a, b) => {
    const da = extractTimelineItemDate(a) || '';
    const db = extractTimelineItemDate(b) || '';
    return da.localeCompare(db);
  });

  const points = [];

  // Helper for computing group metrics
  const computeGroupStats = (key, label, fullDate, items, extraMeta = {}) => {
    const count = items.length;
    if (count === 0) return null;

    let sumFinal = 0, sumComp = 0, sumLight = 0, sumColor = 0, sumTech = 0;
    let maxFinal = -Infinity;
    let bestItem = items[0];

    for (const it of items) {
      const score = Number(it.final_score || 0);
      sumFinal += score;
      if (score > maxFinal) {
        maxFinal = score;
        bestItem = it;
      }
      sumComp += Number(it.composition_score || 0);
      sumLight += Number(it.lighting_score || 0);
      sumColor += Number(it.color_score || 0);
      sumTech += Number(it.technique_score || 0);
    }

    const avgFinal = Math.round((sumFinal / count) * 10) / 10;
    const bestFinal = Math.round(maxFinal * 10) / 10;
    const avgComp = Math.round((sumComp / count) * 10) / 10;
    const avgLight = Math.round((sumLight / count) * 10) / 10;
    const avgColor = Math.round((sumColor / count) * 10) / 10;
    const avgTech = Math.round((sumTech / count) * 10) / 10;

    // Top 25% Percentile (A컷 풀 평균, 노이즈 절사)
    const sortedByScore = [...items].sort((a, b) => Number(b.final_score || 0) - Number(a.final_score || 0));
    const k25 = Math.max(1, Math.ceil(items.length * 0.25));
    const top25Items = sortedByScore.slice(0, k25);
    const top25Sum = top25Items.reduce((acc, it) => acc + Number(it.final_score || 0), 0);
    const top25Avg = Math.round((top25Sum / k25) * 10) / 10;

    // User Ratings Calculation
    const userScoredItems = items.filter(it => it.user_score !== null && it.user_score !== undefined && !isNaN(Number(it.user_score)));
    let userAvg = null;
    let userBest = null;
    if (userScoredItems.length > 0) {
      const userSum = userScoredItems.reduce((acc, it) => acc + Number(it.user_score), 0);
      userAvg = Math.round((userSum / userScoredItems.length) * 10) / 10;
      userBest = Math.round(Math.max(...userScoredItems.map(it => Number(it.user_score))) * 10) / 10;
    }

    return {
      key,
      label,
      fullDate,
      count,
      avgFinal,
      bestFinal,
      top25Avg,
      top25Count: k25,
      userAvg,
      userBest,
      userCount: userScoredItems.length,
      avgComp,
      avgLight,
      avgColor,
      avgTech,
      bestItem,
      items,
      ...extraMeta
    };
  };

  // 1. Mileage Mode (20-cut chunks)
  if (grouping === 'mileage') {
    const CHUNK_SIZE = 20;
    const numBuckets = Math.ceil(sortedItems.length / CHUNK_SIZE);

    for (let b = 0; b < numBuckets; b++) {
      const chunk = sortedItems.slice(b * CHUNK_SIZE, (b + 1) * CHUNK_SIZE);
      if (!chunk.length) continue;

      const startCut = b * CHUNK_SIZE + 1;
      const endCut = b * CHUNK_SIZE + chunk.length;
      const bucketKey = `M_${String(b + 1).padStart(2, '0')}`;
      const firstDate = extractTimelineItemDate(chunk[0]) || '';
      const lastDate = extractTimelineItemDate(chunk[chunk.length - 1]) || '';
      const label = `누적 ${startCut}~${endCut}장`;
      const fullDate = `${label} (${firstDate.slice(5).replace('-', '/')}~${lastDate.slice(5).replace('-', '/')})`;

      const pt = computeGroupStats(bucketKey, label, fullDate, chunk, {
        firstDate,
        lastDate,
        startCut,
        endCut,
        isMileage: true
      });
      if (pt) points.push(pt);
    }
    return points;
  }

  // 2. Temporal Modes (session, weekly, monthly, quarterly)
  const groupsMap = new Map();

  for (const item of sortedItems) {
    const dateStr = extractTimelineItemDate(item);
    if (!dateStr || dateStr.length < 10) continue;

    let groupKey, label, fullDate, extraMeta = {};

    if (grouping === 'weekly') {
      const wInfo = getIsoWeekInfo(dateStr);
      groupKey = wInfo.weekKey;
      label = wInfo.label;
      fullDate = `${wInfo.year}년 ${wInfo.label}`;
      extraMeta = { weekYear: wInfo.year, weekNr: wInfo.weekNr };
    } else if (grouping === 'quarterly') {
      const qInfo = getQuarterInfo(dateStr);
      groupKey = qInfo.quarterKey;
      label = `${qInfo.year}년 ${qInfo.quarter}Q`;
      fullDate = qInfo.seasonTitle;
      extraMeta = { qYear: qInfo.year, qNum: qInfo.quarter };
    } else if (grouping === 'monthly') {
      groupKey = dateStr.slice(0, 7);
      const parts = groupKey.split('-');
      label = `${parts[0].slice(2)}년 ${parseInt(parts[1], 10)}월`;
      fullDate = `${parts[0]}년 ${parseInt(parts[1], 10)}월`;
    } else {
      // Default: session (daily)
      groupKey = dateStr.slice(0, 10);
      const parts = groupKey.split('-');
      label = `${parts[1]}/${parts[2]}`;
      fullDate = groupKey;
    }

    if (!groupsMap.has(groupKey)) {
      groupsMap.set(groupKey, { key: groupKey, label, fullDate, items: [], extraMeta });
    }
    groupsMap.get(groupKey).items.push(item);
  }

  const sortedKeys = Array.from(groupsMap.keys()).sort();
  for (const key of sortedKeys) {
    const grp = groupsMap.get(key);
    const pt = computeGroupStats(grp.key, grp.label, grp.fullDate, grp.items, grp.extraMeta);
    if (pt) points.push(pt);
  }

  return points;
}

/**
 * Compute KPI stats for top summary cards
 */
function computeTimelineKPIs(points) {
  if (!points || points.length === 0) return null;

  const totalSessions = points.length;
  const totalPhotos = points.reduce((acc, p) => acc + p.count, 0);

  const first = points[0];
  const latest = points[points.length - 1];
  
  // AI Growth Delta
  const delta = Math.round((latest.avgFinal - first.avgFinal) * 10) / 10;
  
  // Top 25% Growth Delta
  const top25Delta = Math.round((latest.top25Avg - first.top25Avg) * 10) / 10;

  // Cumulative overall averages
  let totalAiSum = 0;
  let totalUserSum = 0;
  let totalUserCount = 0;

  let allTimeBest = points[0].bestItem;
  let allTimeBestScore = points[0].bestFinal;
  let allTimeBestDate = points[0].key;

  for (const p of points) {
    totalAiSum += p.avgFinal * p.count;
    if (p.userAvg !== null) {
      const userItems = p.items.filter(it => it.user_score !== null && it.user_score !== undefined && !isNaN(Number(it.user_score)));
      totalUserCount += userItems.length;
      totalUserSum += userItems.reduce((acc, cur) => acc + Number(cur.user_score), 0);
    }
    if (p.bestFinal > allTimeBestScore) {
      allTimeBestScore = p.bestFinal;
      allTimeBest = p.bestItem;
      allTimeBestDate = p.key;
    }
  }

  const overallAiAvg = Math.round((totalAiSum / totalPhotos) * 10) / 10;
  const overallUserAvg = totalUserCount > 0 ? Math.round((totalUserSum / totalUserCount) * 10) / 10 : null;

  // Top Growing Skill (구도, 조명, 색감, 기술)
  const subDeltas = [
    { name: '구도', delta: Math.round((latest.avgComp - first.avgComp) * 10) / 10, key: 'comp' },
    { name: '조명', delta: Math.round((latest.avgLight - first.avgLight) * 10) / 10, key: 'light' },
    { name: '색감', delta: Math.round((latest.avgColor - first.avgColor) * 10) / 10, key: 'color' },
    { name: '기술', delta: Math.round((latest.avgTech - first.avgTech) * 10) / 10, key: 'tech' }
  ];
  subDeltas.sort((a, b) => b.delta - a.delta);
  const topGrowthSkill = subDeltas[0];

  return {
    totalSessions,
    totalPhotos,
    firstAvg: first.avgFinal,
    latestAvg: latest.avgFinal,
    delta,
    firstTop25: first.top25Avg,
    latestTop25: latest.top25Avg,
    top25Delta,
    overallAiAvg,
    overallUserAvg,
    totalUserCount,
    allTimeBest,
    allTimeBestScore,
    allTimeBestDate,
    topGrowthSkill,
    subDeltas
  };
}

/**
 * Switch grouping mode (session | weekly | monthly | quarterly | mileage)
 */
function setTimelineGrouping(mode) {
  timelineGrouping = mode;
  renderGrowthTimeline();
}
window.setTimelineGrouping = setTimelineGrouping;

/**
 * Toggle metric visibility in timeline chart
 */
function toggleTimelineMetric(metricKey) {
  if (timelineActiveMetrics.hasOwnProperty(metricKey)) {
    const activeCount = Object.values(timelineActiveMetrics).filter(Boolean).length;
    if (timelineActiveMetrics[metricKey] && activeCount <= 1) {
      return; // Keep at least one metric active
    }
    timelineActiveMetrics[metricKey] = !timelineActiveMetrics[metricKey];
    renderGrowthTimeline();
  }
}
window.toggleTimelineMetric = toggleTimelineMetric;

/**
 * Jump from timeline point directly to gallery filtered by date range
 */
function jumpToTimelineDate(pointKey, groupingMode) {
  if (!pointKey) return;

  hideTimelineTooltip();

  // 1. Switch view to gallery first so that gallery-grid is visible and active
  if (typeof switchView === 'function') {
    switchView('gallery');
  }

  // 2. Resolve target date range based on grouping mode (supports string or legacy boolean isMonthly)
  let mode = timelineGrouping;
  if (typeof groupingMode === 'string') {
    mode = groupingMode;
  } else if (typeof groupingMode === 'boolean') {
    mode = groupingMode ? 'monthly' : 'session';
  } else if (/^\d{4}-\d{2}$/.test(pointKey)) {
    mode = 'monthly';
  } else if (/^\d{4}-W\d{2}$/.test(pointKey)) {
    mode = 'weekly';
  } else if (/^\d{4}-Q\d$/.test(pointKey)) {
    mode = 'quarterly';
  } else if (/^M_\d+$/.test(pointKey)) {
    mode = 'mileage';
  } else if (/^\d{4}-\d{2}-\d{2}$/.test(pointKey)) {
    mode = 'session';
  }
  const points = computeGrowthTimelineData(mode);
  const targetPt = points ? points.find(p => p.key === pointKey) : null;

  if (mode === 'session') {
    if (typeof applySessionDateJump === 'function') {
      applySessionDateJump(pointKey);
    } else if (typeof selectDateSession === 'function') {
      selectDateSession(pointKey);
    }
  } else if (mode === 'mileage' && targetPt && targetPt.firstDate && targetPt.lastDate) {
    if (typeof applyCustomDateJump === 'function') {
      applyCustomDateJump(targetPt.firstDate, targetPt.lastDate);
    }
  } else if (mode === 'weekly' && targetPt && targetPt.weekYear && targetPt.weekNr) {
    const { fromStr, toStr } = getIsoWeekRange(targetPt.weekYear, targetPt.weekNr);
    if (typeof applyCustomDateJump === 'function') {
      applyCustomDateJump(fromStr, toStr);
    }
  } else if (mode === 'quarterly' && targetPt && targetPt.qYear && targetPt.qNum) {
    const { fromStr, toStr } = getQuarterRange(targetPt.qYear, targetPt.qNum);
    if (typeof applyCustomDateJump === 'function') {
      applyCustomDateJump(fromStr, toStr);
    }
  } else if (mode === 'monthly') {
    const parts = pointKey.split('-').map(Number);
    const y = parts[0], m = parts[1];
    const lastDay = new Date(y, m, 0).getDate();
    const fromStr = `${pointKey}-01`;
    const toStr = `${pointKey}-${String(lastDay).padStart(2, '0')}`;
    if (typeof applyCustomDateJump === 'function') {
      applyCustomDateJump(fromStr, toStr);
    }
  } else {
    // Fallback: if single date format YYYY-MM-DD
    if (/^\d{4}-\d{2}-\d{2}$/.test(pointKey) && typeof applySessionDateJump === 'function') {
      applySessionDateJump(pointKey);
    }
  }

  // 3. Smooth scroll down to gallery grid so the user immediately sees filtered photos
  safeSetTimeout(() => {
    const grid = document.getElementById('gallery-grid');
    if (grid) {
      grid.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } else {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  }, 50);
}
window.jumpToTimelineDate = jumpToTimelineDate;

/**
 * Generate pure SVG chart
 */
function renderTimelineSvg(points) {
  if (!points || points.length === 0) return '';

  const svgWidth = 1000;
  const svgHeight = 400;
  const padLeft = 60;
  const padRight = 40;
  const padTop = 35;
  const padBottom = 65;
  const chartWidth = svgWidth - padLeft - padRight;
  const chartHeight = svgHeight - padTop - padBottom;

  // Find score bounds across all active metrics
  let minScore = 5.0;
  let maxScore = 10.0;

  const allVals = [];
  for (const p of points) {
    if (timelineActiveMetrics.avg) allVals.push(p.avgFinal);
    if (timelineActiveMetrics.top25) allVals.push(p.top25Avg);
    if (timelineActiveMetrics.best) allVals.push(p.bestFinal);
    if (timelineActiveMetrics.userAvg && p.userAvg !== null) allVals.push(p.userAvg);
    if (timelineActiveMetrics.comp) allVals.push(p.avgComp);
    if (timelineActiveMetrics.light) allVals.push(p.avgLight);
    if (timelineActiveMetrics.color) allVals.push(p.avgColor);
    if (timelineActiveMetrics.tech) allVals.push(p.avgTech);
  }

  if (allVals.length > 0) {
    const rawMin = Math.min(...allVals);
    minScore = Math.max(0, Math.floor(rawMin - 0.5));
    if (minScore > 5.0) minScore = 5.0;
  }
  const scoreRange = (maxScore - minScore) || 1;

  // Helper coordinate mappers
  const getX = (i) => {
    if (points.length <= 1) return padLeft + chartWidth / 2;
    return padLeft + (i / (points.length - 1)) * chartWidth;
  };
  const getY = (score) => {
    const clamped = Math.max(minScore, Math.min(maxScore, score));
    return padTop + chartHeight - ((clamped - minScore) / scoreRange) * chartHeight;
  };

  // Horizontal Grid Lines & Score labels
  let gridLinesHtml = '';
  const step = 1.0;
  for (let s = minScore; s <= maxScore; s += step) {
    const y = getY(s);
    gridLinesHtml += `
      <line x1="${padLeft}" y1="${y}" x2="${svgWidth - padRight}" y2="${y}" stroke="currentColor" stroke-opacity="0.1" stroke-dasharray="3 3" />
      <text x="${padLeft - 10}" y="${y + 4}" font-size="11" font-weight="700" fill="currentColor" opacity="0.6" text-anchor="end">${s.toFixed(1)}</text>
    `;
  }

  // Defs: Gradients
  const defsHtml = `
    <defs>
      <linearGradient id="timelineAvgGradient" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#4f46e5" stop-opacity="0.28" />
        <stop offset="100%" stop-color="#4f46e5" stop-opacity="0.0" />
      </linearGradient>
      <filter id="timelineDotGlow" x="-50%" y="-50%" width="200%" height="200%">
        <feDropShadow dx="0" dy="2" stdDeviation="2" flood-opacity="0.25" />
      </filter>
    </defs>
  `;

  // Average Area fill (if avg active)
  let areaFillHtml = '';
  if (timelineActiveMetrics.avg && points.length > 1) {
    let pathD = `M ${getX(0)} ${getY(points[0].avgFinal)}`;
    for (let i = 1; i < points.length; i++) {
      pathD += ` L ${getX(i)} ${getY(points[i].avgFinal)}`;
    }
    pathD += ` L ${getX(points.length - 1)} ${padTop + chartHeight} L ${getX(0)} ${padTop + chartHeight} Z`;
    areaFillHtml = `<path d="${pathD}" fill="url(#timelineAvgGradient)" />`;
  }

  // Metric Lines
  const metricKeys = ['avg', 'top25', 'best', 'userAvg', 'comp', 'light', 'color', 'tech'];
  const metricPropMap = {
    avg: 'avgFinal',
    top25: 'top25Avg',
    best: 'bestFinal',
    userAvg: 'userAvg',
    comp: 'avgComp',
    light: 'avgLight',
    color: 'avgColor',
    tech: 'avgTech'
  };

  let linesHtml = '';
  for (const mKey of metricKeys) {
    if (!timelineActiveMetrics[mKey]) continue;
    const cfg = TIMELINE_METRIC_CONFIG[mKey];
    const valProp = metricPropMap[mKey];

    if (mKey === 'userAvg') {
      const validPoints = points.map((p, idx) => ({ p, idx })).filter(item => item.p.userAvg !== null && !isNaN(item.p.userAvg));
      if (validPoints.length > 1) {
        const polyPoints = validPoints.map(item => `${getX(item.idx).toFixed(1)},${getY(item.p.userAvg).toFixed(1)}`).join(' ');
        linesHtml += `
          <polyline points="${polyPoints}" fill="none" stroke="${cfg.color}" stroke-width="${cfg.strokeWidth}"
            stroke-linejoin="round" stroke-linecap="round" />
        `;
      }
    } else {
      if (points.length > 1) {
        const polyPoints = points.map((p, i) => `${getX(i).toFixed(1)},${getY(p[valProp]).toFixed(1)}`).join(' ');
        linesHtml += `
          <polyline points="${polyPoints}" fill="none" stroke="${cfg.color}" stroke-width="${cfg.strokeWidth}"
            ${cfg.dash ? `stroke-dasharray="${cfg.dash}"` : ''} stroke-linejoin="round" stroke-linecap="round" />
        `;
      }
    }
  }

  // Points, X-Axis ticks, and interactive hover targets
  let pointsHtml = '';
  let xLabelsHtml = '';
  const labelInterval = points.length > 20 ? 3 : (points.length > 10 ? 2 : 1);

  points.forEach((p, i) => {
    const x = getX(i);
    const yAvg = getY(p.avgFinal);
    const yBest = getY(p.bestFinal);

    // X Axis Label
    if (i % labelInterval === 0 || i === points.length - 1) {
      xLabelsHtml += `
        <text x="${x}" y="${svgHeight - padBottom + 20}" font-size="11" font-weight="700" fill="currentColor" opacity="0.8" text-anchor="middle">
          ${p.label}
        </text>
        <text x="${x}" y="${svgHeight - padBottom + 35}" font-size="9.5" font-weight="600" fill="currentColor" opacity="0.5" text-anchor="middle">
          ${p.count}장
        </text>
      `;
    }

    // Dots for active metrics with click handlers
    if (timelineActiveMetrics.best) {
      pointsHtml += `
        <circle cx="${x}" cy="${yBest}" r="4.2" fill="#f59e0b" stroke="#ffffff" stroke-width="1.5"
          style="cursor:pointer;pointer-events:all;"
          onclick="jumpToTimelineDate('${p.key}', '${timelineGrouping}')" />
      `;
    }
    if (timelineActiveMetrics.top25) {
      pointsHtml += `
        <rect x="${x - 3.5}" y="${getY(p.top25Avg) - 3.5}" width="7" height="7" rx="1.5" fill="#0d9488" stroke="#ffffff" stroke-width="1.5"
          style="cursor:pointer;pointer-events:all;"
          onclick="jumpToTimelineDate('${p.key}', '${timelineGrouping}')" />
      `;
    }
    if (timelineActiveMetrics.userAvg && p.userAvg !== null) {
      pointsHtml += `
        <circle cx="${x}" cy="${getY(p.userAvg)}" r="4.5" fill="#e11d48" stroke="#ffffff" stroke-width="1.8"
          style="cursor:pointer;pointer-events:all;"
          onclick="jumpToTimelineDate('${p.key}', '${timelineGrouping}')" />
      `;
    }
    if (timelineActiveMetrics.avg) {
      pointsHtml += `
        <circle cx="${x}" cy="${yAvg}" r="5.5" fill="#ffffff" stroke="#4f46e5" stroke-width="2.5" filter="url(#timelineDotGlow)"
          style="cursor:pointer;pointer-events:all;"
          onclick="jumpToTimelineDate('${p.key}', '${timelineGrouping}')" />
      `;
    }

    // Solid transparent vertical hit area for smooth hover & click
    pointsHtml += `
      <rect x="${x - 18}" y="${padTop}" width="36" height="${chartHeight + 15}"
        fill="#ffffff" opacity="0" pointer-events="all" style="cursor:pointer;"
        data-point-idx="${i}" data-date="${p.key}"
        onmouseenter="showTimelineTooltip(${i}, ${x}, ${yAvg}, event)"
        onmousemove="updateTimelineTooltipPos(event)"
        onmouseleave="scheduleHideTimelineTooltip()"
        onclick="jumpToTimelineDate('${p.key}', '${timelineGrouping}')" />
    `;
  });

  return `
    <svg viewBox="0 0 ${svgWidth} ${svgHeight}" class="timeline-chart-svg" style="width:100%;height:auto;display:block;">
      ${defsHtml}
      ${gridLinesHtml}
      ${areaFillHtml}
      ${linesHtml}
      ${pointsHtml}
      ${xLabelsHtml}
    </svg>
  `;
}

/**
 * Tooltip handlers
 */
function showTimelineTooltip(idx, xCoord, yCoord, event) {
  cancelHideTimelineTooltip();

  const points = computeGrowthTimelineData(timelineGrouping);
  if (!points || !points[idx]) return;
  const p = points[idx];

  const tooltip = document.getElementById('timeline-tooltip');
  if (!tooltip) return;

  const dateTitle = `📅 ${p.fullDate}`;

  const bestThumb = p.bestItem ? `
    <div style="display:flex;align-items:center;gap:10px;margin:8px 0;padding:6px 8px;background:rgba(0,0,0,0.04);border-radius:8px;">
      <img src="/api/image/${p.bestItem.id}" alt="${safeEscapeHtml(p.bestItem.filename || '')}" style="width:52px;height:52px;object-fit:cover;border-radius:6px;border:1px solid rgba(0,0,0,0.1);" onerror="this.style.display='none'">
      <div style="flex:1;min-width:0;">
        <div style="font-size:0.75rem;font-weight:800;color:var(--navy);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">👑 최고점 A컷: ${safeEscapeHtml(p.bestItem.filename || '')}</div>
        <div style="font-size:0.73rem;color:#f59e0b;font-weight:900;margin-top:2px;">★ ${p.bestFinal}점 (${p.bestItem.grade || 'A'})</div>
      </div>
    </div>
  ` : '';

  tooltip.innerHTML = `
    <div style="font-size:0.86rem;font-weight:800;color:var(--navy);display:flex;justify-content:space-between;align-items:center;gap:8px;">
      <span>${dateTitle}</span>
      <span style="font-size:0.72rem;background:#4f46e5;color:#fff;padding:2px 7px;border-radius:999px;font-weight:700;">📸 ${p.count}장</span>
    </div>
    ${bestThumb}
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:6px;font-size:0.76rem;">
      <div style="background:var(--card-sub, #f8fafc);padding:5px 7px;border-radius:6px;border:1px solid var(--line,#e2e8f0);">
        <strong style="color:#4f46e5;">AI 평균:</strong> ★ ${p.avgFinal}점
      </div>
      <div style="background:var(--card-sub, #f8fafc);padding:5px 7px;border-radius:6px;border:1px solid var(--line,#e2e8f0);">
        <strong style="color:#0d9488;">상위 25%:</strong> ★ ${p.top25Avg}점
      </div>
      <div style="background:var(--card-sub, #f8fafc);padding:5px 7px;border-radius:6px;border:1px solid var(--line,#e2e8f0);">
        <strong style="color:#f59e0b;">AI 최고점:</strong> ★ ${p.bestFinal}점
      </div>
      <div style="background:var(--card-sub, #f8fafc);padding:5px 7px;border-radius:6px;border:1px solid var(--line,#e2e8f0);">
        <strong style="color:#e11d48;">내 평가:</strong> ${p.userAvg !== null ? '★ ' + p.userAvg + '점 (' + p.userCount + '장)' : '-'}
      </div>
      <div style="background:var(--card-sub, #f8fafc);padding:5px 7px;border-radius:6px;border:1px solid var(--line,#e2e8f0);">
        <strong style="color:#10b981;">구도:</strong> ${p.avgComp} · <strong style="color:#f97316;">조명:</strong> ${p.avgLight}
      </div>
      <div style="background:var(--card-sub, #f8fafc);padding:5px 7px;border-radius:6px;border:1px solid var(--line,#e2e8f0);">
        <strong style="color:#ec4899;">색감:</strong> ${p.avgColor} · <strong style="color:#8b5cf6;">기술:</strong> ${p.avgTech}
      </div>
    </div>
    <div style="margin-top:10px;padding-top:8px;border-top:1px dashed var(--line,#e2e8f0);text-align:center;">
      <button type="button" class="upload-btn"
        style="padding:6px 14px;font-size:0.76rem;background:#4f46e5;color:#fff;border:none;border-radius:8px;width:100%;cursor:pointer;font-weight:700;display:inline-flex;align-items:center;justify-content:center;gap:6px;box-shadow:0 2px 6px rgba(79,70,229,0.3);"
        onclick="jumpToTimelineDate('${p.key}', '${timelineGrouping}')">
        <span>📸</span> <span>이 기간 사진 갤러리 열기 (${p.count}장) ➔</span>
      </button>
    </div>
  `;

  tooltip.style.display = 'block';
  updateTimelineTooltipPos(event);
}
window.showTimelineTooltip = showTimelineTooltip;

function updateTimelineTooltipPos(event) {
  const tooltip = document.getElementById('timeline-tooltip');
  const wrap = document.getElementById('timeline-chart-wrap');
  if (!tooltip || !wrap || !event) return;

  const wrapRect = wrap.getBoundingClientRect();
  let mouseX = event.clientX - wrapRect.left;
  let mouseY = event.clientY - wrapRect.top;

  const ttWidth = 280;
  const ttHeight = 250;

  let left = mouseX + 16;
  if (left + ttWidth > wrapRect.width) {
    left = mouseX - ttWidth - 16;
  }
  let top = mouseY - 40;
  if (top < 10) top = 10;
  if (top + ttHeight > wrapRect.height) {
    top = Math.max(10, wrapRect.height - ttHeight - 10);
  }

  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}
window.updateTimelineTooltipPos = updateTimelineTooltipPos;

/**
 * Main Render Function for Timeline View
 */
function renderGrowthTimeline() {
  const container = document.getElementById('timeline-view');
  if (!container) return;

  const rawAll = (typeof allData !== 'undefined' && Array.isArray(allData)) ? allData : [];
  const points = computeGrowthTimelineData(timelineGrouping);
  const kpis = computeTimelineKPIs(points);
  const activeFilterLabel = getTimelineActiveFiltersInfo();

  if (!points || points.length === 0) {
    container.innerHTML = `
      <div style="text-align:center;padding:70px 20px;color:var(--muted);background:var(--card);border:1px dashed var(--line);border-radius:16px;">
        <div style="font-size:2.4rem;margin-bottom:12px;">📈</div>
        <div style="font-size:1.15rem;font-weight:800;color:var(--navy);margin-bottom:8px;">타임라인을 표시할 촬영 데이터가 없습니다.</div>
        <p style="font-size:0.86rem;max-width:500px;margin:0 auto 16px;">
          ${activeFilterLabel
            ? `현재 선택된 필터 [${activeFilterLabel}]에 일치하는 사진이 없습니다. 필터를 해제해 보세요.`
            : '사진을 업로드하여 첫 번째 피규어 사진 분석을 진행해 보세요!'}
        </p>
        ${activeFilterLabel ? `
          <button type="button" class="filter-btn" style="padding:6px 16px;font-weight:700;color:#4f46e5;border-color:#818cf8;" onclick="resetTimelineSubFilters()">✕ 필터 해제하고 전체 보기</button>
        ` : ''}
      </div>
    `;
    return;
  }

  // Top-25% Growth Delta Badge
  let top25GrowthBadge = '';
  if (kpis.top25Delta > 0) {
    top25GrowthBadge = `<span style="color:#0d9488;font-weight:800;">+${kpis.top25Delta.toFixed(1)}점 상승 ↗</span>`;
  } else if (kpis.top25Delta < 0) {
    top25GrowthBadge = `<span style="color:#ef4444;font-weight:800;">${kpis.top25Delta.toFixed(1)}점 ↘</span>`;
  } else {
    top25GrowthBadge = `<span style="color:var(--muted);font-weight:800;">유지 (변화 없음)</span>`;
  }

  // Metric Toggle Buttons HTML
  const metricButtonsHtml = Object.keys(TIMELINE_METRIC_CONFIG).map(mKey => {
    const cfg = TIMELINE_METRIC_CONFIG[mKey];
    const isActive = timelineActiveMetrics[mKey];
    return `
      <button type="button"
              class="filter-btn slim-btn ${isActive ? 'active' : ''}"
              onclick="toggleTimelineMetric('${mKey}')"
              style="padding:3px 10px;font-size:0.75rem;border-radius:999px;${isActive ? `background:${cfg.color};color:#ffffff;border-color:${cfg.color};font-weight:800;` : 'opacity:0.7;'}"
              title="${cfg.label} 점수 추이선 표시/숨김">
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${isActive ? '#fff' : cfg.color};margin-right:4px;"></span>
        ${cfg.label}
      </button>
    `;
  }).join('');

  // Top Toolbar & Switchers
  const toolbarHtml = `
    <div class="timeline-top-bar" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:14px 20px;margin-bottom:20px;box-shadow:0 2px 8px rgba(0,0,0,0.03);">
      <div>
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
          <h2 style="margin:0;font-size:1.18rem;font-weight:800;color:var(--navy);display:flex;align-items:center;gap:8px;">
            <span>📈</span> 사진 성장 & 점수 발전 타임라인
          </h2>
          ${activeFilterLabel ? `
            <span style="display:inline-flex;align-items:center;gap:5px;background:rgba(79,70,229,0.08);color:#4f46e5;border:1px solid rgba(99,102,241,0.3);padding:3px 10px;border-radius:999px;font-size:0.75rem;font-weight:700;">
              <span>필터: ${safeEscapeHtml(activeFilterLabel)}</span>
              <button type="button" onclick="resetTimelineSubFilters()" style="border:none;background:transparent;color:#4f46e5;font-weight:800;cursor:pointer;padding:0 2px;" title="필터 해제">✕</button>
            </span>
          ` : ''}
        </div>
        <span style="font-size:0.78rem;color:var(--muted);margin-top:3px;display:block;">
          촬영 시기(일별·주별·월별·분기·누적 마일리지)에 따른 AI 종합 평균, 상위 25% A컷 풀, 내 직접 평가의 발전 궤적을 비교합니다.
        </span>
      </div>

      <!-- Granularity Multi-Scale Switcher -->
      <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
        <span style="font-size:0.76rem;font-weight:700;color:var(--muted);margin-right:2px;">집계 스케일:</span>
        <div style="display:inline-flex;background:var(--filter-btn-bg, #e2e8f0);border:1px solid var(--line, #cbd5e1);border-radius:10px;padding:3px;gap:2px;flex-wrap:wrap;">
          <button type="button" class="toggle-logic-btn ${timelineGrouping === 'session' ? 'active' : ''}" onclick="setTimelineGrouping('session')" style="font-size:0.75rem;padding:3px 9px;" title="출사 날짜(세션) 단위">
            📅 일별
          </button>
          <button type="button" class="toggle-logic-btn ${timelineGrouping === 'weekly' ? 'active' : ''}" onclick="setTimelineGrouping('weekly')" style="font-size:0.75rem;padding:3px 9px;" title="주간(Weekly) 단위 집계">
            🗓️ 주별
          </button>
          <button type="button" class="toggle-logic-btn ${timelineGrouping === 'monthly' ? 'active' : ''}" onclick="setTimelineGrouping('monthly')" style="font-size:0.75rem;padding:3px 9px;" title="월간(Monthly) 단위 집계">
            📆 월별
          </button>
          <button type="button" class="toggle-logic-btn ${timelineGrouping === 'quarterly' ? 'active' : ''}" onclick="setTimelineGrouping('quarterly')" style="font-size:0.75rem;padding:3px 9px;" title="분기·계절(Quarterly) 단위 집계">
            🍂 분기·계절
          </button>
          <button type="button" class="toggle-logic-btn ${timelineGrouping === 'mileage' ? 'active' : ''}" onclick="setTimelineGrouping('mileage')" style="font-size:0.75rem;padding:3px 9px;color:#0d9488;font-weight:800;" title="셔터 누적 20장 단위 마일리지 레벨업 뷰">
            🎯 누적 20컷
          </button>
        </div>
      </div>
    </div>
  `;

  // 4 KPI Summary Cards
  const kpiGridHtml = `
    <div class="timeline-kpis-grid" style="display:grid;grid-template-columns:repeat(auto-fit, minmax(220px, 1fr));gap:14px;margin-bottom:20px;">
      <!-- KPI 1: Total Sessions & Photos -->
      <div class="timeline-kpi-card" style="background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:0 2px 6px rgba(0,0,0,0.02);">
        <div style="font-size:0.76rem;font-weight:700;color:var(--muted);margin-bottom:4px;">총 집계 구간 / 분석 사진</div>
        <div style="font-size:1.45rem;font-weight:900;color:var(--navy);">${kpis.totalSessions}구간 <span style="font-size:0.92rem;font-weight:700;color:var(--muted);">(${kpis.totalPhotos}장)</span></div>
        <div style="font-size:0.74rem;color:var(--muted);margin-top:4px;">시작: ${points[0].label} ~ 최근: ${points[points.length - 1].label}</div>
      </div>

      <!-- KPI 2: Top-25% A-Cut Growth Delta -->
      <div class="timeline-kpi-card" style="background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:0 2px 6px rgba(0,0,0,0.02);">
        <div style="font-size:0.76rem;font-weight:700;color:#0d9488;margin-bottom:4px;">🎯 실질 A컷 성장폭 (상위 25%)</div>
        <div style="font-size:1.45rem;font-weight:900;color:var(--navy);">${top25GrowthBadge}</div>
        <div style="font-size:0.74rem;color:var(--muted);margin-top:4px;">
          초기 A컷 ★${kpis.firstTop25}점 → 최근 A컷 ★${kpis.latestTop25}점 (스냅 노이즈 제거)
        </div>
      </div>

      <!-- KPI 3: AI vs User Comparison -->
      <div class="timeline-kpi-card" style="background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:0 2px 6px rgba(0,0,0,0.02);">
        <div style="font-size:0.76rem;font-weight:700;color:#e11d48;margin-bottom:4px;">⚖️ AI 평가 vs 내 직접 평가</div>
        <div style="font-size:1.35rem;font-weight:900;color:var(--navy);">
          AI ★${kpis.overallAiAvg}점 <span style="font-size:0.9rem;font-weight:600;color:var(--muted);">vs</span> 내 점수 ★${kpis.overallUserAvg !== null ? kpis.overallUserAvg : '-'}점
        </div>
        <div style="font-size:0.74rem;color:var(--muted);margin-top:4px;">
          ${kpis.overallUserAvg !== null
            ? `평균 편차: ${Math.abs(kpis.overallAiAvg - kpis.overallUserAvg).toFixed(1)}점 (${kpis.totalUserCount}장 직접 평가 완료)`
            : '사진에 직접 점수를 매겨 AI 평가와 비교해 보세요!'}
        </div>
      </div>

      <!-- KPI 4: Top Growing Skill -->
      <div class="timeline-kpi-card" style="background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:0 2px 6px rgba(0,0,0,0.02);">
        <div style="font-size:0.76rem;font-weight:700;color:var(--muted);margin-bottom:4px;">가장 많이 성장한 부문</div>
        <div style="font-size:1.35rem;font-weight:900;color:#10b981;">
          ${kpis.topGrowthSkill ? `${kpis.topGrowthSkill.name} (${kpis.topGrowthSkill.delta >= 0 ? `+${kpis.topGrowthSkill.delta}` : kpis.topGrowthSkill.delta}점)` : '-'}
        </div>
        <div style="font-size:0.74rem;color:var(--muted);margin-top:4px;">
          구도·조명·색감·기술 4대 평가 요소 비교
        </div>
      </div>
    </div>
  `;

  // Chart Container with Controls
  const chartCardHtml = `
    <div style="background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;margin-bottom:24px;box-shadow:0 2px 8px rgba(0,0,0,0.03);">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:16px;">
        <div style="font-size:0.92rem;font-weight:800;color:var(--navy);display:flex;align-items:center;gap:6px;">
          <span>📊</span> 점수 발전 추이 곡선
          <span style="font-size:0.74rem;font-weight:600;color:var(--muted);">(차트 점 또는 툴팁을 클릭하면 해당 구간 갤러리로 즉시 이동합니다)</span>
        </div>
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
          <span style="font-size:0.74rem;font-weight:700;color:var(--muted);margin-right:2px;">표시 지표:</span>
          ${metricButtonsHtml}
        </div>
      </div>

      <!-- Interactive SVG Chart Area with Tooltip -->
      <div id="timeline-chart-wrap" class="timeline-chart-wrap" style="position:relative;width:100%;overflow-x:auto;">
        ${renderTimelineSvg(points)}
        <div id="timeline-tooltip" class="timeline-tooltip" style="display:none;position:absolute;z-index:90;width:280px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px;box-shadow:0 10px 25px rgba(0,0,0,0.18);pointer-events:auto;"
          onmouseenter="cancelHideTimelineTooltip()"
          onmouseleave="hideTimelineTooltip()"></div>
      </div>
    </div>
  `;

  // Session History Log Table (Reverse chronological order)
  const sortedDesc = [...points].reverse();
  const sessionsTableHtml = `
    <div style="background:var(--card);border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:0 2px 8px rgba(0,0,0,0.03);">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px;">
        <div style="font-size:0.95rem;font-weight:800;color:var(--navy);display:flex;align-items:center;gap:6px;">
          <span>📋</span> 출사 구간별 히스토리 기록 (${sortedDesc.length}건)
        </div>
        <span style="font-size:0.75rem;color:var(--muted);">최신 순 정렬</span>
      </div>

      <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;font-size:0.8rem;text-align:left;">
          <thead>
            <tr style="border-bottom:2px solid var(--line);color:var(--muted);font-weight:700;">
              <th style="padding:10px 8px;">구간 / 출사일</th>
              <th style="padding:10px 8px;">사진 수</th>
              <th style="padding:10px 8px;">AI 종합 평균</th>
              <th style="padding:10px 8px;">🎯 상위 25% (A컷)</th>
              <th style="padding:10px 8px;">👤 내 점수</th>
              <th style="padding:10px 8px;">👑 최고점 A컷</th>
              <th style="padding:10px 8px;">4대 요소</th>
              <th style="padding:10px 8px;text-align:right;">갤러리 바로가기</th>
            </tr>
          </thead>
          <tbody>
            ${sortedDesc.map(p => `
              <tr style="border-bottom:1px solid var(--line);transition:background 0.15s ease;" onmouseenter="this.style.background='var(--card-sub, #f8fafc)'" onmouseleave="this.style.background='transparent'">
                <td style="padding:10px 8px;font-weight:800;color:var(--navy);">
                  📅 ${p.fullDate}
                  <span style="display:block;font-size:0.72rem;font-weight:600;color:var(--muted);">${p.label}</span>
                </td>
                <td style="padding:10px 8px;">
                  <span style="background:rgba(79,70,229,0.08);color:#4f46e5;font-weight:800;padding:2px 8px;border-radius:999px;font-size:0.74rem;">
                    ${p.count}장
                  </span>
                </td>
                <td style="padding:10px 8px;font-weight:800;font-size:0.86rem;color:#4f46e5;">
                  ★ ${p.avgFinal}점
                </td>
                <td style="padding:10px 8px;font-weight:800;font-size:0.86rem;color:#0d9488;">
                  ★ ${p.top25Avg}점
                </td>
                <td style="padding:10px 8px;font-weight:800;font-size:0.86rem;color:#e11d48;">
                  ${p.userAvg !== null ? `★ ${p.userAvg}점` : '<span style="color:var(--muted);font-weight:400;">-</span>'}
                </td>
                <td style="padding:10px 8px;">
                  <div style="display:flex;align-items:center;gap:8px;">
                    ${p.bestItem ? `
                      <img src="/api/image/${p.bestItem.id}" alt="${safeEscapeHtml(p.bestItem.filename || '')}" style="width:34px;height:34px;object-fit:cover;border-radius:6px;border:1px solid var(--line);" onerror="this.style.display='none'">
                    ` : ''}
                    <div>
                      <span style="font-weight:800;color:#f59e0b;">★ ${p.bestFinal}점</span>
                      <span style="display:block;font-size:0.72rem;color:var(--muted);max-width:130px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                        ${safeEscapeHtml(p.bestItem ? p.bestItem.filename : '')}
                      </span>
                    </div>
                  </div>
                </td>
                <td style="padding:10px 8px;font-size:0.73rem;color:var(--muted);">
                  <span style="color:#10b981;font-weight:700;">구도 ${p.avgComp}</span> · 
                  <span style="color:#f97316;font-weight:700;">조명 ${p.avgLight}</span><br>
                  <span style="color:#ec4899;font-weight:700;">색감 ${p.avgColor}</span> · 
                  <span style="color:#8b5cf6;font-weight:700;">기술 ${p.avgTech}</span>
                </td>
                <td style="padding:10px 8px;text-align:right;">
                  <button type="button" class="filter-btn slim-btn" style="padding:4px 10px;font-size:0.74rem;color:#4f46e5;border-color:#c7d2fe;background:rgba(79,70,229,0.06);font-weight:700;"
                    onclick="jumpToTimelineDate('${p.key}', '${timelineGrouping}')">
                    사진 보기 ➔
                  </button>
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;

  container.innerHTML = toolbarHtml + kpiGridHtml + chartCardHtml + sessionsTableHtml;
}
window.renderGrowthTimeline = renderGrowthTimeline;
window.computeGrowthTimelineData = computeGrowthTimelineData;
window.computeTimelineKPIs = computeTimelineKPIs;
