/**
 * Crop Viewer & SNS Advice Component
 * Handles AI aesthetic crop recommendations, exact pixel canvas crop computation,
 * real-time overlay positioning, and social caption copying.
 */

if (typeof escapeHtml === 'undefined') {
  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }
}

let currentCropBox = null;
let currentCropRatioKey = 'instagram_crop_4_5';

const TARGET_CROP_RATIOS = {
  original: { name: 'Original', tag: '원본 유지 (No Crop)', w: 0, h: 0, ratio: 0 },
  instagram_crop_4_5: { name: 'Instagram 4:5', tag: '4:5 (수직 매거진 / 인스타)', w: 4, h: 5, ratio: 4 / 5 },
  instagram_crop_1_1: { name: 'Instagram 1:1', tag: '1:1 (클래식 정방형)', w: 1, h: 1, ratio: 1.0 },
  x_crop_16_9: { name: 'X 16:9', tag: '16:9 (와이드 시네마틱)', w: 16, h: 9, ratio: 16 / 9 },
  x_crop_3_4: { name: 'X 3:4', tag: '3:4 (수직 와이드)', w: 3, h: 4, ratio: 3 / 4 }
};

function getCropRatioLabel(ratioKey) {
  if (ratioKey === 'original') return '📷 원본 유지 (No Crop)';
  if (TARGET_CROP_RATIOS[ratioKey]) return TARGET_CROP_RATIOS[ratioKey].tag;
  return ratioKey;
}

function renderSnsAdviceContent(advice, recordId) {
  const item = (typeof allData !== 'undefined' && Array.isArray(allData))
    ? allData.find(d => d.id === recordId)
    : null;
  const currentAdv = (item && item.sns_advice) ? item.sns_advice : (advice || {});

  const bestKey = currentAdv ? currentAdv.best_ratio_key : null;
  const bestReason = currentAdv ? currentAdv.best_ratio_reason : null;

  if (!currentCropRatioKey) {
    currentCropRatioKey = bestKey || 'instagram_crop_4_5';
  }

  const ratios = [
    { key: 'original', icon: '📷', name: '원본 유지 (No Crop)' },
    { key: 'instagram_crop_4_5', icon: '📸', name: '4:5 (수직 매거진 / 인스타)' },
    { key: 'instagram_crop_1_1', icon: '🟦', name: '1:1 (클래식 정방형)' },
    { key: 'x_crop_16_9', icon: '🐦', name: '16:9 (와이드 시네마틱)' },
    { key: 'x_crop_3_4', icon: '📱', name: '3:4 (수직 와이드)' }
  ];

  const buttonsHtml = ratios.map(r => {
    const isOriginal = (r.key === 'original');
    const hasData = isOriginal ? Boolean(bestKey) : Boolean(currentAdv && currentAdv[r.key]);
    const isActive = (r.key === currentCropRatioKey);
    const isBest = (bestKey && r.key === bestKey);
    const checkBadge = hasData && !isBest ? '<span style="color:#0284c7;font-size:0.75rem;margin-left:4px;font-weight:700;">✓</span>' : '';
    const bestBadge = isBest ? '<span class="best-ratio-badge">👑 AI 추천</span>' : '';
    return `<button class="crop-ratio-btn ${isActive ? 'active' : ''} ${isBest ? 'is-best-ratio-btn' : ''}" id="btn-crop-${r.key}" onclick="selectCropRatio('${r.key}', ${recordId})">${r.icon} ${escapeHtml(r.name)}${bestBadge}${checkBadge}</button>`;
  }).join('');

  const bestPickBanner = bestKey ? `
    <div class="best-ratio-banner">
      <div class="best-ratio-header">
        <span class="best-ratio-badge-pill">👑 AI Best Pick</span>
        <b style="color:var(--ink);font-size:0.88rem;">AI 큐레이터 추천 최적 구도: <span style="color:var(--blue);">${escapeHtml(getCropRatioLabel(bestKey))}</span></b>
      </div>
      <div class="best-ratio-desc">${escapeHtml(bestReason || '이 사진의 피규어 구도와 여백에 가장 균형 잡힌 최적 비율입니다.')}</div>
    </div>
  ` : '';

  return `
    <div>
      ${bestPickBanner}
      <div style="font-size:0.83rem;font-weight:700;color:var(--blue);margin-bottom:6px;margin-top:${bestKey ? '10px' : '0'};">
        🎨 사진의 미적 완성도가 가장 높은 구도를 우선 제안하며, 규격별 탭을 전환하여 즉시 미리보세요:
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px;">
        ${buttonsHtml}
        <button class="crop-ratio-btn" style="color:#ef4444;" onclick="clearCropOverlay()">❌ 프레임 숨기기</button>
      </div>

      <div id="crop-ratio-detail-area">
        ${renderCropRatioDetailArea(currentCropRatioKey, currentAdv, recordId)}
      </div>

      <!-- SNS 캡션 & 해시태그 독립 영역 -->
      <div id="sns-caption-area" style="margin-top:14px;">
        ${renderSnsCaptionArea(currentAdv, recordId)}
      </div>
    </div>
  `;
}

