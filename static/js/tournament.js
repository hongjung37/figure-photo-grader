// static/js/tournament.js - Blind 1:1 Tournament Culling Subsystem

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
