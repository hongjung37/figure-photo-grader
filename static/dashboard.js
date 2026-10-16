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

let allData = [];
let currentFilter = 'all';
let currentCatFilter = 'all';
let currentDetailId = null;
let currentView = 'gallery';
// Tag filter & taxonomy logic are modularized in static/js/tag_filter.js

function setCatFilter(cat, btn) {
  currentCatFilter = cat;
  document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderGallery();
}

let currentBurstDist = 15;

async function loadData() {
  allData = await API.fetchAnalyses(currentBurstDist);
  updateStats();
  populateCompareSelects();
  populateTagSelectorAndQuickTags();
  updateTagFilterUI();
  renderGallery();
  if (currentView === 'insights') {
    renderTagInsights();
  }
}

const loadAnalyses = loadData;

async function changeBurstSensitivity(val) {
  currentBurstDist = parseInt(val) || 15;
  await loadData();
}

function updateStats() {
  document.getElementById('total-count').textContent = allData.length;
  if (!allData.length) return;
  const avg = (allData.reduce((acc, cur) => acc + cur.final_score, 0) / allData.length).toFixed(1);
  const good = allData.filter(d => d.final_score >= 7.0).length;
  document.getElementById('avg-score').textContent = avg;
  document.getElementById('good-count').textContent = good;
}