function renderCropRatioDetailArea(ratioKey, currentAdv, recordId) {
  const item = (typeof allData !== 'undefined' && Array.isArray(allData))
    ? allData.find(d => d.id === recordId)
    : null;
  const isOriginal = (ratioKey === 'original');
  const target = TARGET_CROP_RATIOS[ratioKey] || TARGET_CROP_RATIOS['instagram_crop_4_5'];
  const box = currentAdv ? currentAdv[ratioKey] : null;
  const isBest = currentAdv && currentAdv.best_ratio_key === ratioKey;

  if (isOriginal) {
    const bestKey = currentAdv ? currentAdv.best_ratio_key : null;
    const bestReason = currentAdv ? currentAdv.best_ratio_reason : null;
    const originalTip = currentAdv ? currentAdv.original_tip : null;
    const compositionNotes = (item && item.composition_notes) ? item.composition_notes : null;

    let mainOpinionHtml = '';
    if (isBest) {
      // AI specifically selected original as the best ratio
      const reasonText = bestReason || originalTip || compositionNotes || '촬영 당시의 피규어 구도와 여백이 가장 균형 잡혀 있습니다.';
      mainOpinionHtml = `<div id="crop-tip-desc" style="color:var(--ink);line-height:1.5;">${escapeHtml(reasonText)}</div>`;
    } else {
      // User clicked 'original', but AI recommended a crop ratio as Best Pick
      const originalText = originalTip || compositionNotes || '촬영 당시의 피규어 배치와 공간 여백이 온전히 담긴 원본 프레이밍입니다.';
      const comparisonHtml = bestKey ? `
        <div style="margin-top:8px;padding-top:8px;border-top:1px dashed var(--line);font-size:0.80rem;color:var(--muted);line-height:1.45;">
          💡 <b>AI 제안과의 비교</b>: AI는 피사체 집중도를 높이기 위해 <b>${escapeHtml(getCropRatioLabel(bestKey))}</b>을(를) 추천했습니다${bestReason ? ` (사유: ${escapeHtml(bestReason)})` : ''}. 하지만 피규어의 전신 실루엣이나 배경의 공간감을 온전히 살리고 싶을 때 원본 유지가 훌륭한 대안이 됩니다.
        </div>
      ` : '';

      mainOpinionHtml = `
        <div id="crop-tip-desc" style="color:var(--ink);line-height:1.5;">
          <div style="font-weight:700;color:var(--blue);margin-bottom:3px;font-size:0.82rem;">📐 원본 구도에 대한 AI 분석:</div>
          <div>${escapeHtml(originalText)}</div>
          ${comparisonHtml}
        </div>
      `;
    }

    return `
      <div id="crop-tip-box" class="sns-tip-box ${isBest ? 'is-best-tip-box' : ''}">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;flex-wrap:wrap;gap:6px;">
          <div style="display:flex;align-items:center;gap:6px;">
            <b id="crop-tip-title" style="color:var(--blue);font-size:0.92rem;">📷 원본 구도 유지 (No Crop)</b>
            ${isBest ? '<span class="best-ratio-badge-pill">👑 AI Best Pick</span>' : ''}
          </div>
          <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
            <button class="filter-btn" style="padding:4px 9px;font-size:0.76rem;background:var(--card);color:var(--muted);border-color:var(--line);" onclick="requestAllSnsCrops(${recordId}, this)">🔄 전체 일괄 재분석</button>
            <a class="upload-btn" style="padding:5px 12px;font-size:0.78rem;background:#0284c7;text-decoration:none;display:inline-flex;align-items:center;color:white;" href="/api/image/${recordId}?original=1" download target="_blank">📥 원본 고해상도 다운로드</a>
          </div>
        </div>
        ${mainOpinionHtml}
      </div>
    `;
  }

  if (box) {
    return `
      <div id="crop-tip-box" class="sns-tip-box ${isBest ? 'is-best-tip-box' : ''}">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;flex-wrap:wrap;gap:6px;">
          <div style="display:flex;align-items:center;gap:6px;">
            <b id="crop-tip-title" style="color:var(--blue);font-size:0.92rem;">${escapeHtml(box.ratio_label || target.tag)}</b>
            ${isBest ? '<span class="best-ratio-badge-pill">👑 AI Best Pick</span>' : ''}
          </div>
          <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
            <button class="filter-btn" style="padding:4px 9px;font-size:0.76rem;background:rgba(56,189,248,0.15);color:var(--blue);border-color:var(--line);" onclick="requestSingleSnsCrop('${ratioKey}', ${recordId}, this, true)">🔄 이 비율만 다시 제안</button>
            <button class="filter-btn" style="padding:4px 9px;font-size:0.76rem;background:var(--card);color:var(--muted);border-color:var(--line);" onclick="requestAllSnsCrops(${recordId}, this)">🔄 전체 4종 일괄 재분석</button>
            <button class="upload-btn" id="btn-crop-download" style="padding:5px 12px;font-size:0.78rem;background:#0284c7;" onclick="downloadCroppedImage('${ratioKey}', ${recordId})">✂️ 이 비율로 잘라 다운로드</button>
          </div>
        </div>
        <div id="crop-tip-desc" style="color:var(--ink);line-height:1.45;">${escapeHtml(box.composition_tip || '피사체 중심 추천 구도입니다.')}</div>
      </div>
    `;
  }

  return `
    <div id="crop-tip-box" style="background:var(--card-sub);padding:16px;border-radius:10px;font-size:0.85rem;border:1px dashed var(--line);text-align:center;">
      <div style="color:var(--blue);font-weight:700;margin-bottom:6px;font-size:0.92rem;">
        SNS 최적 크롭 제안이 아직 생성되지 않았습니다.
      </div>
      <div style="color:var(--muted);font-size:0.8rem;margin-bottom:12px;">
        단 1회의 Gemini 호출로 4대 규격(인스타 4:5, 1:1, X 16:9, 3:4)과 AI 자체 선정 최적 비율(원본 유지 포함)을 한 번에 분석합니다.
      </div>
      <button class="upload-btn" style="background:#0284c7;padding:8px 20px;font-size:0.86rem;margin:0 auto;display:inline-flex;" onclick="requestSingleSnsCrop('${ratioKey}', ${recordId}, this, false)">
        ✨ SNS 4대 규격 + 최적 비율 일괄 제안 받기 (1회 호출)
      </button>
    </div>
  `;
}

