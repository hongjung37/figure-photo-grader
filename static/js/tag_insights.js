// static/js/tag_insights.js - Visual Tag Analytics & 1:1 Photo Comparison View

if (typeof window.escapeHtml !== 'function') {
  window.escapeHtml = function(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  };
}
var escapeHtml = window.escapeHtml;

let currentView = 'gallery'; // 'gallery', 'compare', 'insights'
let insightsDimension = 'tag'; // 'tag', 'focal'
let insightsRatingMode = 'ai'; // 'ai', 'user', 'diff'
let insightsMinCount = 2;

window.currentView = currentView;
window.insightsDimension = insightsDimension;
window.insightsRatingMode = insightsRatingMode;
window.insightsMinCount = insightsMinCount;

const FOCAL_BANDS_DEF = [
  { key: 'wide_24',      label: '24mm 이하 (광각)',      short_label: '24mm 광각',       icon: '🌄', order: 1, min: 0,  max: 28,   desc: '넓은 배경 공간감과 강한 원근감 · 주변부 왜곡과 배경 정리에 유의' },
  { key: 'semi_wide_35', label: '35mm 부근 (준광각)',    short_label: '35mm 준광각',     icon: '🌿', order: 2, min: 28, max: 40,   desc: '피사체와 주변 환경의 스토리텔링 조화 · 자연스러운 일상 스냅' },
  { key: 'standard_50',  label: '50mm 부근 (표준)',      short_label: '50mm 표준',       icon: '📷', order: 3, min: 40, max: 60,   desc: '사람 시야에 가장 가까운 표준 원근감 · 안정적인 피규어 전신/반신 주력 화각' },
  { key: 'portrait_85',  label: '70~85mm (준망원)',      short_label: '70~85mm 준망원',  icon: '🌟', order: 4, min: 60, max: 90,   desc: '왜곡 억제와 아름다운 배경 흐림(보케) · 피규어 인물화의 황금 화각' },
  { key: 'tele_100',     label: '100mm+ (망원/매크로)',  short_label: '100mm+ 망원/접사', icon: '🔬', order: 5, min: 90, max: 9999, desc: '강력한 배경 압축과 피사체 분리 · 눈동자 데칼 및 미세 조형 클로즈업' },
  { key: 'unknown',      label: '미식별 (EXIF 없음)',    short_label: '화각 미식별',     icon: '❓', order: 6, min: null, max: null, desc: '메타데이터가 없는 웹 다운로드 또는 캡처 이미지' }
];
window.FOCAL_BANDS_DEF = FOCAL_BANDS_DEF;

const CLIENT_STRENGTH_THEMES = [
  { theme: '🎯 칼초점 & 눈동자 디테일', keywords: ['초점', '눈동자', '선명', '데칼', '디테일', '명확'] },
  { theme: '✨ 배경 분리 & 보케(심도)', keywords: ['분리', '흐림', '보케', '심도', '아웃포커싱'] },
  { theme: '🎨 색감 대비 & 톤 조화', keywords: ['색', '톤', '파스텔', '화사', '대비', '조화'] },
  { theme: '🌿 공간감 & 스토리텔링 연출', keywords: ['소품', '공간', '맥락', '상황', '분위기', '야외', '레이어', '배경'] },
  { theme: '📐 안정적인 구도 & 프레이밍', keywords: ['구도', '프레이밍', '실루엣', '배치', '포즈', '시선'] },
  { theme: '💡 자연스러운 빛 & 조명 활용', keywords: ['자연광', '조명', '광원', '빛', '역광'] }
];

const CLIENT_IMPROVEMENT_THEMES = [
  { theme: '💡 입체감 부족 (림라이트·측광 필요)', keywords: ['림라이트', '사광', '측광', '측면', '입체감', '보조광'] },
  { theme: '✂️ 가장자리 잘림 & 여백 답답함', keywords: ['여백', '잘림', '크롭', '답답', '가장자리', '하단', '머리 위'] },
  { theme: '🧹 주변 산만함 & 시선 분산 요소', keywords: ['시선 분산', '산만', '정리', '덜어', '빈 벽', '배경의', '가리지', '프레임 밖'] },
  { theme: '🔍 피사체 비중 부족 (더 크게 촬영 권장)', keywords: ['크게 담', '비중을 줄', '존재감', '주인공으로', '타이트하게'] },
  { theme: '☀️ 반사 하이라이트 & 노출·대비 제어', keywords: ['반사', '하이라이트', '확산', '대비', '어두운', '노출', '밝기', '붉은 조명'] },
  { theme: '🎯 초점·피사계심도 보완', keywords: ['초점', '흔들림', '심도', '조리개', '선명'] }
];

function extractFocalLengthMm(item) {
  if (!item) return null;
  if (item.focal_length_mm !== undefined && item.focal_length_mm !== null) {
    const v = Number(item.focal_length_mm);
    if (!Number.isNaN(v) && v >= 1 && v <= 2000) return Math.round(v * 10) / 10;
  }
  const exif = item.exif || {};
  const det = item.detected_camera_settings || {};
  const candidates = [
    exif.FocalLengthIn35mmFilm,
    exif.FocalLengthIn35mmFormat,
    exif.FocalLength,
    det.focal_length,
    det.FocalLength
  ];
  for (const raw of candidates) {
    if (raw === undefined || raw === null) continue;
    if (Array.isArray(raw) && raw.length === 2 && Number(raw[1]) !== 0) {
      const f = Number(raw[0]) / Number(raw[1]);
      if (!Number.isNaN(f) && f >= 1 && f <= 2000) return Math.round(f * 10) / 10;
    }
    const m = String(raw).match(/(\d+(?:\.\d+)?)/);
    if (m) {
      const f = parseFloat(m[1]);
      if (!Number.isNaN(f) && f >= 1 && f <= 2000) return Math.round(f * 10) / 10;
    }
  }
  const lensStr = String(det.lens || exif.LensModel || '').trim();
  if (lensStr && !/\d+\s*-\s*\d+\s*mm/i.test(lensStr)) {
    const mp = lensStr.match(/\b(\d{2,3}(?:\.\d+)?)\s*mm\b/i);
    if (mp) {
      const f = parseFloat(mp[1]);
      if (!Number.isNaN(f) && f >= 8 && f <= 1200) return Math.round(f * 10) / 10;
    }
  }
  return null;
}
window.extractFocalLengthMm = extractFocalLengthMm;

function classifyFocalBandClient(focalMm) {
  if (focalMm === null || focalMm === undefined || focalMm <= 0) return FOCAL_BANDS_DEF[5];
  if (focalMm <= 28) return FOCAL_BANDS_DEF[0];
  if (focalMm <= 40) return FOCAL_BANDS_DEF[1];
  if (focalMm <= 60) return FOCAL_BANDS_DEF[2];
  if (focalMm <= 90) return FOCAL_BANDS_DEF[3];
  return FOCAL_BANDS_DEF[4];
}
window.classifyFocalBandClient = classifyFocalBandClient;

