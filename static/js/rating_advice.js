// static/js/rating_advice.js - User Rating & Lightroom Retouching Advice Module

function _escapeRatingHtml(str) {
  if (typeof escapeHtml === 'function') return escapeHtml(str);
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
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
      const dataList = (typeof allData !== 'undefined' ? allData : (window.allData || []));
      const item = dataList.find(d => d.id === id);
      if (item) {
        item.user_score = data.user_score;
      }
      if (typeof openDetailModal === 'function') openDetailModal(id);
      if (typeof renderScoreDistPanel === 'function') renderScoreDistPanel();
      if (typeof renderGallery === 'function') renderGallery();
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
      <b style="color:var(--blue)">🌡️ 화이트밸런스/색조:</b> ${_escapeRatingHtml(advice.temp_tint_notes)}
    </div>
    <div class="lr-tip-box">
      <b style="color:var(--accent)">🎨 마스킹 및 세부 후보정 팁:</b> ${_escapeRatingHtml(advice.retouching_guide)}
    </div>
  `;
}

async function requestLrAdvice(recordId, btn) {
  const origText = btn.textContent;
  const dataList = (typeof allData !== 'undefined' ? allData : (window.allData || []));
  const item = dataList.find(d => d.id === recordId);
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
        badgeEl.innerHTML = `<span style="font-size:0.73rem;background:rgba(99,102,241,0.14);color:#4f46e5;padding:2px 8px;border-radius:999px;font-weight:700;">${_escapeRatingHtml(usedLabel)}</span>`;
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

// Global scope export
window.renderScoreComparisonBox = renderScoreComparisonBox;
window.submitUserScore = submitUserScore;
window.setQuickUserScore = setQuickUserScore;
window.clearUserScore = clearUserScore;
window.renderLrAdviceContent = renderLrAdviceContent;
window.requestLrAdvice = requestLrAdvice;