function renderSnsCaptionArea(currentAdv, recordId) {
  const hasCaption = currentAdv && currentAdv.social_caption;
  if (!hasCaption) {
    return `
      <div style="background:white;padding:12px 14px;border-radius:10px;font-size:0.85rem;border:1px solid #e0f2fe;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
        <span style="color:#64748b;">✍️ SNS 감성 캡션과 해시태그가 필요하신가요?</span>
        <button class="filter-btn" style="background:#0284c7;color:white;border-color:#0284c7;padding:5px 12px;font-size:0.78rem;" onclick="requestSnsCaption(${recordId}, this, false)">
          ✍️ SNS 캡션 & 해시태그 제안 받기
        </button>
      </div>
    `;
  }

  const hashtags = currentAdv.hashtags || [];
  return `
    <div style="background:white;padding:12px 14px;border-radius:10px;font-size:0.85rem;border:1px solid #e0f2fe;margin-bottom:8px;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
        <b style="color:#0369a1;">✍️ SNS 감성 캡션:</b>
        <div style="display:flex;gap:6px;">
          <button class="filter-btn" style="padding:2px 8px;font-size:0.74rem;" onclick="requestSnsCaption(${recordId}, this, true)">🔄 다시 생성</button>
          <button class="filter-btn" style="padding:2px 8px;font-size:0.74rem;" onclick="copyCaption(${recordId}, this)">📋 캡션 복사</button>
        </div>
      </div>
      <div style="color:#1e293b;white-space:pre-wrap;background:#f8fafc;padding:8px 12px;border-radius:6px;line-height:1.45;">${escapeHtml(currentAdv.social_caption)}</div>
    </div>

    <div style="background:white;padding:12px 14px;border-radius:10px;font-size:0.85rem;border:1px solid #e0f2fe;">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <b style="color:#0369a1;">🏷️ 추천 해시태그:</b>
        <button class="filter-btn" style="padding:2px 8px;font-size:0.74rem;" onclick="copyHashtags(${recordId}, this)">📋 전체 복사</button>
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:6px;">
        ${hashtags.map(t => `<span class="tag-pill" style="background:#e0f2fe;color:#0369a1;">${escapeHtml(t)}</span>`).join('')}
      </div>
    </div>
  `;
}

