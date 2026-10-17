// static/js/detail_modal.js - Photo Detail Modal, Navigation & Zoom Module

function _escapeDetailHtml(str) {
  if (typeof escapeHtml === 'function') return escapeHtml(str);
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function _formatCapturedAt(value) {
  if (typeof formatCapturedAt === 'function') return formatCapturedAt(value);
  if (!value) return '촬영 시각 정보 없음';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return `촬영 ${value}`;
  return `촬영 ${date.toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'medium' })}`;
}

function renderCrossCheckOpinion(op) {
  if (!op) return '';
  return `
    <div class="cross-check-opinion-card">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;flex-wrap:wrap;gap:8px;">
        <div style="display:flex;align-items:center;gap:8px;">
          <span style="font-size:1.2rem;">🤝</span>
          <div>
            <strong class="cross-check-title">OpenAI 크로스 체크 의견 (${_escapeDetailHtml(op.model || 'GPT-6 Luna')})</strong>
            <div style="font-size:0.73rem;color:var(--muted);">Gemini 본 평가와 별도로 제공되는 독립적인 보조 비평입니다. (점수 합산/평균 없음)</div>
          </div>
        </div>
        <div style="text-align:right;">
          <span class="cross-check-score">${op.score !== undefined && op.score !== null ? Number(op.score).toFixed(1) : '-'}</span>
          <small style="color:var(--muted);font-size:0.75rem;"> / 10점</small>
        </div>
      </div>
      ${op.reason ? `<div class="cross-check-reason-box"><b>OpenAI 총평:</b> ${_escapeDetailHtml(op.reason)}</div>` : ''}
      ${(op.composition_critique || op.lighting_critique) ? `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px;">
          ${op.composition_critique ? `
            <div class="cross-check-comp-box">
              <b style="display:block;margin-bottom:2px;">📐 구도 비평:</b>
              <span>${_escapeDetailHtml(op.composition_critique)}</span>
            </div>
          ` : ''}
          ${op.lighting_critique ? `
            <div class="cross-check-light-box">
              <b style="display:block;margin-bottom:2px;">💡 조명 비평:</b>
              <span>${_escapeDetailHtml(op.lighting_critique)}</span>
            </div>
          ` : ''}
        </div>
      ` : ''}
      ${((op.strengths && op.strengths.length) || (op.improvements && op.improvements.length)) ? `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:0.78rem;">
          ${op.strengths && op.strengths.length ? `
            <div class="cross-check-strengths-box">
              <b style="display:block;margin-bottom:2px;">✓ OpenAI 시각 강점:</b>
              <ul style="margin:4px 0 0;padding-left:16px;">${op.strengths.map(s => `<li>${_escapeDetailHtml(s)}</li>`).join('')}</ul>
            </div>
          ` : ''}
          ${op.improvements && op.improvements.length ? `
            <div class="cross-check-improvements-box">
              <b style="display:block;margin-bottom:2px;">✗ OpenAI 조언/개선점:</b>
              <ul style="margin:4px 0 0;padding-left:16px;">${op.improvements.map(i => `<li>${_escapeDetailHtml(i)}</li>`).join('')}</ul>
            </div>
          ` : ''}
        </div>
      ` : ''}
    </div>
  `;
}

function renderExifSummary(exif, detectedSettings) {
  const parts = [];
  if (exif && Object.keys(exif).length) {
    if (exif.Make || exif.Model) parts.push(`${_escapeDetailHtml(exif.Make || '')} ${_escapeDetailHtml(exif.Model || '')}`.trim());
    if (exif.FNumber) parts.push(`F/${_escapeDetailHtml(exif.FNumber)}`);
    if (exif.ExposureTime) parts.push(`${_escapeDetailHtml(exif.ExposureTime)}s`);
    if (exif.ISOSpeedRatings) parts.push(`ISO ${_escapeDetailHtml(exif.ISOSpeedRatings)}`);
    if (exif.FocalLength) parts.push(`${_escapeDetailHtml(exif.FocalLength)}mm`);
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
      if (v) dParts.push(`${_escapeDetailHtml(v)}`);
    }
    if (dParts.length) {
      html += `<div style="margin-top:6px;background:#eef2ff;color:#4338ca;padding:4px 10px;border-radius:6px;font-size:0.8rem;display:inline-block;border:1px solid #c7d2fe;"><b>🔍 워터마크 감지 스펙:</b> ${dParts.join(' · ')}</div>`;
    }
  }
  return html;
}

