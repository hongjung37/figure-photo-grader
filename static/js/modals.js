// static/js/modals.js - Upload, Usage Stats, and Model Settings Modals

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

async function getFilesFromEntry(entry, rootFolderName = '') {
  if (entry.isFile) {
    return new Promise((resolve) => {
      entry.file(f => {
        if (rootFolderName) {
          try { f._folderName = rootFolderName; } catch (e) {}
        }
        resolve([f]);
      }, () => resolve([]));
    });
  } else if (entry.isDirectory) {
    const folderLabel = rootFolderName || entry.name || '';
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
      const fList = await getFilesFromEntry(child, folderLabel);
      subFiles.push(...fList);
    }
    return subFiles;
  }
  return [];
}

function escapeUsageHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

let currentUsagePeriod = 'all';
let currentUsageDateFrom = '';
let currentUsageDateTo = '';

const USAGE_PERIOD_LABELS = {
  all: '전체',
  today: '오늘',
  yesterday: '어제',
  '24h': '최근 24시간',
  '7d': '최근 7일',
  '30d': '최근 30일',
  custom: '직접 지정'
};

function updateUsagePeriodPillsUI() {
  const pills = document.querySelectorAll('.usage-period-btn');
  pills.forEach(btn => {
    btn.classList.toggle('active', btn.getAttribute('data-period') === currentUsagePeriod);
  });
}

async function setUsagePeriod(period) {
  currentUsagePeriod = period || 'all';
  currentUsageDateFrom = '';
  currentUsageDateTo = '';
  const fromEl = document.getElementById('usage-date-from');
  const toEl = document.getElementById('usage-date-to');
  if (fromEl) fromEl.value = '';
  if (toEl) toEl.value = '';
  updateUsagePeriodPillsUI();
  await refreshUsageStats();
}

function onUsageCustomDateChange() {
  const fromEl = document.getElementById('usage-date-from');
  const toEl = document.getElementById('usage-date-to');
  currentUsageDateFrom = fromEl ? (fromEl.value || '').trim() : '';
  currentUsageDateTo = toEl ? (toEl.value || '').trim() : '';
}

async function applyUsageCustomDate() {
  onUsageCustomDateChange();
  if (!currentUsageDateFrom && !currentUsageDateTo) {
    currentUsagePeriod = 'all';
  } else {
    currentUsagePeriod = 'custom';
  }
  updateUsagePeriodPillsUI();
  await refreshUsageStats();
}

async function syncUsageWithDashboardScope() {
  const fromEl = document.getElementById('date-scope-from');
  const toEl = document.getElementById('date-scope-to');
  const dFrom = (typeof currentDateFrom !== 'undefined' ? currentDateFrom : (fromEl ? fromEl.value : '')) || '';
  const dTo = (typeof currentDateTo !== 'undefined' ? currentDateTo : (toEl ? toEl.value : '')) || '';
  const dPreset = (typeof currentDatePreset !== 'undefined' ? currentDatePreset : 'all');

  const uFrom = document.getElementById('usage-date-from');
  const uTo = document.getElementById('usage-date-to');

  if (dPreset === 'today') {
    currentUsagePeriod = 'today';
    currentUsageDateFrom = '';
    currentUsageDateTo = '';
    if (uFrom) uFrom.value = '';
    if (uTo) uTo.value = '';
  } else if (dPreset === 'yesterday') {
    currentUsagePeriod = 'yesterday';
    currentUsageDateFrom = '';
    currentUsageDateTo = '';
    if (uFrom) uFrom.value = '';
    if (uTo) uTo.value = '';
  } else if (dPreset === '7d') {
    currentUsagePeriod = '7d';
    currentUsageDateFrom = '';
    currentUsageDateTo = '';
    if (uFrom) uFrom.value = '';
    if (uTo) uTo.value = '';
  } else if (dPreset === '30d') {
    currentUsagePeriod = '30d';
    currentUsageDateFrom = '';
    currentUsageDateTo = '';
    if (uFrom) uFrom.value = '';
    if (uTo) uTo.value = '';
  } else if (dFrom || dTo) {
    currentUsagePeriod = 'custom';
    currentUsageDateFrom = dFrom;
    currentUsageDateTo = dTo;
    if (uFrom) uFrom.value = dFrom;
    if (uTo) uTo.value = dTo;
  } else {
    currentUsagePeriod = 'all';
    currentUsageDateFrom = '';
    currentUsageDateTo = '';
    if (uFrom) uFrom.value = '';
    if (uTo) uTo.value = '';
  }
  updateUsagePeriodPillsUI();
  await refreshUsageStats();
}