function getImageRenderedRect(img) {
  if (!img) return null;
  const cW = img.clientWidth;
  const cH = img.clientHeight;
  const nW = img.naturalWidth || 1;
  const nH = img.naturalHeight || 1;
  if (!cW || !cH) return null;

  const containerRatio = cW / cH;
  const imgRatio = nW / nH;
  let rW, rH, offX, offY;

  if (imgRatio > containerRatio) {
    rW = cW;
    rH = cW / imgRatio;
    offX = 0;
    offY = (cH - rH) / 2;
  } else {
    rH = cH;
    rW = cH * imgRatio;
    offX = (cW - rW) / 2;
    offY = 0;
  }

  return {
    left: img.offsetLeft + offX,
    top: img.offsetTop + offY,
    width: rW,
    height: rH,
    naturalW: nW,
    naturalH: nH
  };
}

function calculateExactCrop(ratioKey, box, naturalW, naturalH) {
  if (ratioKey === 'original' || !box) return null;
  const target = TARGET_CROP_RATIOS[ratioKey] || { name: '1:1', tag: '1:1', w: 1, h: 1, ratio: 1.0 };
  const targetRatio = target.ratio;

  const cx = ((box.xmin + box.xmax) / 2) * naturalW;
  const cy = ((box.ymin + box.ymax) / 2) * naturalH;

  const rawW = Math.max(1, (box.xmax - box.xmin) * naturalW);
  const rawH = Math.max(1, (box.ymax - box.ymin) * naturalH);

  let cropW, cropH;
  if (rawW / rawH > targetRatio) {
    cropW = rawW;
    cropH = cropW / targetRatio;
  } else {
    cropH = rawH;
    cropW = cropH * targetRatio;
  }

  if (cropW > naturalW) {
    cropW = naturalW;
    cropH = cropW / targetRatio;
  }
  if (cropH > naturalH) {
    cropH = naturalH;
    cropW = cropH * targetRatio;
  }
  if (cropW > naturalW) {
    cropW = naturalW;
    cropH = cropW / targetRatio;
  }

  let sx = cx - cropW / 2;
  let sy;
  if (cropH < rawH) {
    // When height trimming is required (e.g. portrait photo into 1:1 or 16:9),
    // anchor near box.ymin (the top of the subject / intended headroom) rather than
    // blind midpoint centering which cuts off the head and centers on the belly.
    const headroomBuffer = Math.min(box.ymin * naturalH, cropH * 0.05);
    sy = (box.ymin * naturalH) - headroomBuffer;
    if (sy + cropH > naturalH) {
      sy = naturalH - cropH;
    }
  } else {
    sy = cy - cropH / 2;
  }

  if (sx < 0) sx = 0;
  if (sx + cropW > naturalW) sx = naturalW - cropW;
  if (sy < 0) sy = 0;
  if (sy + cropH > naturalH) sy = naturalH - cropH;

  sx = Math.max(0, sx);
  sy = Math.max(0, sy);

  let intH = Math.max(1, Math.floor(cropH));
  let intW = Math.max(1, Math.round(intH * targetRatio));

  if (intW > naturalW) {
    intW = Math.floor(naturalW);
    intH = Math.max(1, Math.round(intW / targetRatio));
  }
  if (intH > naturalH) {
    intH = Math.floor(naturalH);
    intW = Math.max(1, Math.round(intH * targetRatio));
  }

  const intSx = Math.max(0, Math.min(naturalW - intW, Math.round(sx)));
  const intSy = Math.max(0, Math.min(naturalH - intH, Math.round(sy)));

  return {
    target,
    sx: intSx,
    sy: intSy,
    sw: intW,
    sh: intH,
    normX: intSx / naturalW,
    normY: intSy / naturalH,
    normW: intW / naturalW,
    normH: intH / naturalH
  };
}

