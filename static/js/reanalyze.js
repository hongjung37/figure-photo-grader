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
  const samplingWrap = document.getElementById(`reanalyze-sampling-wrap-${id}`);
  if (samplingWrap) {
    samplingWrap.style.display = (mode === 'full') ? 'block' : 'none';
  }
}

function renderReanalyzePanel(item) {
  const currentCategoryKey = getCategoryKeyFromTitle(item.figure_category);
  const mainModel = (item.model || '').toLowerCase();
  const isMainOpenAI = mainModel.startsWith('gpt') || mainModel.includes('luna');
  const counterpartProv = isMainOpenAI ? 'Gemini' : 'OpenAI';
  const counterpartModelName = isMainOpenAI ? 'Flash-Lite 3.5' : 'GPT-6 Luna';
  const mainProv = isMainOpenAI ? 'OpenAI' : 'Gemini';
  const hasCrossCheck = Boolean(item.cross_check_opinion);
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
                <option value="luna" ${savedTier === 'luna' ? 'selected' : ''}>🌙 OpenAI GPT-6 Luna (최고 정확도 엄격 심사 - 추천)</option>
                <option value="standard" ${savedTier === 'standard' ? 'selected' : ''}>🔍 Gemini Flash-Lite 3.5 (균형 잡힌 표준 화질 평가)</option>
                <option value="lite" ${savedTier === 'lite' ? 'selected' : ''}>⚡ Gemini Flash-Lite 3.1 (초고속 스크리닝)</option>
                <option value="pro" ${savedTier === 'pro' ? 'selected' : ''}>💎 Gemini Flash 3.8 (고화질 디테일 심층 비평)</option>
                <option value="hydrogen" ${savedTier === 'hydrogen' ? 'selected' : ''}>⚛️ Gemini 4 Hydrogen (차세대 고속·고정밀 분석)</option>
                <option value="ensemble" ${savedTier === 'ensemble' ? 'selected' : ''}>🤝 앙상블: Flash-Lite 3.5 + GPT-6 Luna 크로스체크</option>
                <option value="ensemble-pro" ${savedTier === 'ensemble-pro' ? 'selected' : ''}>🤝 앙상블: Flash 3.8 (Pro) + GPT-6 Luna 크로스체크</option>
                <option value="ensemble-hydrogen" ${savedTier === 'ensemble-hydrogen' ? 'selected' : ''}>🤝 앙상블: 4 Hydrogen + GPT-6 Luna 크로스체크</option>
              </select>

              <label class="reanalyze-sublabel" for="reanalyze-depth-${item.id}" style="margin-top:8px;display:block;">분석 깊이 (모드):</label>
              <select id="reanalyze-depth-${item.id}" class="select-input reanalyze-select" onclick="event.stopPropagation()">
                <option value="full" selected>🔍 정밀 분석 (장단점 · 4대 영역 노트 · 8대 미학 태그 전체)</option>
                <option value="fast">⚡ 경량 분석 (5대 점수 · 초점 판정 · 1줄 핵심 사유만 빠르게)</option>
              </select>
            </div>
          </div>
        </div>

        <div class="reanalyze-mode-card" onclick="selectReanalyzeMode(${item.id}, 'cross_check_only')">
          <input type="radio" name="reanalyze-mode-${item.id}" value="cross_check_only" onchange="selectReanalyzeMode(${item.id}, 'cross_check_only')">
          <div class="reanalyze-mode-content">
            <div class="reanalyze-mode-badge-wrap">
              <span class="reanalyze-mode-badge mode-luna">🤝 ${counterpartProv} ${counterpartModelName} 보조 의견 (경량)</span>
              <span class="reanalyze-token-tag">⚡ 본 점수·모델 유지</span>
            </div>
            <strong class="reanalyze-mode-title">${hasCrossCheck ? `${counterpartProv} 크로스체크 의견 갱신 (경량)` : `${counterpartProv} 크로스체크 비평 추가 (경량)`}</strong>
            <p class="reanalyze-mode-text">
              주 평가(${mainProv} ${Number(item.final_score || 0).toFixed(1)}점)와 주 모델을 변경하지 않고 보존하며, 상대 모델인 <b>${counterpartProv} ${counterpartModelName}</b>의 독립된 경량 비평 및 4대 세부 점수만 약 1~4초 만에 빠르게 갱신합니다.
            </p>
          </div>
        </div>
      </div>

      <div class="reanalyze-category-row">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
          <label class="reanalyze-sublabel" for="reanalyze-category-${item.id}" style="margin:0;">피규어 촬영 세부 유형:</label>
          ${item.figure_category ? `<span style="font-size:0.75rem;color:var(--muted);">현재 판정: <b>${_escapeReanalyzeHtml(item.figure_category)}</b></span>` : ''}
        </div>
        <select id="reanalyze-category-${item.id}" class="select-input reanalyze-select">
          <option value="auto" selected>자동 판별 (사진 분석으로 자동 분류 - 캐시 최적화 권장)</option>
          <option value="general">📷 일반 피규어 촬영 (기본 전시/조형 중심)</option>
          <option value="macro">🔍 접사/디테일 (도색, 접합선, 데칼 초점 심사)</option>
          <option value="snap">🌿 일상/야외 스냅 (배경 조화, 자연광, 생활감 심사)</option>
          <option value="staging">🎬 스튜디오 연출/디오라마 (드라마틱 조명, 콘트라스트)</option>
        </select>
      </div>

      <div id="reanalyze-sampling-wrap-${item.id}" class="reanalyze-sampling-wrap" style="margin-top: 10px; padding: 9px 12px; background: rgba(99,102,241,0.06); border: 1px dashed rgba(99,102,241,0.32); border-radius: 8px;">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:0.83rem;font-weight:600;color:var(--text);user-select:none;margin:0;">
            <input type="checkbox" id="reanalyze-median-${item.id}" ${(window.ModelSettings && window.ModelSettings.get('median_sampling') === 'true') ? 'checked' : ''} style="width:16px;height:16px;accent-color:#4f46e5;cursor:pointer;" onchange="if(window.ModelSettings) window.ModelSettings.set('median_sampling', this.checked ? 'true' : 'false');">
            <span>🎯 병렬 채점 후 중앙값(Median) 채택</span>
          </label>
          <select id="reanalyze-sample-count-${item.id}" class="select-input" style="padding:2px 8px;font-size:0.75rem;height:auto;width:auto;" onclick="event.stopPropagation();">
            <option value="3" selected>3회 병렬 (권장)</option>
            <option value="5">🔥 5회 병렬 (초정밀)</option>
          </select>
        </div>
        <div style="font-size:0.75rem;color:var(--muted);margin-top:3px;padding-left:24px;line-height:1.4;">
          동일 사진을 여러 번 동시 병렬 채점하여 단발성 튀는 점수(Outlier)를 배제하고 가장 신뢰도 높은 중앙값 분석을 저장합니다.
        </div>
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

  const depthSelect = document.getElementById(`reanalyze-depth-${id}`);
  const analysisMode = (depthSelect && depthSelect.value === 'fast') ? 'fast' : 'full';

  const catSelect = document.getElementById(`reanalyze-category-${id}`);
  const category = catSelect ? catSelect.value : 'auto';

  const medianCheckbox = document.getElementById(`reanalyze-median-${id}`);
  const sampleSelect = document.getElementById(`reanalyze-sample-count-${id}`);
  const chosenSampleCount = sampleSelect ? (parseInt(sampleSelect.value, 10) || 3) : 3;
  const sampleCount = (medianCheckbox && medianCheckbox.checked && mode === 'full') ? chosenSampleCount : 1;

  const submitBtn = document.getElementById(`reanalyze-submit-btn-${id}`);
  const statusEl = document.getElementById(`reanalyze-status-${id}`);

  const initialList = (typeof allData !== 'undefined' && Array.isArray(allData)) ? allData : (window.allData || []);
  const beforeItem = initialList.find(d => d.id === id);
  const prevScore = beforeItem ? Number(beforeItem.final_score) : null;
  const prevModel = beforeItem ? beforeItem.model : null;
  const prevLunaScore = (beforeItem && beforeItem.cross_check_opinion && beforeItem.cross_check_opinion.score != null)
    ? Number(beforeItem.cross_check_opinion.score)
    : null;

  const mainModel = ((beforeItem && beforeItem.model) || '').toLowerCase();
  const isMainOpenAI = mainModel.startsWith('gpt') || mainModel.includes('luna');
  const counterpartProv = isMainOpenAI ? 'Gemini' : 'OpenAI';
  const counterpartModelName = isMainOpenAI ? 'Flash-Lite 3.5' : 'GPT-6 Luna';

  if (submitBtn) submitBtn.disabled = true;
  if (statusEl) {
    statusEl.style.display = 'block';
    const chosenLabel = tierSelect && tierSelect.selectedOptions && tierSelect.selectedOptions[0]
      ? tierSelect.selectedOptions[0].textContent
      : tier;
    const depthLabel = analysisMode === 'fast' ? '⚡ 경량 재평가' : '🔍 정밀 재평가';
    const modeName = mode === 'cross_check_only'
      ? `${counterpartProv} ${counterpartModelName} 크로스체크 단독 (경량)`
      : `AI ${depthLabel} (${_escapeReanalyzeHtml(chosenLabel)})`;
    const samplingText = (sampleCount > 1 && mode === 'full') ? ' [🎯 3회 중앙값 정밀 채점]' : '';
    statusEl.innerHTML = `⏳ <b>${modeName}${samplingText}</b> 실행 중... (경량 크로스체크 약 1~4초 소요)`;
  }

  try {
    const res = await API.reanalyzePhoto(id, mode, tier, category, sampleCount, analysisMode);
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
      sampledScores: (Array.isArray(res.sampled_scores) && res.sampled_scores.length) ? res.sampled_scores : null,
      medianScore: res.median_score != null ? Number(res.median_score) : null,
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

async function upgradeFastToFullAnalysis(id, btn) {
  const initialList = (typeof allData !== 'undefined' && Array.isArray(allData)) ? allData : (window.allData || []);
  const beforeItem = initialList.find(d => d.id === id);
  const tier = (beforeItem && beforeItem.model)
    ? beforeItem.model
    : ((window.ModelSettings && window.ModelSettings.get('photo_grading')) || 'luna');
  const category = beforeItem ? getCategoryKeyFromTitle(beforeItem.figure_category) : 'auto';
  const prevScore = beforeItem ? Number(beforeItem.final_score) : null;
  const prevModel = beforeItem ? beforeItem.model : null;

  const origText = btn ? btn.innerHTML : '';
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '⏳ 정밀(Full) 분석 업그레이드 중... (약 5~10초)';
  }
  try {
    const res = await API.reanalyzePhoto(id, 'full', tier, category, 1, 'full');
    if (!res || !res.success) {
      throw new Error((res && res.error) || '알 수 없는 오류');
    }
    if (typeof loadData === 'function') {
      await loadData();
    }
    const dataList = (typeof allData !== 'undefined' && Array.isArray(allData)) ? allData : (window.allData || []);
    const targetItem = dataList.find(d => d.id === id);
    if (targetItem && res.analysis) {
      Object.assign(targetItem, res.analysis);
      if (typeof updateStats === 'function') updateStats();
      if (typeof renderScoreDistPanel === 'function') renderScoreDistPanel();
      if (typeof renderGallery === 'function') renderGallery();
    }
    const updatedAnalysis = res.analysis || targetItem || {};
    window._lastReanalyzeDiff = {
      id: id,
      mode: 'full',
      prevScore: prevScore,
      newScore: updatedAnalysis.final_score != null ? Number(updatedAnalysis.final_score) : prevScore,
      prevModel: prevModel,
      newModel: updatedAnalysis.model || prevModel,
      timestamp: Date.now()
    };
    if (typeof openDetailModal === 'function') {
      openDetailModal(id);
    }
  } catch (err) {
    alert(`정밀 분석 업그레이드 실패: ${err.message}`);
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origText;
    }
  }
}

