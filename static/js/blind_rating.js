// static/js/blind_rating.js - Blind Random Rating & Speed Feedback Subsystem (Option A)

function safeBlindEscape(str) {
  if (typeof escapeHtml === 'function') return escapeHtml(str);
  if (typeof window !== 'undefined' && typeof window.escapeHtml === 'function') return window.escapeHtml(str);
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

let blindState = {
  mode: 'setup', // 'setup', 'grading', 'summary'
  pool: [],
  currentIndex: 0,
  ratedCount: 0,
  autoNextDelay: 1500, // ms
  autoNextTimer: null,
  isRevealed: false,
  sessionResults: [],
  selectedSource: 'unrated',
  selectedLimit: 20,
  currentScoreInput: '',
};

function openBlindRatingModal() {
  const modal = document.getElementById('blind-rating-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  renderBlindSetup();
  window.addEventListener('keydown', handleBlindKeydown);
}

function closeBlindRatingModal(e) {
  if (e && e.target && e.target.id !== 'blind-rating-modal' && !e.target.classList.contains('close-btn') && !e.target.classList.contains('blind-close-trigger')) return;
  if (blindState.mode === 'grading' && blindState.sessionResults.length > 0 && blindState.currentIndex < blindState.pool.length) {
    if (!confirm('블라인드 채점이 진행 중입니다. 종료하시겠습니까? (지금까지 매긴 점수는 안전하게 저장되었습니다)')) {
      return;
    }
  }
  clearBlindAutoTimer();
  window.removeEventListener('keydown', handleBlindKeydown);
  const modal = document.getElementById('blind-rating-modal');
  if (modal) modal.style.display = 'none';
  blindState.mode = 'setup';

  // 갤러리 및 통계 화면 새로고침
  if (typeof renderScoreDistPanel === 'function') renderScoreDistPanel();
  if (typeof renderGallery === 'function') renderGallery();
  if (typeof renderTagInsights === 'function') renderTagInsights();
}

function clearBlindAutoTimer() {
  if (blindState.autoNextTimer) {
    clearTimeout(blindState.autoNextTimer);
    blindState.autoNextTimer = null;
  }
}

function renderBlindSetup() {
  clearBlindAutoTimer();
  blindState.mode = 'setup';
  blindState.sessionResults = [];
  blindState.currentIndex = 0;
  blindState.isRevealed = false;

  const dataList = (typeof allData !== 'undefined' ? allData : (window.allData || []));
  const unratedPhotos = dataList.filter(d => d.user_score === null || d.user_score === undefined);
  const filteredPhotos = typeof filterList === 'function' ? filterList(dataList) : dataList;
  const totalPhotos = dataList.length;

  const container = document.getElementById('blind-body-container');
  if (!container) return;

  if (totalPhotos === 0) {
    container.innerHTML = `
      <div style="text-align:center;padding:60px 20px;">
        <div style="font-size:3.5rem;margin-bottom:12px;">📷</div>
        <h3 style="font-size:1.3rem;margin-bottom:8px;color:white;">평가할 사진이 없습니다</h3>
        <p style="color:#94a3b8;margin-bottom:20px;">먼저 사진을 업로드하고 AI 분석을 완료해 주세요.</p>
        <button class="upload-btn" style="margin:0 auto;" onclick="closeBlindRatingModal(); openUploadModal();">+ 사진 업로드하기</button>
      </div>
    `;
    return;
  }

  container.innerHTML = `
    <div class="blind-setup-card">
      <div class="blind-setup-header">
        <span style="font-size:2rem;">🎯</span>
        <div>
          <h3 style="margin:0;font-size:1.3rem;color:white;font-weight:800;">블라인드 내 점수 매기기</h3>
          <p style="margin:4px 0 0;font-size:0.86rem;color:#94a3b8;">
            AI 점수와 코멘트를 완전히 가린 상태에서, 순수한 시각으로 나만의 점수를 매깁니다.<br>
            점수를 확정하는 즉시 <strong>AI 점수와 차이(Option A)</strong>가 공개됩니다!
          </p>
        </div>
      </div>

      <div style="margin-top:24px;">
        <label class="blind-setup-label">1. 평가 대상 사진 범위</label>
        <div class="blind-option-grid">
          <label class="blind-option-box ${blindState.selectedSource === 'unrated' ? 'active' : ''}" onclick="selectBlindSource('unrated')">
            <input type="radio" name="blind-source" value="unrated" ${blindState.selectedSource === 'unrated' ? 'checked' : ''} style="display:none;">
            <div style="font-weight:700;color:white;font-size:0.95rem;display:flex;align-items:center;gap:6px;">
              <span>⭐ 아직 평가 안 한 사진만</span>
              <span class="blind-badge-pill">${unratedPhotos.length}장</span>
            </div>
            <div style="font-size:0.8rem;color:#94a3b8;margin-top:4px;">내 점수가 아직 없는 사진만 모아서 집중 채점합니다. (추천)</div>
          </label>

          <label class="blind-option-box ${blindState.selectedSource === 'all' ? 'active' : ''}" onclick="selectBlindSource('all')">
            <input type="radio" name="blind-source" value="all" ${blindState.selectedSource === 'all' ? 'checked' : ''} style="display:none;">
            <div style="font-weight:700;color:white;font-size:0.95rem;display:flex;align-items:center;gap:6px;">
              <span>🎲 전체 사진 중 무작위</span>
              <span class="blind-badge-pill">${totalPhotos}장</span>
            </div>
            <div style="font-size:0.8rem;color:#94a3b8;margin-top:4px;">이미 매긴 점수와 상관없이 전체에서 무작위 셔플합니다.</div>
          </label>

          <label class="blind-option-box ${blindState.selectedSource === 'filtered' ? 'active' : ''}" onclick="selectBlindSource('filtered')">
            <input type="radio" name="blind-source" value="filtered" ${blindState.selectedSource === 'filtered' ? 'checked' : ''} style="display:none;">
            <div style="font-weight:700;color:white;font-size:0.95rem;display:flex;align-items:center;gap:6px;">
              <span>🔍 현재 필터/컬렉션 사진</span>
              <span class="blind-badge-pill">${filteredPhotos.length}장</span>
            </div>
            <div style="font-size:0.8rem;color:#94a3b8;margin-top:4px;">현재 대시보드에서 선택한 컬렉션이나 필터 대상만 채점합니다.</div>
          </label>
        </div>
      </div>

      <div style="margin-top:22px;">
        <label class="blind-setup-label">2. 이번 세션 채점 규모 (장수)</label>
        <div id="blind-limit-chips" style="display:flex;gap:10px;flex-wrap:wrap;">
          ${[10, 20, 30, 50, -1].map(num => `
            <button type="button" class="blind-chip-btn ${blindState.selectedLimit === num ? 'active' : ''}" onclick="selectBlindLimit(${num})">
              ${num === -1 ? '전체 전부' : `${num}장`}
            </button>
          `).join('')}
        </div>
      </div>

      <div style="margin-top:22px;">
        <label class="blind-setup-label">3. AI 점수 공개 후 자동 넘김 속도</label>
        <div style="display:flex;gap:10px;align-items:center;">
          <select id="blind-delay-select" class="select-input" style="background:#0f172a;border-color:#334155;color:white;padding:8px 12px;" onchange="blindState.autoNextDelay = parseInt(this.value)">
            <option value="1200" ${blindState.autoNextDelay === 1200 ? 'selected' : ''}>빠르게 (1.2초 후 자동 이동)</option>
            <option value="1800" ${blindState.autoNextDelay === 1800 ? 'selected' : ''}>적당하게 (1.8초 후 자동 이동)</option>
            <option value="2500" ${blindState.autoNextDelay === 2500 ? 'selected' : ''}>여유있게 (2.5초 후 자동 이동)</option>
            <option value="0" ${blindState.autoNextDelay === 0 ? 'selected' : ''}>수동 넘김 (스페이스/엔터/버튼으로만 이동)</option>
          </select>
          <span style="font-size:0.8rem;color:#94a3b8;">* 점수 공개 중 언제든 [스페이스]나 [엔터]를 누르면 즉시 다음으로 이동합니다.</span>
        </div>
      </div>

      <div style="margin-top:32px;display:flex;justify-content:flex-end;gap:12px;">
        <button class="filter-btn" style="background:#334155;border-color:#475569;color:#e2e8f0;padding:12px 24px;font-size:0.92rem;" onclick="closeBlindRatingModal()">취소</button>
        <button class="upload-btn" style="background:linear-gradient(135deg, #0284c7, #2563eb);padding:12px 30px;font-size:1rem;font-weight:800;" onclick="startBlindRatingSession()">
          🎯 무작위 셔플 후 채점 시작
        </button>
      </div>
    </div>
  `;
}

function selectBlindSource(src) {
  blindState.selectedSource = src;
  renderBlindSetup();
}

function selectBlindLimit(limit) {
  blindState.selectedLimit = limit;
  renderBlindSetup();
}

function startBlindRatingSession() {
  const dataList = (typeof allData !== 'undefined' ? allData : (window.allData || []));
  let pool = [];

  if (blindState.selectedSource === 'unrated') {
    pool = dataList.filter(d => d.user_score === null || d.user_score === undefined);
  } else if (blindState.selectedSource === 'filtered') {
    pool = typeof filterList === 'function' ? [...filterList(dataList)] : [...dataList];
  } else {
    pool = [...dataList];
  }

  if (pool.length === 0) {
    alert('선택한 조건에 해당하는 사진이 없습니다.');
    return;
  }

  // Fisher-Yates Random Shuffle
  for (let i = pool.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }

  if (blindState.selectedLimit > 0 && pool.length > blindState.selectedLimit) {
    pool = pool.slice(0, blindState.selectedLimit);
  }

  blindState.pool = pool;
  blindState.currentIndex = 0;
  blindState.ratedCount = 0;
  blindState.sessionResults = [];
  blindState.mode = 'grading';
  blindState.isRevealed = false;

  renderBlindGradingCard();
}

function renderBlindGradingCard() {
  clearBlindAutoTimer();
  blindState.isRevealed = false;

  const currentIdx = blindState.currentIndex;
  const total = blindState.pool.length;

  if (currentIdx >= total) {
    renderBlindSummary();
    return;
  }

  const item = blindState.pool[currentIdx];
  const progressPct = Math.min(100, Math.round(((currentIdx) / total) * 100));

  const container = document.getElementById('blind-body-container');
  if (!container) return;

  const quickScores = [5.0, 6.0, 7.0, 7.5, 8.0, 8.5, 9.0, 9.5, 10.0];

  // 메타데이터 (카메라/조리개 등 기술 정보만 표시, AI 평가 관련 숨김)
  const metaParts = [];
  if (item.camera_model) metaParts.push(item.camera_model);
  if (item.focal_length) metaParts.push(`${item.focal_length}mm`);
  if (item.f_number) metaParts.push(`F${Number(item.f_number).toFixed(1)}`);
  if (item.shutter_speed) metaParts.push(item.shutter_speed);
  if (item.iso) metaParts.push(`ISO ${item.iso}`);
  const metaStr = metaParts.length > 0 ? metaParts.join(' • ') : '촬영 메타데이터 없음';

  container.innerHTML = `
    <div class="blind-arena-layout">
      <!-- 헤더 프로그레스 바 -->
      <div class="blind-arena-header">
        <div style="display:flex;align-items:center;gap:12px;">
          <span class="blind-badge-step">진행 ${currentIdx + 1} / ${total}장</span>
          <span style="font-size:0.85rem;color:#94a3b8;font-weight:600;">${safeBlindEscape(item.filename || item.photo_filename || '사진')}</span>
        </div>
        <div style="display:flex;align-items:center;gap:10px;">
          <button type="button" class="blind-action-btn" onclick="skipBlindItem()" title="점수를 매기지 않고 다음 사진으로 넘어갑니다 (단축키: Tab 또는 Space)">건너뛰기 (Skip) ↷</button>
          <button type="button" class="blind-action-btn" onclick="closeBlindRatingModal()" title="채점 종료 (단축키: ESC)">✕ 종료</button>
        </div>
      </div>
      <div class="blind-progress-track">
        <div class="blind-progress-fill" style="width:${progressPct}%;"></div>
      </div>

      <!-- 메인 콘텐츠: 사진 + 채점 패널 -->
      <div class="blind-main-split">
        <!-- 좌측: 고화질 사진 뷰어 -->
        <div class="blind-photo-column">
          <div class="blind-img-wrapper" id="blind-img-wrapper" onclick="toggleBlindImgZoom()">
            <img id="blind-active-photo" src="/api/image/${item.id}" alt="Blind Photo" class="blind-main-img">
            <div class="blind-zoom-hint">🔍 클릭하여 확대/축소</div>
          </div>
          <div class="blind-photo-meta">
            <span class="blind-cat-badge">📁 ${safeBlindEscape(item.figure_category || '일반 피규어')}</span>
            <span style="color:#94a3b8;font-size:0.8rem;">${safeBlindEscape(metaStr)}</span>
          </div>
        </div>

        <!-- 우측: 채점 인터랙션 패널 -->
        <div class="blind-control-column">
          <div class="blind-panel-card">
            <!-- 1. 블라인드 안내 또는 점수 공개 배너 (동적 치환) -->
            <div id="blind-feedback-area">
              <div class="blind-guide-box">
                <div style="font-size:1.15rem;font-weight:800;color:white;margin-bottom:6px;display:flex;align-items:center;gap:8px;">
                  <span>🔒</span> <span>AI 점수 블라인드 상태</span>
                </div>
                <p style="font-size:0.84rem;color:#cbd5e1;margin:0;line-height:1.5;">
                  선입견 없이 사진의 구도, 포즈, 조명, 초점의 디테일을 감상하고 직관적인 나만의 점수를 매겨보세요.
                </p>
              </div>
            </div>

            <!-- 2. 점수 입력 버튼 그룹 -->
            <div style="margin-top:20px;">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
                <label style="font-size:0.88rem;font-weight:700;color:#f8fafc;">⚡ 빠른 점수 선택 (원클릭)</label>
                <span style="font-size:0.75rem;color:#38bdf8;font-weight:600;">키보드 [1]~[9], [0=10점]</span>
              </div>
              <div class="blind-quick-scores">
                ${quickScores.map(score => `
                  <button type="button" class="blind-score-btn" onclick="submitBlindScore(${score})">
                    <span class="blind-score-val">${score.toFixed(1)}</span>
                    ${score === 10 ? '<span class="blind-score-sub">만점</span>' : ''}
                  </button>
                `).join('')}
              </div>
            </div>

            <!-- 3. 정밀 직접 입력 (0.1 단위) -->
            <div style="margin-top:18px;">
              <label style="font-size:0.86rem;font-weight:700;color:#f8fafc;display:block;margin-bottom:8px;">✏️ 직접 입력 (0.0 ~ 10.0)</label>
              <div style="display:flex;gap:8px;align-items:center;">
                <div style="position:relative;flex:1;">
                  <input type="number" id="blind-custom-input" class="blind-input-box" min="0" max="10" step="0.1" placeholder="예: 8.3" onkeydown="handleBlindInputKey(event)">
                  <span style="position:absolute;right:12px;top:50%;transform:translateY(-50%);color:#94a3b8;font-weight:700;font-size:0.85rem;">/ 10</span>
                </div>
                <button type="button" class="upload-btn" style="padding:10px 20px;font-weight:800;background:#0284c7;" onclick="submitCustomBlindScore()">확정 (Enter)</button>
              </div>
            </div>

            <!-- 4. 단축키 가이드 -->
            <div class="blind-shortcut-bar">
              <span>⌨️ 단축키:</span>
              <kbd>1~9</kbd> 해당 점수 |
              <kbd>0</kbd> 10점 |
              <kbd>Space</kbd> 다음/스킵 |
              <kbd>←</kbd> 이전 |
              <kbd>ESC</kbd> 닫기
            </div>
          </div>
        </div>
      </div>
    </div>
  `;

  const inputEl = document.getElementById('blind-custom-input');
  if (inputEl) {
    // 자동 포커스 시 숫자키 단축키 충돌을 방지하기 위해 blur 상태 유지하거나 안내
  }
}

function handleBlindInputKey(e) {
  if (e.key === 'Enter') {
    e.preventDefault();
    submitCustomBlindScore();
  }
}

function submitCustomBlindScore() {
  const input = document.getElementById('blind-custom-input');
  if (!input) return;
  const val = parseFloat(input.value);
  if (isNaN(val) || val < 0 || val > 10) {
    alert('점수는 0.0점에서 10.0점 사이로 입력해 주세요.');
    return;
  }
  submitBlindScore(Math.round(val * 10) / 10);
}

async function submitBlindScore(userScore) {
  if (blindState.isRevealed) return; // 이미 점수 공개 중이면 중복 방지
  clearBlindAutoTimer();

  const item = blindState.pool[blindState.currentIndex];
  if (!item) return;

  blindState.isRevealed = true;
  userScore = Math.max(0.0, Math.min(10.0, Math.round(userScore * 10) / 10));

  // 1. 백엔드 API 점수 저장
  try {
    if (typeof API !== 'undefined' && API.ratePhoto) {
      await API.ratePhoto(item.id, userScore);
    } else {
      await fetch('/api/rate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: item.id, user_score: userScore }),
      });
    }

    // 로컬 데이터 동기화
    const dataList = (typeof allData !== 'undefined' ? allData : (window.allData || []));
    const target = dataList.find(d => d.id === item.id);
    if (target) target.user_score = userScore;
    item.user_score = userScore;
  } catch (err) {
    console.error('점수 저장 실패:', err);
  }

  // 2. 결과 기록 (세션 요약용)
  const aiScore = typeof item.final_score === 'number' ? item.final_score : 0.0;
  const diff = Math.round((userScore - aiScore) * 10) / 10;
  blindState.sessionResults.push({
    id: item.id,
    filename: item.filename || item.photo_filename || '사진',
    photo_filename: item.filename || item.photo_filename || '사진',
    user_score: userScore,
    ai_score: aiScore,
    grade: item.grade || 'B',
    diff: diff,
    final_reason: item.final_reason || (item.strengths && item.strengths[0]) || '',
  });
  blindState.ratedCount++;

  // 3. Option A: 즉시 AI 점수 & 차이 Reveal 연출!
  renderBlindRevealAnimation(item, userScore, aiScore, diff);
}

function renderBlindRevealAnimation(item, userScore, aiScore, diff) {
  const feedbackArea = document.getElementById('blind-feedback-area');
  if (!feedbackArea) return;

  let badgeClass, badgeTitle, badgeColor, subMsg;
  const absDiff = Math.abs(diff);

  if (absDiff <= 0.3) {
    badgeClass = 'reveal-match';
    badgeTitle = '✨ 통찰 일치! (Perfect Sync)';
    badgeColor = '#10b981'; // 초록
    subMsg = '👤 나와 🤖 AI의 눈높이가 거의 완벽하게 일치합니다!';
  } else if (diff > 0) {
    badgeClass = 'reveal-higher';
    badgeTitle = `🔥 내 호평 (+${diff.toFixed(1)}점)`;
    badgeColor = '#38bdf8'; // 스카이블루
    subMsg = `내가 AI(${aiScore.toFixed(1)}점)보다 +${diff.toFixed(1)}점 더 높게 평가했습니다. (취향 부합)`;
  } else {
    badgeClass = 'reveal-stricter';
    badgeTitle = `🧐 엄격한 눈 (${diff.toFixed(1)}점)`;
    badgeColor = '#f59e0b'; // 앰버
    subMsg = `내가 AI(${aiScore.toFixed(1)}점)보다 ${absDiff.toFixed(1)}점 더 꼼꼼하고 엄격하게 평가했습니다.`;
  }

  const aiReason = item.final_reason ? `"${safeBlindEscape(item.final_reason)}"` : '';

  feedbackArea.innerHTML = `
    <div class="blind-reveal-card ${badgeClass}">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
        <span style="font-size:0.85rem;font-weight:800;color:${badgeColor};display:flex;align-items:center;gap:6px;">
          ${badgeTitle}
        </span>
        <span class="blind-tag-grade">AI 등급: ${safeBlindEscape(item.grade || 'B')}</span>
      </div>

      <div class="blind-score-compare-row">
        <div class="blind-score-box user">
          <div class="score-label">👤 내 점수</div>
          <div class="score-val">${userScore.toFixed(1)}</div>
        </div>
        <div class="blind-vs-sign">VS</div>
        <div class="blind-score-box ai">
          <div class="score-label">🤖 AI 점수</div>
          <div class="score-val">${aiScore.toFixed(1)}</div>
        </div>
      </div>

      <div style="font-size:0.82rem;color:#e2e8f0;margin-top:10px;text-align:center;">
        ${subMsg}
      </div>

      ${aiReason ? `
        <div class="blind-ai-quote">
          💬 <strong>AI 한줄평:</strong> ${aiReason}
        </div>
      ` : ''}

      <div class="blind-countdown-wrap">
        <div class="blind-countdown-text">
          ${blindState.autoNextDelay > 0 ? `잠시 후 다음 사진으로 이동합니다...` : `다음 사진으로 넘어가려면 [스페이스]를 누르세요.`}
        </div>
        <button type="button" class="upload-btn" style="padding:6px 16px;font-size:0.82rem;background:#0284c7;" onclick="nextBlindItem()">
          즉시 다음 사진 (Space/Enter) →
        </button>
      </div>
    </div>
  `;

  // 4. 자동 다음 타이머 설정
  if (blindState.autoNextDelay > 0) {
    blindState.autoNextTimer = setTimeout(() => {
      nextBlindItem();
    }, blindState.autoNextDelay);
  }
}

function nextBlindItem() {
  clearBlindAutoTimer();
  blindState.currentIndex++;
  renderBlindGradingCard();
}

function skipBlindItem() {
  clearBlindAutoTimer();
  blindState.currentIndex++;
  renderBlindGradingCard();
}

function toggleBlindImgZoom() {
  const imgWrapper = document.getElementById('blind-img-wrapper');
  if (imgWrapper) {
    imgWrapper.classList.toggle('zoomed');
  }
}

function renderBlindSummary() {
  clearBlindAutoTimer();
  blindState.mode = 'summary';

  const container = document.getElementById('blind-body-container');
  if (!container) return;

  const results = blindState.sessionResults;
  const totalRated = results.length;

  if (totalRated === 0) {
    container.innerHTML = `
      <div style="text-align:center;padding:60px 20px;">
        <div style="font-size:3rem;margin-bottom:12px;">🤷‍♂️</div>
        <h3 style="font-size:1.3rem;margin-bottom:8px;color:white;">평가된 사진이 없습니다</h3>
        <p style="color:#94a3b8;margin-bottom:20px;">모든 사진을 건너뛰었습니다.</p>
        <button class="upload-btn" style="margin:0 auto;" onclick="renderBlindSetup()">다시 시도하기</button>
      </div>
    `;
    return;
  }

  const avgUser = results.reduce((acc, r) => acc + r.user_score, 0) / totalRated;
  const avgAi = results.reduce((acc, r) => acc + r.ai_score, 0) / totalRated;
  const avgDiff = Math.round((avgUser - avgAi) * 10) / 10;

  // 정렬을 통한 Best Match & Max Divergence 찾기
  const sortedByAbsDiff = [...results].sort((a, b) => Math.abs(a.diff) - Math.abs(b.diff));
  const bestMatch = sortedByAbsDiff[0];
  const maxDivergence = sortedByAbsDiff[sortedByAbsDiff.length - 1];

  let tendencyText = '';
  if (Math.abs(avgDiff) <= 0.2) {
    tendencyText = '🤖 AI와 👤 나의 평가 기준이 완벽에 가깝게 조화를 이루고 있습니다!';
  } else if (avgDiff > 0) {
    tendencyText = `👤 AI보다 평균 +${avgDiff.toFixed(1)}점 더 관대하고 피규어의 매력을 높게 사는 성향입니다.`;
  } else {
    tendencyText = `👤 AI보다 평균 ${Math.abs(avgDiff).toFixed(1)}점 더 엄격하고 섬세한 시각을 가지셨습니다.`;
  }

  container.innerHTML = `
    <div class="blind-summary-container">
      <div style="text-align:center;margin-bottom:28px;">
        <div style="font-size:3rem;margin-bottom:8px;">🎉</div>
        <h2 style="font-size:1.5rem;font-weight:900;color:white;margin:0 0 6px;">블라인드 채점 세션 완료!</h2>
        <p style="color:#94a3b8;font-size:0.9rem;margin:0;">
          총 <strong>${totalRated}장</strong>의 사진을 편향 없이 평가하셨습니다. 매겨진 점수는 DB에 영구 저장되었습니다.
        </p>
      </div>

      <!-- 종합 통계 카드 -->
      <div class="blind-stat-grid">
        <div class="blind-stat-card">
          <div class="stat-title">평가 완료</div>
          <div class="stat-number" style="color:#38bdf8;">${totalRated} <span style="font-size:1rem;color:#94a3b8;">장</span></div>
        </div>
        <div class="blind-stat-card">
          <div class="stat-title">👤 내 평균 점수</div>
          <div class="stat-number" style="color:#60a5fa;">${avgUser.toFixed(1)} <span style="font-size:1rem;color:#94a3b8;">점</span></div>
        </div>
        <div class="blind-stat-card">
          <div class="stat-title">🤖 AI 평균 점수</div>
          <div class="stat-number" style="color:#c084fc;">${avgAi.toFixed(1)} <span style="font-size:1rem;color:#94a3b8;">점</span></div>
        </div>
        <div class="blind-stat-card">
          <div class="stat-title">평균 격차 (User - AI)</div>
          <div class="stat-number" style="color:${avgDiff >= 0 ? '#38bdf8' : '#fbbf24'};">
            ${avgDiff >= 0 ? `+${avgDiff.toFixed(1)}` : avgDiff.toFixed(1)} <span style="font-size:1rem;color:#94a3b8;">점</span>
          </div>
        </div>
      </div>

      <div class="blind-tendency-banner">
        💡 <strong>평가 성향 분석:</strong> ${tendencyText}
      </div>

      <!-- 하이라이트 사진 2장 비교 (Best Sync vs Max Gap) -->
      <div style="margin-top:24px;display:grid;grid-template-columns:1fr 1fr;gap:16px;">
        <!-- Best Sync -->
        <div class="blind-highlight-card">
          <div class="highlight-badge sync">🤝 가장 생각이 통했던 컷 (일치)</div>
          <div style="display:flex;gap:12px;align-items:center;margin-top:10px;">
            <img src="/api/image/${bestMatch.id}" class="highlight-img" alt="Best Sync">
            <div>
              <div style="font-weight:700;color:white;font-size:0.88rem;">${safeBlindEscape(bestMatch.filename || bestMatch.photo_filename || '사진')}</div>
              <div style="font-size:0.8rem;color:#94a3b8;margin-top:4px;">
                👤 내 점수: <strong>${bestMatch.user_score.toFixed(1)}</strong> / 🤖 AI: <strong>${bestMatch.ai_score.toFixed(1)}</strong>
              </div>
              <div style="font-size:0.75rem;color:#10b981;font-weight:700;margin-top:2px;">
                차이: ${bestMatch.diff >= 0 ? `+${bestMatch.diff.toFixed(1)}` : bestMatch.diff.toFixed(1)}점
              </div>
            </div>
          </div>
        </div>

        <!-- Max Divergence -->
        <div class="blind-highlight-card">
          <div class="highlight-badge gap">⚡ 가장 시각 차이가 컸던 컷 (개성)</div>
          <div style="display:flex;gap:12px;align-items:center;margin-top:10px;">
            <img src="/api/image/${maxDivergence.id}" class="highlight-img" alt="Max Gap">
            <div>
              <div style="font-weight:700;color:white;font-size:0.88rem;">${safeBlindEscape(maxDivergence.filename || maxDivergence.photo_filename || '사진')}</div>
              <div style="font-size:0.8rem;color:#94a3b8;margin-top:4px;">
                👤 내 점수: <strong>${maxDivergence.user_score.toFixed(1)}</strong> / 🤖 AI: <strong>${maxDivergence.ai_score.toFixed(1)}</strong>
              </div>
              <div style="font-size:0.75rem;color:#f59e0b;font-weight:700;margin-top:2px;">
                차이: ${maxDivergence.diff >= 0 ? `+${maxDivergence.diff.toFixed(1)}` : maxDivergence.diff.toFixed(1)}점
              </div>
            </div>
          </div>
        </div>
      </div>

      <div style="margin-top:32px;display:flex;justify-content:center;gap:14px;">
        <button class="filter-btn" style="background:#334155;border-color:#475569;color:#e2e8f0;padding:12px 24px;font-size:0.95rem;" onclick="renderBlindSetup()">
          🔄 새 세션 시작하기
        </button>
        <button class="upload-btn" style="background:linear-gradient(135deg, #0284c7, #2563eb);padding:12px 28px;font-size:0.95rem;font-weight:800;" onclick="closeBlindRatingModal()">
          ✅ 대시보드로 돌아가기
        </button>
      </div>
    </div>
  `;
}

function handleBlindKeydown(e) {
  const modal = document.getElementById('blind-rating-modal');
  if (!modal || modal.style.display !== 'flex') return;

  // ESC: 닫기
  if (e.key === 'Escape') {
    closeBlindRatingModal();
    return;
  }

  if (blindState.mode !== 'grading') return;

  // 인풋창에 포커스가 있으면 글로벌 키 방지
  if (document.activeElement && document.activeElement.id === 'blind-custom-input') {
    return;
  }

  // Reveal 상태일 때: 스페이스나 엔터 누르면 즉시 다음 사진
  if (blindState.isRevealed) {
    if (e.key === ' ' || e.key === 'Enter' || e.key === 'ArrowRight') {
      e.preventDefault();
      nextBlindItem();
    }
    return;
  }

  // 스페이스 or ArrowRight: 건너뛰기
  if (e.key === ' ' || e.key === 'ArrowRight') {
    e.preventDefault();
    skipBlindItem();
    return;
  }

  // 숫자 단축키 (1 ~ 9: 1.0 ~ 9.0점, 0: 10.0점)
  if (e.key >= '1' && e.key <= '9') {
    e.preventDefault();
    submitBlindScore(parseFloat(e.key));
  } else if (e.key === '0') {
    e.preventDefault();
    submitBlindScore(10.0);
  }
}

window.safeBlindEscape = safeBlindEscape;
window.openBlindRatingModal = openBlindRatingModal;
window.closeBlindRatingModal = closeBlindRatingModal;
window.selectBlindSource = selectBlindSource;
window.selectBlindLimit = selectBlindLimit;
window.startBlindRatingSession = startBlindRatingSession;
window.renderBlindSetup = renderBlindSetup;
window.renderBlindGradingCard = renderBlindGradingCard;
window.submitBlindScore = submitBlindScore;
window.submitCustomBlindScore = submitCustomBlindScore;
window.skipBlindItem = skipBlindItem;
window.nextBlindItem = nextBlindItem;
window.toggleBlindImgZoom = toggleBlindImgZoom;