function selectCropRatio(ratioKey, recordId) {
  const item = (typeof allData !== 'undefined' && Array.isArray(allData))
    ? allData.find(d => d.id === recordId)
    : null;
  currentCropRatioKey = ratioKey;

  document.querySelectorAll('.crop-ratio-btn').forEach(b => b.classList.remove('active'));
  const activeBtn = document.getElementById(`btn-crop-${ratioKey}`);
  if (activeBtn) activeBtn.classList.add('active');

  const currentAdv = item ? (item.sns_advice || {}) : {};
  const box = currentAdv[ratioKey];

  const detailArea = document.getElementById('crop-ratio-detail-area');
  if (detailArea) {
    detailArea.innerHTML = renderCropRatioDetailArea(ratioKey, currentAdv, recordId);
  }

  if (ratioKey === 'original') {
    currentCropBox = null;
    const overlay = document.getElementById('crop-box-overlay');
    if (overlay) overlay.style.display = 'none';
  } else if (box) {
    currentCropBox = box;
    repositionCropOverlay();
  } else {
    currentCropBox = null;
    const overlay = document.getElementById('crop-box-overlay');
    if (overlay) overlay.style.display = 'none';
  }
}

function clearCropOverlay() {
  currentCropBox = null;
  currentCropRatioKey = null;
  document.querySelectorAll('.crop-ratio-btn').forEach(b => b.classList.remove('active'));
  const overlay = document.getElementById('crop-box-overlay');
  if (overlay) overlay.style.display = 'none';
}

