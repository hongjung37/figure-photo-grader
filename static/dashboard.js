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
let allCollections = (typeof window !== 'undefined' && window.allCollections) || [];
let currentCollectionFilter = 'all'; // 'all' | 'unassigned' | '<collection_id>'
let isBatchSelectMode = false;
let selectedBatchIds = new Set();
let currentFilter = 'all';
let isHideExcluded = true;
window.isHideExcluded = isHideExcluded;
let currentCatFilter = 'all';
let currentFocalFilter = 'all'; // 'all' | 'wide_24' | 'semi_wide_35' | 'standard_50' | 'portrait_85' | 'tele_100' | 'unknown' | 'mm:<int>'
let currentDateBasis = 'smart'; // 'smart' | 'captured' | 'created'
let currentDatePreset = 'all';  // 'all' | 'today' | '7d' | '30d' | 'this_month' | 'missing_exif' | 'custom' | 'session'
let currentDateFrom = '';       // 'YYYY-MM-DD'
let currentDateTo = '';         // 'YYYY-MM-DD'
let currentSort = 'score_desc';
let currentDetailId = null;
let currentBurstDist = 15;
let currentBurstFilter = 'all'; // 'all', 'best_only', 'stack'
let expandedBurstGroups = new Set();
let selectedScoreBin = null; // 0.5-point or 0.1-point bin key (e.g., '8.0' or 'p_7.8')
let scoreDistMetric = 'ai'; // 'ai' | 'user' | 'overlay'
let scoreDistStep = '0.5'; // '0.5' | '0.1'
let scoreDistCollapsed = false;

window.allCollections = allCollections;
window.currentCollectionFilter = currentCollectionFilter;

// --- Collection Scope & Batch Selection Helpers (Phase 2) ---
function isCollectionScopeActive() {
  return Boolean(currentCollectionFilter && currentCollectionFilter !== 'all');
}
window.isCollectionScopeActive = isCollectionScopeActive;

function matchCollectionScope(item) {
  if (!item) return false;
  if (!currentCollectionFilter || currentCollectionFilter === 'all') return true;
  const cids = Array.isArray(item.collection_ids) ? item.collection_ids.map(Number) : [];
  if (currentCollectionFilter === 'unassigned' || currentCollectionFilter === 'uncollected') {
    return cids.length === 0;
  }
  const targetId = parseInt(currentCollectionFilter, 10);
  if (Number.isNaN(targetId)) return true;
  return cids.includes(targetId);
}
window.matchCollectionScope = matchCollectionScope;

function getCollectionNameById(cid) {
  const num = Number(cid);
  const found = (allCollections || []).find(c => Number(c.id) === num);
  return found ? found.name : `컬렉션 #${cid}`;
}
window.getCollectionNameById = getCollectionNameById;

// --- Date Scope Helpers (Phase 1) ---
function toLocalDateStr(isoStr) {
  if (!isoStr) return null;
  const s = String(isoStr).trim();
  if (!s) return null;
  // Naive ISO date/datetime (like EXIF DateTimeOriginal '2026-11-01T14:23:05') is already camera local date
  if (/^\d{4}-\d{2}-\d{2}/.test(s) && !/(Z|[+-]\d{2}:?\d{2})$/.test(s.slice(10))) {
    return s.slice(0, 10);
  }
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) {
    return /^\d{4}-\d{2}-\d{2}/.test(s) ? s.slice(0, 10) : null;
  }
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function getItemDateStr(item, basis) {
  if (!item) return null;
  const b = basis || currentDateBasis || 'smart';
  const cap = toLocalDateStr(item.captured_at);
  const cre = toLocalDateStr(item.created_at);
  if (b === 'captured') return cap;
  if (b === 'created') return cre;
  return cap || cre;
}
window.getItemDateStr = getItemDateStr;

function isDateOnlyScopeActive() {
  return currentDatePreset !== 'all' || Boolean(currentDateFrom) || Boolean(currentDateTo);
}

function isDateScopeActive() {
  return isCollectionScopeActive() || isDateOnlyScopeActive();
}
window.isDateScopeActive = isDateScopeActive;

function matchDateScope(item) {
  if (!item) return false;
  if (currentDatePreset === 'missing_exif') {
    return !toLocalDateStr(item.captured_at);
  }
  if (!isDateOnlyScopeActive()) return true;
  const dStr = getItemDateStr(item, currentDateBasis);
  if (!dStr) return false;
  if (currentDateFrom && dStr < currentDateFrom) return false;
  if (currentDateTo && dStr > currentDateTo) return false;
  return true;
}
window.matchDateScope = matchDateScope;

function matchGlobalScope(item) {
  return matchCollectionScope(item) && matchDateScope(item);
}
window.matchGlobalScope = matchGlobalScope;

function getScopedData(sourceList) {
  const src = Array.isArray(sourceList) ? sourceList : (Array.isArray(allData) ? allData : []);
  if (!isDateScopeActive()) return src;
  return src.filter(matchGlobalScope);
}
window.getScopedData = getScopedData;

function getDateScopeLabel() {
  const parts = [];
  if (isCollectionScopeActive()) {
    if (currentCollectionFilter === 'unassigned') {
      parts.push('🗂️ 미분류 사진');
    } else {
      parts.push(`🗂️ 컬렉션: ${getCollectionNameById(currentCollectionFilter)}`);
    }
  }
  if (isDateOnlyScopeActive()) {
    const basisLabel = currentDateBasis === 'captured' ? '촬영일' : (currentDateBasis === 'created' ? '분석일' : '스마트');
    if (currentDatePreset === 'missing_exif') {
      parts.push('EXIF 촬영일 미기록');
    } else if (currentDateFrom && currentDateTo && currentDateFrom === currentDateTo) {
      parts.push(`${basisLabel}: ${currentDateFrom} 단일 세션`);
    } else if (currentDateFrom && currentDateTo) {
      parts.push(`${basisLabel}: ${currentDateFrom} ~ ${currentDateTo}`);
    } else if (currentDateFrom) {
      parts.push(`${basisLabel}: ${currentDateFrom} 이후`);
    } else if (currentDateTo) {
      parts.push(`${basisLabel}: ~ ${currentDateTo} 이전`);
    }
  }
  return parts.length ? parts.join(' · ') : '전체 기간';
}
window.getDateScopeLabel = getDateScopeLabel;