function openDetailModal(id) {
  if (typeof clearCropOverlay === 'function') clearCropOverlay();
  const dataList = (typeof allData !== 'undefined' ? allData : (window.allData || []));
  const item = dataList.find(d => d.id === id);
  if (!item) return;

  if (typeof currentDetailId !== 'undefined') currentDetailId = id;
  window.currentDetailId = id;

  const modal = document.getElementById('detail-modal');
  const body = document.getElementById('modal-body');
  if (!body || !modal) return;

  const burstThumbsFn = typeof renderBurstThumbnails === 'function' ? renderBurstThumbnails : (window.renderBurstThumbnails || (() => ''));
  const scoreBoxFn = typeof renderScoreComparisonBox === 'function' ? renderScoreComparisonBox : (window.renderScoreComparisonBox || (() => ''));
  const lrAdviceFn = typeof renderLrAdviceContent === 'function' ? renderLrAdviceContent : (window.renderLrAdviceContent || (() => ''));
  const reanalyzePanelFn = typeof renderReanalyzePanel === 'function' ? renderReanalyzePanel : (window.renderReanalyzePanel || (() => ''));

  const fmtModel = (m) => (window.ModelSettings && m) ? window.ModelSettings.formatBadge(m) : (m || '-');
  const reanalyzeDiff = (window._lastReanalyzeDiff && window._lastReanalyzeDiff.id === item.id) ? window._lastReanalyzeDiff : null;
  let reanalyzeBannerHtml = '';
  if (reanalyzeDiff) {
    if (reanalyzeDiff.mode === 'cross_check_only') {
      const lunaAfter = reanalyzeDiff.newLunaScore != null ? `${reanalyzeDiff.newLunaScore.toFixed(1)}점` : '-';
      const lunaBefore = reanalyzeDiff.prevLunaScore != null ? `${reanalyzeDiff.prevLunaScore.toFixed(1)}점` : '없음';
      reanalyzeBannerHtml = `
        <div style="grid-column: 1 / -1; background: rgba(99,102,241,0.12); border: 1px solid #818cf8; border-radius: 10px; padding: 10px 14px; display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap;">
          <div style="font-size: 0.85rem; color: var(--text);">
            <strong>🤝 GPT-6 Luna 크로스체크 단독 갱신 완료:</strong>
            Luna 보조 점수 <b>${_escapeDetailHtml(lunaBefore)} → ${_escapeDetailHtml(lunaAfter)}</b>
            <span style="color:var(--muted);font-size:0.78rem;margin-left:6px;">(크로스체크 단독 모드는 주 종합 점수 ${item.final_score.toFixed(1)}점과 주 모델을 유지합니다)</span>
          </div>
          <button type="button" class="filter-btn" style="padding:2px 8px;font-size:0.74rem;" onclick="window._lastReanalyzeDiff=null; this.parentElement.remove();">확인 ✕</button>
        </div>
      `;
    } else {
      const pScore = reanalyzeDiff.prevScore != null ? reanalyzeDiff.prevScore : item.final_score;
      const nScore = item.final_score;
      const diffVal = +(nScore - pScore).toFixed(1);
      const diffSign = diffVal > 0 ? `+${diffVal.toFixed(1)}` : `${diffVal.toFixed(1)}`;
      const diffColor = diffVal > 0 ? '#059669' : (diffVal < 0 ? '#e11d48' : '#64748b');
      const pModel = fmtModel(reanalyzeDiff.prevModel);
      const nModel = fmtModel(item.model);
      reanalyzeBannerHtml = `
        <div style="grid-column: 1 / -1; background: rgba(16,185,129,0.12); border: 1px solid #34d399; border-radius: 10px; padding: 10px 14px; display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap;">
          <div style="font-size: 0.86rem; color: var(--text); display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
            <span>✅ <strong>전면 재평가 반영 완료!</strong></span>
            <span>📊 <b>종합 점수:</b> ${pScore.toFixed(1)}점 → <strong style="color:${diffColor};font-size:0.95rem;">${nScore.toFixed(1)}점 (${diffSign}점)</strong></span>
            <span>🤖 <b>평가 모델:</b> ${_escapeDetailHtml(pModel)} → <strong style="color:#4f46e5;">${_escapeDetailHtml(nModel)}</strong> <small style="color:var(--muted);">(${_escapeDetailHtml(item.model)})</small></span>
          </div>
          <button type="button" class="filter-btn" style="padding:2px 8px;font-size:0.74rem;" onclick="window._lastReanalyzeDiff=null; this.parentElement.remove();">확인 ✕</button>
        </div>
      `;
    }
  }

  body.innerHTML = `
    ${reanalyzeBannerHtml}
    ${item.is_burst ? `
      <div class="burst-banner ${item.is_best_pick ? '' : 'is-b-cut'}" style="grid-column: 1 / -1;">
        <div style="display:flex;align-items:center;gap:10px;">
          <span style="font-size:1.4rem;">${item.is_best_pick ? '👑' : '🗂️'}</span>
          <div>
            <div style="font-size:0.92rem;font-weight:800;color:${item.is_best_pick ? '#065f46' : '#991b1b'};">
              ${item.is_best_pick ? `👑 연사 묶음 베스트 컷 (총 ${item.burst_total}장 중 1위 선정)` : `⚠️ 연사 묶음 B컷 (${item.burst_rank}/${item.burst_total}위 · 탈락 사유: ${_escapeDetailHtml(item.drop_reason)})`}
            </div>
            <div style="font-size:0.77rem;color:var(--muted);">동일 구도 및 포즈로 연속 촬영된 연사 세트 중 AI 디테일(초점·조명·완성도) 비교 결과입니다.</div>
          </div>
        </div>
        <div style="display:flex;gap:6px;align-items:center;">
          <span style="font-size:0.78rem;font-weight:700;color:var(--muted);">묶음 컷:</span>
          ${burstThumbsFn(item.burst_group_id, item.id)}
        </div>
      </div>
    ` : ''}

    <div>
      <div class="zoom-wrap" id="zoom-wrap-container" onclick="toggleZoom(event)" onmousemove="panZoom(event)">
        <img class="detail-img" id="detail-modal-img" src="/api/image/${item.id}?original=1" alt="${_escapeDetailHtml(item.filename)}" onload="if(typeof repositionCropOverlay==='function') repositionCropOverlay()">
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
        <div><b>해상도:</b> ${item.width} × ${item.height}px (${_escapeDetailHtml(item.format)})</div>
        <div><b>촬영시각:</b> ${_escapeDetailHtml(item.captured_at ? _formatCapturedAt(item.captured_at).replace(/^촬영 /, '') : '정보 없음')}</div>
        <div><b>분석 모델:</b> <strong style="color:var(--text);">${_escapeDetailHtml(fmtModel(item.model))}</strong> <small>(${_escapeDetailHtml(item.model)})</small> · <b>분석시각:</b> ${_escapeDetailHtml(item.created_at)}</div>
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
        ${reanalyzePanelFn(item)}
      </div>

      <!-- Adobe Lightroom Advice Box (사진 바로 아래 배치) -->
      <div class="lr-advice-box" id="lr-advice-box-section">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
          <h3 class="lr-advice-title" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
            <span class="lr-advice-badge">Lr</span>
            <span>Adobe Lightroom 추천 보정 수치</span>
            <span id="lr-used-model-badge-${item.id}">${item.lr_advice && item.lr_advice.used_model ? `<span style="font-size:0.73rem;background:rgba(99,102,241,0.14);color:#4f46e5;padding:2px 8px;border-radius:999px;font-weight:700;">${_escapeDetailHtml(window.ModelSettings ? window.ModelSettings.formatBadge(item.lr_advice.used_model) : item.lr_advice.used_model)}</span>` : ''}</span>
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
          ${lrAdviceFn(item.lr_advice)}
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
          <h2 style="margin:0;">${_escapeDetailHtml(item.filename)}</h2>
          <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-top:6px;">
            <span class="score-grade" style="font-size:0.86rem;padding:4px 12px;margin:0;">${_escapeDetailHtml(item.grade)}</span>
            <span style="display:inline-flex;align-items:center;gap:4px;font-size:0.78rem;font-weight:700;color:#4f46e5;background:rgba(99,102,241,0.12);border:1px solid rgba(99,102,241,0.3);padding:3px 10px;border-radius:999px;" title="적용된 평가 모델 ID: ${_escapeDetailHtml(item.model)}">
              🤖 ${_escapeDetailHtml(fmtModel(item.model))}
            </span>
          </div>
        </div>
        <div style="text-align:right;">
          <div style="font-size:2.8rem;font-weight:900;color:var(--blue);line-height:1;">${item.final_score.toFixed(1)}</div>
          <small style="color:var(--muted)">10점 만점</small>
        </div>
      </div>

      <div class="final-reason-box">
        <b>종합 총평:</b> ${_escapeDetailHtml(item.final_reason)}
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

        ${item.user_score !== null && item.user_score !== undefined ? scoreBoxFn(item.final_score, item.user_score) : ''}
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
          <div class="note-body">${_escapeDetailHtml(item.composition_notes)}</div>
        </div>
        <div class="note-item-compact" style="border-left: 3px solid #f59e0b;">
          <div class="note-header">
            <span>💡 조명/노출 평가</span>
            <strong style="color:#d97706;">${item.lighting_score.toFixed(1)}</strong>
          </div>
          <div class="note-body">${_escapeDetailHtml(item.lighting_notes)}</div>
        </div>
        <div class="note-item-compact" style="border-left: 3px solid #ec4899;">
          <div class="note-header">
            <span>🎨 색감/톤 평가</span>
            <strong style="color:#db2777;">${item.color_score.toFixed(1)}</strong>
          </div>
          <div class="note-body">${_escapeDetailHtml(item.color_notes)}</div>
        </div>
        <div class="note-item-compact" style="border-left: 3px solid #10b981;">
          <div class="note-header">
            <span>📷 촬영 기술 평가</span>
            <strong style="color:#059669;">${item.technique_score.toFixed(1)}</strong>
          </div>
          <div class="note-body">${_escapeDetailHtml(item.technique_notes)}</div>
        </div>
      </div>

      <!-- 초점 핀 상태 인라인 슬림 바 -->
      <div class="note-item-compact" style="border-left: 3px solid #6366f1;margin-bottom:6px;">
        <div class="note-header">
          <span>🎯 피규어 눈동자/페이스 초점 핀</span>
          <strong style="color:#4f46e5;">${_escapeDetailHtml(item.focus_status || '완벽 칼초점')}</strong>
        </div>
        <div class="note-body">${_escapeDetailHtml(item.focus_notes ? item.focus_notes : '눈동자 아이 데칼 및 안면 조형 핀 상태 양호')}</div>
      </div>

      <!-- 주요 장점 및 단점/개선점 (좌우 2열 배치로 세로 공간 50% 절약) -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:6px;">
        <div class="strengths-box">
          <h4>✓ 주요 장점</h4>
          <ul>${item.strengths.map(s => `<li>${_escapeDetailHtml(s)}</li>`).join('')}</ul>
        </div>
        <div class="improvements-box">
          <h4>✗ 단점 및 촬영 개선점</h4>
          <ul>${item.improvements.map(i => `<li>${_escapeDetailHtml(i)}</li>`).join('')}</ul>
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
  if (typeof currentCropBox !== 'undefined') currentCropBox = null;
  const defaultRatio = (item.sns_advice && item.sns_advice.best_ratio_key)
    ? item.sns_advice.best_ratio_key
    : 'instagram_crop_4_5';
  if (typeof currentCropRatioKey !== 'undefined') currentCropRatioKey = defaultRatio;
  const overlay = document.getElementById('crop-box-overlay');
  if (overlay) overlay.style.display = 'none';
  if (item.sns_advice && (item.sns_advice[defaultRatio] || defaultRatio === 'original')) {
    setTimeout(() => {
      if (typeof selectCropRatio === 'function') selectCropRatio(defaultRatio, item.id);
    }, 150);
  }

  const img = document.getElementById('detail-modal-img');
  if (img) {
    if (img.complete) {
      if (typeof repositionCropOverlay === 'function') repositionCropOverlay();
      if (typeof renderImageHistogram === 'function') renderImageHistogram(img);
    } else {
      img.addEventListener('load', () => {
        if (typeof repositionCropOverlay === 'function') repositionCropOverlay();
        if (typeof renderImageHistogram === 'function') renderImageHistogram(img);
      }, { once: true });
    }
  }
  updateModalNavButtons();
}

function closeDetailModal() {
  if (typeof clearCropOverlay === 'function') clearCropOverlay();
  const m = document.getElementById('detail-modal');
  if (m) m.style.display = 'none';
  if (typeof currentDetailId !== 'undefined') currentDetailId = null;
  window.currentDetailId = null;
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

function updateModalNavButtons() {
  const prevBtn = document.getElementById('modal-prev-btn');
  const nextBtn = document.getElementById('modal-next-btn');
  if (!prevBtn || !nextBtn) return;
  const dataList = (typeof allData !== 'undefined' ? allData : (window.allData || []));
  const sortFn = (typeof sortList === 'function' ? sortList : (list => list));
  const filterFn = (typeof filterList === 'function' ? filterList : (list => list));
  const filtered = sortFn(filterFn(dataList));
  const detailId = (typeof currentDetailId !== 'undefined' && currentDetailId !== null) ? currentDetailId : window.currentDetailId;
  const idx = filtered.findIndex(d => d.id === detailId);
  if (idx === -1) {
    prevBtn.disabled = true;
    nextBtn.disabled = true;
    return;
  }
  prevBtn.disabled = (idx <= 0);
  nextBtn.disabled = (idx >= filtered.length - 1);
  prevBtn.title = idx > 0 ? `이전 사진: ${filtered[idx - 1].filename} (← / J)` : '첫 번째 사진입니다';
  nextBtn.title = idx < filtered.length - 1 ? `다음 사진: ${filtered[idx + 1].filename} (→ / K)` : '마지막 사진입니다';
}

function navigateDetail(dir) {
  const modal = document.getElementById('detail-modal');
  const detailId = (typeof currentDetailId !== 'undefined' && currentDetailId !== null) ? currentDetailId : window.currentDetailId;
  if (!modal || modal.style.display !== 'flex' || detailId === null || detailId === undefined) return;
  const dataList = (typeof allData !== 'undefined' ? allData : (window.allData || []));
  const sortFn = (typeof sortList === 'function' ? sortList : (list => list));
  const filterFn = (typeof filterList === 'function' ? filterList : (list => list));
  const filtered = sortFn(filterFn(dataList));
  const idx = filtered.findIndex(d => d.id === detailId);
  if (idx === -1) return;
  const nextIdx = idx + dir;
  if (nextIdx >= 0 && nextIdx < filtered.length) {
    openDetailModal(filtered[nextIdx].id);
  }
}

// Global scope export
window.renderCrossCheckOpinion = renderCrossCheckOpinion;
window.renderExifSummary = renderExifSummary;
window.openDetailModal = openDetailModal;
window.closeDetailModal = closeDetailModal;
window.closeModal = closeModal;
window.toggleZoom = toggleZoom;
window.panZoom = panZoom;
window.updateModalNavButtons = updateModalNavButtons;
window.navigateDetail = navigateDetail;