function repositionCropOverlay() {
  const overlay = document.getElementById('crop-box-overlay');
  const img = document.getElementById('detail-modal-img');
  if (!overlay || !img || !currentCropBox || !currentCropRatioKey || currentCropRatioKey === 'original') {
    if (overlay) overlay.style.display = 'none';
    return;
  }
  if (img.classList.contains('zoomed')) {
    overlay.style.display = 'none';
    return;
  }

  const rect = getImageRenderedRect(img);
  if (!rect || rect.width <= 0 || rect.height <= 0) {
    overlay.style.display = 'none';
    return;
  }

  const crop = calculateExactCrop(currentCropRatioKey, currentCropBox, rect.naturalW, rect.naturalH);
  if (!crop) {
    overlay.style.display = 'none';
    return;
  }

  const top = Math.round(rect.top + crop.normY * rect.height);
  const left = Math.round(rect.left + crop.normX * rect.width);
  const width = Math.round(crop.normW * rect.width);
  const height = Math.round(crop.normH * rect.height);

  overlay.style.top = `${top}px`;
  overlay.style.left = `${left}px`;
  overlay.style.width = `${width}px`;
  overlay.style.height = `${height}px`;
  overlay.style.display = 'block';

  const badge = document.getElementById('crop-overlay-badge');
  if (badge) {
    badge.textContent = `${crop.target.tag} (${crop.sw}×${crop.sh})`;
  }
}

if (typeof window !== 'undefined') {
  window.addEventListener('resize', repositionCropOverlay);
}

async function downloadCroppedImage(ratioKey, recordId) {
  if (ratioKey === 'original') {
    const a = document.createElement('a');
    a.href = `/api/image/${recordId}?original=1`;
    a.download = '';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    return;
  }

  const item = (typeof allData !== 'undefined' && Array.isArray(allData))
    ? allData.find(d => d.id === recordId)
    : null;
  if (!item || !item.sns_advice) return;
  const box = item.sns_advice[ratioKey];
  if (!box) return;

  const img = new Image();
  img.crossOrigin = 'anonymous';
  img.src = `/api/image/${recordId}?original=1`;
  await new Promise((resolve, reject) => {
    img.onload = resolve;
    img.onerror = reject;
  });

  const origW = img.naturalWidth || 1;
  const origH = img.naturalHeight || 1;
  const crop = calculateExactCrop(ratioKey, box, origW, origH);
  if (!crop || crop.sw <= 0 || crop.sh <= 0) return;

  const canvas = document.createElement('canvas');
  canvas.width = crop.sw;
  canvas.height = crop.sh;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, crop.sx, crop.sy, crop.sw, crop.sh, 0, 0, crop.sw, crop.sh);

  const safeName = item.filename.replace(/\.[^/.]+$/, '');
  const outName = `${safeName}_${ratioKey.replace('crop_', '')}_${crop.sw}x${crop.sh}.png`;
  canvas.toBlob((blob) => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = outName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 'image/png');
}

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    const orig = btn.textContent;
    btn.textContent = '✓ 복사됨!';
    setTimeout(() => { btn.textContent = orig; }, 1500);
  } catch (err) {
    prompt('텍스트 복사:', text);
  }
}

async function copyCaption(recordId, btn) {
  const item = (typeof allData !== 'undefined' && Array.isArray(allData))
    ? allData.find(d => d.id === recordId)
    : null;
  if (!item || !item.sns_advice) return;
  await copyText(item.sns_advice.social_caption, btn);
}

async function copyHashtags(recordId, btn) {
  const item = (typeof allData !== 'undefined' && Array.isArray(allData))
    ? allData.find(d => d.id === recordId)
    : null;
  if (!item || !item.sns_advice) return;
  await copyText(item.sns_advice.hashtags.join(' '), btn);
}