function summarizeFeedbackThemesClient(photoTextsList, themePatterns, totalCount, topN) {
  if (!totalCount || totalCount <= 0) return [];
  const results = [];
  for (const pat of themePatterns) {
    let matchedPhotos = 0;
    let sampleQuote = '';
    for (const texts of photoTextsList) {
      if (!Array.isArray(texts)) continue;
      let hit = false;
      for (const sentence of texts) {
        const sStr = String(sentence || '').trim();
        if (pat.keywords.some(kw => sStr.includes(kw))) {
          hit = true;
          if (!sampleQuote) sampleQuote = sStr;
          break;
        }
      }
      if (hit) matchedPhotos += 1;
    }
    if (matchedPhotos > 0) {
      results.push({
        theme: pat.theme,
        photo_count: matchedPhotos,
        pct: Math.round((matchedPhotos / totalCount) * 100),
        sample: sampleQuote
      });
    }
  }
  results.sort((a, b) => b.photo_count - a.photo_count);
  return results.slice(0, topN || 3);
}

function setInsightsDimension(dim) {
  insightsDimension = (dim === 'focal') ? 'focal' : 'tag';
  window.insightsDimension = insightsDimension;
  renderTagInsights();
}
window.setInsightsDimension = setInsightsDimension;

function filterByFocalFromInsights(focalKey) {
  switchView('gallery');
  if (typeof setFocalFilter === 'function') {
    setFocalFilter(focalKey);
  }
}
window.filterByFocalFromInsights = filterByFocalFromInsights;

function switchView(mode) {
  currentView = mode;
  window.currentView = mode;
  const galleryGrid = document.getElementById('gallery-grid');
  const compareView = document.getElementById('compare-view');
  const insightsView = document.getElementById('insights-view');
  const scoreDistPanel = document.getElementById('score-dist-panel');
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
    if (typeof renderScoreDistPanel === 'function') renderScoreDistPanel();
  } else if (mode === 'compare') {
    if (galleryGrid) galleryGrid.style.display = 'none';
    if (compareView) compareView.style.display = 'block';
    if (insightsView) insightsView.style.display = 'none';
    if (scoreDistPanel) scoreDistPanel.style.display = 'none';
    populateCompareSelects();
    updateComparison();
  } else if (mode === 'insights') {
    if (galleryGrid) galleryGrid.style.display = 'none';
    if (compareView) compareView.style.display = 'none';
    if (insightsView) insightsView.style.display = 'block';
    if (scoreDistPanel) scoreDistPanel.style.display = 'none';
    renderTagInsights();
  }
}

function setInsightsMinCount(val) {
  insightsMinCount = parseInt(val) || 2;
  window.insightsMinCount = insightsMinCount;
  renderTagInsights();
}

function setInsightsRatingMode(mode) {
  insightsRatingMode = mode;
  window.insightsRatingMode = insightsRatingMode;
  renderTagInsights();
}