// Global scope export
window.getCategoryKeyFromTitle = getCategoryKeyFromTitle;
window.toggleReanalyzePanel = toggleReanalyzePanel;
window.selectReanalyzeMode = selectReanalyzeMode;
window.renderReanalyzePanel = renderReanalyzePanel;
window.executeReanalyze = executeReanalyze;

// --- Batch Photo Re-analysis ---
let _batchReanalyzeCancelled = false;
let _batchReanalyzeResults = [];
let _batchReanalyzeMode = 'full';

function selectBatchOperationMode(mode) {
  const isCc = (mode === 'cross_check_only');
  _batchReanalyzeMode = isCc ? 'cross_check_only' : 'full';
  const cardFull = document.getElementById('batch-mode-card-full');
  const cardCc = document.getElementById('batch-mode-card-cc');
  const radFull = document.getElementById('batch-op-mode-full');
  const radCc = document.getElementById('batch-op-mode-cc');
  const secFull = document.getElementById('batch-reanalyze-full-settings');
  const secCc = document.getElementById('batch-reanalyze-cc-settings');
  const startBtn = document.getElementById('btn-batch-reanalyze-start');

  if (cardFull) cardFull.classList.toggle('selected', !isCc);
  if (cardCc) cardCc.classList.toggle('selected', isCc);
  if (radFull) radFull.checked = !isCc;
  if (radCc) radCc.checked = isCc;

  if (secFull) secFull.style.display = isCc ? 'none' : 'block';
  if (secCc) secCc.style.display = isCc ? 'block' : 'none';

  if (startBtn) {
    if (isCc) {
      startBtn.innerHTML = '🤝 크로스체크 일괄 채워넣기 시작';
      startBtn.style.background = '#0284c7';
    } else {
      startBtn.innerHTML = '🚀 일괄 재평가 시작';
      startBtn.style.background = '#0d9488';
    }
  }
}