async function requestSingleSnsCrop(ratioKey, recordId, btn, force=false) {
  const origText = btn.textContent;
  btn.textContent = 'Gemini 맞춤 구도 분석 중...';
  btn.disabled = true;

  try {
    const data = await (window.API ? window.API.fetchSnsCrop(recordId, ratioKey, force) : (await fetch(`/api/sns-crop/${ratioKey}/${recordId}${force ? '?force=true' : ''}`, { method: 'POST' })).json());
    if (data.success && (data.crop_box || ratioKey === 'original' || data.advice)) {
      const item = (typeof allData !== 'undefined' && Array.isArray(allData))
        ? allData.find(d => d.id === recordId)
        : null;
      if (item) {
        if (!item.sns_advice) item.sns_advice = {};
        // The server may have generated all 4 ratios at once; keep every cached crop.
        Object.assign(item.sns_advice, data.advice || {});
        if (data.crop_box) {
          item.sns_advice[ratioKey] = data.crop_box;
        }
        currentCropRatioKey = ratioKey;
        const container = document.getElementById('sns-advice-content');
        if (container) {
          container.innerHTML = renderSnsAdviceContent(item.sns_advice, recordId);
        }
        selectCropRatio(ratioKey, recordId);
      }
    } else {
      alert(`크롭 제안 생성 실패: ${data.error || '알 수 없는 오류'}`);
      btn.textContent = origText;
      btn.disabled = false;
    }
  } catch (err) {
    alert(`오류: ${err.message}`);
    btn.textContent = origText;
    btn.disabled = false;
  }
}

async function requestAllSnsCrops(recordId, btn) {
  const origText = btn.textContent;
  btn.textContent = 'Gemini 4종 구도 일괄 분석 중...';
  btn.disabled = true;

  try {
    const data = await (window.API ? window.API.fetchSnsCrop(recordId, 'all', true) : (await fetch(`/api/sns-crop/all/${recordId}?force=true`, { method: 'POST' })).json());
    if (data.success && data.advice) {
      const item = (typeof allData !== 'undefined' && Array.isArray(allData))
        ? allData.find(d => d.id === recordId)
        : null;
      if (item) {
        if (!item.sns_advice) item.sns_advice = {};
        Object.assign(item.sns_advice, data.advice);
        const bestRatio = item.sns_advice.best_ratio_key || currentCropRatioKey || 'instagram_crop_4_5';
        currentCropRatioKey = bestRatio;
        const container = document.getElementById('sns-advice-content');
        if (container) {
          container.innerHTML = renderSnsAdviceContent(item.sns_advice, recordId);
        }
        selectCropRatio(bestRatio, recordId);
      }
    } else {
      alert(`크롭 제안 생성 실패: ${data.error || '알 수 없는 오류'}`);
      btn.textContent = origText;
      btn.disabled = false;
    }
  } catch (err) {
    alert(`오류: ${err.message}`);
    btn.textContent = origText;
    btn.disabled = false;
  }
}

async function requestSnsCaption(recordId, btn, force=false) {
  const origText = btn.textContent;
  btn.textContent = 'Gemini 캡션 생성 중...';
  btn.disabled = true;

  try {
    const data = await (window.API ? window.API.fetchSnsCaption(recordId, force) : (await fetch(`/api/sns-caption/${recordId}${force ? '?force=true' : ''}`, { method: 'POST' })).json());
    if (data.success && data.social_caption) {
      const item = (typeof allData !== 'undefined' && Array.isArray(allData))
        ? allData.find(d => d.id === recordId)
        : null;
      if (item) {
        if (!item.sns_advice) item.sns_advice = {};
        item.sns_advice.social_caption = data.social_caption;
        item.sns_advice.hashtags = data.hashtags;
        const captionArea = document.getElementById('sns-caption-area');
        if (captionArea) {
          captionArea.innerHTML = renderSnsCaptionArea(item.sns_advice, recordId);
        }
      }
    } else {
      alert(`캡션 생성 실패: ${data.error || '알 수 없는 오류'}`);
      btn.textContent = origText;
      btn.disabled = false;
    }
  } catch (err) {
    alert(`오류: ${err.message}`);
    btn.textContent = origText;
    btn.disabled = false;
  }
}

async function requestSnsAdvice(recordId, btn) {
  await requestSingleSnsCrop('instagram_crop_4_5', recordId, btn, false);
}
