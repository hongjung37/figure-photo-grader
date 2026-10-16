// static/js/tag_insights.js - Visual Tag Analytics & 1:1 Photo Comparison View

let currentView = 'gallery'; // 'gallery', 'compare', 'insights'
let insightsRatingMode = 'ai'; // 'ai', 'user', 'diff'
let insightsMinCount = 2;

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
                ${catTags.length ? catTags.slice(0, 6).map((t, idx) => renderCategoryTagRow(t)).join('') : `<div style="font-size:0.78rem;color:var(--muted);padding:14px;text-align:center;">최소 등록 기준(${insightsMinCount}장)을 만족하는 태그가 아직 없습니다.</div>`}
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
  if (!selA || !selB) return;
  const options = allData.map(d => `<option value="${d.id}">${escapeHtml(d.filename)} (${d.final_score.toFixed(1)}점 - ${escapeHtml(d.grade)})</option>`).join('');
  selA.innerHTML = options;
  selB.innerHTML = options;
  if (allData.length > 1) selB.selectedIndex = 1;
}

function updateComparison() {
  const selA = document.getElementById('comp-a-select');
  const selB = document.getElementById('comp-b-select');
  if (!selA || !selB) return;
  const idA = parseInt(selA.value);
  const idB = parseInt(selB.value);
  const a = allData.find(d => d.id === idA);
  const b = allData.find(d => d.id === idB);
  if (!a || !b) return;

  const content = document.getElementById('compare-content');
  if (!content) return;
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