function computeClientTagStats(minCount) {
  const dataList = (typeof allData !== 'undefined' && Array.isArray(allData)) ? allData : [];
  const totalPhotos = dataList.length;
  const userRatedPhotos = dataList.filter(d => d.user_score !== null && d.user_score !== undefined).length;
  const tagData = {};
  const categoriesMap = (typeof TAG_CATEGORIES !== 'undefined' ? TAG_CATEGORIES : (window.TAG_CATEGORIES || {}));

  dataList.forEach(d => {
    const tags = d.aesthetic_tags || {};
    const aiScore = d.final_score || 0;
    const uScore = (d.user_score !== null && d.user_score !== undefined) ? d.user_score : null;
    const lScore = d.lighting_score || 0;
    const cScore = d.composition_score || 0;
    const tScore = d.technique_score || 0;
    const colScore = d.color_score || 0;

    for (const [ckey, list] of Object.entries(tags)) {
      if (Array.isArray(list)) {
        const cname = categoriesMap[ckey] || ckey;
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

function renderInsightsScoreDistSection(dataList) {
  if (typeof computeScoreDistribution !== 'function' || typeof SCORE_BINS_05 === 'undefined') return '';

  const isStep01 = (typeof scoreDistStep !== 'undefined' && scoreDistStep === '0.1');
  const mainBins = (typeof getActiveScoreBins === 'function')
    ? getActiveScoreBins(dataList, isStep01 ? '0.1' : '0.5')
    : SCORE_BINS_05;

  const aiDist = computeScoreDistribution(dataList, d => d.final_score, mainBins);
  const userDist = computeScoreDistribution(dataList, d => d.user_score, mainBins);
  const compDist = computeScoreDistribution(dataList, d => d.composition_score, SCORE_BINS_05);
  const lightDist = computeScoreDistribution(dataList, d => d.lighting_score, SCORE_BINS_05);
  const colorDist = computeScoreDistribution(dataList, d => d.color_score, SCORE_BINS_05);
  const techDist = computeScoreDistribution(dataList, d => d.technique_score, SCORE_BINS_05);

  const maxMain = Math.max(aiDist.maxCount, userDist.maxCount, 1);
  const metrics = [
    { label: '📐 구도 (Composition)', dist: compDist, accent: '#3b82f6' },
    { label: '💡 조명 (Lighting)', dist: lightDist, accent: '#f59e0b' },
    { label: '🎨 색감 (Color)', dist: colorDist, accent: '#ec4899' },
    { label: '🎯 기술·초점 (Technique)', dist: techDist, accent: '#10b981' }
  ];

  return `
    <div class="insights-score-section">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px;">
        <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
          <div>
            <h3 style="margin:0;font-size:1.08rem;font-weight:800;color:var(--navy);display:flex;align-items:center;gap:6px;">
              📈 ${isStep01 ? '0.1점 정밀' : '0.5점 단위'} 종합 점수 분포 & 4대 심사 영역 비교
            </h3>
            <span style="font-size:0.76rem;color:var(--muted);">
              전체 사진(${aiDist.total}장)의 점수 밀집도와 구도·조명·색감·기술 영역별 체급을 비교합니다. (막대 클릭 시 해당 점수대 갤러리로 이동)
            </span>
          </div>
          <div style="display:inline-flex;background:var(--filter-btn-bg);border:1px solid var(--line);border-radius:8px;padding:2px;gap:2px;">
            <button type="button" class="toggle-logic-btn ${!isStep01 ? 'active' : ''}" onclick="setScoreDistStep('0.5')">0.5점 단위</button>
            <button type="button" class="toggle-logic-btn ${isStep01 ? 'active' : ''}" onclick="setScoreDistStep('0.1')">0.1점 단위 (정밀)</button>
          </div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;font-size:0.75rem;">
          <span class="score-dist-kpi-pill">🤖 AI 평균 <strong>${aiDist.mean.toFixed(2)}점</strong> (중앙값 ${aiDist.median.toFixed(1)})</span>
          ${userDist.total > 0 ? `<span class="score-dist-kpi-pill">👤 내 점수 평균 <strong>${userDist.mean.toFixed(2)}점</strong> (${userDist.total}장)</span>` : ''}
          <span class="score-dist-kpi-pill">🏆 상위 10% 컷 <strong>${aiDist.top10Cutoff.toFixed(1)}점+</strong></span>
        </div>
      </div>

      <!-- Main AI vs User Histogram -->
      <div class="score-dist-scroll-wrap">
        <div class="score-dist-bars ${isStep01 ? 'step-01' : 'step-05'}" style="--bin-count:${mainBins.length};">
          ${mainBins.map((bin, idx) => {
            const aiBin = aiDist.bins[idx];
            const uBin = userDist.bins[idx];
            const hAi = aiBin.count > 0 ? Math.max(8, Math.round((aiBin.count / maxMain) * 100)) : 4;
            const hUser = uBin.count > 0 ? Math.max(8, Math.round((uBin.count / maxMain) * 100)) : 4;
            return `
              <div class="score-dist-col ${aiBin.count === 0 && uBin.count === 0 ? 'empty' : ''}"
                   onclick="switchView('gallery'); selectScoreBin('${bin.key}');"
                   title="${bin.label}점 (${bin.sub}) — AI: ${aiBin.count}장 (${aiBin.pct}%) / 내 점수: ${uBin.count}장 (${uBin.pct}%) | 클릭 시 갤러리 이동">
                <div class="score-dist-count">
                  <span style="color:${bin.color};">${isStep01 ? aiBin.count : aiBin.count + '장'}</span>
                  ${userDist.total > 0 ? `<span class="score-dist-pct" style="color:#4f46e5;">${isStep01 ? '/' + uBin.count : '👤 ' + uBin.count + '장'}</span>` : `<span class="score-dist-pct">${aiBin.count > 0 ? aiBin.pct + '%' : ''}</span>`}
                </div>
                <div class="score-dist-bar-wrap">
                  <div class="score-dist-bar" style="height:${hAi}%;background:${bin.color};opacity:${aiBin.count > 0 ? 1 : 0.22};"></div>
                  ${userDist.total > 0 ? `<div class="score-dist-bar user-overlay-bar" style="height:${hUser}%;opacity:${uBin.count > 0 ? 0.95 : 0.18};"></div>` : ''}
                </div>
                <div class="score-dist-label">${bin.label}</div>
                ${!isStep01 ? `<div class="score-dist-sublabel">${bin.sub}</div>` : ''}
              </div>
            `;
          }).join('')}
        </div>
      </div>

      <!-- 4 Evaluation Domains Mini Histograms -->
      <div class="insights-4metrics-grid">
        ${metrics.map(m => {
          const mMax = Math.max(m.dist.maxCount, 1);
          return `
            <div class="metric-dist-card">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <span style="font-size:0.82rem;font-weight:800;color:var(--navy);">${m.label}</span>
                <strong style="font-size:0.95rem;color:${m.accent};">평균 ${m.dist.mean.toFixed(2)}점</strong>
              </div>
              <div style="display:flex;justify-content:space-between;font-size:0.7rem;color:var(--muted);margin-top:2px;">
                <span>중앙값 ${m.dist.median.toFixed(1)}점</span>
                <span>최고 ${m.dist.maxScore.toFixed(1)} / 최저 ${m.dist.minScore.toFixed(1)}</span>
              </div>
              <div class="metric-mini-bars">
                ${SCORE_BINS_05.map((bin, idx) => {
                  const b = m.dist.bins[idx];
                  const h = b.count > 0 ? Math.max(10, Math.round((b.count / mMax) * 100)) : 4;
                  return `
                    <div style="display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;"
                         title="${m.label} ${bin.label} (${bin.sub}): ${b.count}장 (${b.pct}%)">
                      <span style="font-size:0.6rem;font-weight:700;color:var(--muted);margin-bottom:2px;">${b.count > 0 ? b.count : ''}</span>
                      <div style="width:100%;height:${h}%;background:${m.accent};border-radius:3px 3px 1px 1px;opacity:${b.count > 0 ? 0.9 : 0.18};"></div>
                      <span style="font-size:0.58rem;color:var(--muted);margin-top:2px;">${bin.label}</span>
                    </div>
                  `;
                }).join('')}
              </div>
            </div>
          `;
        }).join('')}
      </div>
    </div>
  `;
}

function computeClientFocalStats(minCount) {
  const dataList = (typeof allData !== 'undefined' && Array.isArray(allData)) ? allData : [];
  const totalPhotos = dataList.length;
  let identifiedPhotos = 0;
  let userRatedPhotos = 0;

  const bandBuckets = {};
  const exactBuckets = {};

  FOCAL_BANDS_DEF.forEach(bdef => {
    bandBuckets[bdef.key] = {
      def: bdef,
      count: 0,
      ai_scores: [],
      user_scores: [],
      lighting_scores: [],
      composition_scores: [],
      technique_scores: [],
      color_scores: [],
      photo_strengths: [],
      photo_improvements: [],
      tag_counts: {},
      lens_counts: {},
      exact_mm_scores: {}
    };
  });

  dataList.forEach(d => {
    const fl = extractFocalLengthMm(d);
    if (fl !== null) identifiedPhotos += 1;
    const uScore = (d.user_score !== null && d.user_score !== undefined) ? Number(d.user_score) : null;
    if (uScore !== null && !Number.isNaN(uScore)) userRatedPhotos += 1;

    const bdef = classifyFocalBandClient(fl);
    const bkey = bdef.key;
    const bk = bandBuckets[bkey];

    const aiScore = Number(d.final_score || 0);
    const lScore = Number(d.lighting_score || 0);
    const cScore = Number(d.composition_score || 0);
    const tScore = Number(d.technique_score || 0);
    const colScore = Number(d.color_score || 0);

    bk.count += 1;
    bk.ai_scores.push(aiScore);
    if (uScore !== null && !Number.isNaN(uScore)) bk.user_scores.push(uScore);
    bk.lighting_scores.push(lScore);
    bk.composition_scores.push(cScore);
    bk.technique_scores.push(tScore);
    bk.color_scores.push(colScore);
    bk.photo_strengths.push(Array.isArray(d.strengths) ? d.strengths : []);
    bk.photo_improvements.push(Array.isArray(d.improvements) ? d.improvements : []);

    const tags = d.aesthetic_tags || {};
    for (const list of Object.values(tags)) {
      if (Array.isArray(list)) {
        list.forEach(t => {
          bk.tag_counts[t] = (bk.tag_counts[t] || 0) + 1;
        });
      }
    }

    const exif = d.exif || {};
    const det = d.detected_camera_settings || {};
    const lens = String(d.lens_model || exif.LensModel || det.lens || '').trim();
    if (lens) {
      bk.lens_counts[lens] = (bk.lens_counts[lens] || 0) + 1;
    }

    if (fl !== null) {
      const mmInt = Math.round(fl);
      if (!bk.exact_mm_scores[mmInt]) bk.exact_mm_scores[mmInt] = [];
      bk.exact_mm_scores[mmInt].push(aiScore);

      if (!exactBuckets[mmInt]) {
        exactBuckets[mmInt] = {
          mm: mmInt,
          label: `${mmInt}mm`,
          band_key: bkey,
          band_label: bdef.label,
          short_label: bdef.short_label,
          count: 0,
          ai_scores: [],
          user_scores: [],
          lighting_scores: [],
          composition_scores: [],
          technique_scores: [],
          color_scores: [],
          photo_strengths: [],
          photo_improvements: []
        };
      }
      const eb = exactBuckets[mmInt];
      eb.count += 1;
      eb.ai_scores.push(aiScore);
      if (uScore !== null && !Number.isNaN(uScore)) eb.user_scores.push(uScore);
      eb.lighting_scores.push(lScore);
      eb.composition_scores.push(cScore);
      eb.technique_scores.push(tScore);
      eb.color_scores.push(colScore);
      eb.photo_strengths.push(Array.isArray(d.strengths) ? d.strengths : []);
      eb.photo_improvements.push(Array.isArray(d.improvements) ? d.improvements : []);
    }
  });

  const avgArr = arr => arr.length ? (arr.reduce((a, b) => a + b, 0) / arr.length) : 0;

  const bands = [];
  FOCAL_BANDS_DEF.forEach(bdef => {
    const bk = bandBuckets[bdef.key];
    if (bk.count === 0) return;
    if (bdef.key !== 'unknown' && bk.count < minCount) return;

    const avgAi = avgArr(bk.ai_scores);
    const avgUser = bk.user_scores.length ? avgArr(bk.user_scores) : null;
    const diff = avgUser !== null ? Math.round((avgUser - avgAi) * 100) / 100 : null;

    const topTags = Object.entries(bk.tag_counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([tag, count]) => ({ tag, count }));

    const lenses = Object.entries(bk.lens_counts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([lens, count]) => ({ lens, count }));

    const exactMms = Object.entries(bk.exact_mm_scores)
      .map(([mmStr, scores]) => ({
        mm: parseInt(mmStr, 10),
        label: `${mmStr}mm`,
        count: scores.length,
        avg_ai_score: Math.round(avgArr(scores) * 100) / 100
      }))
      .sort((a, b) => a.mm - b.mm);

    bands.push({
      band_key: bdef.key,
      band_label: bdef.label,
      short_label: bdef.short_label,
      icon: bdef.icon,
      desc: bdef.desc,
      order: bdef.order,
      count: bk.count,
      avg_ai_score: Math.round(avgAi * 100) / 100,
      avg_user_score: avgUser !== null ? Math.round(avgUser * 100) / 100 : null,
      score_diff: diff,
      user_rated_count: bk.user_scores.length,
      avg_lighting_score: Math.round(avgArr(bk.lighting_scores) * 100) / 100,
      avg_composition_score: Math.round(avgArr(bk.composition_scores) * 100) / 100,
      avg_technique_score: Math.round(avgArr(bk.technique_scores) * 100) / 100,
      avg_color_score: Math.round(avgArr(bk.color_scores) * 100) / 100,
      top_strengths: summarizeFeedbackThemesClient(bk.photo_strengths, CLIENT_STRENGTH_THEMES, bk.count, 3),
      top_improvements: summarizeFeedbackThemesClient(bk.photo_improvements, CLIENT_IMPROVEMENT_THEMES, bk.count, 3),
      top_tags: topTags,
      lenses: lenses,
      exact_mms: exactMms
    });
  });

  const exactFocalLengths = Object.values(exactBuckets)
    .filter(eb => eb.count >= minCount)
    .map(eb => {
      const avgAi = avgArr(eb.ai_scores);
      const avgUser = eb.user_scores.length ? avgArr(eb.user_scores) : null;
      const diff = avgUser !== null ? Math.round((avgUser - avgAi) * 100) / 100 : null;
      return {
        mm: eb.mm,
        label: eb.label,
        band_key: eb.band_key,
        band_label: eb.band_label,
        short_label: eb.short_label,
        count: eb.count,
        avg_ai_score: Math.round(avgAi * 100) / 100,
        avg_user_score: avgUser !== null ? Math.round(avgUser * 100) / 100 : null,
        score_diff: diff,
        user_rated_count: eb.user_scores.length,
        avg_lighting_score: Math.round(avgArr(eb.lighting_scores) * 100) / 100,
        avg_composition_score: Math.round(avgArr(eb.composition_scores) * 100) / 100,
        avg_technique_score: Math.round(avgArr(eb.technique_scores) * 100) / 100,
        avg_color_score: Math.round(avgArr(eb.color_scores) * 100) / 100,
        top_strengths: summarizeFeedbackThemesClient(eb.photo_strengths, CLIENT_STRENGTH_THEMES, eb.count, 2),
        top_improvements: summarizeFeedbackThemesClient(eb.photo_improvements, CLIENT_IMPROVEMENT_THEMES, eb.count, 2)
      };
    })
    .sort((a, b) => a.mm - b.mm);

  const knownBands = bands.filter(b => b.band_key !== 'unknown');
  const getBandMetricScore = (b) => {
    if (insightsRatingMode === 'user' && b.avg_user_score !== null) return b.avg_user_score;
    return b.avg_ai_score;
  };
  const sortedByScore = [...knownBands].sort((a, b) => getBandMetricScore(b) - getBandMetricScore(a));
  const sortedByCount = [...knownBands].sort((a, b) => b.count - a.count);

  const bestBand = sortedByScore.length ? sortedByScore[0] : null;
  const weakestBand = sortedByScore.length >= 2 ? sortedByScore[sortedByScore.length - 1] : null;
  const mostUsedBand = sortedByCount.length ? sortedByCount[0] : null;

  return {
    totalPhotos,
    identifiedPhotos,
    unknownPhotos: totalPhotos - identifiedPhotos,
    userRatedPhotos,
    bands,
    knownBands,
    exactFocalLengths,
    bestBand,
    weakestBand,
    mostUsedBand
  };
}
window.computeClientFocalStats = computeClientFocalStats;

function renderFocalBandCard(b, totalIdentified) {
  const primaryScore = (insightsRatingMode === 'user' && b.avg_user_score !== null) ? b.avg_user_score : b.avg_ai_score;
  const scoreColor = getScoreColor(primaryScore);
  const sharePct = totalIdentified > 0 && b.band_key !== 'unknown'
    ? Math.round((b.count / totalIdentified) * 100)
    : 0;

  return `
    <div class="focal-band-card">
      <div class="focal-band-card-header">
        <div>
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
            <span style="font-size:1.25rem;">${b.icon || '🔭'}</span>
            <h4 style="margin:0;font-size:1.05rem;font-weight:900;color:var(--navy);">${escapeHtml(b.band_label)}</h4>
            <span style="font-size:0.75rem;font-weight:800;background:#e0f2fe;color:#0369a1;padding:2px 8px;border-radius:999px;">
              ${b.count}장 ${b.band_key !== 'unknown' ? `(${sharePct}%)` : ''}
            </span>
          </div>
          <p style="margin:4px 0 0;font-size:0.76rem;color:var(--muted);">${escapeHtml(b.desc || '')}</p>
        </div>

        <div style="text-align:right;display:flex;flex-direction:column;align-items:flex-end;gap:4px;">
          <div style="display:flex;align-items:baseline;gap:6px;">
            ${b.avg_user_score !== null ? `<span style="font-size:0.78rem;font-weight:700;color:#4f46e5;">👤 ${b.avg_user_score.toFixed(2)}</span>` : ''}
            <strong style="font-size:1.35rem;font-weight:900;color:${scoreColor};">🤖 ${b.avg_ai_score.toFixed(2)}</strong>
            <small style="font-size:0.74rem;color:var(--muted);">/10</small>
          </div>
          <button type="button" class="filter-btn" style="padding:3px 10px;font-size:0.74rem;font-weight:700;color:#0284c7;border-color:#bae6fd;background:#f0f9ff;"
                  onclick="filterByFocalFromInsights('${b.band_key}')">
            📷 이 화각 사진 ${b.count}장 모아보기 →
          </button>
        </div>
      </div>

      <!-- 4 Domain Scores Mini Bar -->
      <div class="focal-domain-scores-row">
        <div class="focal-domain-item">
          <span>📐 구도</span>
          <strong style="color:#3b82f6;">${b.avg_composition_score.toFixed(2)}</strong>
        </div>
        <div class="focal-domain-item">
          <span>💡 조명</span>
          <strong style="color:#f59e0b;">${b.avg_lighting_score.toFixed(2)}</strong>
        </div>
        <div class="focal-domain-item">
          <span>🎨 색감</span>
          <strong style="color:#ec4899;">${b.avg_color_score.toFixed(2)}</strong>
        </div>
        <div class="focal-domain-item">
          <span>🎯 기술·초점</span>
          <strong style="color:#10b981;">${b.avg_technique_score.toFixed(2)}</strong>
        </div>
      </div>

      ${b.exact_mms && b.exact_mms.length ? `
        <div style="margin-top:10px;display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
          <span style="font-size:0.73rem;font-weight:700;color:var(--muted);">포함된 세부 화각(클릭 시 단독 필터):</span>
          ${b.exact_mms.map(em => `
            <span class="focal-mm-pill" onclick="filterByFocalFromInsights('mm:${em.mm}')" title="클릭하여 ${em.label} 사진(${em.count}장)만 갤러리에서 보기">
              🔭 <b>${em.label}</b> <small>(${em.count}장 · ${em.avg_ai_score.toFixed(1)}점)</small>
            </span>
          `).join('')}
        </div>
      ` : ''}

      ${b.lenses && b.lenses.length ? `
        <div style="margin-top:6px;font-size:0.73rem;color:var(--muted);display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
          <span style="font-weight:700;">주요 사용 렌즈:</span>
          ${b.lenses.map(l => `<span style="background:var(--card-sub);border:1px solid var(--line);padding:1px 7px;border-radius:6px;font-weight:600;color:var(--ink);">${escapeHtml(l.lens)} (${l.count}장)</span>`).join('')}
        </div>
      ` : ''}

      <!-- Strengths vs Weaknesses Two-Column Box -->
      <div class="focal-sw-grid">
        <div class="focal-sw-box strengths">
          <div class="focal-sw-title" style="color:#065f46;">✓ 이 화각에서의 주요 강점 (Strengths)</div>
          ${b.top_strengths && b.top_strengths.length ? b.top_strengths.map(st => `
            <div class="focal-sw-item">
              <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;">
                <span style="font-weight:800;font-size:0.8rem;color:var(--ink);">${escapeHtml(st.theme)}</span>
                <span style="font-size:0.7rem;font-weight:800;background:#d1fae5;color:#065f46;padding:1px 6px;border-radius:999px;white-space:nowrap;">
                  ${st.photo_count}장 (${st.pct}%)
                </span>
              </div>
              ${st.sample ? `<div class="focal-sw-quote">“${escapeHtml(st.sample)}”</div>` : ''}
            </div>
          `).join('') : '<div style="font-size:0.78rem;color:var(--muted);">추출된 강점 패턴이 없습니다.</div>'}
        </div>

        <div class="focal-sw-box weaknesses">
          <div class="focal-sw-title" style="color:#991b1b;">✗ 자주 지적되는 약점 & 보완 포인트 (Weaknesses)</div>
          ${b.top_improvements && b.top_improvements.length ? b.top_improvements.map(im => `
            <div class="focal-sw-item">
              <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;">
                <span style="font-weight:800;font-size:0.8rem;color:var(--ink);">${escapeHtml(im.theme)}</span>
                <span style="font-size:0.7rem;font-weight:800;background:#fee2e2;color:#991b1b;padding:1px 6px;border-radius:999px;white-space:nowrap;">
                  ${im.photo_count}장 (${im.pct}%)
                </span>
              </div>
              ${im.sample ? `<div class="focal-sw-quote">“${escapeHtml(im.sample)}”</div>` : ''}
            </div>
          `).join('') : '<div style="font-size:0.78rem;color:var(--muted);">추출된 약점 패턴이 없습니다.</div>'}
        </div>
      </div>

      ${b.top_tags && b.top_tags.length ? `
        <div style="margin-top:10px;padding-top:8px;border-top:1px dashed var(--line);display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
          <span style="font-size:0.73rem;font-weight:700;color:var(--muted);">🏷️ 이 화각의 빈출 시각 태그:</span>
          ${b.top_tags.map(t => {
            const style = (typeof getTagColorStyle === 'function') ? getTagColorStyle(t.tag) : (window.getTagColorStyle ? window.getTagColorStyle(t.tag) : '');
            const escapedTag = escapeHtml(t.tag);
            return `<span class="tag-pill" data-tag-action="toggle" data-tag="${escapedTag}" style="${style}cursor:pointer;font-size:0.72rem;font-weight:600;" title="클릭하여 #${escapedTag} 사진 모아보기">#${escapedTag} (${t.count})</span>`;
          }).join('')}
        </div>
      ` : ''}
    </div>
  `;
}

function renderFocalInsightsContent(fStats, dataList) {
  const idPct = fStats.totalPhotos ? Math.round((fStats.identifiedPhotos / fStats.totalPhotos) * 100) : 0;
  const mostPct = fStats.identifiedPhotos && fStats.mostUsedBand
    ? Math.round((fStats.mostUsedBand.count / fStats.identifiedPhotos) * 100)
    : 0;

  return `
    <!-- Focal KPI Summary Cards -->
    <div class="insights-kpi-grid">
      <div class="insights-kpi-card">
        <div class="insights-kpi-title">🔭 화각 식별 데이터</div>
        <div class="insights-kpi-value">${fStats.identifiedPhotos} <small style="font-size:0.9rem;font-weight:500;color:var(--muted);">/ ${fStats.totalPhotos}장 (${idPct}%)</small></div>
        <div class="insights-kpi-sub">EXIF 메타데이터 + 워터마크 OCR 통합</div>
      </div>

      <div class="insights-kpi-card">
        <div class="insights-kpi-title">🏆 최고 평점 화각대</div>
        <div class="insights-kpi-value" style="font-size:1.2rem;color:#0d9488;">
          ${fStats.bestBand ? `${fStats.bestBand.icon} ${escapeHtml(fStats.bestBand.short_label)}` : '-'}
        </div>
        <div class="insights-kpi-sub">
          ${fStats.bestBand ? `평균 ${fStats.bestBand.avg_ai_score.toFixed(2)}점 (${fStats.bestBand.count}장 촬영)` : '화각 데이터 부족'}
        </div>
      </div>

      <div class="insights-kpi-card">
        <div class="insights-kpi-title">📸 주력(최다 촬영) 화각대</div>
        <div class="insights-kpi-value" style="font-size:1.2rem;color:#2563eb;">
          ${fStats.mostUsedBand ? `${fStats.mostUsedBand.icon} ${escapeHtml(fStats.mostUsedBand.short_label)}` : '-'}
        </div>
        <div class="insights-kpi-sub">
          ${fStats.mostUsedBand ? `식별 사진 중 ${fStats.mostUsedBand.count}장 (${mostPct}%) · 평균 ${fStats.mostUsedBand.avg_ai_score.toFixed(2)}점` : '화각 데이터 부족'}
        </div>
      </div>

      <div class="insights-kpi-card">
        <div class="insights-kpi-title">⚠️ 집중 보완 필요 화각대</div>
        <div class="insights-kpi-value" style="font-size:1.2rem;color:#e11d48;">
          ${fStats.weakestBand ? `${fStats.weakestBand.icon} ${escapeHtml(fStats.weakestBand.short_label)}` : '-'}
        </div>
        <div class="insights-kpi-sub">
          ${fStats.weakestBand ? `평균 ${fStats.weakestBand.avg_ai_score.toFixed(2)}점 (${fStats.weakestBand.count}장 · 프레이밍/배경 주의)` : '비교 대상 부족'}
        </div>
      </div>
    </div>

    <!-- Focal Band Overview Comparison Table -->
    <div class="insights-score-section" style="margin-bottom:24px;">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:14px;">
        <div>
          <h3 style="margin:0;font-size:1.08rem;font-weight:800;color:var(--navy);">
            📊 화각 구간별 종합 성적표 & 4대 심사 영역(구도·조명·색감·기술) 한눈에 비교
          </h3>
          <span style="font-size:0.76rem;color:var(--muted);">
            초점거리(24mm 광각 ~ 100mm+ 망원/매크로)에 따른 점수 편차와 핵심 장단점을 비교합니다. (행 클릭 시 해당 화각 사진 갤러리 이동)
          </span>
        </div>
      </div>

      <div style="overflow-x:auto;">
        <table class="focal-compare-table">
          <thead>
            <tr>
              <th>화각 구간</th>
              <th style="text-align:center;">촬영 수</th>
              <th>종합 점수 (AI / 내 점수)</th>
              <th style="text-align:center;">📐 구도</th>
              <th style="text-align:center;">💡 조명</th>
              <th style="text-align:center;">🎨 색감</th>
              <th style="text-align:center;">🎯 기술</th>
              <th>최다 강점 (Top 1)</th>
              <th>최다 지적 약점 (Top 1)</th>
            </tr>
          </thead>
          <tbody>
            ${fStats.bands.map(b => {
              const score = (insightsRatingMode === 'user' && b.avg_user_score !== null) ? b.avg_user_score : b.avg_ai_score;
              const sColor = getScoreColor(score);
              const topS = b.top_strengths && b.top_strengths.length ? b.top_strengths[0] : null;
              const topI = b.top_improvements && b.top_improvements.length ? b.top_improvements[0] : null;
              return `
                <tr onclick="filterByFocalFromInsights('${b.band_key}')" style="cursor:pointer;" title="클릭하여 ${escapeHtml(b.band_label)} 사진 모아보기">
                  <td>
                    <strong style="color:var(--navy);font-size:0.86rem;">${b.icon} ${escapeHtml(b.band_label)}</strong>
                  </td>
                  <td style="text-align:center;font-weight:700;">${b.count}장</td>
                  <td style="min-width:165px;">
                    <div style="display:flex;align-items:center;gap:6px;">
                      <strong style="color:${sColor};font-size:0.92rem;">🤖 ${b.avg_ai_score.toFixed(2)}</strong>
                      ${b.avg_user_score !== null ? `<span style="font-size:0.74rem;color:#4f46e5;font-weight:700;">(👤 ${b.avg_user_score.toFixed(1)})</span>` : ''}
                    </div>
                    <div class="tag-progress-track" style="height:5px;margin-top:3px;">
                      <div class="tag-progress-fill" style="width:${Math.min(100, Math.max(0, score * 10))}%;background:${sColor};"></div>
                    </div>
                  </td>
                  <td style="text-align:center;font-weight:700;color:#3b82f6;">${b.avg_composition_score.toFixed(2)}</td>
                  <td style="text-align:center;font-weight:700;color:#f59e0b;">${b.avg_lighting_score.toFixed(2)}</td>
                  <td style="text-align:center;font-weight:700;color:#ec4899;">${b.avg_color_score.toFixed(2)}</td>
                  <td style="text-align:center;font-weight:700;color:#10b981;">${b.avg_technique_score.toFixed(2)}</td>
                  <td style="font-size:0.76rem;color:#065f46;font-weight:700;">
                    ${topS ? `${escapeHtml(topS.theme)} (${topS.pct}%)` : '-'}
                  </td>
                  <td style="font-size:0.76rem;color:#991b1b;font-weight:700;">
                    ${topI ? `${escapeHtml(topI.theme)} (${topI.pct}%)` : '-'}
                  </td>
                </tr>
              `;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Detailed Diagnosis Cards per Focal Band -->
    <div style="margin-bottom:28px;">
      <div style="margin-bottom:14px;">
        <h3 style="margin:0;font-size:1.15rem;font-weight:800;color:var(--navy);">
          🔍 화각대별 강점(Strengths) & 단점/보완점(Weaknesses) 심층 진단
        </h3>
        <span style="font-size:0.78rem;color:var(--muted);">
          각 화각 구간으로 촬영할 때 가장 잘 살리고 있는 강점과 AI 심사에서 반복적으로 지적된 약점 원문을 확인하세요.
        </span>
      </div>
      <div class="focal-cards-grid">
        ${fStats.bands.map(b => renderFocalBandCard(b, fStats.identifiedPhotos)).join('')}
      </div>
    </div>

    <!-- Exact Focal Length (mm) Breakdown Table -->
    ${fStats.exactFocalLengths.length ? `
      <div class="insights-score-section">
        <div style="margin-bottom:12px;">
          <h3 style="margin:0;font-size:1.06rem;font-weight:800;color:var(--navy);">
            📏 단일 초점거리(mm)별 정밀 랭킹 (최소 ${insightsMinCount}장 이상 촬영된 화각)
          </h3>
          <span style="font-size:0.76rem;color:var(--muted);">
            특정 mm 화각(예: 24mm, 35mm, 50mm, 70mm)을 클릭하면 해당 초점거리로 촬영된 사진만 갤러리에서 필터링합니다.
          </span>
        </div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(250px, 1fr));gap:12px;">
          ${fStats.exactFocalLengths.map(ef => {
            const sc = (insightsRatingMode === 'user' && ef.avg_user_score !== null) ? ef.avg_user_score : ef.avg_ai_score;
            const col = getScoreColor(sc);
            const s1 = ef.top_strengths && ef.top_strengths[0] ? ef.top_strengths[0].theme : '-';
            const i1 = ef.top_improvements && ef.top_improvements[0] ? ef.top_improvements[0].theme : '-';
            return `
              <div class="metric-dist-card" style="cursor:pointer;transition:transform 0.15s;" onclick="filterByFocalFromInsights('mm:${ef.mm}')" title="클릭하여 ${ef.label} 사진(${ef.count}장)만 갤러리에서 보기">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
                  <div>
                    <strong style="font-size:1.05rem;color:var(--navy);">🔭 ${ef.label}</strong>
                    <span style="font-size:0.72rem;color:var(--muted);margin-left:4px;">(${ef.count}장 · ${escapeHtml(ef.short_label)})</span>
                  </div>
                  <strong style="font-size:1rem;color:${col};">🤖 ${ef.avg_ai_score.toFixed(2)}점</strong>
                </div>
                <div style="display:flex;justify-content:space-between;font-size:0.72rem;color:var(--muted);margin-bottom:6px;">
                  <span>📐구도 ${ef.avg_composition_score.toFixed(1)}</span>
                  <span>💡조명 ${ef.avg_lighting_score.toFixed(1)}</span>
                  <span>🎨색감 ${ef.avg_color_score.toFixed(1)}</span>
                  <span>🎯기술 ${ef.avg_technique_score.toFixed(1)}</span>
                </div>
                <div style="font-size:0.72rem;color:#065f46;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">✓ ${escapeHtml(s1)}</div>
                <div style="font-size:0.72rem;color:#991b1b;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px;">✗ ${escapeHtml(i1)}</div>
              </div>
            `;
          }).join('')}
        </div>
      </div>
    ` : ''}
  `;
}

function renderTagInsights() {
  const container = document.getElementById('insights-view');
  if (!container) return;

  const dataList = (typeof allData !== 'undefined' && Array.isArray(allData)) ? allData : [];
  if (!dataList.length) {
    container.innerHTML = '<div style="text-align:center;padding:60px;color:var(--muted)">분석된 사진 데이터가 없습니다. 먼저 사진을 업로드해 분석해주세요.</div>';
    return;
  }

  const stats = computeClientTagStats(insightsMinCount);
  const fStats = computeClientFocalStats(insightsMinCount);

  const topAi = stats.allTags.length ? [...stats.allTags].sort((a, b) => b.avg_ai_score - a.avg_ai_score)[0] : null;
  const userRatePct = stats.totalPhotos ? Math.round((stats.userRatedPhotos / stats.totalPhotos) * 100) : 0;
  const categoriesMap = (typeof TAG_CATEGORIES !== 'undefined' ? TAG_CATEGORIES : (window.TAG_CATEGORIES || {}));
  const isFocalMode = insightsDimension === 'focal';

  const toolbarHtml = `
    <!-- Insights Toolbar -->
    <div class="insights-toolbar" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;margin-bottom:20px;">
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
        <!-- Dimension Switcher: Tag vs Focal Length -->
        <div style="display:inline-flex;background:var(--filter-btn-bg, #e2e8f0);border:1px solid var(--line, #cbd5e1);border-radius:12px;padding:3px;gap:3px;">
          <button type="button" class="toggle-logic-btn ${!isFocalMode ? 'active' : ''}" onclick="setInsightsDimension('tag')" style="font-size:0.84rem;padding:6px 14px;">
            🏷️ 시각 태그별 강점·약점 (${stats.filteredCount})
          </button>
          <button type="button" class="toggle-logic-btn ${isFocalMode ? 'active' : ''}" onclick="setInsightsDimension('focal')" style="font-size:0.84rem;padding:6px 14px;">
            🔭 화각(초점거리)별 강점·약점 (${fStats.identifiedPhotos}장)
          </button>
        </div>

        <span style="font-size:1.05rem;font-weight:900;color:var(--navy);display:flex;align-items:center;gap:6px;">
          ${isFocalMode ? '🔭 화각(24mm ~ 100mm+)별 강점·약점 & 심사 분석' : '📊 시각 태그별 평균 점수 & 미학 경향성 인사이트'}
        </span>
      </div>

      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
        <!-- Sample Min Count Filter -->
        <div style="display:inline-flex;align-items:center;gap:6px;background:var(--card-sub, #f1f5f9);padding:4px 10px;border-radius:10px;border:1px solid var(--line, #e2e8f0);">
          <span style="font-size:0.78rem;font-weight:700;color:var(--muted);">최소 사진 수:</span>
          <select class="select-input" style="padding:2px 8px;font-size:0.78rem;border:none;background:transparent;font-weight:700;color:#0284c7;cursor:pointer;" onchange="setInsightsMinCount(this.value)">
            <option value="1" ${insightsMinCount === 1 ? 'selected' : ''}>1장 이상 (전체)</option>
            <option value="2" ${insightsMinCount === 2 ? 'selected' : ''}>2장 이상 (표준 권장)</option>
            <option value="3" ${insightsMinCount === 3 ? 'selected' : ''}>3장 이상</option>
            <option value="5" ${insightsMinCount === 5 ? 'selected' : ''}>5장 이상 (대용량)</option>
          </select>
        </div>

        <!-- Rating Mode Switcher -->
        <div style="display:inline-flex;background:var(--filter-btn-bg, #e2e8f0);border:1px solid var(--line, #cbd5e1);border-radius:10px;padding:3px;gap:2px;">
          <button class="toggle-logic-btn ${insightsRatingMode === 'ai' ? 'active' : ''}" onclick="setInsightsRatingMode('ai')">🤖 AI 점수</button>
          <button class="toggle-logic-btn ${insightsRatingMode === 'user' ? 'active' : ''}" onclick="setInsightsRatingMode('user')">👤 내 점수</button>
          <button class="toggle-logic-btn ${insightsRatingMode === 'diff' ? 'active' : ''}" onclick="setInsightsRatingMode('diff')">⚖️ AI vs 내 점수 비교</button>
        </div>
      </div>
    </div>
  `;

  if (isFocalMode) {
    container.innerHTML = toolbarHtml + renderFocalInsightsContent(fStats, dataList);
    return;
  }

  container.innerHTML = toolbarHtml + `

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

    ${renderInsightsScoreDistSection(dataList)}

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
        ${Object.entries(categoriesMap).map(([ckey, cname]) => {
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
  const style = (typeof getTagColorStyle === 'function') ? getTagColorStyle(t.tag) : (window.getTagColorStyle ? window.getTagColorStyle(t.tag) : '');
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
  const style = (typeof getTagColorStyle === 'function') ? getTagColorStyle(t.tag) : (window.getTagColorStyle ? window.getTagColorStyle(t.tag) : '');
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
  const dataList = (typeof allData !== 'undefined' && Array.isArray(allData)) ? allData : [];
  if (!dataList.length) {
    selA.innerHTML = '<option value="">(비교할 사진 없음)</option>';
    selB.innerHTML = '<option value="">(비교할 사진 없음)</option>';
    return;
  }
  const prevA = selA.value;
  const prevB = selB.value;
  const options = dataList.map(d => `<option value="${d.id}">${escapeHtml(d.filename)} (${(d.final_score || 0).toFixed(1)}점 - ${escapeHtml(d.grade || '-')})</option>`).join('');
  selA.innerHTML = options;
  selB.innerHTML = options;

  const hasPrevA = dataList.some(d => String(d.id) === String(prevA));
  const hasPrevB = dataList.some(d => String(d.id) === String(prevB));

  if (hasPrevA) {
    selA.value = prevA;
  } else {
    selA.selectedIndex = 0;
  }

  if (hasPrevB) {
    selB.value = prevB;
  } else if (dataList.length > 1) {
    selB.selectedIndex = 1;
  } else {
    selB.selectedIndex = 0;
  }
}

function updateComparison() {
  const selA = document.getElementById('comp-a-select');
  const selB = document.getElementById('comp-b-select');
  const content = document.getElementById('compare-content');
  if (!content) return;

  const dataList = (typeof allData !== 'undefined' && Array.isArray(allData)) ? allData : [];
  if (!dataList.length) {
    content.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:60px;color:var(--muted)">비교할 사진 데이터가 없습니다. 먼저 사진을 업로드해 분석해주세요.</div>';
    return;
  }

  if (selA && selB && (!selA.options || selA.options.length === 0 || !selA.value)) {
    populateCompareSelects();
  }

  const idA = selA ? parseInt(selA.value) : NaN;
  const idB = selB ? parseInt(selB.value) : NaN;
  const a = dataList.find(d => d.id === idA) || dataList[0];
  const b = dataList.find(d => d.id === idB) || (dataList.length > 1 ? dataList[1] : dataList[0]);
  if (!a || !b) return;

  if (selA && String(selA.value) !== String(a.id)) selA.value = String(a.id);
  if (selB && String(selB.value) !== String(b.id)) selB.value = String(b.id);

  content.innerHTML = [a, b].map((item, idx) => `
    <div class="compare-col">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <h3 style="margin:0;">사진 ${idx === 0 ? 'A' : 'B'}: ${escapeHtml(item.filename)}</h3>
        <span class="score-grade">${escapeHtml(item.grade || '-')}</span>
      </div>
      <img class="compare-img" src="/api/image/${item.id}">
      <div style="display:flex;justify-content:space-between;align-items:center;margin:16px 0;">
        <span style="font-weight:700;font-size:1.1rem">종합 점수</span>
        <strong style="font-size:2.2rem;color:var(--blue)">${(item.final_score || 0).toFixed(1)}<small style="font-size:0.9rem;color:var(--muted)"> / 10</small></strong>
      </div>
      <div class="mini-scores" style="font-size:0.84rem;padding:12px;">
        <div><span>구도</span><strong>${(item.composition_score || 0).toFixed(1)}</strong></div>
        <div><span>조명</span><strong>${(item.lighting_score || 0).toFixed(1)}</strong></div>
        <div><span>색감</span><strong>${(item.color_score || 0).toFixed(1)}</strong></div>
        <div><span>기술</span><strong>${(item.technique_score || 0).toFixed(1)}</strong></div>
      </div>
      <div class="final-reason-box" style="margin-bottom:12px;">
        <b>한줄 총평:</b> ${escapeHtml(item.final_reason || '')}
      </div>
      <div class="strengths-box">
        <h4>✓ 주요 장점</h4>
        <ul>${(item.strengths || []).map(s => `<li>${escapeHtml(s)}</li>`).join('')}</ul>
      </div>
      <div class="improvements-box" style="margin-top:8px;">
        <h4>✗ 단점 및 아쉬운 점</h4>
        <ul>${(item.improvements || []).map(i => `<li>${escapeHtml(i)}</li>`).join('')}</ul>
      </div>
      ${item.cross_check_opinion ? `
        <div class="cross-check-compare-box">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
            <b class="cross-check-comp-title">🤝 OpenAI 크로스 체크 (${escapeHtml(item.cross_check_opinion.model || 'GPT-6 Luna')})</b>
            <strong class="cross-check-comp-score">${item.cross_check_opinion.score !== undefined && item.cross_check_opinion.score !== null ? Number(item.cross_check_opinion.score).toFixed(1) : '-'}점</strong>
          </div>
          <div class="cross-check-comp-reason">${escapeHtml(item.cross_check_opinion.reason || '')}</div>
        </div>
      ` : ''}
    </div>
  `).join('');
}

// Global exports
window.switchView = switchView;
window.setInsightsMinCount = setInsightsMinCount;
window.setInsightsRatingMode = setInsightsRatingMode;
window.computeClientTagStats = computeClientTagStats;
window.getScoreColor = getScoreColor;
window.renderTagInsights = renderTagInsights;
window.renderTagStatRow = renderTagStatRow;
window.renderCategoryTagRow = renderCategoryTagRow;
window.populateCompareSelects = populateCompareSelects;
window.updateComparison = updateComparison;