function updateBatchReanalyzeSkipCount() {
  const batchIds = (typeof selectedBatchIds !== 'undefined') ? selectedBatchIds : (window.selectedBatchIds || new Set());
  const dataList = (typeof allData !== 'undefined' ? allData : (window.allData || []));
  const items = dataList.filter(it => batchIds.has(Number(it.id)));
  const hasCcCount = items.filter(it => Boolean(it.cross_check_opinion)).length;
  const missingCcCount = items.length - hasCcCount;
  const skipBadge = document.getElementById('batch-reanalyze-skip-cc-badge');
  const checkbox = document.getElementById('batch-reanalyze-skip-existing-cc');
  if (skipBadge) {
    if (checkbox && !checkbox.checked) {
      skipBadge.textContent = `전체 ${items.length}장 덮어쓰기 생성`;
      skipBadge.style.background = '#fef3c7';
      skipBadge.style.color = '#b45309';
    } else {
      if (missingCcCount === 0) {
        skipBadge.textContent = `모든 사진에 이미 보유 중 (${hasCcCount}장 건너뜀)`;
      } else if (hasCcCount === 0) {
        skipBadge.textContent = `전체 ${missingCcCount}장 신규 생성`;
      } else {
        skipBadge.textContent = `미보유 ${missingCcCount}장 채우기 (기보유 ${hasCcCount}장 건너뜀)`;
      }
      skipBadge.style.background = '#e0f2fe';
      skipBadge.style.color = '#0369a1';
    }
  }
}

