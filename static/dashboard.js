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
let allData = [];
let currentFilter = 'all';
let currentCatFilter = 'all';
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
  btn.classList.add('active');
  renderGallery();
}

async function loadData() {
  allData = await API.fetchAnalyses(currentBurstDist);
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
  currentBurstDist = parseInt(val) || 15;
  await loadData();
}

function updateStats() {
  const totalEl = document.getElementById('total-count');
  const avgEl = document.getElementById('avg-score');
  const goodEl = document.getElementById('good-count');
  if (totalEl) totalEl.textContent = allData.length;
  if (!allData.length) return;
  const avg = (allData.reduce((acc, cur) => acc + cur.final_score, 0) / allData.length).toFixed(1);
  const good = allData.filter(d => d.final_score >= 7.0).length;
  if (avgEl) avgEl.textContent = avg;
  if (goodEl) goodEl.textContent = good;
}

function setBurstFilter(mode, btn) {
  currentBurstFilter = mode;
  document.querySelectorAll('.burst-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
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
  btn.classList.add('active');
  renderGallery();
}

function filterList(list) {
  let res = list;
  if (currentFilter === 'pro') res = res.filter(d => d.final_score >= 9.0);
  else if (currentFilter === 'very_good') res = res.filter(d => d.final_score >= 8.0 && d.final_score < 9.0);
  else if (currentFilter === 'good') res = res.filter(d => d.final_score >= 7.0 && d.final_score < 8.0);
  else if (currentFilter === 'normal') res = res.filter(d => d.final_score >= 5.0 && d.final_score < 7.0);

  if (currentCatFilter !== 'all') {
    res = res.filter(d => d.figure_category === currentCatFilter);
  }

  if (currentBurstFilter === 'best_only') {
    res = res.filter(d => !d.is_burst || d.is_best_pick);
  } else if (currentBurstFilter === 'stack') {
    res = res.filter(d => !d.is_burst || d.is_best_pick || expandedBurstGroups.has(d.burst_group_id));
  }

  if (typeof selectedTags !== 'undefined' && selectedTags.size > 0 && typeof getAllTagsFromItem === 'function') {
    res = res.filter(d => {
      const itemTags = getAllTagsFromItem(d);
      if (typeof tagLogic !== 'undefined' && tagLogic === 'AND') {
        for (const t of selectedTags) {
          if (!itemTags.has(t)) return false;
        }
        return true;
      } else {
        for (const t of selectedTags) {
          if (itemTags.has(t)) return true;
        }
        return false;
      }
    });
  }

  return res;
}

function sortList(list) {
  const sortSelect = document.getElementById('sort-select');
  const sort = sortSelect ? sortSelect.value : 'score_desc';
  return [...list].sort((a, b) => {
    if (sort === 'score_desc') return b.final_score - a.final_score;
    if (sort === 'score_asc') return a.final_score - b.final_score;
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
    if (sort === 'gap_desc') {
      const ga = (a.user_score !== null && a.user_score !== undefined) ? Math.abs(a.user_score - a.final_score) : -1;
      const gb = (b.user_score !== null && b.user_score !== undefined) ? Math.abs(b.user_score - b.final_score) : -1;
      return gb - ga;
    }
    if (sort === 'newest') return b.id - a.id;
    if (sort === 'name') return a.filename.localeCompare(b.filename);
    return 0;
  });
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

// --- Detail Modal & Inspector ---
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

function openDetailModal(id) {
  if (typeof clearCropOverlay === 'function') clearCropOverlay();
  const item = allData.find(d => d.id === id);
  if (!item) return;
  currentDetailId = id;
  const modal = document.getElementById('detail-modal');
  const body = document.getElementById('modal-body');

  body.innerHTML = `
    ${item.is_burst ? `
      <div class="burst-banner ${item.is_best_pick ? '' : 'is-b-cut'}" style="grid-column: 1 / -1;">
        <div style="display:flex;align-items:center;gap:10px;">
          <span style="font-size:1.4rem;">${item.is_best_pick ? '👑' : '🗂️'}</span>
          <div>
            <div style="font-size:0.92rem;font-weight:800;color:${item.is_best_pick ? '#065f46' : '#991b1b'};">
              ${item.is_best_pick ? `👑 연사 묶음 베스트 컷 (총 ${item.burst_total}장 중 1위 선정)` : `⚠️ 연사 묶음 B컷 (${item.burst_rank}/${item.burst_total}위 · 탈락 사유: ${escapeHtml(item.drop_reason)})`}
            </div>
            <div style="font-size:0.77rem;color:var(--muted);">동일 구도 및 포즈로 연속 촬영된 연사 세트 중 AI 디테일(초점·조명·완성도) 비교 결과입니다.</div>
          </div>
        </div>
        <div style="display:flex;gap:6px;align-items:center;">
          <span style="font-size:0.78rem;font-weight:700;color:var(--muted);">묶음 컷:</span>
          ${renderBurstThumbnails(item.burst_group_id, item.id)}
        </div>
      </div>
    ` : ''}

    <div>
      <div class="zoom-wrap" id="zoom-wrap-container" onclick="toggleZoom(event)" onmousemove="panZoom(event)">
        <img class="detail-img" id="detail-modal-img" src="/api/image/${item.id}?original=1" alt="${escapeHtml(item.filename)}" onload="if(typeof repositionCropOverlay==='function') repositionCropOverlay()">
        <div class="crop-box-overlay" id="crop-box-overlay">
          <span class="crop-overlay-badge" id="crop-overlay-badge"></span>
        </div>
        <span class="zoom-hint">🔍 클릭하여 초점/데칼 2.4배 확대</span>
      </div>
      <div class="kbd-hint">
        <span>단축키:</span>
        <span><span class="kbd-key">←</span>/<span class="kbd-key">J</span> 이전</span>
        <span><span class="kbd-key">→</span>/<span class="kbd-key">K</span> 다음</span>
        <span><span class="kbd-key">Space</span> 줌 토글</span>
        <span><span class="kbd-key">Esc</span> 닫기</span>
      </div>
      <div style="margin-top:12px;font-size:0.84rem;color:var(--muted)">
        <div><b>해상도:</b> ${item.width} × ${item.height}px (${escapeHtml(item.format)})</div>
        <div><b>분석 모델:</b> ${escapeHtml(item.model)} · <b>분석시각:</b> ${escapeHtml(item.created_at)}</div>
        ${renderExifSummary(item.exif, item.detected_camera_settings)}
      </div>

      <div style="display:flex;gap:8px;margin-top:14px;margin-bottom:12px;flex-wrap:wrap;justify-content:space-between;align-items:center;">
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="filter-btn reanalyze-btn" onclick="toggleReanalyzePanel(${item.id})">>🔄 재평가</button>
          <button class="filter-btn" style="background:#312e81;color:white;border-color:#312e81;padding:5px 12px;font-size:0.8rem;" onclick="document.getElementById('lr-advice-box-section').scrollIntoView({behavior:'smooth'})">🛠️ 라이트룸 보정값 바로가기</button>
          <button class="filter-btn" style="background:#0284c7;color:white;border-color:#0284c7;padding:5px 12px;font-size:0.8rem;" onclick="document.getElementById('sns-advice-box-section').scrollIntoView({behavior:'smooth'})">📱 SNS 크롭 & 캡션 바로가기</button>
        </div>
        <button class="filter-btn" style="background:#fee2e2;color:#b91c1c;border-color:#fca5a5;padding:5px 12px;font-size:0.8rem;font-weight:700;" onclick="deleteAnalysisRecord(${item.id})">🗑️ 이 평가 기록 삭제</button>
      </div>

      <!-- 재평가 패널 (기본 숨김, 🔄 재평가 버튼 클릭 시 토글) -->
      <div id="reanalyze-panel-${item.id}" class="reanalyze-panel" style="display:none;">
        ${renderReanalyzePanel(item)}
      </div>

      <!-- Adobe Lightroom Advice Box (사진 바로 아래 배치) -->
      <div class="lr-advice-box" id="lr-advice-box-section">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
          <h3 class="lr-advice-title" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
            <span class="lr-advice-badge">Lr</span>
            <span>Adobe Lightroom 추천 보정 수치</span>
            <span id="lr-used-model-badge-${item.id}">${item.lr_advice && item.lr_advice.used_model ? `<span style="font-size:0.73rem;background:rgba(99,102,241,0.14);color:#4f46e5;padding:2px 8px;border-radius:999px;font-weight:700;">${escapeHtml(window.ModelSettings ? window.ModelSettings.formatBadge(item.lr_advice.used_model) : item.lr_advice.used_model)}</span>` : ''}</span>
          </h3>
          <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
            <select id="lr-model-select-${item.id}" class="select-input" style="padding:4px 8px;font-size:0.76rem;height:auto;" onchange="if(window.ModelSettings) window.ModelSettings.set('lightroom_advice', this.value)" title="라이트룸 보정 수치 분석 모델 선택">
              ${window.ModelSettings ? window.ModelSettings.renderOptionsHtml(window.ModelSettings.get('lightroom_advice')) : '<option value="lite">⚡ Flash-Lite 3.1</option>'}
            </select>
            <button class="filter-btn" style="background:#4f46e5;color:white;border-color:#4f46e5;" onclick="requestLrAdvice(${item.id}, this)">
              ${item.lr_advice ? '🔄 보정 수치 다시 제안' : '🛠️ 라이트룸 보정 수치 제안 받기'}
            </button>
          </div>
        </div>
        <div id="lr-advice-content">
          ${renderLrAdviceContent(item.lr_advice)}
        </div>
      </div>

      <!-- SNS Crop & Caption Advice Box (사진 바로 아래 배치) -->
      <div class="sns-advice-box" id="sns-advice-box-section">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
          <h3 class="sns-advice-title">
            <span style="background:#0284c7;color:white;padding:2px 7px;border-radius:4px;font-size:0.78rem;">SNS</span>
            <span>인스타 · X(트위터) 규격별 크롭 & 캡션 제안</span>
          </h3>
          <span style="font-size:0.75rem;color:#0284c7;background:rgba(56,189,248,0.15);padding:3px 9px;border-radius:6px;font-weight:700;">
            ⚡ 비율 선택형 토큰 절약 모드
          </span>
        </div>
        <div id="sns-advice-content">
          ${typeof renderSnsAdviceContent === 'function' ? renderSnsAdviceContent(item.sns_advice, item.id) : ''}
        </div>
      </div>
    </div>

    <div>
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;">
        <div>
          <h2 style="margin:0;">${escapeHtml(item.filename)}</h2>
          <span class="score-grade" style="font-size:0.86rem;padding:4px 12px;">${escapeHtml(item.grade)}</span>
        </div>
        <div style="text-align:right;">
          <div style="font-size:2.8rem;font-weight:900;color:var(--blue);line-height:1;">${item.final_score.toFixed(1)}</div>
          <small style="color:var(--muted)">10점 만점</small>
        </div>
      </div>

      <div class="final-reason-box">
        <b>종합 총평:</b> ${escapeHtml(item.final_reason)}
      </div>

      <!-- 사용자 직접 평점 매기기 & AI 비교 영역 -->
      <div class="user-score-section">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
          <div style="display:flex;align-items:center;gap:6px;">
            <span style="font-size:1.15rem;">👤</span>
            <div>
              <b class="user-score-title">내 직접 평가 평점 (User Rating)</b>
              <div style="font-size:0.73rem;color:var(--muted);">점수를 직접 매겨 AI와 시각을 비교해보세요.</div>
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
            <div class="user-score-input-wrap">
              <input type="number" id="detail-user-score-input" class="user-score-input" min="0" max="10" step="0.1" 
                     value="${item.user_score !== null && item.user_score !== undefined ? item.user_score.toFixed(1) : ''}" 
                     placeholder="0.0~10">
              <span style="font-size:0.75rem;color:var(--muted);font-weight:600;">/ 10</span>
            </div>
            <button class="filter-btn" style="background:#0284c7;color:white;border-color:#0284c7;padding:4px 10px;font-weight:700;font-size:0.78rem;" onclick="submitUserScore(${item.id})">저장</button>
            ${item.user_score !== null && item.user_score !== undefined ? `
              <button class="filter-btn" style="background:var(--filter-btn-bg);color:var(--muted);border-color:var(--line);padding:4px 8px;font-size:0.76rem;" onclick="clearUserScore(${item.id})">초기화</button>
            ` : ''}
          </div>
        </div>

        <div style="display:flex;gap:4px;align-items:center;margin-top:8px;flex-wrap:wrap;">
          <span style="font-size:0.73rem;color:var(--muted);font-weight:600;">빠른 점수:</span>
          ${[6.0, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0].map(s => `
            <button class="quick-score-btn" onclick="setQuickUserScore(${item.id}, ${s})">${s.toFixed(1)}</button>
          `).join('')}
        </div>

        ${item.user_score !== null && item.user_score !== undefined ? renderScoreComparisonBox(item.final_score, item.user_score) : ''}
      </div>

      <!-- 세부 평가 요소 점수 요약 그래프 (우측 상단) -->
      <div class="score-summary-card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <h3 style="margin:0;font-size:0.94rem;font-weight:800;color:var(--navy);display:flex;align-items:center;gap:6px;">
            📊 세부 평가 요소 점수 요약
          </h3>
          <span style="font-size:0.74rem;color:var(--muted);font-weight:600;">10점 만점 기준</span>
        </div>
        <div class="score-bars-list">
          <div class="score-bar-row">
            <div class="score-bar-label">
              <span>📐 구도 (Composition)</span>
              <strong style="color:#2563eb;">${item.composition_score.toFixed(1)} <small style="color:var(--muted);font-weight:500;">/ 10</small></strong>
            </div>
            <div class="score-bar-track">
              <div class="score-bar-fill score-bar-comp" style="width:${Math.min(100, Math.max(0, item.composition_score * 10))}%;"></div>
            </div>
          </div>
          <div class="score-bar-row">
            <div class="score-bar-label">
              <span>💡 조명/노출 (Lighting)</span>
              <strong style="color:#d97706;">${item.lighting_score.toFixed(1)} <small style="color:var(--muted);font-weight:500;">/ 10</small></strong>
            </div>
            <div class="score-bar-track">
              <div class="score-bar-fill score-bar-light" style="width:${Math.min(100, Math.max(0, item.lighting_score * 10))}%;"></div>
            </div>
          </div>
          <div class="score-bar-row">
            <div class="score-bar-label">
              <span>🎨 색감/톤 (Color)</span>
              <strong style="color:#db2777;">${item.color_score.toFixed(1)} <small style="color:var(--muted);font-weight:500;">/ 10</small></strong>
            </div>
            <div class="score-bar-track">
              <div class="score-bar-fill score-bar-color" style="width:${Math.min(100, Math.max(0, item.color_score * 10))}%;"></div>
            </div>
          </div>
          <div class="score-bar-row">
            <div class="score-bar-label">
              <span>📷 촬영 기술 (Technique)</span>
              <strong style="color:#059669;">${item.technique_score.toFixed(1)} <small style="color:var(--muted);font-weight:500;">/ 10</small></strong>
            </div>
            <div class="score-bar-track">
              <div class="score-bar-fill score-bar-tech" style="width:${Math.min(100, Math.max(0, item.technique_score * 10))}%;"></div>
            </div>
          </div>
        </div>
      </div>

      <!-- 세부 평가 요소별 코멘트 (2x2 그리드 컴팩트 배치) -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:6px;">
        <div class="note-item-compact" style="border-left: 3px solid #3b82f6;">
          <div class="note-header">
            <span>📐 구도 평가</span>
            <strong style="color:#2563eb;">${item.composition_score.toFixed(1)}</strong>
          </div>
          <div class="note-body">${escapeHtml(item.composition_notes)}</div>
        </div>
        <div class="note-item-compact" style="border-left: 3px solid #f59e0b;">
          <div class="note-header">
            <span>💡 조명/노출 평가</span>
            <strong style="color:#d97706;">${item.lighting_score.toFixed(1)}</strong>
          </div>
          <div class="note-body">${escapeHtml(item.lighting_notes)}</div>
        </div>
        <div class="note-item-compact" style="border-left: 3px solid #ec4899;">
          <div class="note-header">
            <span>🎨 색감/톤 평가</span>
            <strong style="color:#db2777;">${item.color_score.toFixed(1)}</strong>
          </div>
          <div class="note-body">${escapeHtml(item.color_notes)}</div>
        </div>
        <div class="note-item-compact" style="border-left: 3px solid #10b981;">
          <div class="note-header">
            <span>📷 촬영 기술 평가</span>
            <strong style="color:#059669;">${item.technique_score.toFixed(1)}</strong>
          </div>
          <div class="note-body">${escapeHtml(item.technique_notes)}</div>
        </div>
      </div>

      <!-- 초점 핀 상태 인라인 슬림 바 -->
      <div class="note-item-compact" style="border-left: 3px solid #6366f1;margin-bottom:6px;">
        <div class="note-header">
          <span>🎯 피규어 눈동자/페이스 초점 핀</span>
          <strong style="color:#4f46e5;">${escapeHtml(item.focus_status || '완벽 칼초점')}</strong>
        </div>
        <div class="note-body">${escapeHtml(item.focus_notes ? item.focus_notes : '눈동자 아이 데칼 및 안면 조형 핀 상태 양호')}</div>
      </div>

      <!-- 주요 장점 및 단점/개선점 (좌우 2열 배치로 세로 공간 50% 절약) -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:6px;">
        <div class="strengths-box">
          <h4>✓ 주요 장점</h4>
          <ul>${item.strengths.map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ul>
        </div>
        <div class="improvements-box">
          <h4>✗ 단점 및 촬영 개선점</h4>
          <ul>${item.improvements.map(i => `<li>${escapeHtml(i)}</li>`).join('')}</ul>
        </div>
      </div>

      <!-- OpenAI 크로스 체크 독립 비평 의견 (앙상블 시) -->
      ${renderCrossCheckOpinion(item.cross_check_opinion)}

      <div style="margin-top:8px;">
        <span style="font-size:0.78rem;font-weight:700;color:var(--muted);display:block;margin-bottom:4px;">🏷️ 분위기 & 스타일 태그</span>
        <div class="tag-pills">
          ${typeof renderTagPills === 'function' ? renderTagPills(item.aesthetic_tags, 50) : ''}
        </div>
      </div>
    </div>
  `;
  modal.style.display = 'flex';
  currentCropBox = null;
  const defaultRatio = (item.sns_advice && item.sns_advice.best_ratio_key)
    ? item.sns_advice.best_ratio_key
    : 'instagram_crop_4_5';
  currentCropRatioKey = defaultRatio;
  const overlay = document.getElementById('crop-box-overlay');
  if (overlay) overlay.style.display = 'none';
  if (item.sns_advice && (item.sns_advice[defaultRatio] || defaultRatio === 'original')) {
    setTimeout(() => {
      if (typeof selectCropRatio === 'function') selectCropRatio(defaultRatio, item.id);
    }, 150);
  }
}

function renderCrossCheckOpinion(op) {
  if (!op) return '';
  return `
    <div class="cross-check-opinion-card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;flex-wrap:wrap;gap:8px;">
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="font-size:1.2rem;">🤝</span>
          <div>
            <strong class="cross-check-title">OpenAI 크로스 체크 의견 (${escapeHtml(op.model || 'GPT-6 Luna')})</strong>
            <div style="font-size:0.73rem;color:var(--muted);">Gemini 본 평가와 별도로 제공되는 독립적인 보조 비평입니다. (점수 합산/평균 없음)</div>
          </div>
        </div>
        <div style="text-align:right;">
          <span class="cross-check-score">${op.score !== undefined && op.score !== null ? Number(op.score).toFixed(1) : '-'}</span>
          <small style="color:var(--muted);font-size:0.75rem;"> / 10점</small>
        </div>
      </div>
      ${op.reason ? `<div class="cross-check-reason-box"><b>OpenAI 총평:</b> ${escapeHtml(op.reason)}</div>` : ''}
      ${(op.composition_critique || op.lighting_critique) ? `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px;">
          ${op.composition_critique ? `
            <div class="cross-check-comp-box">
              <b style="display:block;margin-bottom:2px;">📐 구도 비평:</b>
              <span>${escapeHtml(op.composition_critique)}</span>
            </div>
          ` : ''}
          ${op.lighting_critique ? `
            <div class="cross-check-light-box">
              <b style="display:block;margin-bottom:2px;">💡 조명 비평:</b>
              <span>${escapeHtml(op.lighting_critique)}</span>
            </div>
          ` : ''}
        </div>
      ` : ''}
      ${((op.strengths && op.strengths.length) || (op.improvements && op.improvements.length)) ? `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:0.78rem;">
          ${op.strengths && op.strengths.length ? `
            <div class="cross-check-strengths-box">
              <b style="display:block;margin-bottom:2px;">✓ OpenAI 시각 강점:</b>
              <ul style="margin:4px 0 0;padding-left:16px;">${op.strengths.map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ul>
            </div>
          ` : ''}
          ${op.improvements && op.improvements.length ? `
            <div class="cross-check-improvements-box">
              <b style="display:block;margin-bottom:2px;">✗ OpenAI 조언/개선점:</b>
              <ul style="margin:4px 0 0;padding-left:16px;">${op.improvements.map(i => `<li>${escapeHtml(i)}</li>`).join('')}</ul>
            </div>
          ` : ''}
        </div>
      ` : ''}
    </div>
  `;
}

function getCategoryKeyFromTitle(categoryTitle) {
  if (!categoryTitle) return 'auto';
  if (categoryTitle.includes('접사') || categoryTitle.includes('디테일') || categoryTitle.includes('macro')) return 'macro';
  if (categoryTitle.includes('스냅') || categoryTitle.includes('야외') || categoryTitle.includes('일상') || categoryTitle.includes('snap')) return 'snap';
  if (categoryTitle.includes('연출') || categoryTitle.includes('디오라마') || categoryTitle.includes('스튜디오') || categoryTitle.includes('staging')) return 'staging';
  if (categoryTitle.includes('일반') || categoryTitle.includes('general')) return 'general';
  return 'auto';
}

function toggleReanalyzePanel(id) {
  const panel = document.getElementById(`reanalyze-panel-${id}`);
  if (!panel) return;
  if (panel.style.display === 'none' || !panel.style.display) {
    panel.style.display = 'block';
  } else {
    panel.style.display = 'none';
  }
}

function selectReanalyzeMode(id, mode) {
  const panel = document.getElementById(`reanalyze-panel-${id}`);
  if (!panel) return;
  const cards = panel.querySelectorAll('.reanalyze-mode-card');
  const radios = panel.querySelectorAll(`input[name="reanalyze-mode-${id}"]`);
  radios.forEach(r => {
    r.checked = (r.value === mode);
  });
  cards.forEach(c => {
    const r = c.querySelector('input[type="radio"]');
    if (r && r.value === mode) {
      c.classList.add('selected');
    } else {
      c.classList.remove('selected');
    }
  });
  const tierWrap = document.getElementById(`reanalyze-tier-wrap-${id}`);
  if (tierWrap) {
    tierWrap.style.display = (mode === 'full') ? 'block' : 'none';
  }
}

function renderReanalyzePanel(item) {
  const currentCategoryKey = getCategoryKeyFromTitle(item.figure_category);
  const hasLuna = Boolean(item.cross_check_opinion);
  
  return `
    <div class="reanalyze-panel-inner">
      <div class="reanalyze-header">
        <div class="reanalyze-title">
          <span>🔄</span>
          <strong>사진 AI 재평가 및 추가 분석</strong>
        </div>
        <button class="reanalyze-close-btn" title="닫기" onclick="toggleReanalyzePanel(${item.id})">&times;</button>
      </div>
      <p class="reanalyze-desc">
        원하는 분석 방식을 선택하세요. 사진을 다시 업로드할 필요 없이 기존 원본/고화질 이미지를 즉시 활용합니다.
      </p>

      <div class="reanalyze-modes">
        <label class="reanalyze-mode-card ${!hasLuna ? 'selected' : ''}" onclick="selectReanalyzeMode(${item.id}, 'cross_check_only')">
          <input type="radio" name="reanalyze-mode-${item.id}" value="cross_check_only" ${!hasLuna ? 'checked' : ''} onchange="selectReanalyzeMode(${item.id}, 'cross_check_only')">
          <div class="reanalyze-mode-content">
            <div class="reanalyze-mode-badge-wrap">
              <span class="reanalyze-mode-badge mode-luna">🤝 GPT-6 Luna 단독 추가</span>
              <span class="reanalyze-token-tag">⚡ ~2.6K 토큰 소모 (경제적)</span>
            </div>
            <strong class="reanalyze-mode-title">${hasLuna ? 'Luna 크로스체크 의견 갱신' : 'OpenAI 크로스체크 비평만 추가'}</strong>
            <p class="reanalyze-mode-text">
              Gemini의 기존 종합 점수·세부 평가는 100% 보존하며, GPT-6 Luna의 독립적인 시각(점수, 구도/조명 비평, 강점/약점)만 빠르게 덧붙입니다.
            </p>
          </div>
        </label>

        <label class="reanalyze-mode-card ${hasLuna ? 'selected' : ''}" onclick="selectReanalyzeMode(${item.id}, 'full')">
          <input type="radio" name="reanalyze-mode-${item.id}" value="full" ${hasLuna ? 'checked' : ''} onchange="selectReanalyzeMode(${item.id}, 'full')">
          <div class="reanalyze-mode-content">
            <div class="reanalyze-mode-badge-wrap">
              <span class="reanalyze-mode-badge mode-full">⚙️ 모델 변경 전체 재평가</span>
            </div>
            <strong class="reanalyze-mode-title">새로운 AI 모델로 전면 재평가</strong>
            <p class="reanalyze-mode-text">
              종합 점수, 세부 평가 코멘트, 초점 핀 분석, 스타일 태그 분류를 선택한 모델로 완전히 새로 생성하여 갱신합니다.
            </p>

            <div id="reanalyze-tier-wrap-${item.id}" class="reanalyze-tier-select-wrap" style="${hasLuna ? '' : 'display:none;'}">
              <label class="reanalyze-sublabel">분석 모델 선택:</label>
              <select id="reanalyze-tier-${item.id}" class="select-input reanalyze-select">
                <option value="standard" ${(window.ModelSettings && window.ModelSettings.get('photo_grading') === 'standard') ? 'selected' : ''}>🔍 Flash-Lite 3.5 (균형 잡힌 표준 화질 평가 - 권장)</option>
                <option value="lite" ${(window.ModelSettings && window.ModelSettings.get('photo_grading') === 'lite') ? 'selected' : ''}>⚡ Flash-Lite 3.1 (초고속 스크리닝)</option>
                <option value="flash-3.6" ${(window.ModelSettings && window.ModelSettings.get('photo_grading') === 'flash-3.6') ? 'selected' : ''}>🧪 Gemini Flash 3.6 (실험적 고성능)</option>
                <option value="flash-3.7" ${(window.ModelSettings && window.ModelSettings.get('photo_grading') === 'flash-3.7') ? 'selected' : ''}>🚀 Gemini Flash 3.7 (차세대 고속 비평)</option>
                <option value="pro" ${(window.ModelSettings && window.ModelSettings.get('photo_grading') === 'pro') ? 'selected' : ''}>💎 Flash 3.8 (고화질 디테일 심층 비평)</option>
                <option value="ensemble" ${(window.ModelSettings && window.ModelSettings.get('photo_grading') === 'ensemble') ? 'selected' : ''}>🤝 Gemini 3.5 + GPT-6 Luna 크로스체크 앙상블</option>
              </select>
            </div>
          </div>
        </label>
      </div>

      <div class="reanalyze-category-row">
        <label class="reanalyze-sublabel">피규어 촬영 세부 유형:</label>
        <select id="reanalyze-category-${item.id}" class="select-input reanalyze-select">
          <option value="auto" ${currentCategoryKey === 'auto' ? 'selected' : ''}>자동 판별 (사진 분석으로 자동 분류)</option>
          <option value="general" ${currentCategoryKey === 'general' ? 'selected' : ''}>📷 일반 피규어 촬영 (기본 전시/조형 중심)</option>
          <option value="macro" ${currentCategoryKey === 'macro' ? 'selected' : ''}>🔍 접사/디테일 (도색, 접합선, 데칼 초점 심사)</option>
          <option value="snap" ${currentCategoryKey === 'snap' ? 'selected' : ''}>🌿 일상/야외 스냅 (배경 조화, 자연광, 생활감 심사)</option>
          <option value="staging" ${currentCategoryKey === 'staging' ? 'selected' : ''}>🎬 스튜디오 연출/디오라마 (드라마틱 조명, 콘트라스트)</option>
        </select>
      </div>

      <div class="reanalyze-actions">
        <button id="reanalyze-submit-btn-${item.id}" class="reanalyze-submit-btn" onclick="executeReanalyze(${item.id})">
          🚀 선택한 조건으로 재평가 시작
        </button>
        <button class="reanalyze-cancel-btn" onclick="toggleReanalyzePanel(${item.id})">
          취소
        </button>
      </div>
      <div id="reanalyze-status-${item.id}" class="reanalyze-status" style="display:none;"></div>
    </div>
  `;
}

async function executeReanalyze(id) {
  const panel = document.getElementById(`reanalyze-panel-${id}`);
  if (!panel) return;

  const modeRadio = panel.querySelector(`input[name="reanalyze-mode-${id}"]:checked`);
  const mode = modeRadio ? modeRadio.value : 'cross_check_only';

  const tierSelect = document.getElementById(`reanalyze-tier-${id}`);
  const tier = tierSelect ? tierSelect.value : 'standard';

  const catSelect = document.getElementById(`reanalyze-category-${id}`);
  const category = catSelect ? catSelect.value : 'auto';

  const submitBtn = document.getElementById(`reanalyze-submit-btn-${id}`);
  const statusEl = document.getElementById(`reanalyze-status-${id}`);

  if (submitBtn) submitBtn.disabled = true;
  if (statusEl) {
    statusEl.style.display = 'block';
    const modeName = mode === 'cross_check_only' ? 'OpenAI GPT-6 Luna 크로스체크' : 'AI 전체 재평가';
    statusEl.innerHTML = `⏳ <b>${modeName}</b> 실행 중... (약 5~15초 소요)`;
  }

  try {
    const res = await API.reanalyzePhoto(id, mode, tier, category);
    if (!res || !res.success) {
      throw new Error((res && res.error) || '알 수 없는 오류');
    }

    // Refresh entire analysis dataset to update rankings, clusters and stats
    await loadData();

    // Re-open detail modal to show freshly evaluated state
    openDetailModal(id);
  } catch (err) {
    if (statusEl) {
      statusEl.style.display = 'block';
      statusEl.innerHTML = `<span style="color:#ef4444;">❌ 재평가 실패: ${escapeHtml(err.message)}</span>`;
    }
    if (submitBtn) submitBtn.disabled = false;
  }
}

function renderScoreComparisonBox(aiScore, userScore) {
  const diff = Math.round((userScore - aiScore) * 10) / 10;
  let badgeClass, badgeText, comment;
  if (Math.abs(diff) <= 0.2) {
    badgeClass = 'diff-badge-match';
    badgeText = '±0.0 (AI와 일치)';
    comment = '🤖 AI와 👤 내 시각이 거의 완벽하게 일치합니다!';
  } else if (diff > 0) {
    badgeClass = 'diff-badge-higher';
    badgeText = `+${diff.toFixed(1)} (AI보다 호평)`;
    comment = `👤 내가 AI(${aiScore.toFixed(1)}점)보다 +${diff.toFixed(1)}점 더 높게 평가했습니다. (개인 취향 부합)`;
  } else {
    badgeClass = 'diff-badge-stricter';
    badgeText = `${diff.toFixed(1)} (AI보다 엄격)`;
    comment = `👤 내가 AI(${aiScore.toFixed(1)}점)보다 ${Math.abs(diff).toFixed(1)}점 더 엄격하게 평가했습니다.`;
  }
  return `
    <div class="score-comparison-box">
      <div style="display:flex;align-items:center;gap:6px;">
        <span style="font-size:0.8rem;font-weight:700;color:var(--navy);">🤖 AI ${aiScore.toFixed(1)} vs 👤 내 점수 ${userScore.toFixed(1)}</span>
        <span class="${badgeClass}" style="font-size:0.72rem;font-weight:800;padding:1px 7px;border-radius:999px;">${badgeText}</span>
      </div>
      <span style="font-size:0.75rem;color:var(--muted);">${comment}</span>
    </div>
  `;
}

async function submitUserScore(id) {
  const input = document.getElementById('detail-user-score-input');
  if (!input) return;
  const raw = input.value.trim();
  let scoreVal = null;
  if (raw !== '') {
    scoreVal = parseFloat(raw);
    if (isNaN(scoreVal) || scoreVal < 0 || scoreVal > 10) {
      alert('점수는 0.0점에서 10.0점 사이로 입력해주세요.');
      return;
    }
    scoreVal = Math.round(scoreVal * 10) / 10;
  }

  try {
    const data = await API.ratePhoto(id, scoreVal);
    if (data.success) {
      const item = allData.find(d => d.id === id);
      if (item) {
        item.user_score = data.user_score;
      }
      openDetailModal(id);
      renderGallery();
      if (typeof populateTagSelectorAndQuickTags === 'function') populateTagSelectorAndQuickTags();
      if (typeof currentView !== 'undefined' && currentView === 'insights' && typeof renderTagInsights === 'function') {
        renderTagInsights();
      }
    } else {
      alert('평점 저장 실패: ' + (data.error || '알 수 없는 오류'));
    }
  } catch (err) {
    alert('평점 저장 중 네트워크 오류: ' + err.message);
  }
}

function setQuickUserScore(id, score) {
  const input = document.getElementById('detail-user-score-input');
  if (input) input.value = score.toFixed(1);
  submitUserScore(id);
}

function clearUserScore(id) {
  if (!confirm('직접 매긴 평가 점수를 초기화하시겠습니까?')) return;
  const input = document.getElementById('detail-user-score-input');
  if (input) input.value = '';
  submitUserScore(id);
}

function renderLrAdviceContent(advice) {
  if (!advice) {
    return `<div style="font-size:0.86rem;color:var(--muted);text-align:center;padding:14px 0;">
      아직 생성된 보정 수치가 없습니다. 위의 <b>[🛠️ 라이트룸 보정 수치 제안 받기]</b> 버튼을 누르면 AI가 노출·명암·화이트밸런스 수치를 온디맨드로 분석합니다.
    </div>`;
  }
  const exp = typeof advice.exposure === 'number' ? advice.exposure : parseFloat(advice.exposure || 0);
  const expStr = (exp > 0 ? '+' : '') + exp.toFixed(2) + ' EV';
  return `
    <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(130px, 1fr));gap:8px;margin-bottom:12px;">
      <div class="lr-metric"><span>노출 (Exposure)</span><strong>${expStr}</strong></div>
      <div class="lr-metric"><span>대비 (Contrast)</span><strong>${advice.contrast > 0 ? '+' : ''}${advice.contrast}</strong></div>
      <div class="lr-metric"><span>하이라이트</span><strong>${advice.highlights > 0 ? '+' : ''}${advice.highlights}</strong></div>
      <div class="lr-metric"><span>그림자 (Shadows)</span><strong>${advice.shadows > 0 ? '+' : ''}${advice.shadows}</strong></div>
      <div class="lr-metric"><span>흰색 계열 (Whites)</span><strong>${advice.whites > 0 ? '+' : ''}${advice.whites}</strong></div>
      <div class="lr-metric"><span>검정 계열 (Blacks)</span><strong>${advice.blacks > 0 ? '+' : ''}${advice.blacks}</strong></div>
      <div class="lr-metric"><span>텍스처 (Texture)</span><strong>${advice.texture > 0 ? '+' : ''}${advice.texture}</strong></div>
      <div class="lr-metric"><span>명료도 (Clarity)</span><strong>${advice.clarity > 0 ? '+' : ''}${advice.clarity}</strong></div>
      <div class="lr-metric"><span>디헤이즈 (Dehaze)</span><strong>${advice.dehaze > 0 ? '+' : ''}${advice.dehaze}</strong></div>
      <div class="lr-metric"><span>활기 (Vibrance)</span><strong>${advice.vibrance > 0 ? '+' : ''}${advice.vibrance}</strong></div>
      <div class="lr-metric"><span>채도 (Saturation)</span><strong>${advice.saturation > 0 ? '+' : ''}${advice.saturation}</strong></div>
    </div>
    <div class="lr-tip-box" style="margin-bottom:8px;">
      <b style="color:var(--blue)">🌡️ 화이트밸런스/색조:</b> ${escapeHtml(advice.temp_tint_notes)}
    </div>
    <div class="lr-tip-box">
      <b style="color:var(--accent)">🎨 마스킹 및 세부 후보정 팁:</b> ${escapeHtml(advice.retouching_guide)}
    </div>
  `;
}

async function requestLrAdvice(recordId, btn) {
  const origText = btn.textContent;
  const item = allData.find(d => d.id === recordId);
  const shouldForce = Boolean(item && item.lr_advice);
  const modelSel = document.getElementById(`lr-model-select-${recordId}`);
  const chosenModel = modelSel ? modelSel.value : (window.ModelSettings ? window.ModelSettings.get('lightroom_advice') : 'lite');
  if (window.ModelSettings) {
    window.ModelSettings.set('lightroom_advice', chosenModel);
  }
  const badgeText = window.ModelSettings ? window.ModelSettings.formatBadge(chosenModel) : chosenModel;

  btn.textContent = `${badgeText} 분석 중...`;
  btn.disabled = true;
  try {
    const data = await API.fetchLightroomAdvice(recordId, shouldForce, chosenModel);
    if (data.success && data.advice) {
      if (data.used_model) {
        data.advice.used_model = data.used_model;
      }
      if (item) {
        item.lr_advice = data.advice;
      }
      const container = document.getElementById('lr-advice-content');
      if (container) {
        container.innerHTML = renderLrAdviceContent(data.advice);
      }
      const badgeEl = document.getElementById(`lr-used-model-badge-${recordId}`);
      if (badgeEl && data.advice.used_model) {
        const usedLabel = window.ModelSettings ? window.ModelSettings.formatBadge(data.advice.used_model) : data.advice.used_model;
        badgeEl.innerHTML = `<span style="font-size:0.73rem;background:rgba(99,102,241,0.14);color:#4f46e5;padding:2px 8px;border-radius:999px;font-weight:700;">${escapeHtml(usedLabel)}</span>`;
      }
      btn.textContent = '🔄 보정 수치 다시 제안';
      btn.disabled = false;
    } else {
      alert(`보정 수치 제안 실패: ${data.error || '알 수 없는 오류'}`);
      btn.textContent = origText;
      btn.disabled = false;
    }
  } catch (err) {
    alert(`오류: ${err.message}`);
    btn.textContent = origText;
    btn.disabled = false;
  }
}

function renderExifSummary(exif, detectedSettings) {
  const parts = [];
  if (exif && Object.keys(exif).length) {
    if (exif.Make || exif.Model) parts.push(`${escapeHtml(exif.Make || '')} ${escapeHtml(exif.Model || '')}`.trim());
    if (exif.FNumber) parts.push(`F/${escapeHtml(exif.FNumber)}`);
    if (exif.ExposureTime) parts.push(`${escapeHtml(exif.ExposureTime)}s`);
    if (exif.ISOSpeedRatings) parts.push(`ISO ${escapeHtml(exif.ISOSpeedRatings)}`);
    if (exif.FocalLength) parts.push(`${escapeHtml(exif.FocalLength)}mm`);
  }
  let html = '';
  if (parts.length) {
    html += `<div style="margin-top:4px;"><b>촬영 설정(EXIF):</b> ${parts.join(' · ')}</div>`;
  } else {
    html += '<div style="margin-top:4px;color:var(--muted);"><b>EXIF:</b> 파일 메타데이터 없음</div>';
  }

  if (detectedSettings && typeof detectedSettings === 'object' && Object.keys(detectedSettings).length) {
    const dParts = [];
    for (const [k, v] of Object.entries(detectedSettings)) {
      if (v) dParts.push(`${escapeHtml(v)}`);
    }
    if (dParts.length) {
      html += `<div style="margin-top:6px;background:#eef2ff;color:#4338ca;padding:4px 10px;border-radius:6px;font-size:0.8rem;display:inline-block;border:1px solid #c7d2fe;"><b>🔍 워터마크 감지 스펙:</b> ${dParts.join(' · ')}</div>`;
    }
  }
  return html;
}

function closeDetailModal() {
  if (typeof clearCropOverlay === 'function') clearCropOverlay();
  const m = document.getElementById('detail-modal');
  if (m) m.style.display = 'none';
  currentDetailId = null;
}

function closeModal(e) {
  if (e && e.target && e.target.id === 'detail-modal') closeDetailModal();
}

function toggleZoom(e) {
  const img = document.getElementById('detail-modal-img');
  if (!img) return;
  img.classList.toggle('zoomed');
  if (img.classList.contains('zoomed') && e) {
    panZoom(e);
  } else {
    img.style.transformOrigin = 'center center';
  }
  if (typeof repositionCropOverlay === 'function') repositionCropOverlay();
}

function panZoom(e) {
  const img = document.getElementById('detail-modal-img');
  if (!img || !img.classList.contains('zoomed')) return;
  const rect = img.getBoundingClientRect();
  const x = Math.max(0, Math.min(100, ((e.clientX - rect.left) / rect.width) * 100));
  const y = Math.max(0, Math.min(100, ((e.clientY - rect.top) / rect.height) * 100));
  img.style.transformOrigin = `${x}% ${y}%`;
}

function navigateDetail(dir) {
  const modal = document.getElementById('detail-modal');
  if (!modal || modal.style.display !== 'flex' || currentDetailId === null) return;
  const filtered = sortList(filterList(allData));
  const idx = filtered.findIndex(d => d.id === currentDetailId);
  if (idx === -1) return;
  const nextIdx = idx + dir;
  if (nextIdx >= 0 && nextIdx < filtered.length) {
    openDetailModal(filtered[nextIdx].id);
  }
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
      if (currentDetailId === id) {
        closeDetailModal();
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
      alert(`총 ${data.count}개 사진의 Lightroom / Capture One 호환 XMP 사이드카 생성이 완료되었습니다!\n라이트룸에서 폴더를 새로고침하면 별점(1~5)과 색상 라벨이 즉시 표시됩니다.`);
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