function formatTodayOffset(daysAgo) {
  const d = new Date();
  d.setDate(d.getDate() - (daysAgo || 0));
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function setDateBasis(basis) {
  currentDateBasis = (basis === 'captured' || basis === 'created') ? basis : 'smart';
  window.currentDateBasis = currentDateBasis;
  ['smart', 'captured', 'created'].forEach(k => {
    const btn = document.getElementById(`date-basis-${k}`);
    if (btn) btn.classList.toggle('active', k === currentDateBasis);
  });
  applyDateScopeChange();
}
window.setDateBasis = setDateBasis;

function setDatePreset(preset, btn) {
  currentDatePreset = preset || 'all';
  window.currentDatePreset = currentDatePreset;
  const today = formatTodayOffset(0);
  if (currentDatePreset === 'all' || currentDatePreset === 'missing_exif') {
    currentDateFrom = '';
    currentDateTo = '';
  } else if (currentDatePreset === 'today') {
    currentDateFrom = today;
    currentDateTo = today;
  } else if (currentDatePreset === '7d') {
    currentDateFrom = formatTodayOffset(6);
    currentDateTo = today;
  } else if (currentDatePreset === '30d') {
    currentDateFrom = formatTodayOffset(29);
    currentDateTo = today;
  } else if (currentDatePreset === 'this_month') {
    currentDateFrom = `${today.slice(0, 7)}-01`;
    currentDateTo = today;
  }
  const fromEl = document.getElementById('date-scope-from');
  const toEl = document.getElementById('date-scope-to');
  if (fromEl) fromEl.value = currentDateFrom;
  if (toEl) toEl.value = currentDateTo;
  applyDateScopeChange();
}
window.setDatePreset = setDatePreset;

function onCustomDateRangeChange() {
  const fromEl = document.getElementById('date-scope-from');
  const toEl = document.getElementById('date-scope-to');
  currentDateFrom = fromEl ? (fromEl.value || '').trim() : '';
  currentDateTo = toEl ? (toEl.value || '').trim() : '';
  if (!currentDateFrom && !currentDateTo) {
    currentDatePreset = 'all';
  } else if (currentDateFrom && currentDateTo && currentDateFrom === currentDateTo) {
    currentDatePreset = 'session';
  } else {
    currentDatePreset = 'custom';
  }
  applyDateScopeChange();
}
window.onCustomDateRangeChange = onCustomDateRangeChange;

function selectDateSession(dateStr) {
  if (!dateStr) return;
  if (currentDatePreset === 'session' && currentDateFrom === dateStr && currentDateTo === dateStr) {
    clearDateScope();
    return;
  }
  currentDatePreset = 'session';
  currentDateFrom = dateStr;
  currentDateTo = dateStr;
  const fromEl = document.getElementById('date-scope-from');
  const toEl = document.getElementById('date-scope-to');
  if (fromEl) fromEl.value = dateStr;
  if (toEl) toEl.value = dateStr;
  applyDateScopeChange();
}
window.selectDateSession = selectDateSession;

function applySessionDateJump(dateStr) {
  if (!dateStr) return;
  currentDateBasis = 'smart';
  ['smart', 'captured', 'created'].forEach(k => {
    const btn = document.getElementById(`date-basis-${k}`);
    if (btn) btn.classList.toggle('active', k === 'smart');
  });
  currentDatePreset = 'session';
  currentDateFrom = dateStr;
  currentDateTo = dateStr;
  const fromEl = document.getElementById('date-scope-from');
  const toEl = document.getElementById('date-scope-to');
  if (fromEl) fromEl.value = dateStr;
  if (toEl) toEl.value = dateStr;
  applyDateScopeChange();
}
window.applySessionDateJump = applySessionDateJump;

function applyCustomDateJump(fromStr, toStr) {
  if (!fromStr || !toStr) return;
  currentDateBasis = 'smart';
  ['smart', 'captured', 'created'].forEach(k => {
    const btn = document.getElementById(`date-basis-${k}`);
    if (btn) btn.classList.toggle('active', k === 'smart');
  });
  currentDatePreset = 'custom';
  currentDateFrom = fromStr;
  currentDateTo = toStr;
  const fromEl = document.getElementById('date-scope-from');
  const toEl = document.getElementById('date-scope-to');
  if (fromEl) fromEl.value = fromStr;
  if (toEl) toEl.value = toStr;
  applyDateScopeChange();
}
window.applyCustomDateJump = applyCustomDateJump;

function clearDateScope() {
  currentCollectionFilter = 'all';
  window.currentCollectionFilter = 'all';
  setDatePreset('all');
}
window.clearDateScope = clearDateScope;

function setCollectionFilter(colKey) {
  const nextVal = String(colKey || 'all');
  if (nextVal !== 'all' && currentCollectionFilter === nextVal) {
    currentCollectionFilter = 'all';
  } else {
    currentCollectionFilter = nextVal;
  }
  window.currentCollectionFilter = currentCollectionFilter;
  applyDateScopeChange();
}
window.setCollectionFilter = setCollectionFilter;

function renderCollectionChips() {
  const container = document.getElementById('collection-scope-chips');
  const manageBtns = document.getElementById('collection-manage-btns');
  const batchSelectEl = document.getElementById('batch-target-collection');
  const removeBtn = document.getElementById('btn-batch-remove-from-col');

  const items = Array.isArray(allData) ? allData : [];
  const cols = Array.isArray(allCollections) ? allCollections : [];
  const unassignedCount = items.filter(it => !Array.isArray(it.collection_ids) || it.collection_ids.length === 0).length;

  const isAll = !currentCollectionFilter || currentCollectionFilter === 'all';
  const isUnassigned = currentCollectionFilter === 'unassigned';
  const isSpecificCol = !isAll && !isUnassigned && /^\d+$/.test(String(currentCollectionFilter));

  if (manageBtns) {
    manageBtns.style.display = isSpecificCol ? 'inline-flex' : 'none';
  }
  if (removeBtn) {
    removeBtn.style.display = isSpecificCol ? 'inline-block' : 'none';
  }

  if (batchSelectEl) {
    const prevVal = batchSelectEl.value;
    let optHtml = '<option value="">담을 컬렉션 선택...</option>';
    cols.forEach(c => {
      optHtml += `<option value="${c.id}">🗂️ ${escapeHtml(c.name)} (${c.count || 0}장)</option>`;
    });
    optHtml += '<option value="__new__">+ 새 컬렉션 만들어 담기...</option>';
    batchSelectEl.innerHTML = optHtml;
    if (prevVal && Array.from(batchSelectEl.options || []).some(o => o.value === prevVal)) {
      batchSelectEl.value = prevVal;
    } else if (isSpecificCol) {
      batchSelectEl.value = String(currentCollectionFilter);
    }
  }

  if (!container) return;

  let html = `
    <button type="button"
            class="filter-btn collection-chip-btn ${isAll ? 'active' : ''}"
            onclick="setCollectionFilter('all')"
            style="padding:3px 10px;font-size:0.75rem;border-radius:999px;">
      전체 사진 (${items.length})
    </button>
    <button type="button"
            class="filter-btn collection-chip-btn ${isUnassigned ? 'active' : ''}"
            onclick="setCollectionFilter('unassigned')"
            style="padding:3px 10px;font-size:0.75rem;border-radius:999px;"
            title="어느 컬렉션에도 속하지 않은 미분류 사진">
      미분류 (${unassignedCount})
    </button>
  `;

  cols.forEach(c => {
    const cid = Number(c.id);
    const colItems = items.filter(it => Array.isArray(it.collection_ids) && it.collection_ids.map(Number).includes(cid));
    const cnt = colItems.length;
    const avg = cnt > 0 ? (colItems.reduce((acc, cur) => acc + Number(cur.final_score || 0), 0) / cnt).toFixed(1) : '-';
    const active = String(currentCollectionFilter) === String(cid);
    html += `
      <button type="button"
              class="filter-btn collection-chip-btn ${active ? 'active' : ''}"
              onclick="setCollectionFilter('${cid}')"
              style="padding:3px 10px;font-size:0.75rem;border-radius:999px;${active ? 'background:#4f46e5;color:#fff;border-color:#4f46e5;font-weight:800;' : ''}"
              title="컬렉션 '${escapeHtml(c.name)}' (${cnt}장 · 평균 ${avg}점) — 클릭 시 이 컬렉션 내부 사진과 통계만 표시">
        📁 ${escapeHtml(c.name)} <span style="opacity:0.86;">(${cnt}장${cnt > 0 ? ` · ★${avg}` : ''})</span>
      </button>
    `;
  });

  container.innerHTML = html;
}
window.renderCollectionChips = renderCollectionChips;

async function createNewCollectionPrompt(initialIds = []) {
  const name = prompt('새 컬렉션(앨범) 이름을 입력하세요:\n(예: 2026-11 스튜디오A, 50mm 베스트컷, 야외출사 후보)');
  if (!name || !name.trim()) return null;
  try {
    const res = await API.createCollection(name.trim(), '#4f46e5', initialIds);
    if (res && res.success && res.collection) {
      allCollections = Array.isArray(res.collections) ? res.collections : allCollections;
      window.allCollections = allCollections;
      currentCollectionFilter = String(res.collection.id);
      window.currentCollectionFilter = currentCollectionFilter;
      await loadData();
      return res.collection;
    } else {
      alert(res.error || '컬렉션 생성에 실패했습니다.');
    }
  } catch (err) {
    alert(`컬렉션 생성 오류: ${err.message}`);
  }
  return null;
}
window.createNewCollectionPrompt = createNewCollectionPrompt;

async function renameActiveCollectionPrompt() {
  if (!currentCollectionFilter || !/^\d+$/.test(String(currentCollectionFilter))) return;
  const cid = parseInt(currentCollectionFilter, 10);
  const curName = getCollectionNameById(cid);
  const newName = prompt('변경할 컬렉션 이름을 입력하세요:', curName);
  if (!newName || !newName.trim() || newName.trim() === curName) return;
  try {
    const res = await API.renameCollection(cid, newName.trim());
    if (res && res.success) {
      allCollections = Array.isArray(res.collections) ? res.collections : allCollections;
      window.allCollections = allCollections;
      renderCollectionChips();
      updateStats();
      if (typeof currentView !== 'undefined' && currentView === 'insights' && typeof renderTagInsights === 'function') {
        renderTagInsights();
      }
    } else {
      alert(res.error || '이름 변경에 실패했습니다.');
    }
  } catch (err) {
    alert(`컬렉션 이름 변경 오류: ${err.message}`);
  }
}
window.renameActiveCollectionPrompt = renameActiveCollectionPrompt;

async function deleteActiveCollectionConfirm() {
  if (!currentCollectionFilter || !/^\d+$/.test(String(currentCollectionFilter))) return;
  const cid = parseInt(currentCollectionFilter, 10);
  const curName = getCollectionNameById(cid);
  if (!confirm(`컬렉션 '${curName}'을(를) 삭제하시겠습니까?\n\n※ 컬렉션(앨범) 묶음만 해제되며, 원본 사진과 AI 분석 기록은 삭제되지 않습니다.`)) {
    return;
  }
  try {
    const res = await API.deleteCollection(cid);
    if (res && res.success) {
      currentCollectionFilter = 'all';
      window.currentCollectionFilter = 'all';
      await loadData();
    } else {
      alert(res.error || '컬렉션 삭제 실패');
    }
  } catch (err) {
    alert(`컬렉션 삭제 오류: ${err.message}`);
  }
}
window.deleteActiveCollectionConfirm = deleteActiveCollectionConfirm;

// --- Batch Photo Selection & Organize (Phase 2) ---
function updateBatchSelectBarUI() {
  const bar = document.getElementById('batch-select-bar');
  const toggleBtn = document.getElementById('btn-toggle-batch-select');
  const countEl = document.getElementById('batch-selected-count');
  if (bar) bar.style.display = isBatchSelectMode ? 'flex' : 'none';
  if (toggleBtn) {
    toggleBtn.classList.toggle('active', isBatchSelectMode);
    toggleBtn.textContent = isBatchSelectMode ? `☑️ 선택 모드 중 (${selectedBatchIds.size}장)` : '☑️ 사진 선택·컬렉션 정리';
  }
  if (countEl) countEl.textContent = String(selectedBatchIds.size);

  const reanalyzeBtn = document.getElementById('btn-batch-reanalyze');
  const reanalyzeLabel = document.getElementById('btn-batch-reanalyze-label');
  if (reanalyzeBtn) {
    const hasSelection = selectedBatchIds.size > 0;
    reanalyzeBtn.disabled = !hasSelection;
    reanalyzeBtn.style.opacity = hasSelection ? '1' : '0.5';
    reanalyzeBtn.style.pointerEvents = hasSelection ? 'auto' : 'none';
  }
  if (reanalyzeLabel) {
    reanalyzeLabel.textContent = selectedBatchIds.size > 0
      ? `선택한 사진 일괄 재평가 (${selectedBatchIds.size}장)`
      : '선택한 사진 일괄 재평가';
  }
}

function toggleBatchSelectMode(forceState) {
  isBatchSelectMode = (typeof forceState === 'boolean') ? forceState : !isBatchSelectMode;
  if (!isBatchSelectMode) {
    selectedBatchIds.clear();
  }
  updateBatchSelectBarUI();
  renderGallery(false);
}
window.toggleBatchSelectMode = toggleBatchSelectMode;

function toggleBatchSelectPhoto(id, e) {
  if (e) e.stopPropagation();
  const numId = Number(id);
  if (selectedBatchIds.has(numId)) {
    selectedBatchIds.delete(numId);
  } else {
    selectedBatchIds.add(numId);
  }
  updateBatchSelectBarUI();
  renderGallery(false);
}
window.toggleBatchSelectPhoto = toggleBatchSelectPhoto;

function onGalleryCardClick(id, e) {
  if (isBatchSelectMode) {
    toggleBatchSelectPhoto(id, e);
    return;
  }
  openDetailModal(id);
}
window.onGalleryCardClick = onGalleryCardClick;

function selectAllFilteredPhotos() {
  const filtered = filterList(allData);
  filtered.forEach(it => selectedBatchIds.add(Number(it.id)));
  updateBatchSelectBarUI();
  renderGallery(false);
}
window.selectAllFilteredPhotos = selectAllFilteredPhotos;

function clearBatchSelection() {
  selectedBatchIds.clear();
  updateBatchSelectBarUI();
  renderGallery(false);
}
window.clearBatchSelection = clearBatchSelection;

async function applyBatchAddToCollection() {
  if (selectedBatchIds.size === 0) {
    alert('먼저 컬렉션에 담을 사진을 1장 이상 선택해 주세요.');
    return;
  }
  const sel = document.getElementById('batch-target-collection');
  const targetVal = sel ? sel.value : '';
  const ids = Array.from(selectedBatchIds);

  if (!targetVal) {
    alert('담을 컬렉션을 드롭다운에서 선택해 주세요.');
    return;
  }
  if (targetVal === '__new__') {
    const created = await createNewCollectionPrompt(ids);
    if (created) {
      selectedBatchIds.clear();
      updateBatchSelectBarUI();
    }
    return;
  }
  try {
    const res = await API.updateCollectionItems(parseInt(targetVal, 10), ids, 'add');
    if (res && res.success) {
      selectedBatchIds.clear();
      updateBatchSelectBarUI();
      await loadData();
    } else {
      alert(res.error || '컬렉션에 사진을 추가하지 못했습니다.');
    }
  } catch (err) {
    alert(`컬렉션 담기 오류: ${err.message}`);
  }
}
window.applyBatchAddToCollection = applyBatchAddToCollection;

async function applyBatchRemoveFromCurrentCollection() {
  if (!currentCollectionFilter || !/^\d+$/.test(String(currentCollectionFilter))) return;
  if (selectedBatchIds.size === 0) {
    alert('현재 컬렉션에서 제외할 사진을 선택해 주세요.');
    return;
  }
  const cid = parseInt(currentCollectionFilter, 10);
  const ids = Array.from(selectedBatchIds);
  try {
    const res = await API.updateCollectionItems(cid, ids, 'remove');
    if (res && res.success) {
      selectedBatchIds.clear();
      updateBatchSelectBarUI();
      await loadData();
    } else {
      alert(res.error || '컬렉션에서 제외하지 못했습니다.');
    }
  } catch (err) {
    alert(`컬렉션 제외 오류: ${err.message}`);
  }
}
window.applyBatchRemoveFromCurrentCollection = applyBatchRemoveFromCurrentCollection;

function renderDateSessionChips() {
  const container = document.getElementById('date-session-chips');
  if (!container) return;
  const sourceItems = (Array.isArray(allData) ? allData : []).filter(matchCollectionScope);
  if (!sourceItems.length) {
    container.innerHTML = '<span style="font-size:0.74rem;color:var(--muted);">데이터 없음</span>';
    return;
  }

  const buckets = {};
  let missingCount = 0;
  sourceItems.forEach(item => {
    const dStr = getItemDateStr(item, currentDateBasis);
    if (!dStr) {
      missingCount += 1;
      return;
    }
    if (!buckets[dStr]) {
      buckets[dStr] = { date: dStr, count: 0, scoreSum: 0 };
    }
    buckets[dStr].count += 1;
    buckets[dStr].scoreSum += Number(item.final_score || 0);
  });

  const sortedDates = Object.values(buckets)
    .sort((a, b) => b.date.localeCompare(a.date))
    .slice(0, 10);

  if (!sortedDates.length) {
    container.innerHTML = '<span style="font-size:0.74rem;color:var(--muted);">해당 기준의 날짜 기록이 없습니다</span>';
    return;
  }

  container.innerHTML = sortedDates.map(b => {
    const avg = (b.scoreSum / b.count).toFixed(1);
    const shortDate = b.date.slice(5).replace('-', '/'); // MM/DD
    const isActive = (currentDateFrom === b.date && currentDateTo === b.date && currentDatePreset !== 'missing_exif');
    return `
      <button type="button"
              class="filter-btn date-session-chip ${isActive ? 'active' : ''}"
              onclick="selectDateSession('${b.date}')"
              style="padding:2px 8px;font-size:0.73rem;border-radius:999px;${isActive ? 'background:#4f46e5;color:#fff;border-color:#4f46e5;font-weight:800;' : ''}"
              title="${b.date} 세션 (${b.count}장 · 평균 ${avg}점) — 클릭 시 이 날짜만 분석/필터링">
        📅 ${shortDate} <span style="opacity:0.85;">(${b.count}장 · ★${avg})</span>
      </button>
    `;
  }).join('');
}

let dateScopeDrawerOpen = false;
let advFilterDrawerOpen = false;

function toggleDateScopeDrawer(forceState) {
  dateScopeDrawerOpen = (typeof forceState === 'boolean') ? forceState : !dateScopeDrawerOpen;
  const drawer = document.getElementById('date-scope-drawer');
  const arrow = document.getElementById('date-drawer-arrow');
  if (drawer) drawer.style.display = dateScopeDrawerOpen ? 'block' : 'none';
  if (arrow) arrow.textContent = dateScopeDrawerOpen ? '▴' : '▾';
  updateDateScopeUI();
}
window.toggleDateScopeDrawer = toggleDateScopeDrawer;

function toggleAdvFilterDrawer(forceState) {
  advFilterDrawerOpen = (typeof forceState === 'boolean') ? forceState : !advFilterDrawerOpen;
  const drawer = document.getElementById('adv-filter-drawer');
  const arrow = document.getElementById('adv-filter-arrow');
  const btn = document.getElementById('btn-toggle-adv-filters');
  if (drawer) drawer.style.display = advFilterDrawerOpen ? 'block' : 'none';
  if (arrow) arrow.textContent = advFilterDrawerOpen ? '▴' : '▾';
  if (btn) btn.classList.toggle('active', advFilterDrawerOpen);
}
window.toggleAdvFilterDrawer = toggleAdvFilterDrawer;

function getDateOnlyShortLabel() {
  if (!isDateOnlyScopeActive()) return '전체 기간';
  const presetLabels = {
    today: '오늘',
    '7d': '최근 7일',
    '30d': '최근 30일',
    this_month: '이번 달',
    missing_exif: 'EXIF 미기록'
  };
  if (presetLabels[currentDatePreset]) return presetLabels[currentDatePreset];
  if (currentDateFrom && currentDateTo) {
    if (currentDateFrom === currentDateTo) return currentDateFrom.slice(5).replace('-', '/');
    return `${currentDateFrom.slice(5)}~${currentDateTo.slice(5)}`;
  }
  if (currentDateFrom) return `${currentDateFrom.slice(5)}~`;
  if (currentDateTo) return `~${currentDateTo.slice(5)}`;
  return '기간 지정됨';
}

function updateDateScopeUI() {
  const dateActive = isDateOnlyScopeActive();
  document.querySelectorAll('.date-preset-btn[data-date-preset]').forEach(btn => {
    const p = btn.getAttribute('data-date-preset');
    btn.classList.toggle('active', p === currentDatePreset);
  });
  const clearBtn = document.getElementById('btn-clear-date-scope');
  if (clearBtn) clearBtn.style.display = dateActive ? 'inline-flex' : 'none';

  const triggerBtn = document.getElementById('btn-toggle-date-drawer');
  const labelEl = document.getElementById('date-drawer-label');
  if (labelEl) {
    labelEl.textContent = getDateOnlyShortLabel();
  }
  if (triggerBtn) {
    triggerBtn.classList.toggle('has-active-scope', dateActive);
    triggerBtn.classList.toggle('active', dateScopeDrawerOpen);
  }
}

function applyDateScopeChange() {
  renderCollectionChips();
  updateDateScopeUI();
  renderDateSessionChips();
  updateStats();
  if (typeof populateCompareSelects === 'function') populateCompareSelects();
  if (typeof populateTagSelectorAndQuickTags === 'function') populateTagSelectorAndQuickTags();
  renderScoreDistPanel();
  renderGallery();
  if (typeof currentView !== 'undefined' && currentView === 'insights' && typeof renderTagInsights === 'function') {
    renderTagInsights();
  }
  if (typeof currentView !== 'undefined' && currentView === 'timeline' && typeof renderGrowthTimeline === 'function') {
    renderGrowthTimeline();
  }
}
window.applyDateScopeChange = applyDateScopeChange;

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

  // Filter items by current global scope (collection + date) + category/focal/tag/burst (excluding grade & bin filter so full distribution is visible)
  const baseList = allData.filter(item => {
    if (isHideExcluded && item.is_excluded) return false;
    if (!matchGlobalScope(item)) return false;
    if (currentCatFilter !== 'all' && item.figure_category !== currentCatFilter) return false;
    if (currentFocalFilter !== 'all' && !matchFocalFilter(item, currentFocalFilter)) return false;
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

const FOCAL_BAND_SHORT_LABELS = {
  wide_24: '24mm 이하',
  semi_wide_35: '35mm 부근',
  standard_50: '50mm 부근',
  portrait_85: '70~85mm',
  tele_100: '100mm+',
  unknown: '화각 미식별'
};

const BURST_SHORT_LABELS = {
  best_only: '👑 Best Pick만',
  stack: '🗂️ 연사 묶기',
  burst_only: '연사 컷만'
};

function updateAdvFilterSummaryUI() {
  const pillsEl = document.getElementById('active-adv-filter-pills');
  const countBadge = document.getElementById('adv-filter-count-badge');
  const triggerBtn = document.getElementById('btn-toggle-adv-filters');

  let activeCount = 0;
  const pills = [];

  if (currentCatFilter && currentCatFilter !== 'all') {
    activeCount += 1;
    pills.push(`
      <span class="active-adv-pill" title="활성 피규어 유형 필터">
        <span>${escapeHtml(currentCatFilter)}</span>
        <button type="button" onclick="setCatFilter('all')" title="유형 필터 해제">✕</button>
      </span>
    `);
  }

  if (currentFocalFilter && currentFocalFilter !== 'all' && !currentFocalFilter.startsWith('mm:')) {
    activeCount += 1;
    const flLabel = FOCAL_BAND_SHORT_LABELS[currentFocalFilter] || currentFocalFilter;
    pills.push(`
      <span class="active-adv-pill" title="활성 화각 구간 필터">
        <span>🔭 ${escapeHtml(flLabel)}</span>
        <button type="button" onclick="clearFocalFilter()" title="화각 필터 해제">✕</button>
      </span>
    `);
  } else if (currentFocalFilter && currentFocalFilter.startsWith('mm:')) {
    activeCount += 1;
  }

  if (currentBurstFilter && currentBurstFilter !== 'all') {
    activeCount += 1;
    const bLabel = BURST_SHORT_LABELS[currentBurstFilter] || currentBurstFilter;
    pills.push(`
      <span class="active-adv-pill" title="활성 연사 선별 필터">
        <span>${escapeHtml(bLabel)}</span>
        <button type="button" onclick="setBurstFilter('all')" title="연사 필터 해제">✕</button>
      </span>
    `);
  }

  if (typeof selectedTags !== 'undefined' && selectedTags && selectedTags.size > 0) {
    activeCount += selectedTags.size;
    Array.from(selectedTags).forEach(tag => {
      const escTag = escapeHtml(tag);
      pills.push(`
        <span class="active-adv-pill" style="background:rgba(14,165,233,0.12);color:#0284c7;border-color:rgba(14,165,233,0.35);" title="활성 미학 태그 필터">
          <span>#${escTag}</span>
          <button type="button" data-tag-action="toggle" data-tag="${escTag}" title="태그 필터 해제">✕</button>
        </span>
      `);
    });
  }

  if (pillsEl) {
    pillsEl.innerHTML = pills.join('');
  }
  if (countBadge) {
    if (activeCount > 0) {
      countBadge.textContent = String(activeCount);
      countBadge.style.display = 'inline-flex';
    } else {
      countBadge.style.display = 'none';
    }
  }
  if (triggerBtn) {
    triggerBtn.classList.toggle('has-active-filter', activeCount > 0);
  }
}
window.updateAdvFilterSummaryUI = updateAdvFilterSummaryUI;

function setCatFilter(cat, btn) {
  currentCatFilter = cat || 'all';
  document.querySelectorAll('.cat-btn').forEach(b => {
    const cVal = b.getAttribute ? b.getAttribute('data-cat-val') : null;
    if (btn) {
      b.classList.toggle('active', b === btn);
    } else if (cVal) {
      b.classList.toggle('active', cVal === currentCatFilter);
    } else {
      b.classList.remove('active');
    }
  });
  updateAdvFilterSummaryUI();
  renderScoreDistPanel();
  renderGallery();
  if (typeof currentView !== 'undefined' && currentView === 'timeline' && typeof renderGrowthTimeline === 'function') {
    renderGrowthTimeline();
  }
}

function getItemFocalMm(item) {
  if (!item) return null;
  if (item.focal_length_mm !== undefined && item.focal_length_mm !== null) {
    const num = Number(item.focal_length_mm);
    if (!Number.isNaN(num) && num > 0) return num;
  }
  if (typeof window.extractFocalLengthMm === 'function') {
    return window.extractFocalLengthMm(item);
  }
  const exif = item.exif || {};
  const det = item.detected_camera_settings || {};
  const raw = exif.FocalLengthIn35mmFilm || exif.FocalLength || det.focal_length || det.FocalLength;
  if (raw !== undefined && raw !== null) {
    const m = String(raw).match(/(\d+(?:\.\d+)?)/);
    if (m) {
      const fval = parseFloat(m[1]);
      if (fval >= 1 && fval <= 2000) return Math.round(fval * 10) / 10;
    }
  }
  const lensStr = String(det.lens || exif.LensModel || '');
  if (lensStr && !/\d+\s*-\s*\d+\s*mm/i.test(lensStr)) {
    const mp = lensStr.match(/\b(\d{2,3}(?:\.\d+)?)\s*mm\b/i);
    if (mp) return parseFloat(mp[1]);
  }
  return null;
}

function getItemFocalBandKey(item) {
  if (item && item.focal_band_key) return item.focal_band_key;
  const fl = getItemFocalMm(item);
  if (fl === null || fl <= 0) return 'unknown';
  if (fl <= 28) return 'wide_24';
  if (fl <= 40) return 'semi_wide_35';
  if (fl <= 60) return 'standard_50';
  if (fl <= 90) return 'portrait_85';
  return 'tele_100';
}

function matchFocalFilter(item, focalKey) {
  if (!focalKey || focalKey === 'all') return true;
  if (focalKey.startsWith('mm:')) {
    const targetMm = parseInt(focalKey.slice(3), 10);
    const fl = getItemFocalMm(item);
    return fl !== null && Math.round(fl) === targetMm;
  }
  return getItemFocalBandKey(item) === focalKey;
}

function updateFocalExactBadge() {
  const badge = document.getElementById('active-focal-exact-badge');
  const text = document.getElementById('active-focal-exact-text');
  if (!badge || !text) return;
  if (currentFocalFilter && currentFocalFilter.startsWith('mm:')) {
    const mmVal = currentFocalFilter.slice(3);
    text.textContent = `🔭 단일 화각: ${mmVal}mm`;
    badge.style.display = 'inline-flex';
  } else {
    badge.style.display = 'none';
  }
}

function setFocalFilter(focalKey, btn) {
  currentFocalFilter = focalKey || 'all';
  window.currentFocalFilter = currentFocalFilter;
  document.querySelectorAll('.focal-btn').forEach(b => {
    const bKey = b.getAttribute ? b.getAttribute('data-focal-key') : null;
    if (btn) {
      b.classList.toggle('active', b === btn);
    } else if (bKey) {
      b.classList.toggle('active', bKey === currentFocalFilter);
    } else {
      b.classList.remove('active');
    }
  });
  updateFocalExactBadge();
  updateAdvFilterSummaryUI();
  renderScoreDistPanel();
  renderGallery();
  if (typeof currentView !== 'undefined' && currentView === 'timeline' && typeof renderGrowthTimeline === 'function') {
    renderGrowthTimeline();
  }
}

function clearFocalFilter() {
  setFocalFilter('all');
}

async function loadData() {
  const data = await API.fetchAnalyses(currentBurstDist);
  allData = Array.isArray(data) ? data : [];
  window.allData = allData;
  if (API && typeof API.fetchCollections === 'function') {
    try {
      const cols = await API.fetchCollections();
      allCollections = Array.isArray(cols) ? cols : [];
      window.allCollections = allCollections;
    } catch (e) {
      allCollections = [];
      window.allCollections = [];
    }
  }
  renderCollectionChips();
  updateDateScopeUI();
  renderDateSessionChips();
  updateStats();
  if (typeof populateCompareSelects === 'function') populateCompareSelects();
  if (typeof populateTagSelectorAndQuickTags === 'function') populateTagSelectorAndQuickTags();
  if (typeof updateTagFilterUI === 'function') updateTagFilterUI();
  renderScoreDistPanel();
  renderGallery();
  if (typeof currentView !== 'undefined' && currentView === 'insights' && typeof renderTagInsights === 'function') {
    renderTagInsights();
  }
  if (typeof currentView !== 'undefined' && currentView === 'timeline' && typeof renderGrowthTimeline === 'function') {
    renderGrowthTimeline();
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
  const summaryEl = document.getElementById('active-date-scope-summary');

  const scoped = getScopedData(allData);
  const activeScope = isDateScopeActive();

  if (totalEl) {
    totalEl.textContent = activeScope ? `${scoped.length} / ${allData.length}` : String(allData.length);
  }
  if (!scoped.length) {
    if (avgEl) avgEl.textContent = '0.0';
    if (goodEl) goodEl.textContent = '0';
    if (summaryEl) {
      if (activeScope) {
        summaryEl.style.display = 'inline';
        summaryEl.textContent = `🎯 [${getDateScopeLabel()}] 해당 기간 사진 0장`;
      } else {
        summaryEl.style.display = 'none';
      }
    }
    return;
  }
  const avgNum = scoped.reduce((acc, cur) => acc + cur.final_score, 0) / scoped.length;
  const avg = avgNum.toFixed(1);
  const good = scoped.filter(d => d.final_score >= 7.0).length;
  if (avgEl) avgEl.textContent = avg;
  if (goodEl) goodEl.textContent = String(good);

  if (summaryEl) {
    if (activeScope && allData.length > 0) {
      const globalAvg = allData.reduce((acc, cur) => acc + cur.final_score, 0) / allData.length;
      const diff = avgNum - globalAvg;
      const diffSign = diff >= 0 ? `+${diff.toFixed(2)}▲` : `${diff.toFixed(2)}▼`;
      summaryEl.style.display = 'inline';
      summaryEl.textContent = `🎯 [${getDateScopeLabel()}] ${scoped.length}장 · 평균 ${avgNum.toFixed(2)}점 (전체 대비 ${diffSign})`;
    } else {
      summaryEl.style.display = 'none';
    }
  }
}

function setBurstFilter(mode, btn) {
  currentBurstFilter = mode || 'all';
  document.querySelectorAll('.burst-btn, .burst-filter-btn').forEach(b => {
    const bVal = b.getAttribute ? b.getAttribute('data-burst-val') : null;
    if (btn) {
      b.classList.toggle('active', b === btn);
    } else if (bVal) {
      b.classList.toggle('active', bVal === currentBurstFilter);
    } else {
      b.classList.remove('active');
    }
  });
  updateAdvFilterSummaryUI();
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
  document.querySelectorAll('.filter-btn:not(.burst-btn):not(.cat-btn):not(.focal-btn):not(.date-preset-btn):not(.date-session-chip):not(.collection-chip-btn):not(#btn-toggle-score-dist):not(#btn-toggle-date-drawer):not(#btn-toggle-adv-filters):not(#btn-clear-tag-filter)').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  renderGallery();
}

function filterList(list) {
  return list.filter(item => {
    // 0. Prompt test / statistical exclusion filter
    if (isHideExcluded && item.is_excluded) return false;

    // 0-b. Global Scope filter (Collection + Date)
    if (!matchGlobalScope(item)) return false;

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

    // 2-b. Focal length filter
    if (currentFocalFilter !== 'all' && !matchFocalFilter(item, currentFocalFilter)) return false;

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

function isFastAnalysisItem(item) {
  if (!item) return false;
  if (item.analysis_mode === 'fast') return true;
  if (item.analysis_mode === 'full') return false;
  const hasNotes = Boolean(
    (item.composition_notes && String(item.composition_notes).trim()) ||
    (item.lighting_notes && String(item.lighting_notes).trim()) ||
    (item.color_notes && String(item.color_notes).trim()) ||
    (item.technique_notes && String(item.technique_notes).trim())
  );
  const hasLists = Boolean(
    (Array.isArray(item.strengths) && item.strengths.length > 0) ||
    (Array.isArray(item.improvements) && item.improvements.length > 0)
  );
  return !(hasNotes || hasLists);
}

function renderGalleryCard(item) {
  const modelBadgeText = (window.ModelSettings && item.model)
    ? window.ModelSettings.formatBadge(item.model)
    : (item.model || '');
  const focalMm = getItemFocalMm(item);
  const isFast = isFastAnalysisItem(item);
  const tagPillsHtml = typeof renderTagPills === 'function' ? renderTagPills(item.aesthetic_tags) : '';
  const isBatchChecked = isBatchSelectMode && selectedBatchIds.has(Number(item.id));
  const itemColIds = Array.isArray(item.collection_ids) ? item.collection_ids.map(Number) : [];
  const itemColBadgesHtml = itemColIds.map(cid => {
    const col = (allCollections || []).find(c => Number(c.id) === cid);
    if (!col) return '';
    return `<span style="display:inline-block;margin-top:4px;margin-left:4px;font-size:0.72rem;font-weight:800;color:#0f766e;background:#f0fdfa;border:1px solid #99f6e4;padding:1px 7px;border-radius:6px;" title="소속 컬렉션: ${escapeHtml(col.name)}">📁 ${escapeHtml(col.name)}</span>`;
  }).join('');
  return `
    <article class="card ${item.is_excluded ? 'card-excluded' : ''}" style="${isBatchChecked ? 'box-shadow:0 0 0 3px #0d9488;border-color:#0d9488;' : ''}" onclick="onGalleryCardClick(${item.id}, event)">
      ${isBatchSelectMode ? `
        <div style="position:absolute;top:10px;left:10px;z-index:6;display:flex;align-items:center;gap:6px;">
          <span style="background:${isBatchChecked ? '#0d9488' : 'rgba(15,23,42,0.75)'};color:white;padding:4px 9px;border-radius:8px;font-size:0.75rem;font-weight:800;box-shadow:0 2px 6px rgba(0,0,0,0.25);">
            ${isBatchChecked ? '☑️ 선택됨' : '⬜ 선택'}
          </span>
          <button type="button" class="filter-btn" style="padding:3px 7px;font-size:0.7rem;background:rgba(255,255,255,0.92);color:#0f172a;border:1px solid #cbd5e1;" onclick="event.stopPropagation(); openDetailModal(${item.id})">🔍 상세</button>
        </div>
      ` : ''}
      <button class="card-exclude-btn" title="${item.is_excluded ? '통계에 다시 포함' : '프롬프트 테스트/통계에서 제외'}" onclick="event.stopPropagation(); toggleExcludeRecord(${item.id})">${item.is_excluded ? '↩️' : '🚫'}</button>
      <button class="card-delete-btn" title="이 분석 기록 삭제" onclick="event.stopPropagation(); deleteAnalysisRecord(${item.id})">🗑️</button>
      <img class="card-thumb" src="/api/image/${item.id}" alt="${escapeHtml(item.filename)}" loading="lazy">
      <div class="card-body">
        <div class="card-header">
          <div>
            <h3 class="card-title">${escapeHtml(item.filename)}</h3>
            <div style="margin-top:4px;font-size:0.72rem;color:var(--muted);">📷 ${escapeHtml(formatCapturedAt(item.captured_at))}</div>
            <span style="display:inline-block;margin-top:4px;font-size:0.75rem;font-weight:700;color:#4f46e5;background:#eef2ff;padding:2px 7px;border-radius:6px;">${escapeHtml(item.figure_category)}</span>
            ${item.is_excluded ? '<span class="badge-excluded" title="프롬프트 테스트/통계 제외">🚫 통계 제외</span>' : ''}
            <span style="display:inline-block;margin-top:4px;margin-left:4px;font-size:0.75rem;font-weight:700;color:#0d9488;background:#f0fdfa;padding:2px 7px;border-radius:6px;">🎯 ${escapeHtml(item.focus_status || '완벽 칼초점')}</span>
            ${focalMm !== null ? `<span style="display:inline-block;margin-top:4px;margin-left:4px;font-size:0.74rem;font-weight:700;color:#0369a1;background:#e0f2fe;border:1px solid #bae6fd;padding:1px 7px;border-radius:6px;" title="촬영 화각(초점거리): ${focalMm}mm">🔭 ${Math.round(focalMm)}mm</span>` : ''}
            ${modelBadgeText ? `<span style="display:inline-block;margin-top:4px;margin-left:4px;font-size:0.73rem;font-weight:700;color:#334155;background:rgba(148,163,184,0.16);border:1px solid rgba(148,163,184,0.35);padding:1px 7px;border-radius:6px;" title="평가 모델: ${escapeHtml(item.model)}">🤖 ${escapeHtml(modelBadgeText)}</span>` : ''}
            ${isFast ? `<span style="display:inline-block;margin-top:4px;margin-left:4px;font-size:0.73rem;font-weight:800;color:#b45309;background:#fef3c7;border:1px solid #fde68a;padding:1px 7px;border-radius:6px;" title="대량 선별용 경량 분석 모드 (상세 비평·미학 태그 생략)">⚡ 경량</span>` : ''}
            ${itemColBadgesHtml}
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
              <span class="cross-check-badge" title="${(/gemini/i.test(item.cross_check_opinion.model || '') ? 'Gemini' : 'OpenAI')}(${escapeHtml(item.cross_check_opinion.model || '')}) 보조 의견: ${Number(item.cross_check_opinion.score).toFixed(1)}점">🤝 ${/gemini/i.test(item.cross_check_opinion.model || '') ? 'Gemini' : 'OpenAI'} ${Number(item.cross_check_opinion.score).toFixed(1)}</span>
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
        ${tagPillsHtml ? `<div class="tag-pills">${tagPillsHtml}</div>` : ''}
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
window.setFocalFilter = setFocalFilter;
window.clearFocalFilter = clearFocalFilter;
window.getItemFocalMm = getItemFocalMm;
window.getItemFocalBandKey = getItemFocalBandKey;
window.matchFocalFilter = matchFocalFilter;
window.isFastAnalysisItem = isFastAnalysisItem;
window.setBurstFilter = setBurstFilter;
window.toggleExpandBurstGroup = toggleExpandBurstGroup;
window.initTheme = initTheme;
window.toggleTheme = toggleTheme;
window.selectedBatchIds = selectedBatchIds;
window.isBatchSelectMode = isBatchSelectMode;

function toggleHideExcluded() {
  isHideExcluded = !isHideExcluded;
  window.isHideExcluded = isHideExcluded;
  updateHideExcludedButtonUI();
  renderGallery();
  renderScoreDistPanel();
}

function updateHideExcludedButtonUI() {
  const btn = document.getElementById('btn-toggle-hide-excluded');
  const label = document.getElementById('label-hide-excluded');
  if (!btn || !label) return;
  if (isHideExcluded) {
    btn.classList.add('active');
    btn.style.background = '#fef2f2';
    btn.style.color = '#991b1b';
    btn.style.borderColor = '#fca5a5';
    label.textContent = '🧪 테스트 숨김 ON';
  } else {
    btn.classList.remove('active');
    btn.style.background = '';
    btn.style.color = '';
    btn.style.borderColor = '';
    label.textContent = '🧪 테스트 숨김 OFF';
  }
}

async function toggleExcludeRecord(id, targetState = null) {
  const item = allData.find(d => Number(d.id) === Number(id));
  if (!item) return;
  const newState = (targetState !== null) ? targetState : !item.is_excluded;
  try {
    const res = await fetch('/api/toggle-exclude', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, is_excluded: newState })
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      alert(data.error || '제외 상태 변경에 실패했습니다.');
      return;
    }
    item.is_excluded = newState;
    renderGallery(false);
    renderScoreDistPanel();
    if (typeof renderTagInsights === 'function' && window.currentView === 'insights') {
      renderTagInsights();
    }
    if (typeof renderGrowthTimeline === 'function' && window.currentView === 'timeline') {
      renderGrowthTimeline();
    }
    if (typeof currentDetailId !== 'undefined' && Number(currentDetailId) === Number(id)) {
      if (typeof openDetailModal === 'function') openDetailModal(id);
    }
  } catch (err) {
    console.error(err);
    alert('서버 통신 오류가 발생했습니다.');
  }
}

async function applyBatchExclude(isExcluded) {
  if (!selectedBatchIds || selectedBatchIds.size === 0) {
    alert('선택된 사진이 없습니다.');
    return;
  }
  const ids = Array.from(selectedBatchIds);
  const actionText = isExcluded ? '통계에서 제외' : '통계에 다시 포함';
  if (!confirm(`선택한 ${ids.length}장의 사진을 ${actionText}하시겠습니까?`)) {
    return;
  }
  try {
    const res = await fetch('/api/batch-exclude', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids, is_excluded: isExcluded })
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      alert(data.error || '일괄 처리에 실패했습니다.');
      return;
    }
    ids.forEach(id => {
      const item = allData.find(d => Number(d.id) === Number(id));
      if (item) item.is_excluded = isExcluded;
    });
    renderGallery(false);
    renderScoreDistPanel();
    if (typeof renderTagInsights === 'function' && window.currentView === 'insights') {
      renderTagInsights();
    }
    if (typeof renderGrowthTimeline === 'function' && window.currentView === 'timeline') {
      renderGrowthTimeline();
    }
    alert(`총 ${data.count}장의 사진이 ${actionText}되었습니다.`);
  } catch (err) {
    console.error(err);
    alert('일괄 처리 중 오류가 발생했습니다.');
  }
}

window.updateBatchSelectBarUI = updateBatchSelectBarUI;
window.toggleHideExcluded = toggleHideExcluded;
window.updateHideExcludedButtonUI = updateHideExcludedButtonUI;
window.toggleExcludeRecord = toggleExcludeRecord;
window.applyBatchExclude = applyBatchExclude;
window.isHideExcluded = isHideExcluded;