let currentBurstFilter = 'all'; // 'all', 'best_only', 'stack'
let expandedBurstGroups = new Set();

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
  renderGallery();
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

  if (selectedTags.size > 0) {
    res = res.filter(d => {
      const itemTags = getAllTagsFromItem(d);
      if (tagLogic === 'AND') {
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
  const sort = document.getElementById('sort-select').value;
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

function renderGallery() {
  const container = document.getElementById('gallery-grid');
  const filtered = sortList(filterList(allData));
  if (!filtered.length) {
    container.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:60px;color:var(--muted)">해당 조건의 분석 사진이 없습니다.</div>';
    return;
  }
  container.innerHTML = filtered.map(item => `
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
          ${renderTagPills(item.aesthetic_tags)}
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
  `).join('');
}

// getTagColorStyle and renderTagPills are modularized in static/js/tag_filter.js


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
  clearCropOverlay();
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
        <img class="detail-img" id="detail-modal-img" src="/api/image/${item.id}?original=1" alt="${escapeHtml(item.filename)}" onload="repositionCropOverlay()">
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
          <button class="filter-btn reanalyze-btn" onclick="toggleReanalyzePanel(${item.id})">🔄 재평가</button>
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
          ${renderSnsAdviceContent(item.sns_advice, item.id)}
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
          ${renderTagPills(item.aesthetic_tags, 50)}
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
    setTimeout(() => { selectCropRatio(defaultRatio, item.id); }, 150);
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
      populateTagSelectorAndQuickTags();
      if (currentView === 'insights') {
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

// --- Crop Viewer & SNS Advice Component ---
// Note: Extracted to /static/js/crop_viewer.js for modular architecture.

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
  clearCropOverlay();
  document.getElementById('detail-modal').style.display = 'none';
  currentDetailId = null;
}
function closeModal(e) { if (e.target.id === 'detail-modal') closeDetailModal(); }

function toggleZoom(e) {
  const img = document.getElementById('detail-modal-img');
  if (!img) return;
  img.classList.toggle('zoomed');
  if (img.classList.contains('zoomed') && e) {
    panZoom(e);
  } else {
    img.style.transformOrigin = 'center center';
  }
  repositionCropOverlay();
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
  if (modal.style.display !== 'flex' || currentDetailId === null) return;
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

let tourState = {
  mode: 'setup', // 'setup', 'battle', 'champion'
  candidates: [],
  roundMatches: [],
  currentMatchIdx: 0,
  nextRound: [],
  selectedScale: 8,
  totalSteps: 0,
  completedSteps: 0,
  champion: null,
};

function openTournamentModal() {
  const modal = document.getElementById('tournament-modal');
  modal.style.display = 'flex';
  renderTournamentSetup();
}

function closeTournamentModal(e) {
  if (e && e.target && e.target.id !== 'tournament-modal' && !e.target.classList.contains('close-btn')) return;
  const modal = document.getElementById('tournament-modal');
  modal.style.display = 'none';
  tourState.mode = 'setup';
}

function renderTournamentSetup() {
  tourState.mode = 'setup';
  document.getElementById('tour-round-badge').style.display = 'none';
  document.getElementById('tour-progress-wrap').style.display = 'none';
  document.getElementById('tour-subtitle').textContent = '점수와 파일명을 가리고 순수 시각적 느낌만으로 최고의 A컷을 토너먼트로 선별합니다.';

  const totalPhotos = allData.length;
  const burstGroups = [...new Set(allData.filter(d => d.burst_group_id).map(d => d.burst_group_id))];

  const container = document.getElementById('tour-body-container');
  if (totalPhotos < 2) {
    container.innerHTML = `
      <div style="text-align:center;padding:60px 20px;">
        <div style="font-size:3.5rem;margin-bottom:12px;">📷</div>
        <h3 style="font-size:1.3rem;margin-bottom:8px;color:white;">사진이 부족합니다</h3>
        <p style="color:#94a3b8;margin-bottom:20px;">블라인드 토너먼트를 진행하려면 최소 2장 이상의 사진이 분석되어 있어야 합니다.<br>새 사진을 업로드하거나 분석을 먼저 완료해 주세요.</p>
        <button class="upload-btn" style="margin:0 auto;" onclick="closeTournamentModal(); openUploadModal();">+ 사진 업로드하기</button>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div style="max-width:580px;margin:auto;width:100%;background:#1e293b;padding:32px;border-radius:20px;border:1px solid #334155;">
      <h3 style="font-size:1.3rem;margin:0 0 8px;display:flex;align-items:center;gap:8px;color:white;">
        <span>⚔️</span> 토너먼트 설정
      </h3>
      <p style="color:#94a3b8;font-size:0.86rem;margin:0 0 24px;line-height:1.5;">
        A/B 사진의 점수와 파일명이 완전히 가려진 상태로 1:1 대결이 진행됩니다.<br>
        키보드 <strong>A (또는 ←)</strong> / <strong>B (또는 →)</strong> 키로 더 마음에 드는 사진을 선택하세요!
      </p>

      <div style="margin-bottom:18px;">
        <label style="display:block;font-size:0.86rem;font-weight:700;margin-bottom:8px;color:#cbd5e1;">참가 대상 사진 범위</label>
        <select class="select-input" id="tour-source-select" style="width:100%;background:#0f172a;border-color:#334155;color:white;" onchange="updateTourScaleOptions()">
          <option value="all">전체 분석 사진 (${totalPhotos}장 중)</option>
          <option value="filtered">현재 필터링된 사진 (${getFilteredCount()}장)</option>
          ${burstGroups.length > 0 ? `<option value="burst">연사(Burst) 그룹 사진만 (${allData.filter(d => d.burst_group_id).length}장)</option>` : ''}
        </select>
      </div>

      <div style="margin-bottom:20px;">
        <label style="display:block;font-size:0.86rem;font-weight:700;margin-bottom:8px;color:#cbd5e1;">토너먼트 대진 규모</label>
        <div id="tour-scale-chips" style="display:flex;gap:8px;flex-wrap:wrap;"></div>
      </div>

      <div style="margin-bottom:24px;display:flex;align-items:center;gap:10px;">
        <input type="checkbox" id="tour-shuffle-chk" checked style="width:18px;height:18px;accent-color:#38bdf8;cursor:pointer;">
        <label for="tour-shuffle-chk" style="font-size:0.88rem;color:#e2e8f0;cursor:pointer;">대진표 무작위 셔플 (Random Seeding)</label>
      </div>

      <div style="display:flex;gap:12px;justify-content:flex-end;">
        <button class="filter-btn" style="background:#334155;border-color:#475569;color:#e2e8f0;padding:10px 20px;font-size:0.9rem;" onclick="closeTournamentModal()">취소</button>
        <button class="upload-btn" style="background:linear-gradient(135deg, #0284c7, #3b82f6);padding:10px 24px;font-size:0.95rem;font-weight:800;" onclick="startTournament()">토너먼트 시작 ⚔️</button>
      </div>
    </div>
  `;
  updateTourScaleOptions();
}

function getFilteredCount() {
  return filterList(allData).length;
}

let selectedTourScale = 8;

function updateTourScaleOptions() {
  const src = document.getElementById('tour-source-select')?.value || 'all';
  let pool = allData;
  if (src === 'filtered') pool = filterList(allData);
  else if (src === 'burst') pool = allData.filter(d => d.burst_group_id);
  const count = pool.length;

  const scales = [
    { num: 2, label: '결승 단판 (2강)' },
    { num: 4, label: '4강 (준결승)' },
    { num: 8, label: '8강전' },
    { num: 16, label: '16강전' },
    { num: 32, label: '32강전' },
  ].filter(s => s.num <= count);

  if (!scales.some(s => s.num === count) && count >= 2) {
    scales.push({ num: count, label: `전체 참가 (${count}강)` });
  }

  const validNums = scales.map(s => s.num);
  if (!validNums.includes(selectedTourScale)) {
    selectedTourScale = validNums.includes(8) ? 8 : (validNums.includes(4) ? 4 : validNums[validNums.length - 1]);
  }

  const chipsContainer = document.getElementById('tour-scale-chips');
  if (chipsContainer) {
    chipsContainer.innerHTML = scales.map(s => `
      <button type="button" class="filter-btn ${s.num === selectedTourScale ? 'active' : ''}"
        style="padding:8px 16px;font-size:0.86rem;${s.num === selectedTourScale ? 'background:#0284c7;border-color:#38bdf8;color:white;font-weight:700;' : 'background:#0f172a;border-color:#334155;color:#94a3b8;'}"
        onclick="setTourScale(${s.num})">
        ${s.label}
      </button>
    `).join('');
  }
}

function setTourScale(n) {
  selectedTourScale = n;
  updateTourScaleOptions();
}

function startTournament() {
  const src = document.getElementById('tour-source-select')?.value || 'all';
  let pool = [...allData];
  if (src === 'filtered') pool = filterList(allData);
  else if (src === 'burst') pool = allData.filter(d => d.burst_group_id);

  if (pool.length < 2) {
    alert('참가 가능한 사진이 2장 이상이어야 합니다.');
    return;
  }

  const shuffle = document.getElementById('tour-shuffle-chk')?.checked ?? true;
  if (shuffle) {
    pool.sort(() => Math.random() - 0.5);
  }

  const count = Math.min(selectedTourScale, pool.length);
  const candidates = pool.slice(0, count);

  tourState.candidates = candidates;
  tourState.nextRound = [];
  tourState.currentMatchIdx = 0;
  tourState.champion = null;
  tourState.mode = 'battle';

  tourState.roundMatches = makeMatchesFromList(candidates);
  tourState.totalSteps = count - 1;
  tourState.completedSteps = 0;

  document.getElementById('tour-round-badge').style.display = 'inline-block';
  document.getElementById('tour-progress-wrap').style.display = 'block';

  renderTournamentMatch();
}

function makeMatchesFromList(list) {
  const matches = [];
  for (let i = 0; i < list.length; i += 2) {
    if (i + 1 < list.length) {
      matches.push([list[i], list[i + 1]]);
    } else {
      tourState.nextRound.push(list[i]);
    }
  }
  return matches;
}

function getRoundTitle(remaining) {
  if (remaining === 2) return '결승전 (FINAL)';
  if (remaining === 4) return '준결승 (4강전)';
  if (remaining === 8) return '8강전';
  if (remaining === 16) return '16강전';
  if (remaining === 32) return '32강전';
  return `${remaining}강전`;
}

function renderTournamentMatch() {
  const matches = tourState.roundMatches;
  const idx = tourState.currentMatchIdx;
  if (idx >= matches.length) return;

  const currentPair = matches[idx];
  const photoA = currentPair[0];
  const photoB = currentPair[1];

  const roundTitle = getRoundTitle(matches.length * 2);
  document.getElementById('tour-round-badge').textContent = `${roundTitle} • Match ${idx + 1}/${matches.length}`;
  document.getElementById('tour-subtitle').textContent = `[키보드 단축키] A / ← (왼쪽 A 선택) | B / → (오른쪽 B 선택) | ESC (종료)`;

  const progressPct = Math.min(100, Math.round((tourState.completedSteps / Math.max(1, tourState.totalSteps)) * 100));
  document.getElementById('tour-progress-bar').style.width = `${progressPct}%`;

  const container = document.getElementById('tour-body-container');
  container.innerHTML = `
    <div class="tour-vs-container">
      <!-- Card A -->
      <div class="tour-card" onclick="selectTournamentWinner('A')">
        <div class="tour-card-header">
          <span style="font-weight:800;font-size:1.02rem;color:#38bdf8;display:flex;align-items:center;gap:6px;">
            <kbd style="background:#0284c7;color:white;padding:2px 8px;border-radius:6px;font-size:0.85rem;">A</kbd> 사진 (선택: A 또는 ←)
          </span>
          <span style="font-size:0.74rem;background:#0f172a;color:#94a3b8;padding:3px 8px;border-radius:6px;">🔒 블라인드 컷</span>
        </div>
        <div class="tour-card-img-wrap">
          <img class="tour-card-img" src="/api/image/${photoA.id}" alt="Photo A">
        </div>
        <div class="tour-card-footer">
          <button class="upload-btn" style="width:100%;justify-content:center;background:#0284c7;font-weight:800;" onclick="event.stopPropagation(); selectTournamentWinner('A');">
            👈 A 사진 선택 (A / ←)
          </button>
        </div>
      </div>

      <!-- VS Badge -->
      <div style="display:flex;flex-direction:column;align-items:center;gap:12px;">
        <div class="tour-vs-badge">VS</div>
        <button class="filter-btn" style="background:#1e293b;border-color:#334155;color:#94a3b8;font-size:0.75rem;padding:4px 10px;" onclick="selectTournamentWinner('RANDOM')">
          🎲 무작위 결정
        </button>
      </div>

      <!-- Card B -->
      <div class="tour-card" onclick="selectTournamentWinner('B')">
        <div class="tour-card-header">
          <span style="font-weight:800;font-size:1.02rem;color:#f43f5e;display:flex;align-items:center;gap:6px;">
            <kbd style="background:#e11d48;color:white;padding:2px 8px;border-radius:6px;font-size:0.85rem;">B</kbd> 사진 (선택: B 또는 →)
          </span>
          <span style="font-size:0.74rem;background:#0f172a;color:#94a3b8;padding:3px 8px;border-radius:6px;">🔒 블라인드 컷</span>
        </div>
        <div class="tour-card-img-wrap">
          <img class="tour-card-img" src="/api/image/${photoB.id}" alt="Photo B">
        </div>
        <div class="tour-card-footer">
          <button class="upload-btn" style="width:100%;justify-content:center;background:#e11d48;font-weight:800;" onclick="event.stopPropagation(); selectTournamentWinner('B');">
            B 사진 선택 👉 (B / →)
          </button>
        </div>
      </div>
    </div>
  `;
}

function selectTournamentWinner(winnerSide) {
  if (tourState.mode !== 'battle') return;
  const currentPair = tourState.roundMatches[tourState.currentMatchIdx];
  if (!currentPair) return;

  let winner;
  if (winnerSide === 'A') winner = currentPair[0];
  else if (winnerSide === 'B') winner = currentPair[1];
  else winner = Math.random() < 0.5 ? currentPair[0] : currentPair[1];

  tourState.nextRound.push(winner);
  tourState.completedSteps++;
  tourState.currentMatchIdx++;

  if (tourState.currentMatchIdx < tourState.roundMatches.length) {
    renderTournamentMatch();
  } else {
    if (tourState.nextRound.length === 1) {
      tourState.mode = 'champion';
      tourState.champion = tourState.nextRound[0];
      renderTournamentChampion(tourState.champion);
    } else {
      tourState.roundMatches = makeMatchesFromList(tourState.nextRound);
      tourState.nextRound = [];
      tourState.currentMatchIdx = 0;
      renderTournamentMatch();
    }
  }
}

function renderTournamentChampion(winner) {
  tourState.mode = 'champion';
  document.getElementById('tour-round-badge').textContent = '👑 우승 (CHAMPION)';
  document.getElementById('tour-round-badge').style.background = '#f59e0b';
  document.getElementById('tour-progress-wrap').style.display = 'none';
  document.getElementById('tour-subtitle').textContent = '블라인드 토너먼트 최종 우승 컷이 결정되었습니다! AI 비평 결과와 내 선택을 비교해 보세요.';

  const sorted = [...allData].sort((a, b) => b.final_score - a.final_score);
  const aiRank = sorted.findIndex(d => d.id === winner.id) + 1;
  const totalCount = allData.length;

  let matchInsight = '';
  if (aiRank === 1) {
    matchInsight = `
      <div style="background:#064e3b;border:1px solid #059669;padding:12px 16px;border-radius:12px;margin-bottom:14px;display:flex;align-items:center;gap:12px;">
        <span style="font-size:1.8rem;">✨</span>
        <div>
          <strong style="color:#6ee7b7;font-size:0.95rem;">100% 일치: AI 평가 1위와 완벽하게 일치합니다!</strong>
          <div style="color:#a7f3d0;font-size:0.8rem;margin-top:2px;">사진가님의 심미적 직관과 AI의 정밀 광학·구도 평가가 완벽히 합치된 최고의 컷입니다.</div>
        </div>
      </div>
    `;
  } else if (aiRank <= 3) {
    matchInsight = `
      <div style="background:#1e3a8a;border:1px solid #3b82f6;padding:12px 16px;border-radius:12px;margin-bottom:14px;display:flex;align-items:center;gap:12px;">
        <span style="font-size:1.8rem;">🎯</span>
        <div>
          <strong style="color:#93c5fd;font-size:0.95rem;">높은 일치도: AI 평가 최상위권 (전체 ${totalCount}장 중 ${aiRank}위)</strong>
          <div style="color:#bfdbfe;font-size:0.8rem;margin-top:2px;">객관적인 화질·기술 점수에서도 상위권에 랭크된 검증된 A컷입니다.</div>
        </div>
      </div>
    `;
  } else {
    matchInsight = `
      <div style="background:#4c1d95;border:1px solid #8b5cf6;padding:12px 16px;border-radius:12px;margin-bottom:14px;display:flex;align-items:center;gap:12px;">
        <span style="font-size:1.8rem;">🎨</span>
        <div>
          <strong style="color:#d8b4fe;font-size:0.95rem;">작가 고유의 감성 컷 (AI 평가 ${totalCount}장 중 ${aiRank}위)</strong>
          <div style="color:#e9d5ff;font-size:0.8rem;margin-top:2px;">AI의 단순 기술적 척도를 뛰어넘는 고유한 분위기와 매력이 작가님의 눈길을 사로잡았습니다!</div>
        </div>
      </div>
    `;
  }

  const container = document.getElementById('tour-body-container');
  container.innerHTML = `
    <div style="display:grid;grid-template-columns:1.1fr 1fr;gap:24px;align-items:center;max-width:1150px;margin:auto;width:100%;">
      <div style="background:#020617;border-radius:20px;border:3px solid #f59e0b;overflow:hidden;box-shadow:0 0 40px rgba(245, 158, 11, 0.25);position:relative;">
        <div style="position:absolute;top:16px;left:16px;background:rgba(245, 158, 11, 0.95);color:#0f172a;font-weight:900;font-size:0.88rem;padding:4px 14px;border-radius:999px;box-shadow:0 4px 12px rgba(0,0,0,0.3);">
          👑 토너먼트 최종 우승 컷
        </div>
        <img src="/api/image/${winner.id}" style="width:100%;max-height:64vh;object-fit:contain;display:block;">
      </div>

      <div style="background:#1e293b;padding:24px;border-radius:20px;border:1px solid #334155;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <h2 style="margin:0;font-size:1.3rem;font-weight:800;color:white;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${escapeHtml(winner.filename)}">
            ${escapeHtml(winner.filename)}
          </h2>
          <span class="score-grade" style="font-size:0.82rem;padding:3px 10px;">${escapeHtml(winner.grade)}</span>
        </div>

        <div style="font-size:0.78rem;color:#94a3b8;margin-bottom:14px;">
          촬영 세부 유형: <strong style="color:#cbd5e1;">${escapeHtml(winner.figure_category)}</strong> • 
          초점: <strong style="color:#2dd4bf;">${escapeHtml(winner.focus_status)}</strong>
        </div>

        ${matchInsight}

        <div style="display:grid;grid-template-columns:repeat(4, 1fr);gap:6px;background:#0f172a;padding:12px;border-radius:12px;margin-bottom:14px;text-align:center;">
          <div><span style="font-size:0.72rem;color:#94a3b8;display:block;">구도</span><strong style="font-size:1.05rem;color:#38bdf8;">${winner.composition_score.toFixed(1)}</strong></div>
          <div><span style="font-size:0.72rem;color:#94a3b8;display:block;">조명</span><strong style="font-size:1.05rem;color:#38bdf8;">${winner.lighting_score.toFixed(1)}</strong></div>
          <div><span style="font-size:0.72rem;color:#94a3b8;display:block;">색감</span><strong style="font-size:1.05rem;color:#38bdf8;">${winner.color_score.toFixed(1)}</strong></div>
          <div><span style="font-size:0.72rem;color:#94a3b8;display:block;">기술</span><strong style="font-size:1.05rem;color:#38bdf8;">${winner.technique_score.toFixed(1)}</strong></div>
        </div>

        <div style="font-size:0.84rem;color:#e2e8f0;line-height:1.45;margin-bottom:14px;background:#0f172a;padding:10px 14px;border-radius:10px;">
          ${escapeHtml(winner.final_reason)}
        </div>

        <div style="margin-bottom:18px;">
          <span style="font-size:0.75rem;color:#94a3b8;display:block;margin-bottom:6px;font-weight:700;">미학 & 분위기 태그:</span>
          <div class="tag-pills" style="margin-top:0;">
            ${renderTagPills(winner.aesthetic_tags, 10)}
          </div>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
          <button class="upload-btn" id="btn-save-champ" style="background:#0d9488;justify-content:center;font-size:0.85rem;" onclick="saveTournamentWinner(${winner.id}, this)">
            ⭐ '토너먼트 1위'로 등록
          </button>
          <button class="upload-btn" style="background:#2563eb;justify-content:center;font-size:0.85rem;" onclick="closeTournamentModal(); openDetailModal(${winner.id});">
            🔍 보정/크롭 상세 보기
          </button>
          <button class="filter-btn" style="background:#334155;border-color:#475569;color:#e2e8f0;padding:8px;font-size:0.85rem;" onclick="renderTournamentSetup()">
            🔄 다시 토너먼트 하기
          </button>
          <button class="filter-btn" style="background:#0f172a;border-color:#334155;color:#94a3b8;padding:8px;font-size:0.85rem;" onclick="closeTournamentModal()">
            ✕ 갤러리로 돌아가기
          </button>
        </div>
      </div>
    </div>
  `;
}

async function saveTournamentWinner(id, btn) {
  if (btn) {
    btn.disabled = true;
    btn.textContent = '저장 중...';
  }
  try {
    const data = await API.updateStatus(id, '토너먼트 1위');
    if (data.success) {
      if (btn) btn.textContent = '✓ 저장 완료!';
      await loadAnalyses();
    } else {
      alert(`저장 실패: ${data.error}`);
      if (btn) btn.disabled = false;
    }
  } catch (err) {
    alert(`오류: ${err.message}`);
    if (btn) btn.disabled = false;
  }
}

function handleTournamentKey(e) {
  if (tourState.mode === 'battle') {
    if (e.key === 'a' || e.key === 'A' || e.key === 'ArrowLeft') {
      e.preventDefault();
      selectTournamentWinner('A');
    } else if (e.key === 'b' || e.key === 'B' || e.key === 'ArrowRight') {
      e.preventDefault();
      selectTournamentWinner('B');
    } else if (e.key === 'Escape') {
      e.preventDefault();
      closeTournamentModal();
    }
  } else if (e.key === 'Escape') {
    e.preventDefault();
    closeTournamentModal();
  }
}

window.addEventListener('keydown', (e) => {
  if (['input', 'textarea', 'select'].includes(document.activeElement?.tagName?.toLowerCase())) return;
  const tourModal = document.getElementById('tournament-modal');
  if (tourModal && tourModal.style.display === 'flex') {
    handleTournamentKey(e);
    return;
  }
  if (e.key === 'Escape') {
    closeDetailModal();
    closeUsageModal();
    closeUploadModal();
  } else if (e.key === 'ArrowRight' || e.key === 'k') {
    navigateDetail(1);
  } else if (e.key === 'ArrowLeft' || e.key === 'j') {
    navigateDetail(-1);
  } else if (e.key === ' ' || e.code === 'Space') {
    const modal = document.getElementById('detail-modal');
    if (modal.style.display === 'flex') {
      e.preventDefault();
      toggleZoom();
    }
  }
});

function switchView(mode) {
  currentView = mode;
  const galleryGrid = document.getElementById('gallery-grid');
  const compareView = document.getElementById('compare-view');
  const insightsView = document.getElementById('insights-view');
  const tabGallery = document.getElementById('tab-gallery');
  const tabCompare = document.getElementById('tab-compare');
  const tabInsights = document.getElementById('tab-insights');

  if (tabGallery) tabGallery.classList.toggle('active', mode === 'gallery');
  if (tabCompare) tabCompare.classList.toggle('active', mode === 'compare');
  if (tabInsights) tabInsights.classList.toggle('active', mode === 'insights');

  if (mode === 'gallery') {
    if (galleryGrid) galleryGrid.style.display = 'grid';
    if (compareView) compareView.style.display = 'none';
    if (insightsView) insightsView.style.display = 'none';
  } else if (mode === 'compare') {
    if (galleryGrid) galleryGrid.style.display = 'none';
    if (compareView) compareView.style.display = 'block';
    if (insightsView) insightsView.style.display = 'none';
    updateComparison();
  } else if (mode === 'insights') {
    if (galleryGrid) galleryGrid.style.display = 'none';
    if (compareView) compareView.style.display = 'none';
    if (insightsView) insightsView.style.display = 'block';
    renderTagInsights();
  }
}

function setInsightsMinCount(val) {
  insightsMinCount = parseInt(val) || 2;
  renderTagInsights();
}

function setInsightsRatingMode(mode) {
  insightsRatingMode = mode;
  renderTagInsights();
}

function computeClientTagStats(minCount) {
  const totalPhotos = allData.length;
  const userRatedPhotos = allData.filter(d => d.user_score !== null && d.user_score !== undefined).length;
  const tagData = {};

  allData.forEach(d => {
    const tags = d.aesthetic_tags || {};
    const aiScore = d.final_score || 0;
    const uScore = (d.user_score !== null && d.user_score !== undefined) ? d.user_score : null;
    const lScore = d.lighting_score || 0;
    const cScore = d.composition_score || 0;
    const tScore = d.technique_score || 0;
    const colScore = d.color_score || 0;

    for (const [ckey, list] of Object.entries(tags)) {
      if (Array.isArray(list)) {
        const cname = TAG_CATEGORIES[ckey] || ckey;
        list.forEach(t => {
          const key = ckey + '::' + t;
          if (!tagData[key]) {
            tagData[key] = {
              category_key: ckey,
              category_name: cname,
              tag: t,
              count: 0,
              ai_scores: [],
              user_scores: [],
              lighting_scores: [],
              composition_scores: [],
              technique_scores: [],
              color_scores: []
            };
          }
          const td = tagData[key];
          td.count += 1;
          td.ai_scores.push(aiScore);
          if (uScore !== null) td.user_scores.push(uScore);
          td.lighting_scores.push(lScore);
          td.composition_scores.push(cScore);
          td.technique_scores.push(tScore);
          td.color_scores.push(colScore);
        });
      }
    }
  });

  const allTags = [];
  for (const td of Object.values(tagData)) {
    if (td.count < minCount) continue;
    const avgAi = td.ai_scores.length ? (td.ai_scores.reduce((a, b) => a + b, 0) / td.ai_scores.length) : 0;
    const avgUser = td.user_scores.length ? (td.user_scores.reduce((a, b) => a + b, 0) / td.user_scores.length) : null;
    const avgLight = td.lighting_scores.length ? (td.lighting_scores.reduce((a, b) => a + b, 0) / td.lighting_scores.length) : 0;
    const avgComp = td.composition_scores.length ? (td.composition_scores.reduce((a, b) => a + b, 0) / td.composition_scores.length) : 0;
    const avgTech = td.technique_scores.length ? (td.technique_scores.reduce((a, b) => a + b, 0) / td.technique_scores.length) : 0;
    const avgColor = td.color_scores.length ? (td.color_scores.reduce((a, b) => a + b, 0) / td.color_scores.length) : 0;

    const diff = (avgUser !== null) ? Math.round((avgUser - avgAi) * 10) / 10 : null;

    allTags.push({
      category_key: td.category_key,
      category_name: td.category_name,
      tag: td.tag,
      count: td.count,
      avg_ai_score: Math.round(avgAi * 10) / 10,
      avg_user_score: (avgUser !== null) ? Math.round(avgUser * 10) / 10 : null,
      score_diff: diff,
      user_rated_count: td.user_scores.length,
      avg_lighting_score: Math.round(avgLight * 10) / 10,
      avg_composition_score: Math.round(avgComp * 10) / 10,
      avg_technique_score: Math.round(avgTech * 10) / 10,
      avg_color_score: Math.round(avgColor * 10) / 10
    });
  }

  let sortedTags = [...allTags];
  if (insightsRatingMode === 'user') {
    sortedTags.sort((a, b) => {
      const sa = a.avg_user_score !== null ? a.avg_user_score : -1;
      const sb = b.avg_user_score !== null ? b.avg_user_score : -1;
      return sb - sa;
    });
  } else if (insightsRatingMode === 'diff') {
    sortedTags.sort((a, b) => {
      const da = a.score_diff !== null ? a.score_diff : -999;
      const db = b.score_diff !== null ? b.score_diff : -999;
      return db - da;
    });
  } else {
    sortedTags.sort((a, b) => b.avg_ai_score - a.avg_ai_score);
  }

  const topTags = sortedTags.slice(0, 5);
  const bottomTags = (sortedTags.length >= 2) ? [...sortedTags].reverse().slice(0, 5) : [];

  const categories = {};
  for (const t of sortedTags) {
    if (!categories[t.category_key]) categories[t.category_key] = [];
    categories[t.category_key].push(t);
  }

  const tagsWithDiff = allTags.filter(t => t.score_diff !== null);
  const bestFavTag = tagsWithDiff.length ? [...tagsWithDiff].sort((a, b) => b.score_diff - a.score_diff)[0] : null;

  return {
    totalPhotos,
    userRatedPhotos,
    totalUniqueTags: Object.keys(tagData).length,
    filteredCount: allTags.length,
    allTags,
    topTags,
    bottomTags,
    categories,
    bestFavTag
  };
}

function getScoreColor(score) {
  if (score >= 9.0) return '#2563eb';
  if (score >= 8.0) return '#0d9488';
  if (score >= 7.0) return '#d97706';
  return '#e11d48';
}

function renderTagInsights() {
  const container = document.getElementById('insights-view');
  if (!container) return;

  const stats = computeClientTagStats(insightsMinCount);

  if (!allData.length) {
    container.innerHTML = '<div style="text-align:center;padding:60px;color:var(--muted)">분석된 사진 데이터가 없습니다. 먼저 사진을 업로드해 분석해주세요.</div>';
    return;
  }

  const topAi = stats.allTags.length ? [...stats.allTags].sort((a, b) => b.avg_ai_score - a.avg_ai_score)[0] : null;
  const userRatePct = stats.totalPhotos ? Math.round((stats.userRatedPhotos / stats.totalPhotos) * 100) : 0;

  container.innerHTML = `
    <!-- Insights Toolbar -->
    <div class="insights-toolbar">
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
        <span style="font-size:1.15rem;font-weight:900;color:var(--navy);display:flex;align-items:center;gap:6px;">
          📊 시각 태그별 평균 점수 & 미학 경향성 인사이트
        </span>
        <span style="font-size:0.75rem;background:#e0f2fe;color:#0369a1;padding:3px 9px;border-radius:999px;font-weight:700;">
          총 ${stats.filteredCount}개 태그 분석됨
        </span>
      </div>

      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
        <!-- Sample Min Count Filter -->
        <div style="display:inline-flex;align-items:center;gap:6px;background:#f1f5f9;padding:4px 10px;border-radius:10px;border:1px solid #e2e8f0;">
          <span style="font-size:0.78rem;font-weight:700;color:var(--muted);">최소 사진 수:</span>
          <select class="select-input" style="padding:2px 8px;font-size:0.78rem;border:none;background:transparent;font-weight:700;color:#0284c7;cursor:pointer;" onchange="setInsightsMinCount(this.value)">
            <option value="1" ${insightsMinCount === 1 ? 'selected' : ''}>1장 이상 (전체)</option>
            <option value="2" ${insightsMinCount === 2 ? 'selected' : ''}>2장 이상 (표준 권장)</option>
            <option value="3" ${insightsMinCount === 3 ? 'selected' : ''}>3장 이상</option>
            <option value="5" ${insightsMinCount === 5 ? 'selected' : ''}>5장 이상 (대용량)</option>
          </select>
        </div>

        <!-- Rating Mode Switcher -->
        <div style="display:inline-flex;background:#e2e8f0;border-radius:10px;padding:3px;gap:2px;">
          <button class="toggle-logic-btn ${insightsRatingMode === 'ai' ? 'active' : ''}" onclick="setInsightsRatingMode('ai')">🤖 AI 점수</button>
          <button class="toggle-logic-btn ${insightsRatingMode === 'user' ? 'active' : ''}" onclick="setInsightsRatingMode('user')">👤 내 점수</button>
          <button class="toggle-logic-btn ${insightsRatingMode === 'diff' ? 'active' : ''}" onclick="setInsightsRatingMode('diff')">⚖️ AI vs 내 점수 비교</button>
        </div>
      </div>
    </div>

    <!-- KPI Summary Cards -->
    <div class="insights-kpi-grid">
      <div class="insights-kpi-card">
        <div class="insights-kpi-title">📷 총 분석 데이터</div>
        <div class="insights-kpi-value">${stats.totalPhotos} <small style="font-size:0.9rem;font-weight:500;color:var(--muted)">장</small></div>
        <div class="insights-kpi-sub">고유 시각 태그 ${stats.totalUniqueTags}개 추출</div>
      </div>

      <div class="insights-kpi-card">
        <div class="insights-kpi-title">👤 사용자 직접 평가율</div>
        <div class="insights-kpi-value">${stats.userRatedPhotos} <small style="font-size:0.9rem;font-weight:500;color:var(--muted)">장 (${userRatePct}%)</small></div>
        <div class="insights-kpi-sub">${stats.userRatedPhotos > 0 ? 'AI 점수와 내 취향 비교 가능' : '사진 상세 모달에서 직접 평가해보세요'}</div>
      </div>

      <div class="insights-kpi-card">
        <div class="insights-kpi-title">🌟 AI 최고 평점 태그</div>
        <div class="insights-kpi-value" style="font-size:1.2rem;color:#0d9488;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
          ${topAi ? `#${escapeHtml(topAi.tag)}` : '-'}
        </div>
        <div class="insights-kpi-sub">${topAi ? `평균 ${topAi.avg_ai_score.toFixed(1)}점 (${topAi.count}장 등록)` : '데이터 없음'}</div>
      </div>

      <div class="insights-kpi-card">
        <div class="insights-kpi-title">💡 내 취향 최고 태그 (AI 대비 +차이)</div>
        <div class="insights-kpi-value" style="font-size:1.2rem;color:#6366f1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
          ${stats.bestFavTag ? `#${escapeHtml(stats.bestFavTag.tag)}` : '-'}
        </div>
        <div class="insights-kpi-sub">${stats.bestFavTag ? `AI 대비 +${stats.bestFavTag.score_diff.toFixed(1)}점 더 선호` : '직접 평가가 쌓이면 노출됩니다'}</div>
      </div>
    </div>

    <!-- Top 5 & Bottom 5 Rankings -->
    <div class="insights-rankings-grid">
      <!-- Top 5 -->
      <div class="insights-rank-card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
          <h3 style="margin:0;font-size:1.02rem;display:flex;align-items:center;gap:6px;color:#065f46;">
            <span>🌟</span> 최고 평점 태그 Top 5 (A컷 제조 태그)
          </h3>
          <span style="font-size:0.75rem;color:var(--muted);">클릭 시 갤러리 검색</span>
        </div>
        <div>
          ${stats.topTags.length ? stats.topTags.map((t, idx) => renderTagStatRow(t, idx + 1, 'top')).join('') : '<div style="color:var(--muted);font-size:0.84rem;padding:20px;text-align:center;">조건을 만족하는 태그가 없습니다.</div>'}
        </div>
      </div>

      <!-- Bottom 5 -->
      <div class="insights-rank-card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
          <h3 style="margin:0;font-size:1.02rem;display:flex;align-items:center;gap:6px;color:#991b1b;">
            <span>🔻</span> 감점 요인 / 최저 평점 태그 Bottom 5
          </h3>
          <span style="font-size:0.75rem;color:var(--muted);">클릭 시 갤러리 검색</span>
        </div>
        <div>
          ${stats.bottomTags.length ? stats.bottomTags.map((t, idx) => renderTagStatRow(t, idx + 1, 'bottom')).join('') : '<div style="color:var(--muted);font-size:0.84rem;padding:20px;text-align:center;">조건을 만족하는 태그가 없습니다.</div>'}
        </div>
      </div>
    </div>

    <!-- 8 Aesthetic Categories Breakdown Grid -->
    <div style="margin-top:28px;">
      <div style="margin-bottom:14px;display:flex;justify-content:space-between;align-items:center;">
        <div>
          <h3 style="margin:0;font-size:1.15rem;font-weight:800;color:var(--navy);">
            🎨 8대 미학 카테고리별 세부 스타일 경향성
          </h3>
          <span style="font-size:0.78rem;color:var(--muted);">카테고리별로 어떤 촬영 기법과 구도가 더 높은 점수를 받는지 비교해보세요.</span>
        </div>
      </div>

      <div class="insights-categories-grid">
        ${Object.entries(TAG_CATEGORIES).map(([ckey, cname]) => {
          const catTags = stats.categories[ckey] || [];
          return `
            <div class="category-insight-card">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #e2e8f0;">
                <b style="font-size:0.92rem;color:var(--navy);">${cname}</b>
                <span style="font-size:0.72rem;background:#f1f5f9;color:var(--muted);padding:2px 7px;border-radius:999px;">
                  ${catTags.length}개 태그
                </span>
              </div>
              <div>
                ${catTags.length ? catTags.slice(0, 6).map((t, idx) => renderCategoryTagRow(t)).join('') : '<div style="font-size:0.78rem;color:var(--muted);padding:14px;text-align:center;">최소 등록 기준(${insightsMinCount}장)을 만족하는 태그가 아직 없습니다.</div>'}
              </div>
            </div>
          `;
        }).join('')}
      </div>
    </div>
  `;
}

function renderTagStatRow(t, rank, type) {
  const score = (insightsRatingMode === 'user' && t.avg_user_score !== null) ? t.avg_user_score : t.avg_ai_score;
  const scoreColor = getScoreColor(score);
  const rankColor = type === 'top' ? (rank === 1 ? '#eab308' : (rank === 2 ? '#94a3b8' : '#b45309')) : '#ef4444';
  const style = getTagColorStyle(t.tag);
  const escapedTag = escapeHtml(t.tag);

  return `
    <div class="tag-stat-row">
      <div style="display:flex;align-items:center;gap:8px;overflow:hidden;">
        <span style="font-weight:900;font-size:0.85rem;color:${rankColor};width:18px;">${rank}</span>
        <span class="tag-pill" data-tag-action="toggle" data-tag="${escapedTag}" style="${style}cursor:pointer;font-weight:700;" title="클릭하여 #${escapedTag} 사진 모아보기">
          #${escapedTag}
        </span>
        <small style="color:var(--muted);font-size:0.74rem;">${escapeHtml(t.category_name)} (${t.count}장)</small>
      </div>

      <div style="text-align:right;min-width:140px;">
        <div style="display:flex;align-items:center;justify-content:flex-end;gap:6px;">
          ${t.avg_user_score !== null ? `<span style="font-size:0.74rem;color:#1d4ed8;font-weight:700;">👤 ${t.avg_user_score.toFixed(1)}</span>` : ''}
          <strong style="color:${scoreColor};font-size:0.95rem;">🤖 ${t.avg_ai_score.toFixed(1)}<small style="font-size:0.75rem;font-weight:500;color:var(--muted);">/10</small></strong>
          ${t.score_diff !== null ? `
            <span style="font-size:0.7rem;font-weight:800;padding:1px 5px;border-radius:4px;${t.score_diff > 0 ? 'background:#e0f2fe;color:#0369a1;' : (t.score_diff < 0 ? 'background:#fee2e2;color:#b91c1c;' : 'background:#f3e8ff;color:#7e22ce;')}">
              ${t.score_diff > 0 ? '+' : ''}${t.score_diff.toFixed(1)}
            </span>
          ` : ''}
        </div>
        <div class="tag-progress-track">
          <div class="tag-progress-fill" style="width:${Math.min(100, Math.max(0, score * 10))}%;background:${scoreColor};"></div>
        </div>
      </div>
    </div>
  `;
}

function renderCategoryTagRow(t) {
  const score = (insightsRatingMode === 'user' && t.avg_user_score !== null) ? t.avg_user_score : t.avg_ai_score;
  const scoreColor = getScoreColor(score);
  const style = getTagColorStyle(t.tag);
  const escapedTag = escapeHtml(t.tag);

  return `
    <div style="padding:6px 0;border-bottom:1px solid #f8fafc;display:flex;align-items:center;justify-content:space-between;gap:8px;">
      <span class="tag-pill" data-tag-action="toggle" data-tag="${escapedTag}" style="${style}cursor:pointer;font-size:0.75rem;font-weight:600;" title="클릭하여 #${escapedTag} 사진 모아보기">
        #${escapedTag} <small style="opacity:0.75;">(${t.count})</small>
      </span>

      <div style="text-align:right;min-width:110px;">
        <div style="display:flex;align-items:center;justify-content:flex-end;gap:5px;font-size:0.78rem;">
          <span style="font-weight:800;color:${scoreColor};">${score.toFixed(1)}점</span>
          ${t.avg_user_score !== null && insightsRatingMode !== 'user' ? `<span style="font-size:0.7rem;color:#1d4ed8;">(👤${t.avg_user_score.toFixed(1)})</span>` : ''}
        </div>
        <div class="tag-progress-track" style="height:4px;">
          <div class="tag-progress-fill" style="width:${Math.min(100, Math.max(0, score * 10))}%;background:${scoreColor};"></div>
        </div>
      </div>
    </div>
  `;
}

function populateCompareSelects() {
  const selA = document.getElementById('comp-a-select');
  const selB = document.getElementById('comp-b-select');
  const options = allData.map(d => `<option value="${d.id}">${escapeHtml(d.filename)} (${d.final_score.toFixed(1)}점 - ${escapeHtml(d.grade)})</option>`).join('');
  selA.innerHTML = options;
  selB.innerHTML = options;
  if (allData.length > 1) selB.selectedIndex = 1;
}

function updateComparison() {
  const idA = parseInt(document.getElementById('comp-a-select').value);
  const idB = parseInt(document.getElementById('comp-b-select').value);
  const a = allData.find(d => d.id === idA);
  const b = allData.find(d => d.id === idB);
  if (!a || !b) return;

  const content = document.getElementById('compare-content');
  content.innerHTML = [a, b].map((item, idx) => `
    <div class="compare-col">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <h3 style="margin:0;">사진 ${idx === 0 ? 'A' : 'B'}: ${escapeHtml(item.filename)}</h3>
        <span class="score-grade">${escapeHtml(item.grade)}</span>
      </div>
      <img class="compare-img" src="/api/image/${item.id}">
      <div style="display:flex;justify-content:space-between;align-items:center;margin:16px 0;">
        <span style="font-weight:700;font-size:1.1rem">종합 점수</span>
        <strong style="font-size:2.2rem;color:var(--blue)">${item.final_score.toFixed(1)}<small style="font-size:0.9rem;color:var(--muted)"> / 10</small></strong>
      </div>
      <div class="mini-scores" style="font-size:0.84rem;padding:12px;">
        <div><span>구도</span><strong>${item.composition_score.toFixed(1)}</strong></div>
        <div><span>조명</span><strong>${item.lighting_score.toFixed(1)}</strong></div>
        <div><span>색감</span><strong>${item.color_score.toFixed(1)}</strong></div>
        <div><span>기술</span><strong>${item.technique_score.toFixed(1)}</strong></div>
      </div>
      <div class="final-reason-box" style="margin-bottom:12px;">
        <b>한줄 총평:</b> ${escapeHtml(item.final_reason)}
      </div>
      <div class="strengths-box">
        <h4>✓ 주요 장점</h4>
        <ul>${item.strengths.map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ul>
      </div>
      <div class="improvements-box" style="margin-top:8px;">
        <h4>✗ 단점 및 아쉬운 점</h4>
        <ul>${item.improvements.map(i => `<li>${escapeHtml(i)}</li>`).join('')}</ul>
      </div>
      ${item.cross_check_opinion ? `
        <div class="cross-check-compare-box">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
            <b class="cross-check-comp-title">🤝 OpenAI 크로스 체크 (${escapeHtml(item.cross_check_opinion.model || 'GPT-6 Luna')})</b>
            <strong class="cross-check-comp-score">${item.cross_check_opinion.score !== undefined && item.cross_check_opinion.score !== null ? Number(item.cross_check_opinion.score).toFixed(1) : '-'}점</strong>
          </div>
          <div class="cross-check-comp-reason">${escapeHtml(item.cross_check_opinion.reason)}</div>
        </div>
      ` : ''}
    </div>
  `).join('');
}

const VALID_EXTS = ['.jpg', '.jpeg', '.png', '.webp', '.mpo'];

function isImageFile(file) {
  if (!file || !file.name) return false;
  const name = file.name.toLowerCase();
  return VALID_EXTS.some(ext => name.endsWith(ext));
}

function handleDragOver(e) {
  e.preventDefault();
  e.stopPropagation();
  const dz = document.getElementById('drop-zone');
  if (dz) dz.classList.add('drag-over');
}

function handleDragLeave(e) {
  e.preventDefault();
  e.stopPropagation();
  const dz = document.getElementById('drop-zone');
  if (dz) dz.classList.remove('drag-over');
}

async function getFilesFromEntry(entry) {
  if (entry.isFile) {
    return new Promise((resolve) => {
      entry.file(f => resolve([f]), () => resolve([]));
    });
  } else if (entry.isDirectory) {
    const dirReader = entry.createReader();
    const entries = await new Promise((resolve) => {
      const all = [];
      function readEntries() {
        dirReader.readEntries(results => {
          if (!results.length) {
            resolve(all);
          } else {
            all.push(...results);
            readEntries();
          }
        }, () => resolve(all));
      }
      readEntries();
    });
    const subFiles = [];
    for (const child of entries) {
      const fList = await getFilesFromEntry(child);
      subFiles.push(...fList);
    }
    return subFiles;
  }
  return [];
}

function escapeUsageHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function openUsageModal() {
  document.getElementById('usage-modal').style.display = 'flex';
  await refreshUsageStats();
}

function closeUsageModal(e) {
  if (!e || e.target.id === 'usage-modal') {
    const m = document.getElementById('usage-modal');
    if (m) m.style.display = 'none';
  }
}

async function refreshUsageStats() {
  const body = document.getElementById('usage-body');
  body.innerHTML = '<p style="color:var(--muted);">불러오는 중...</p>';
  try {
    const d = await API.fetchUsageStats();
    if (!d.total_calls) {
      body.innerHTML = '<p style="color:var(--muted);">아직 기록된 API 호출이 없습니다. 사진을 분석하면 여기에 쌓입니다.</p>';
      return;
    }
    const sum = (k) => d.by_task.reduce((a, t) => a + (t[k] || 0), 0);
    const totalIn = sum('input_tokens');
    const totalOut = sum('output_tokens');
    const failures = d.by_task.reduce((a, t) => a + (t.calls - (t.successes || 0)), 0);
    const card = (label, value) => `<div style="background:rgba(148,163,184,0.12);border-radius:10px;padding:10px 14px;min-width:110px;"><div style="font-size:0.72rem;color:var(--muted);">${label}</div><div style="font-size:1.25rem;font-weight:800;">${value}</div></div>`;
    const th = 'text-align:left;padding:6px 8px;border-bottom:1px solid rgba(148,163,184,0.3);font-size:0.78rem;color:var(--muted);';
    const td = 'padding:6px 8px;border-bottom:1px solid rgba(148,163,184,0.15);font-size:0.82rem;';
    const fmtModelBadge = (m) => {
      const label = (window.ModelSettings && m) ? window.ModelSettings.formatBadge(m) : (m || '-');
      const isLuna = String(m || '').toLowerCase().includes('luna') || String(m || '').toLowerCase().includes('gpt');
      const bg = isLuna ? 'rgba(99,102,241,0.15)' : 'rgba(2,132,199,0.12)';
      const color = isLuna ? '#4f46e5' : '#0284c7';
      return `<span style="background:${bg};color:${color};padding:2px 7px;border-radius:999px;font-weight:700;font-size:0.75rem;">${escapeUsageHtml(label)}</span> <small style="color:var(--muted);font-size:0.72rem;">(${escapeUsageHtml(m)})</small>`;
    };
    const modelRows = (d.by_model || []).map(m => `<tr>
      <td style="${td}">${fmtModelBadge(m.used_model)}</td>
      <td style="${td}">${m.calls}</td>
      <td style="${td}">${m.calls - (m.successes || 0)}</td>
      <td style="${td}">${m.fallbacks || 0}</td>
      <td style="${td}">${(m.input_tokens || 0).toLocaleString()}</td>
      <td style="${td}">${(m.output_tokens || 0).toLocaleString()}</td>
      <td style="${td}">${((m.avg_ms || 0) / 1000).toFixed(1)}s</td>
    </tr>`).join('');
    const taskRows = d.by_task.map(t => `<tr>
      <td style="${td}">${escapeUsageHtml(t.task)}</td>
      <td style="${td}">${t.calls}</td>
      <td style="${td}">${t.calls - (t.successes || 0)}</td>
      <td style="${td}">${t.fallbacks || 0}</td>
      <td style="${td}">${t.retries || 0}</td>
      <td style="${td}">${(t.input_tokens || 0).toLocaleString()}</td>
      <td style="${td}">${(t.output_tokens || 0).toLocaleString()}</td>
      <td style="${td}">${((t.avg_ms || 0) / 1000).toFixed(1)}s</td>
    </tr>`).join('');
    const recentRows = d.recent.map(r => `<tr>
      <td style="${td}">${escapeUsageHtml((r.created_at || '').replace('T', ' ').slice(5, 19))}</td>
      <td style="${td}">${escapeUsageHtml(r.task)}</td>
      <td style="${td}">${fmtModelBadge(r.used_model)}${r.fallback ? ` <span style="color:#d97706;font-size:0.73rem;">(폴백: ${escapeUsageHtml(r.requested_model || '')}→)</span>` : ''}</td>
      <td style="${td}">${((r.duration_ms || 0) / 1000).toFixed(1)}s</td>
      <td style="${td}">${r.input_tokens == null ? '-' : r.input_tokens.toLocaleString()} / ${r.output_tokens == null ? '-' : r.output_tokens.toLocaleString()}</td>
      <td style="${td}color:${r.success ? 'var(--teal)' : '#e11d48'};" title="${escapeUsageHtml(r.error || '')}">${r.success ? '성공' : '실패'}</td>
    </tr>`).join('');
    body.innerHTML = `
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px;">
        ${card('총 호출', d.total_calls)}${card('실패', failures)}${card('입력 토큰', totalIn.toLocaleString())}${card('출력 토큰', totalOut.toLocaleString())}
      </div>
      ${modelRows ? `
        <h3 style="margin:0 0 6px;font-size:0.95rem;">🤖 모델별 사용량</h3>
        <table style="width:100%;border-collapse:collapse;margin-bottom:18px;">
          <thead><tr><th style="${th}">사용 모델</th><th style="${th}">호출</th><th style="${th}">실패</th><th style="${th}">폴백</th><th style="${th}">입력 tok</th><th style="${th}">출력 tok</th><th style="${th}">평균 시간</th></tr></thead>
          <tbody>${modelRows}</tbody>
        </table>
      ` : ''}
      <h3 style="margin:0 0 6px;font-size:0.95rem;">🛠️ 기능별 사용량</h3>
      <table style="width:100%;border-collapse:collapse;margin-bottom:18px;">
        <thead><tr><th style="${th}">작업</th><th style="${th}">호출</th><th style="${th}">실패</th><th style="${th}">폴백</th><th style="${th}">재시도</th><th style="${th}">입력 tok</th><th style="${th}">출력 tok</th><th style="${th}">평균 시간</th></tr></thead>
        <tbody>${taskRows}</tbody>
      </table>
      <h3 style="margin:0 0 6px;font-size:0.95rem;">🕒 최근 호출 (30건)</h3>
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr><th style="${th}">시각(UTC)</th><th style="${th}">작업</th><th style="${th}">모델</th><th style="${th}">소요</th><th style="${th}">입력/출력 tok</th><th style="${th}">결과</th></tr></thead>
        <tbody>${recentRows}</tbody>
      </table>`;
  } catch (err) {
    body.innerHTML = `<p style="color:#e11d48;">사용량을 불러오지 못했습니다: ${escapeUsageHtml(err.message)}</p>`;
  }
}

function openModelSettingsModal() {
  const modal = document.getElementById('model-settings-modal');
  if (!modal) return;
  const s = window.ModelSettings ? window.ModelSettings.load() : {
    photo_grading: 'standard',
    lightroom_advice: 'lite',
    sns_crop: 'lite',
    sns_caption: 'lite'
  };
  const gEl = document.getElementById('setting-model-grading');
  const lrEl = document.getElementById('setting-model-lr');
  const cropEl = document.getElementById('setting-model-crop');
  const capEl = document.getElementById('setting-model-caption');
  const statusEl = document.getElementById('model-settings-status');

  if (gEl) gEl.value = s.photo_grading || 'standard';
  if (lrEl) lrEl.value = s.lightroom_advice || 'lite';
  if (cropEl) cropEl.value = s.sns_crop || 'lite';
  if (capEl) capEl.value = s.sns_caption || 'lite';
  if (statusEl) statusEl.textContent = '';

  modal.style.display = 'flex';
}

function closeModelSettingsModal(e) {
  if (!e || e.target.id === 'model-settings-modal') {
    const modal = document.getElementById('model-settings-modal');
    if (modal) modal.style.display = 'none';
  }
}

function applyModelPreset(presetKey) {
  const presets = {
    speed: { photo_grading: 'lite', lightroom_advice: 'lite', sns_crop: 'lite', sns_caption: 'lite' },
    balanced: { photo_grading: 'standard', lightroom_advice: 'lite', sns_crop: 'lite', sns_caption: 'lite' },
    luna_all: { photo_grading: 'ensemble', lightroom_advice: 'luna', sns_crop: 'luna', sns_caption: 'luna' },
    pro_all: { photo_grading: 'pro', lightroom_advice: 'pro', sns_crop: 'pro', sns_caption: 'pro' }
  };
  const p = presets[presetKey];
  if (!p) return;
  const gEl = document.getElementById('setting-model-grading');
  const lrEl = document.getElementById('setting-model-lr');
  const cropEl = document.getElementById('setting-model-crop');
  const capEl = document.getElementById('setting-model-caption');
  if (gEl) gEl.value = p.photo_grading;
  if (lrEl) lrEl.value = p.lightroom_advice;
  if (cropEl) cropEl.value = p.sns_crop;
  if (capEl) capEl.value = p.sns_caption;

  const statusEl = document.getElementById('model-settings-status');
  if (statusEl) {
    statusEl.textContent = '✨ 프리셋이 선택되었습니다. [설정 저장 및 적용]을 눌러 확정하세요.';
  }
}

function saveModelSettingsFromModal() {
  const gEl = document.getElementById('setting-model-grading');
  const lrEl = document.getElementById('setting-model-lr');
  const cropEl = document.getElementById('setting-model-crop');
  const capEl = document.getElementById('setting-model-caption');

  const newSettings = {
    photo_grading: gEl ? gEl.value : 'standard',
    lightroom_advice: lrEl ? lrEl.value : 'lite',
    sns_crop: cropEl ? cropEl.value : 'lite',
    sns_caption: capEl ? capEl.value : 'lite'
  };

  if (window.ModelSettings) {
    window.ModelSettings.save(newSettings);
  }

  // Sync upload modal tier if present
  const uploadTierEl = document.getElementById('upload-tier');
  if (uploadTierEl) {
    uploadTierEl.value = newSettings.photo_grading;
  }

  // Sync any open inline selectors in detail modal
  document.querySelectorAll('[id^="lr-model-select-"]').forEach(el => {
    el.value = newSettings.lightroom_advice;
  });
  document.querySelectorAll('[id^="sns-crop-model-select-"]').forEach(el => {
    el.value = newSettings.sns_crop;
  });
  document.querySelectorAll('[id^="sns-caption-model-select-"]').forEach(el => {
    el.value = newSettings.sns_caption;
  });

  const statusEl = document.getElementById('model-settings-status');
  if (statusEl) {
    statusEl.textContent = '✓ 작업별 AI 모델 설정이 저장 및 적용되었습니다!';
  }
  setTimeout(() => {
    closeModelSettingsModal();
  }, 550);
}

let isBatchUploading = false;

function openUploadModal() {
  document.getElementById('upload-modal').style.display = 'flex';
  const uploadTierEl = document.getElementById('upload-tier');
  if (uploadTierEl && window.ModelSettings) {
    uploadTierEl.value = window.ModelSettings.get('photo_grading');
  }
  document.getElementById('upload-status').textContent = '';
  document.getElementById('progress-container').style.display = 'none';
  document.getElementById('progress-bar').style.width = '0%';
  document.getElementById('progress-percent').textContent = '0%';
  document.getElementById('progress-text').textContent = '';
  document.getElementById('progress-current-file').textContent = '';
  const forceBox = document.getElementById('upload-force');
  if (forceBox) forceBox.checked = false;
  // reset file inputs
  const mInput = document.getElementById('file-input-multi');
  if (mInput) mInput.value = '';
  const fInput = document.getElementById('folder-input');
  if (fInput) fInput.value = '';
}

function closeUploadModal(e) {
  if (isBatchUploading) {
    if (!confirm('현재 사진 분석이 진행 중입니다. 닫으시겠습니까? (백그라운드에서 분석은 계속됩니다)')) return;
  }
  if (!e || e.target.id === 'upload-modal') {
    document.getElementById('upload-modal').style.display = 'none';
  }
}

async function handleFilesSelect(fileList) {
  if (!fileList || fileList.length === 0 || isBatchUploading) return;
  const files = Array.from(fileList).filter(isImageFile);
  if (files.length === 0) {
    alert('선택된 항목에 지원하는 사진 파일(JPG, PNG, WEBP, MPO)이 없습니다.');
    return;
  }
  await processBatchUpload(files);
}

async function handleDrop(e) {
  e.preventDefault();
  e.stopPropagation();
  const dz = document.getElementById('drop-zone');
  if (dz) dz.classList.remove('drag-over');
  if (isBatchUploading) return;

  let collected = [];
  const items = e.dataTransfer.items;
  if (items && items.length > 0 && items[0].webkitGetAsEntry) {
    for (let i = 0; i < items.length; i++) {
      const entry = items[i].webkitGetAsEntry();
      if (entry) {
        const fList = await getFilesFromEntry(entry);
        collected.push(...fList);
      }
    }
  } else if (e.dataTransfer.files) {
    collected = Array.from(e.dataTransfer.files);
  }

  const validFiles = collected.filter(isImageFile);
  if (validFiles.length === 0) {
    alert('드롭된 항목에 지원하는 사진 파일(JPG, PNG, WEBP, MPO)이 없습니다.');
    return;
  }
  await processBatchUpload(validFiles);
}

async function processBatchUpload(files) {
  isBatchUploading = true;
  const tier = document.getElementById('upload-tier').value;
  const category = document.getElementById('upload-category').value;
  const force = document.getElementById('upload-force').checked;
  const progContainer = document.getElementById('progress-container');
  const progText = document.getElementById('progress-text');
  const progPercent = document.getElementById('progress-percent');
  const progBar = document.getElementById('progress-bar');
  const progFile = document.getElementById('progress-current-file');
  const status = document.getElementById('upload-status');

  progContainer.style.display = 'block';
  status.textContent = '';
  
  const total = files.length;
  let successCount = 0;
  let failCount = 0;

  for (let i = 0; i < total; i++) {
    const file = files[i];
    const currentNum = i + 1;
    const pct = Math.round(((i) / total) * 100);
    progPercent.textContent = `${pct}%`;
    progBar.style.width = `${pct}%`;
    progText.textContent = `[${currentNum} / ${total}장] AI 모델 분석 진행 중...`;
    progFile.textContent = `현재 분석 파일: ${file.name} (${(file.size / 1024 / 1024).toFixed(1)}MB)`;

    const formData = new FormData();
    formData.append('image', file, file.name);
    formData.append('tier', tier);
    formData.append('category', category);

    try {
      const result = await API.uploadPhoto(formData, force);
      if (result.success) {
        successCount++;
        const dupNote = result.duplicate ? ' (이미 분석된 사진 - API 호출 생략)' : '';
        status.textContent = `✓ [${currentNum}/${total}] ${file.name} 완료${dupNote} (${result.analysis.final_score.toFixed(1)}점 - ${result.analysis.figure_category})`;
        status.style.color = 'var(--teal)';
      } else {
        failCount++;
        status.textContent = `✗ [${currentNum}/${total}] ${file.name} 실패: ${result.error || '오류'}`;
        status.style.color = '#e11d48';
      }
    } catch (err) {
      failCount++;
      status.textContent = `✗ [${currentNum}/${total}] ${file.name} 전송 오류: ${err.message}`;
      status.style.color = '#e11d48';
    }
  }

  progPercent.textContent = '100%';
  progBar.style.width = '100%';
  progText.textContent = '모든 분석이 완료되었습니다!';
  progFile.textContent = '';
  
  status.textContent = `🎉 총 ${total}장 중 ${successCount}장 분석 성공${failCount > 0 ? `, ${failCount}장 실패` : ''}`;
  status.style.color = successCount > 0 ? 'var(--teal)' : '#e11d48';

  setTimeout(() => {
    isBatchUploading = false;
    closeUploadModal();
    loadData();
  }, 1500);
}

window.addEventListener('DOMContentLoaded', () => {
  initTheme();
  loadData();
});