async function openUsageModal() {
  const modal = document.getElementById('usage-modal');
  if (modal) modal.style.display = 'flex';

  const scopeActive = (typeof isDateScopeActive === 'function') ? isDateScopeActive() : false;
  const dFrom = (typeof currentDateFrom !== 'undefined' ? currentDateFrom : '');
  const dTo = (typeof currentDateTo !== 'undefined' ? currentDateTo : '');
  const dPreset = (typeof currentDatePreset !== 'undefined' ? currentDatePreset : '');

  const uFrom = document.getElementById('usage-date-from');
  const uTo = document.getElementById('usage-date-to');

  if (scopeActive && (dFrom || dTo || dPreset === 'today' || dPreset === 'yesterday')) {
    if (dPreset === 'today') {
      currentUsagePeriod = 'today';
      currentUsageDateFrom = '';
      currentUsageDateTo = '';
      if (uFrom) uFrom.value = '';
      if (uTo) uTo.value = '';
    } else if (dPreset === 'yesterday') {
      currentUsagePeriod = 'yesterday';
      currentUsageDateFrom = '';
      currentUsageDateTo = '';
      if (uFrom) uFrom.value = '';
      if (uTo) uTo.value = '';
    } else {
      currentUsagePeriod = 'custom';
      currentUsageDateFrom = dFrom;
      currentUsageDateTo = dTo;
      if (uFrom) uFrom.value = dFrom;
      if (uTo) uTo.value = dTo;
    }
  }

  updateUsagePeriodPillsUI();
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
  if (!body) return;
  body.innerHTML = '<p style="color:var(--muted);">불러오는 중...</p>';
  try {
    const d = await API.fetchUsageStats(currentUsagePeriod, currentUsageDateFrom, currentUsageDateTo);
    let activeLabel = USAGE_PERIOD_LABELS[currentUsagePeriod] || currentUsagePeriod;
    if (currentUsagePeriod === 'custom' || currentUsageDateFrom || currentUsageDateTo) {
      if (currentUsageDateFrom && currentUsageDateTo) {
        activeLabel = `${currentUsageDateFrom} ~ ${currentUsageDateTo}`;
      } else if (currentUsageDateFrom) {
        activeLabel = `${currentUsageDateFrom} 이후`;
      } else {
        activeLabel = `${currentUsageDateTo} 이전`;
      }
    }

    if (!d.total_calls) {
      if (currentUsagePeriod !== 'all') {
        body.innerHTML = `
          <div style="padding:32px 16px;text-align:center;background:rgba(148,163,184,0.06);border-radius:12px;margin-top:8px;">
            <p style="color:var(--muted);font-size:0.92rem;margin-bottom:12px;">선택한 기간(<b>${escapeUsageHtml(activeLabel)}</b>) 동안 기록된 API 호출이 없습니다.</p>
            <button class="upload-btn" style="padding:6px 14px;font-size:0.8rem;background:var(--accent,#38bdf8);border:none;border-radius:6px;cursor:pointer;" onclick="setUsagePeriod('all')">전체 통계 보기</button>
          </div>`;
      } else {
        body.innerHTML = '<p style="color:var(--muted);">아직 기록된 API 호출이 없습니다. 사진을 분석하면 여기에 쌓입니다.</p>';
      }
      return;
    }
    const sum = (k) => d.by_task.reduce((a, t) => a + (t[k] || 0), 0);
    const totalIn = sum('input_tokens');
    const totalOut = sum('output_tokens');
    const totalCached = d.total_cached_tokens != null ? d.total_cached_tokens : sum('cached_tokens');
    const cacheHitPct = totalIn > 0 ? ((totalCached / totalIn) * 100).toFixed(1) : '0.0';
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
    const modelRows = (d.by_model || []).map(m => {
      const inTok = m.input_tokens || 0;
      const cachedTok = m.cached_tokens || 0;
      const hitRate = inTok > 0 ? ((cachedTok / inTok) * 100).toFixed(1) + '%' : '-';
      return `<tr>
        <td style="${td}">${fmtModelBadge(m.used_model)}</td>
        <td style="${td}">${m.calls}</td>
        <td style="${td}">${m.calls - (m.successes || 0)}</td>
        <td style="${td}">${inTok.toLocaleString()}</td>
        <td style="${td};font-weight:700;color:${cachedTok > 0 ? '#10b981' : 'inherit'};">${cachedTok ? '⚡ ' + cachedTok.toLocaleString() : '-'}</td>
        <td style="${td}">${hitRate}</td>
        <td style="${td}">${(m.output_tokens || 0).toLocaleString()}</td>
        <td style="${td}">${((m.avg_ms || 0) / 1000).toFixed(1)}s</td>
      </tr>`;
    }).join('');
    const taskRows = d.by_task.map(t => {
      const cachedTok = t.cached_tokens || 0;
      return `<tr>
        <td style="${td}">${escapeUsageHtml(t.task)}</td>
        <td style="${td}">${t.calls}</td>
        <td style="${td}">${t.calls - (t.successes || 0)}</td>
        <td style="${td}">${t.fallbacks || 0}</td>
        <td style="${td}">${t.retries || 0}</td>
        <td style="${td}">${(t.input_tokens || 0).toLocaleString()}</td>
        <td style="${td};font-weight:700;color:${cachedTok > 0 ? '#10b981' : 'inherit'};">${cachedTok ? '⚡ ' + cachedTok.toLocaleString() : '-'}</td>
        <td style="${td}">${(t.output_tokens || 0).toLocaleString()}</td>
        <td style="${td}">${((t.avg_ms || 0) / 1000).toFixed(1)}s</td>
      </tr>`;
    }).join('');
    const recentRows = d.recent.map(r => {
      const inTok = r.input_tokens;
      const cached = r.cached_tokens;
      let tokStr = '-';
      if (inTok != null) {
        if (cached && cached > 0) {
          const pct = Math.round((cached / inTok) * 100);
          tokStr = `${inTok.toLocaleString()} <span style="color:#10b981;font-size:0.75rem;font-weight:700;">(⚡${cached.toLocaleString()} ${pct}%)</span> / ${(r.output_tokens || 0).toLocaleString()}`;
        } else {
          tokStr = `${inTok.toLocaleString()} / ${(r.output_tokens || 0).toLocaleString()}`;
        }
      }
      const rawIso = r.created_at || '';
      let timeLabel = rawIso.replace('T', ' ').slice(5, 19);
      try {
        if (rawIso) {
          const dt = new Date(rawIso);
          if (!isNaN(dt.getTime())) {
            const m = String(dt.getMonth() + 1).padStart(2, '0');
            const day = String(dt.getDate()).padStart(2, '0');
            const h = String(dt.getHours()).padStart(2, '0');
            const min = String(dt.getMinutes()).padStart(2, '0');
            const s = String(dt.getSeconds()).padStart(2, '0');
            timeLabel = `${m}-${day} ${h}:${min}:${s}`;
          }
        }
      } catch (e) {}
      return `<tr>
        <td style="${td}">${escapeUsageHtml(timeLabel)}</td>
        <td style="${td}">${escapeUsageHtml(r.task)}</td>
        <td style="${td}">${fmtModelBadge(r.used_model)}${r.fallback ? ` <span style="color:#d97706;font-size:0.73rem;">(폴백)</span>` : ''}</td>
        <td style="${td}">${((r.duration_ms || 0) / 1000).toFixed(1)}s</td>
        <td style="${td}">${tokStr}</td>
        <td style="${td}color:${r.success ? 'var(--teal)' : '#e11d48'};" title="${escapeUsageHtml(r.error || '')}">${r.success ? '성공' : '실패'}</td>
      </tr>`;
    }).join('');
    const periodNotice = currentUsagePeriod !== 'all'
      ? `<div style="margin-bottom:12px;font-size:0.8rem;color:var(--muted);display:flex;align-items:center;gap:6px;">
           <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#10b981;"></span>
           조회 기간: <strong style="color:var(--ink);">${escapeUsageHtml(activeLabel)}</strong> 집계 결과입니다 (총 ${d.total_calls.toLocaleString()}건).
         </div>`
      : '';
    body.innerHTML = `
      ${periodNotice}
      <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px;">
        ${card('총 호출', d.total_calls.toLocaleString())}${card('실패', failures.toLocaleString())}${card('총 입력 토큰', totalIn.toLocaleString())}${card('⚡ 캐시 적중', `${totalCached.toLocaleString()} <span style="font-size:0.74rem;color:#10b981;font-weight:700;">(${cacheHitPct}%)</span>`)}${card('출력 토큰', totalOut.toLocaleString())}
      </div>
      ${modelRows ? `
        <h3 style="margin:0 0 6px;font-size:0.95rem;">🤖 모델별 사용량 & 캐시 적중률</h3>
        <table style="width:100%;border-collapse:collapse;margin-bottom:18px;">
          <thead><tr><th style="${th}">사용 모델</th><th style="${th}">호출</th><th style="${th}">실패</th><th style="${th}">총 입력</th><th style="${th}">⚡ 캐시 적중</th><th style="${th}">적중률</th><th style="${th}">출력</th><th style="${th}">평균 시간</th></tr></thead>
          <tbody>${modelRows}</tbody>
        </table>
      ` : ''}
      <h3 style="margin:0 0 6px;font-size:0.95rem;">🛠️ 기능별 사용량</h3>
      <table style="width:100%;border-collapse:collapse;margin-bottom:18px;">
        <thead><tr><th style="${th}">작업</th><th style="${th}">호출</th><th style="${th}">실패</th><th style="${th}">폴백</th><th style="${th}">재시도</th><th style="${th}">총 입력</th><th style="${th}">⚡ 캐시 적중</th><th style="${th}">출력</th><th style="${th}">평균 시간</th></tr></thead>
        <tbody>${taskRows}</tbody>
      </table>
      <h3 style="margin:0 0 6px;font-size:0.95rem;">🕒 최근 호출 (해당 기간 내 최신 ${Math.min(30, d.recent.length)}건 / 총 ${d.total_calls.toLocaleString()}건 중)</h3>
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr><th style="${th}">시각(로컬)</th><th style="${th}">작업</th><th style="${th}">모델</th><th style="${th}">소요</th><th style="${th}">입력(⚡캐시) / 출력 tok</th><th style="${th}">결과</th></tr></thead>
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
    photo_grading: 'luna',
    lightroom_advice: 'lite',
    sns_crop: 'lite',
    sns_caption: 'lite'
  };
  const gEl = document.getElementById('setting-model-grading');
  const lrEl = document.getElementById('setting-model-lr');
  const cropEl = document.getElementById('setting-model-crop');
  const capEl = document.getElementById('setting-model-caption');
  const statusEl = document.getElementById('model-settings-status');

  if (gEl) gEl.value = s.photo_grading || 'luna';
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
  document.querySelectorAll('[id^="reanalyze-tier-"]').forEach(el => {
    el.value = newSettings.photo_grading;
  });
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

function selectUploadAnalysisMode(mode) {
  const normalized = mode === 'fast' ? 'fast' : 'full';
  const inputEl = document.getElementById('upload-analysis-mode');
  if (inputEl) inputEl.value = normalized;

  const fullBtn = document.getElementById('upload-mode-full-btn');
  const fastBtn = document.getElementById('upload-mode-fast-btn');
  const hintEl = document.getElementById('upload-mode-hint');

  if (fullBtn && fastBtn) {
    if (normalized === 'fast') {
      fastBtn.style.border = '2px solid #d97706';
      fastBtn.style.background = 'rgba(245,158,11,0.10)';
      fullBtn.style.border = '1px solid var(--line)';
      fullBtn.style.background = 'var(--card-sub)';
    } else {
      fullBtn.style.border = '2px solid #4f46e5';
      fullBtn.style.background = 'rgba(79,70,229,0.08)';
      fastBtn.style.border = '1px solid var(--line)';
      fastBtn.style.background = 'var(--card-sub)';
    }
  }

  if (hintEl) {
    if (normalized === 'fast') {
      hintEl.innerHTML = '⚡ <strong>경량 분석(Fast Culling) 모드:</strong> 50~100장 대량 셀렉용으로 <b>5대 점수 · 초점 판정 · 1줄 핵심 사유</b>만 빠르게 추출합니다. (세부 노트·미학 태그 생략, 추후 A컷만 정밀 업그레이드 가능)';
    } else {
      hintEl.innerHTML = '🔍 <strong>정밀 분석(Full) 모드:</strong> 구도·조명·색감·기술 상세 비평과 강점/개선점, 8대 미학 태그를 모두 생성합니다.';
    }
  }
}

function onUploadCollectionSelectChange(sel) {
  const newInput = document.getElementById('upload-new-collection-name');
  if (!newInput) return;
  if (sel && sel.value === '__new__') {
    newInput.style.display = 'block';
    newInput.focus();
  } else {
    newInput.style.display = 'none';
  }
}
window.onUploadCollectionSelectChange = onUploadCollectionSelectChange;

function populateUploadCollectionSelect() {
  const sel = document.getElementById('upload-collection-select');
  if (!sel) return;
  const cols = (typeof window.allCollections !== 'undefined' && Array.isArray(window.allCollections)) ? window.allCollections : [];
  const activeCol = (typeof window.currentCollectionFilter !== 'undefined') ? String(window.currentCollectionFilter) : 'all';
  let html = '<option value="">선택 안 함 (미분류 상태로 업로드)</option>';
  cols.forEach(c => {
    const isSel = (activeCol === String(c.id)) ? 'selected' : '';
    html += `<option value="${c.id}" ${isSel}>🗂️ ${escapeUsageHtml(c.name)} (${c.count || 0}장)</option>`;
  });
  html += '<option value="__new__">+ 새 컬렉션 직접 입력하여 생성...</option>';
  sel.innerHTML = html;
  const newInput = document.getElementById('upload-new-collection-name');
  if (newInput) {
    newInput.style.display = 'none';
    newInput.value = '';
  }
}
window.populateUploadCollectionSelect = populateUploadCollectionSelect;

function onUploadMedianChange(checked) {
  const sel = document.getElementById('upload-sample-count');
  if (sel) {
    sel.disabled = !checked;
    sel.style.opacity = checked ? '1' : '0.5';
    sel.style.pointerEvents = checked ? 'auto' : 'none';
  }
  if (window.ModelSettings) {
    window.ModelSettings.set('median_sampling', checked ? 'true' : 'false');
  }
}
window.onUploadMedianChange = onUploadMedianChange;

function openUploadModal() {
  document.getElementById('upload-modal').style.display = 'flex';
  const uploadTierEl = document.getElementById('upload-tier');
  if (uploadTierEl && window.ModelSettings) {
    uploadTierEl.value = window.ModelSettings.get('photo_grading');
  }
  const medianBox = document.getElementById('upload-median');
  if (medianBox && window.ModelSettings) {
    medianBox.checked = (window.ModelSettings.get('median_sampling') === 'true');
  }
  if (medianBox) {
    onUploadMedianChange(medianBox.checked);
  }
  const currentModeEl = document.getElementById('upload-analysis-mode');
  selectUploadAnalysisMode(currentModeEl && currentModeEl.value === 'fast' ? 'fast' : 'full');
  populateUploadCollectionSelect();
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
  try {
    const tier = document.getElementById('upload-tier').value;
    const category = document.getElementById('upload-category').value;
    const modeInput = document.getElementById('upload-analysis-mode');
    const analysisMode = (modeInput && modeInput.value === 'fast') ? 'fast' : 'full';
    const force = document.getElementById('upload-force').checked;
    const medianBox = document.getElementById('upload-median');
    const sampleCountSelect = document.getElementById('upload-sample-count');
    const useMedian = medianBox ? medianBox.checked : false;
    const chosenSamples = sampleCountSelect ? (parseInt(sampleCountSelect.value, 10) || 3) : 3;
    const sampleCount = useMedian ? chosenSamples : 1;
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
    const modeTag = analysisMode === 'fast' ? '⚡ 경량 선별' : '🔍 정밀 분석';
    const sampleTag = sampleCount > 1 ? ` (🎯 ${sampleCount}회 병렬)` : '';

    for (let i = 0; i < total; i++) {
      const file = files[i];
      const currentNum = i + 1;
      const pct = Math.round(((i) / total) * 100);
      progPercent.textContent = `${pct}%`;
      progBar.style.width = `${pct}%`;
      progText.textContent = `[${currentNum} / ${total}장] AI 모델 ${modeTag}${sampleTag} 진행 중...`;
      progFile.textContent = `현재 분석 파일: ${file.name} (${(file.size / 1024 / 1024).toFixed(1)}MB)`;

      const formData = new FormData();
      formData.append('image', file, file.name);
      formData.append('tier', tier);
      formData.append('category', category);
      formData.append('analysis_mode', analysisMode);
      formData.append('sample_count', String(sampleCount));

      const colSelectEl = document.getElementById('upload-collection-select');
      const colNewInputEl = document.getElementById('upload-new-collection-name');
      const autoFolderBox = document.getElementById('upload-auto-folder-collection');
      const selectedColVal = colSelectEl ? colSelectEl.value : '';
      let fileFolderName = file._folderName || '';
      if (!fileFolderName && file.webkitRelativePath && file.webkitRelativePath.includes('/')) {
        fileFolderName = file.webkitRelativePath.split('/')[0].trim();
      }
      if (selectedColVal === '__new__' && colNewInputEl && colNewInputEl.value.trim()) {
        formData.append('collection_name', colNewInputEl.value.trim());
      } else if (selectedColVal && /^\d+$/.test(selectedColVal)) {
        formData.append('collection_id', selectedColVal);
      } else if ((!autoFolderBox || autoFolderBox.checked) && fileFolderName) {
        formData.append('collection_name', fileFolderName);
      }

      try {
        const result = await API.uploadPhoto(formData, force);
        if (result.success) {
          successCount++;
          const dupNote = result.duplicate ? ' (이미 분석된 사진 - API 호출 생략)' : '';
          const sampleNote = (result.sampled_scores && result.sampled_scores.length > 1)
            ? ` [중앙값: ${result.sampled_scores.join(', ')}]`
            : '';
          status.textContent = `✓ [${currentNum}/${total}] ${file.name} 완료${dupNote} (${result.analysis.final_score.toFixed(1)}점${sampleNote} - ${result.analysis.figure_category})`;
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
  } catch (err) {
    isBatchUploading = false;
    alert(`업로드 처리 중 오류 발생: ${err.message}`);
  }
}

// --- Window-level Drag & Drop Prevention & Auto-Upload ---
if (typeof window !== 'undefined') {
  window.addEventListener('dragover', (e) => {
    e.preventDefault();
  });

  window.addEventListener('drop', async (e) => {
    e.preventDefault();
    const dropZone = document.getElementById('drop-zone');
    if (dropZone && (e.target === dropZone || dropZone.contains(e.target))) {
      return;
    }

    if (isBatchUploading) return;

    let collected = [];
    const items = e.dataTransfer && e.dataTransfer.items;
    if (items && items.length > 0 && items[0].webkitGetAsEntry) {
      for (let i = 0; i < items.length; i++) {
        const entry = items[i].webkitGetAsEntry();
        if (entry) {
          const fList = await getFilesFromEntry(entry);
          collected.push(...fList);
        }
      }
    } else if (e.dataTransfer && e.dataTransfer.files) {
      collected = Array.from(e.dataTransfer.files);
    }

    const validFiles = collected.filter(isImageFile);
    if (validFiles.length > 0) {
      openUploadModal();
      await processBatchUpload(validFiles);
    }
  });

  window.setUsagePeriod = setUsagePeriod;
  window.refreshUsageStats = refreshUsageStats;
  window.onUsageCustomDateChange = onUsageCustomDateChange;
  window.applyUsageCustomDate = applyUsageCustomDate;
  window.syncUsageWithDashboardScope = syncUsageWithDashboardScope;
}
