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

// --- Progressive Gallery Chunk Rendering ---
const GALLERY_PAGE_SIZE = 40;
let currentGalleryRenderCount = GALLERY_PAGE_SIZE;
let galleryObserver = null;

function setCatFilter(cat, btn) {
  currentCatFilter = cat;
  document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
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
  document.querySelectorAll('.filter-btn:not(.burst-btn):not(.cat-btn)').forEach(b => b.classList.remove('active'));
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
