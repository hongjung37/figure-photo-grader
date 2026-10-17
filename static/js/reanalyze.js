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
    if (typeof loadData === 'function') {
      await loadData();
    }

    // Re-open detail modal to show freshly evaluated state
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
