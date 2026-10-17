// static/js/reanalyze.js - Photo Re-analysis & Additional Model Evaluations

function _escapeReanalyzeHtml(str) {
  if (typeof escapeHtml === 'function') return escapeHtml(str);
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
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
  const savedTier = (window.ModelSettings && window.ModelSettings.get('photo_grading')) || 'standard';
  const currentModelBadge = (window.ModelSettings && item.model)
    ? window.ModelSettings.formatBadge(item.model)
    : (item.model || '알 수 없음');

  return `
    <div class="reanalyze-panel-inner">
      <div class="reanalyze-header">
        <div class="reanalyze-title">
          <span>🔄</span>
          <strong>사진 AI 재평가 및 추가 분석</strong>
        </div>
        <button class="reanalyze-close-btn" title="닫기" onclick="toggleReanalyzePanel(${item.id})">&times;</button>
      </div>
      <div style="background:rgba(99,102,241,0.08);border:1px solid rgba(99,102,241,0.24);border-radius:8px;padding:7px 12px;margin-bottom:10px;font-size:0.79rem;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px;">
        <span>📌 <b>현재 평가 모델:</b> <strong style="color:#4f46e5;">${_escapeReanalyzeHtml(currentModelBadge)}</strong> <small style="color:var(--muted);">(${_escapeReanalyzeHtml(item.model || '-')})</small></span>
        <span><b>현재 종합 점수:</b> <strong style="color:var(--blue);font-size:0.88rem;">${Number(item.final_score || 0).toFixed(1)}점</strong></span>
      </div>
      <p class="reanalyze-desc">
        원하는 분석 방식을 선택하세요. 전체 재평가를 선택하면 종합 점수와 평가 모델 표시가 선택한 모델로 즉시 갱신됩니다.
      </p>

      <div class="reanalyze-modes">
        <div class="reanalyze-mode-card selected" onclick="selectReanalyzeMode(${item.id}, 'full')">
          <input type="radio" name="reanalyze-mode-${item.id}" value="full" checked onchange="selectReanalyzeMode(${item.id}, 'full')">
          <div class="reanalyze-mode-content">
            <div class="reanalyze-mode-badge-wrap">
              <span class="reanalyze-mode-badge mode-full">⚙️ 모델 변경 / 새 프롬프트 전체 재평가 (권장)</span>
            </div>
            <strong class="reanalyze-mode-title">선택한 AI 모델로 전면 재평가 (점수·모델 즉시 갱신)</strong>
            <p class="reanalyze-mode-text">
              종합 점수, 4대 세부 점수, 총평 코멘트, 스타일 태그, 평가 모델 표시를 선택한 모델과 최신 프롬프트로 완전히 새로 생성하여 덮어씁니다.
            </p>

            <div id="reanalyze-tier-wrap-${item.id}" class="reanalyze-tier-select-wrap" onclick="event.stopPropagation()">
              <label class="reanalyze-sublabel" for="reanalyze-tier-${item.id}">적용할 분석 모델 선택:</label>
              <select id="reanalyze-tier-${item.id}" class="select-input reanalyze-select" onclick="event.stopPropagation()" onchange="event.stopPropagation(); if(window.ModelSettings) window.ModelSettings.set('photo_grading', this.value);">
                <option value="standard" ${savedTier === 'standard' ? 'selected' : ''}>🔍 Gemini Flash-Lite 3.5 (균형 잡힌 표준 화질 평가 - 권장)</option>
                <option value="lite" ${savedTier === 'lite' ? 'selected' : ''}>⚡ Gemini Flash-Lite 3.1 (초고속 스크리닝)</option>
                <option value="flash-3.6" ${savedTier === 'flash-3.6' ? 'selected' : ''}>🧪 Gemini Flash 3.6 (실험적 고성능)</option>
                <option value="flash-3.7" ${savedTier === 'flash-3.7' ? 'selected' : ''}>🚀 Gemini Flash 3.7 (차세대 고속 비평)</option>
                <option value="pro" ${savedTier === 'pro' ? 'selected' : ''}>💎 Gemini Flash 3.8 (고화질 디테일 심층 비평)</option>
                <option value="ensemble" ${savedTier === 'ensemble' ? 'selected' : ''}>🤝 앙상블: Flash-Lite 3.5 + GPT-6 Luna 크로스체크</option>
                <option value="ensemble-3.7" ${savedTier === 'ensemble-3.7' ? 'selected' : ''}>🤝 앙상블: Flash 3.7 + GPT-6 Luna 크로스체크</option>
                <option value="ensemble-pro" ${savedTier === 'ensemble-pro' ? 'selected' : ''}>🤝 앙상블: Flash 3.8 (Pro) + GPT-6 Luna 크로스체크</option>
              </select>
            </div>
          </div>
        </div>

        <div class="reanalyze-mode-card" onclick="selectReanalyzeMode(${item.id}, 'cross_check_only')">
          <input type="radio" name="reanalyze-mode-${item.id}" value="cross_check_only" onchange="selectReanalyzeMode(${item.id}, 'cross_check_only')">
          <div class="reanalyze-mode-content">
            <div class="reanalyze-mode-badge-wrap">
              <span class="reanalyze-mode-badge mode-luna">🤝 GPT-6 Luna 보조 의견만 단독 추가</span>
              <span class="reanalyze-token-tag">⚡ 본 점수·모델 유지</span>
            </div>
            <strong class="reanalyze-mode-title">${hasLuna ? 'Luna 크로스체크 의견만 다시 생성' : 'OpenAI 크로스체크 비평만 추가 (본 점수 유지)'}</strong>
            <p class="reanalyze-mode-text">
              ⚠️ 주의: 이 모드는 Gemini의 기존 종합 점수(${Number(item.final_score || 0).toFixed(1)}점)와 주 분석 모델을 변경하지 않고 그대로 보존하며, 하단의 GPT-6 Luna 보조 비평 박스만 갱신합니다.
            </p>
          </div>
        </div>
      </div>

      <div class="reanalyze-category-row">
        <label class="reanalyze-sublabel" for="reanalyze-category-${item.id}">피규어 촬영 세부 유형:</label>
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
  const mode = modeRadio ? modeRadio.value : 'full';

  const tierSelect = document.getElementById(`reanalyze-tier-${id}`);
  const tier = tierSelect ? tierSelect.value : 'standard';

  const catSelect = document.getElementById(`reanalyze-category-${id}`);
  const category = catSelect ? catSelect.value : 'auto';

  const submitBtn = document.getElementById(`reanalyze-submit-btn-${id}`);
  const statusEl = document.getElementById(`reanalyze-status-${id}`);

  const initialList = (typeof allData !== 'undefined' && Array.isArray(allData)) ? allData : (window.allData || []);
  const beforeItem = initialList.find(d => d.id === id);
  const prevScore = beforeItem ? Number(beforeItem.final_score) : null;
  const prevModel = beforeItem ? beforeItem.model : null;
  const prevLunaScore = (beforeItem && beforeItem.cross_check_opinion && beforeItem.cross_check_opinion.score != null)
    ? Number(beforeItem.cross_check_opinion.score)
    : null;

  if (submitBtn) submitBtn.disabled = true;
  if (statusEl) {
    statusEl.style.display = 'block';
    const chosenLabel = tierSelect && tierSelect.selectedOptions && tierSelect.selectedOptions[0]
      ? tierSelect.selectedOptions[0].textContent
      : tier;
    const modeName = mode === 'cross_check_only'
      ? 'OpenAI GPT-6 Luna 크로스체크 단독'
      : `AI 전체 재평가 (${_escapeReanalyzeHtml(chosenLabel)})`;
    statusEl.innerHTML = `⏳ <b>${modeName}</b> 실행 중... (단독 모델 약 5~10초, 앙상블 약 10~25초 소요)`;
  }

  try {
    const res = await API.reanalyzePhoto(id, mode, tier, category);
    if (!res || !res.success) {
      throw new Error((res && res.error) || '알 수 없는 오류');
    }

    // Refresh entire analysis dataset to update rankings, clusters and stats
    if (typeof loadData === 'function') {
      await loadData();
    }

    // Explicitly synchronize returned analysis fields into allData so score & model are 100% up-to-date
    const dataList = (typeof allData !== 'undefined' && Array.isArray(allData)) ? allData : (window.allData || []);
    const targetItem = dataList.find(d => d.id === id);
    if (targetItem && res.analysis) {
      Object.assign(targetItem, res.analysis);
      if (!targetItem.created_at) {
        targetItem.created_at = new Date().toISOString();
      }
      if (typeof updateStats === 'function') updateStats();
      if (typeof renderScoreDistPanel === 'function') renderScoreDistPanel();
      if (typeof renderGallery === 'function') renderGallery();
    }

    const updatedAnalysis = res.analysis || targetItem || {};
    window._lastReanalyzeDiff = {
      id: id,
      mode: mode,
      prevScore: prevScore,
      newScore: updatedAnalysis.final_score != null ? Number(updatedAnalysis.final_score) : prevScore,
      prevModel: prevModel,
      newModel: updatedAnalysis.model || prevModel,
      prevLunaScore: prevLunaScore,
      newLunaScore: (updatedAnalysis.cross_check_opinion && updatedAnalysis.cross_check_opinion.score != null)
        ? Number(updatedAnalysis.cross_check_opinion.score)
        : null,
      timestamp: Date.now()
    };

    // Re-open detail modal to show freshly evaluated state and verification banner
    if (typeof openDetailModal === 'function') {
      openDetailModal(id);
    }
  } catch (err) {
    if (statusEl) {
      statusEl.style.display = 'block';
      statusEl.innerHTML = `<span style="color:#ef4444;">❌ 재평가 실패: ${_escapeReanalyzeHtml(err.message)}</span>`;
    }
    if (submitBtn) submitBtn.disabled = false;
  }
}

// Global scope export
window.getCategoryKeyFromTitle = getCategoryKeyFromTitle;
window.toggleReanalyzePanel = toggleReanalyzePanel;
window.selectReanalyzeMode = selectReanalyzeMode;
window.renderReanalyzePanel = renderReanalyzePanel;
window.executeReanalyze = executeReanalyze;