function openBatchReanalyzeModal() {
  const batchIds = (typeof selectedBatchIds !== 'undefined') ? selectedBatchIds : (window.selectedBatchIds || new Set());
  if (!batchIds || batchIds.size === 0) {
    alert('일괄 재평가할 사진을 1장 이상 선택해 주세요.');
    return;
  }
  const modal = document.getElementById('batch-reanalyze-modal');
  if (!modal) return;

  const count = batchIds.size;
  const countEl = document.getElementById('batch-reanalyze-target-count');
  if (countEl) countEl.textContent = String(count);

  const prevCountEl = document.getElementById('batch-reanalyze-preview-count');
  if (prevCountEl) prevCountEl.textContent = `총 ${count}장`;

  // Render preview strip
  const strip = document.getElementById('batch-reanalyze-preview-strip');
  if (strip) {
    const dataList = (typeof allData !== 'undefined' ? allData : (window.allData || []));
    const items = dataList.filter(it => batchIds.has(Number(it.id)));
    strip.innerHTML = items.map(it => {
      const score = (it.final_score != null) ? Number(it.final_score).toFixed(1) : '-';
      const mBadge = (window.ModelSettings && it.model) ? window.ModelSettings.formatBadge(it.model) : (it.model || '');
      const ccBadge = it.cross_check_opinion
        ? `<span style="font-size:0.65rem;background:rgba(2,132,199,0.12);color:#0284c7;padding:1px 4px;border-radius:3px;">🤝${Number(it.cross_check_opinion.score).toFixed(1)}</span>`
        : '';
      return `
        <div style="flex:0 0 160px;background:var(--card-bg, #fff);border:1px solid var(--line, #cbd5e1);border-radius:8px;padding:6px;display:flex;gap:8px;align-items:center;">
          <img src="/api/image/${it.id}" style="width:48px;height:48px;object-fit:cover;border-radius:6px;background:#0f172a;flex-shrink:0;">
          <div style="overflow:hidden;flex:1;">
            <div style="font-weight:700;font-size:0.75rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" title="${_escapeReanalyzeHtml(it.filename)}">${_escapeReanalyzeHtml(it.filename)}</div>
            <div style="display:flex;align-items:center;gap:4px;margin-top:2px;flex-wrap:wrap;">
              <span style="font-size:0.75rem;font-weight:800;color:var(--blue);">${score}점</span>
              ${mBadge ? `<span style="font-size:0.68rem;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${_escapeReanalyzeHtml(mBadge)}</span>` : ''}
              ${ccBadge}
            </div>
          </div>
        </div>
      `;
    }).join('');

    updateBatchReanalyzeSkipCount();
  }

  // Set default model from ModelSettings
  const savedTier = (window.ModelSettings && window.ModelSettings.get('photo_grading')) || 'standard';
  const tierSelect = document.getElementById('batch-reanalyze-tier');
  if (tierSelect && Array.from(tierSelect.options).some(o => o.value === savedTier)) {
    tierSelect.value = savedTier;
  }

  // Median checkbox default
  const medianBox = document.getElementById('batch-reanalyze-median');
  if (medianBox && window.ModelSettings) {
    medianBox.checked = (window.ModelSettings.get('median_sampling') !== 'false');
  }

  // Default operation mode to 'full'
  selectBatchOperationMode('full');

  // Reset sections
  const secConfig = document.getElementById('batch-reanalyze-config-section');
  const secProg = document.getElementById('batch-reanalyze-progress-section');
  const secSum = document.getElementById('batch-reanalyze-summary-section');
  if (secConfig) secConfig.style.display = 'block';
  if (secProg) secProg.style.display = 'none';
  if (secSum) secSum.style.display = 'none';

  modal.style.display = 'flex';
}

function closeBatchReanalyzeModal(e) {
  if (e && e.target && e.target.id !== 'batch-reanalyze-modal' && !e.target.classList.contains('close-btn') && !e.target.classList.contains('filter-btn')) {
    return;
  }
  const modal = document.getElementById('batch-reanalyze-modal');
  if (modal) modal.style.display = 'none';
}

async function executeBatchReanalyze() {
  const batchIds = (typeof selectedBatchIds !== 'undefined') ? selectedBatchIds : (window.selectedBatchIds || new Set());
  const dataList = (typeof allData !== 'undefined' ? allData : (window.allData || []));
  const items = dataList.filter(it => batchIds.has(Number(it.id)));
  if (items.length === 0) return;

  const isCrossCheckOnly = (document.getElementById('batch-op-mode-cc')?.checked === true);
  const skipExisting = isCrossCheckOnly && (document.getElementById('batch-reanalyze-skip-existing-cc')?.checked !== false);

  const tier = document.getElementById('batch-reanalyze-tier')?.value || 'standard';
  const analysisMode = isCrossCheckOnly ? 'fast' : (document.getElementById('batch-reanalyze-depth')?.value || 'fast');
  const categoryChoice = document.getElementById('batch-reanalyze-category')?.value || 'keep';
  const concurrency = parseInt(document.getElementById('batch-reanalyze-concurrency')?.value, 10) || 2;
  const useMedian = isCrossCheckOnly ? false : (document.getElementById('batch-reanalyze-median')?.checked || false);
  const batchSampleSelect = document.getElementById('batch-reanalyze-sample-count');
  const chosenBatchSamples = batchSampleSelect ? (parseInt(batchSampleSelect.value, 10) || 3) : 3;
  const sampleCount = useMedian ? chosenBatchSamples : 1;

  // Show progress section
  document.getElementById('batch-reanalyze-config-section').style.display = 'none';
  document.getElementById('batch-reanalyze-progress-section').style.display = 'block';
  document.getElementById('batch-reanalyze-summary-section').style.display = 'none';

  const progTitle = document.getElementById('batch-reanalyze-progress-title');
  if (progTitle) {
    progTitle.textContent = isCrossCheckOnly ? '🤝 크로스체크 일괄 채워넣기 진행 중...' : '일괄 재평가 진행 중...';
  }

  _batchReanalyzeCancelled = false;
  _batchReanalyzeResults = [];
  _batchReanalyzeMode = isCrossCheckOnly ? 'cross_check_only' : 'full';

  const total = items.length;
  let completed = 0;
  let successCount = 0;
  let skippedCount = 0;
  let failCount = 0;

  const progBar = document.getElementById('batch-reanalyze-progress-bar');
  const progPct = document.getElementById('batch-reanalyze-progress-pct');
  const progStatus = document.getElementById('batch-reanalyze-progress-status');
  const liveList = document.getElementById('batch-reanalyze-live-list');

  // Initialize live list
  liveList.innerHTML = items.map(it => {
    const hasCc = Boolean(it.cross_check_opinion);
    const willSkip = isCrossCheckOnly && skipExisting && hasCc;
    const initialStatus = willSkip ? '건너뜀 대기 (보유 중)' : '대기 중';
    const initialIcon = willSkip ? '⏭️' : '⏱️';
    const mainScore = it.final_score != null ? Number(it.final_score).toFixed(1) : '-';
    const ccInfo = hasCc ? ` · 🤝${Number(it.cross_check_opinion.score).toFixed(1)}점` : '';

    return `
      <div id="batch-item-row-${it.id}" style="display:flex;justify-content:space-between;align-items:center;padding:5px 8px;border-radius:6px;background:var(--card-bg, #fff);border:1px solid var(--line, #e2e8f0);">
        <span style="display:flex;align-items:center;gap:6px;overflow:hidden;flex:1;">
          <span id="batch-item-icon-${it.id}">${initialIcon}</span>
          <strong style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${_escapeReanalyzeHtml(it.filename)}</strong>
          <span style="color:var(--muted);font-size:0.74rem;flex-shrink:0;">(본점수: ${mainScore}점${ccInfo})</span>
        </span>
        <span id="batch-item-status-${it.id}" style="color:var(--muted);font-weight:600;flex-shrink:0;margin-left:10px;">${initialStatus}</span>
      </div>
    `;
  }).join('');

  const updateProgress = () => {
    const pct = total > 0 ? Math.round((completed / total) * 100) : 100;
    if (progBar) progBar.style.width = `${pct}%`;
    if (progPct) progPct.textContent = `${pct}%`;
    if (progStatus) {
      if (isCrossCheckOnly) {
        progStatus.innerHTML = `진행 현황: <b>${completed} / ${total}장 완료</b> (신규 생성 <span style="color:#0284c7;font-weight:700;">${successCount}</span> · 건너뜀 <span style="color:#64748b;font-weight:700;">${skippedCount}</span> · 실패 <span style="color:#e11d48;font-weight:700;">${failCount}</span>)`;
      } else {
        progStatus.innerHTML = `진행 현황: <b>${completed} / ${total}장 완료</b> (성공 <span style="color:#059669;font-weight:700;">${successCount}</span> · 실패 <span style="color:#e11d48;font-weight:700;">${failCount}</span>)`;
      }
    }
  };
  updateProgress();

  let queueIdx = 0;

  async function worker() {
    while (queueIdx < items.length) {
      if (_batchReanalyzeCancelled) break;
      const it = items[queueIdx++];
      const id = Number(it.id);

      const iconEl = document.getElementById(`batch-item-icon-${id}`);
      const statusEl = document.getElementById(`batch-item-status-${id}`);

      // Check skip condition
      if (isCrossCheckOnly && skipExisting && it.cross_check_opinion) {
        skippedCount++;
        completed++;
        if (iconEl) iconEl.textContent = '⏭️';
        if (statusEl) {
          statusEl.innerHTML = `<span style="color:var(--muted);">기존 보유 (${Number(it.cross_check_opinion.score).toFixed(1)}점) 건너뜀</span>`;
        }
        _batchReanalyzeResults.push({
          id,
          filename: it.filename,
          success: true,
          skipped: true,
          prevScore: it.final_score != null ? Number(it.final_score) : null,
          ccScore: Number(it.cross_check_opinion.score),
          model: it.cross_check_opinion.model,
          provider: it.cross_check_opinion.provider,
        });
        updateProgress();
        continue;
      }

      // Determine category
      let category = categoryChoice;
      if (categoryChoice === 'keep') {
        category = getCategoryKeyFromTitle(it.figure_category);
      }

      // Mark running
      if (iconEl) iconEl.textContent = '⏳';
      if (statusEl) {
        statusEl.innerHTML = `<span style="color:#0284c7;">${isCrossCheckOnly ? '크로스체크 생성 중...' : '재평가 중...'}</span>`;
      }

      const pScore = it.final_score != null ? Number(it.final_score) : null;
      let resItem = null;

      try {
        const runMode = isCrossCheckOnly ? 'cross_check_only' : 'full';
        const res = await API.reanalyzePhoto(id, runMode, tier, category, sampleCount, analysisMode);
        if (_batchReanalyzeCancelled) break;
        if (res && res.success && res.analysis) {
          successCount++;
          // Update in-memory data item
          const targetItem = dataList.find(d => Number(d.id) === id);
          if (targetItem) {
            Object.assign(targetItem, res.analysis);
          }

          if (isCrossCheckOnly) {
            const cc = res.analysis.cross_check_opinion;
            const ccScore = cc && cc.score != null ? Number(cc.score) : null;
            const provName = cc ? (cc.provider || '상대 모델') : '크로스체크';
            resItem = {
              id,
              filename: it.filename,
              success: true,
              skipped: false,
              isCrossCheck: true,
              prevScore: pScore,
              ccScore: ccScore,
              model: cc?.model,
              provider: cc?.provider,
            };
            if (iconEl) iconEl.textContent = '🤝';
            if (statusEl) {
              const scoreText = ccScore != null ? `${ccScore.toFixed(1)}점` : '완료';
              statusEl.innerHTML = `<span style="background:rgba(2,132,199,0.12);color:#0284c7;padding:2px 6px;border-radius:4px;font-weight:700;">🤝 ${scoreText}</span> <small style="color:var(--muted);margin-left:4px;">(${provName})</small>`;
            }
          } else {
            const nScore = Number(res.analysis.final_score);
            const diffVal = (pScore != null) ? +(nScore - pScore).toFixed(1) : 0;
            const diffSign = diffVal > 0 ? `+${diffVal.toFixed(1)}` : `${diffVal.toFixed(1)}`;
            const diffColor = diffVal > 0 ? '#059669' : (diffVal < 0 ? '#e11d48' : '#64748b');

            resItem = {
              id,
              filename: it.filename,
              success: true,
              skipped: false,
              isCrossCheck: false,
              prevScore: pScore,
              newScore: nScore,
              diffVal,
              sampledScores: res.sampled_scores || null,
              model: res.analysis.model,
            };

            if (iconEl) iconEl.textContent = '✅';
            if (statusEl) {
              statusEl.innerHTML = `<b>${nScore.toFixed(1)}점</b> <span style="color:${diffColor};font-size:0.75rem;margin-left:4px;">(${diffSign}점)</span>`;
            }
          }
        } else {
          throw new Error((res && res.error) || '응답 오류');
        }
      } catch (err) {
        failCount++;
        resItem = {
          id,
          filename: it.filename,
          success: false,
          skipped: false,
          isCrossCheck: isCrossCheckOnly,
          error: err.message,
          prevScore: pScore,
        };
        if (iconEl) iconEl.textContent = '❌';
        if (statusEl) {
          statusEl.innerHTML = `<span style="color:#e11d48;">실패: ${_escapeReanalyzeHtml(err.message)}</span>`;
        }
      }

      completed++;
      _batchReanalyzeResults.push(resItem);
      updateProgress();
    }
  }

  const workerCount = Math.min(concurrency, items.length);
  const workers = Array.from({ length: workerCount }, () => worker());
  await Promise.all(workers);

  // Show summary section
  showBatchReanalyzeSummary();
}

function showBatchReanalyzeSummary() {
  document.getElementById('batch-reanalyze-progress-section').style.display = 'none';
  document.getElementById('batch-reanalyze-summary-section').style.display = 'block';

  const results = _batchReanalyzeResults || [];
  const total = results.length;
  const isCrossCheck = (_batchReanalyzeMode === 'cross_check_only');

  const titleEl = document.getElementById('batch-reanalyze-summary-title');
  const diffTitleEl = document.getElementById('batch-reanalyze-diff-title');
  const statsEl = document.getElementById('batch-reanalyze-summary-stats');
  const diffList = document.getElementById('batch-reanalyze-diff-list');

  if (isCrossCheck) {
    if (titleEl) titleEl.textContent = '🎉 크로스체크 일괄 채워넣기가 완료되었습니다!';
    if (diffTitleEl) diffTitleEl.textContent = '📊 사진별 크로스체크 채워넣기 결과:';

    const created = results.filter(r => r.success && !r.skipped);
    const skipped = results.filter(r => r.success && r.skipped);
    const fails = results.filter(r => !r.success);

    const validScores = created.map(r => r.ccScore).filter(s => s != null);
    const avgCc = validScores.length > 0
      ? (validScores.reduce((a, b) => a + b, 0) / validScores.length).toFixed(1)
      : null;

    if (statsEl) {
      statsEl.innerHTML = `
        <span>🤝 <b>총 ${total}장</b> 처리 (신규 생성 <strong style="color:#0284c7;">${created.length}장</strong>, 기보유 건너뜀 <strong style="color:#64748b;">${skipped.length}장</strong>, 실패 <strong style="color:#e11d48;">${fails.length}장</strong>)</span>
        ${avgCc ? `<span>📊 신규 크로스체크 평균: <strong style="color:#0284c7;">${avgCc}점</strong></span>` : ''}
      `;
    }

    if (diffList) {
      diffList.innerHTML = results.map(r => {
        if (!r.success) {
          return `
            <div style="display:flex;justify-content:space-between;align-items:center;padding:5px 8px;background:rgba(225,29,72,0.06);border:1px solid rgba(225,29,72,0.25);border-radius:6px;">
              <span>❌ <strong>${_escapeReanalyzeHtml(r.filename)}</strong></span>
              <span style="color:#e11d48;">오류: ${_escapeReanalyzeHtml(r.error)}</span>
            </div>
          `;
        }
        const mainScore = r.prevScore != null ? r.prevScore.toFixed(1) : '-';
        if (r.skipped) {
          const ccScore = r.ccScore != null ? r.ccScore.toFixed(1) : '-';
          return `
            <div style="display:flex;justify-content:space-between;align-items:center;padding:5px 8px;background:var(--card-sub, #f8fafc);border:1px solid var(--line, #e2e8f0);border-radius:6px;opacity:0.85;">
              <span style="display:flex;align-items:center;gap:6px;overflow:hidden;flex:1;">
                <span>⏭️</span>
                <strong style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${_escapeReanalyzeHtml(r.filename)}</strong>
                <span style="font-size:0.72rem;color:var(--muted);">(기존 보유 건너뜀)</span>
              </span>
              <span style="flex-shrink:0;margin-left:10px;font-size:0.78rem;">
                본 점수: <strong>${mainScore}점</strong> | 크로스체크: <span style="font-weight:700;color:#0284c7;">🤝${ccScore}점</span>
              </span>
            </div>
          `;
        }
        const ccScore = r.ccScore != null ? r.ccScore.toFixed(1) : '-';
        const provBadge = r.provider ? `<span style="font-size:0.7rem;background:rgba(2,132,199,0.12);color:#0284c7;padding:1px 5px;border-radius:3px;font-weight:700;">${_escapeReanalyzeHtml(r.provider)}</span>` : '';
        return `
          <div style="display:flex;justify-content:space-between;align-items:center;padding:5px 8px;background:var(--card-bg, #fff);border:1px solid var(--line, #e2e8f0);border-radius:6px;">
            <span style="display:flex;align-items:center;gap:6px;overflow:hidden;flex:1;">
              <span>🤝</span>
              <strong style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${_escapeReanalyzeHtml(r.filename)}</strong>
              ${provBadge}
            </span>
            <span style="flex-shrink:0;margin-left:10px;">
              <span style="color:var(--muted);font-size:0.74rem;">본 점수: ${mainScore}점</span>
              <span style="margin-left:8px;font-weight:800;color:#0284c7;font-size:0.85rem;">크로스체크: ${ccScore}점</span>
            </span>
          </div>
        `;
      }).join('');
    }
    return;
  }

  // Full reanalysis mode
  if (titleEl) titleEl.textContent = '🎉 일괄 재평가가 성공적으로 완료되었습니다!';
  if (diffTitleEl) diffTitleEl.textContent = '📊 사진별 점수 변화 결과 (Before → After):';

  const successes = results.filter(r => r.success);
  const fails = results.filter(r => !r.success);

  let upCount = 0;
  let keepCount = 0;
  let downCount = 0;
  let totalDiff = 0;

  successes.forEach(r => {
    if (r.diffVal > 0.05) upCount++;
    else if (r.diffVal < -0.05) downCount++;
    else keepCount++;
    totalDiff += r.diffVal;
  });

  const avgDiff = successes.length > 0 ? (totalDiff / successes.length).toFixed(2) : '0.00';
  const avgSign = Number(avgDiff) > 0 ? `+${avgDiff}` : `${avgDiff}`;
  const avgColor = Number(avgDiff) > 0 ? '#059669' : (Number(avgDiff) < 0 ? '#e11d48' : '#64748b');

  if (statsEl) {
    statsEl.innerHTML = `
      <span>📦 총 <b>${total}장</b> 처리 (성공 <strong style="color:#059669">${successes.length}</strong>, 실패 <strong style="color:#e11d48">${fails.length}</strong>)</span>
      <span>📈 점수 상승: <strong style="color:#059669">${upCount}장</strong></span>
      <span>➖ 유지: <strong>${keepCount}장</strong></span>
      <span>📉 하락: <strong style="color:#e11d48">${downCount}장</strong></span>
      <span>평균 점수 변화: <strong style="color:${avgColor}">${avgSign}점</strong></span>
    `;
  }

  if (diffList) {
    diffList.innerHTML = results.map(r => {
      if (!r.success) {
        return `
          <div style="display:flex;justify-content:space-between;padding:5px 8px;background:rgba(225,29,72,0.06);border:1px solid rgba(225,29,72,0.25);border-radius:6px;">
            <span>❌ <strong>${_escapeReanalyzeHtml(r.filename)}</strong></span>
            <span style="color:#e11d48;">오류: ${_escapeReanalyzeHtml(r.error)}</span>
          </div>
        `;
      }
      const p = r.prevScore != null ? r.prevScore.toFixed(1) : '-';
      const n = r.newScore.toFixed(1);
      const diffSign = r.diffVal > 0 ? `+${r.diffVal.toFixed(1)}` : `${r.diffVal.toFixed(1)}`;
      const diffColor = r.diffVal > 0 ? '#059669' : (diffVal < 0 ? '#e11d48' : '#64748b');
      const samplingBadges = (r.sampledScores && r.sampledScores.length > 1)
        ? `<small style="color:var(--muted);margin-left:6px;">(3회: ${r.sampledScores.join(', ')}점)</small>`
        : '';
      return `
        <div style="display:flex;justify-content:space-between;align-items:center;padding:5px 8px;background:var(--card-bg, #fff);border:1px solid var(--line, #e2e8f0);border-radius:6px;">
          <span style="display:flex;align-items:center;gap:6px;overflow:hidden;flex:1;">
            <span>✅</span>
            <strong style="white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${_escapeReanalyzeHtml(r.filename)}</strong>
            ${samplingBadges}
          </span>
          <span style="flex-shrink:0;margin-left:10px;">
            <span>${p}점 → <strong style="color:var(--blue);">${n}점</strong></span>
            <span style="margin-left:6px;font-weight:700;color:${diffColor};">(${diffSign}점)</span>
          </span>
        </div>
      `;
    }).join('');
  }
}

function cancelBatchReanalyze() {
  _batchReanalyzeCancelled = true;
  const statusEl = document.getElementById('batch-reanalyze-progress-status');
  if (statusEl) {
    statusEl.innerHTML += `<br><span style="color:#e11d48;font-weight:700;">⏹️ 작업 중단 요청됨... (현재 진행 중인 사진까지만 완료하고 마칩니다)</span>`;
  }
}

async function finishBatchReanalyze() {
  const modal = document.getElementById('batch-reanalyze-modal');
  if (modal) modal.style.display = 'none';

  // Clear batch selection
  if (typeof clearBatchSelection === 'function') {
    clearBatchSelection();
  }

  // Refresh entire data
  if (typeof loadData === 'function') {
    await loadData();
  }
}

window.selectBatchOperationMode = selectBatchOperationMode;
window.updateBatchReanalyzeSkipCount = updateBatchReanalyzeSkipCount;
window.upgradeFastToFullAnalysis = upgradeFastToFullAnalysis;
window.openBatchReanalyzeModal = openBatchReanalyzeModal;
window.closeBatchReanalyzeModal = closeBatchReanalyzeModal;
window.executeBatchReanalyze = executeBatchReanalyze;
window.showBatchReanalyzeSummary = showBatchReanalyzeSummary;
window.cancelBatchReanalyze = cancelBatchReanalyze;
window.finishBatchReanalyze = finishBatchReanalyze;
