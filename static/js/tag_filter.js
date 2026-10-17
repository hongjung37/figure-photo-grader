// --- Tag Filter & Insights Module (static/js/tag_filter.js) ---

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

const TAG_CATEGORIES = {
  "viewpoint": "시점",
  "composition_space": "구도·공간",
  "pose_gaze": "포즈·시선",
  "mood": "분위기",
  "subject_background": "피사체-배경 관계",
  "light_expression": "빛 표현",
  "color_impression": "색조 인상",
  "narrative_implication": "이야기 암시"
};

let selectedTags = new Set();
let tagLogic = 'AND'; // 'AND' or 'OR'

function setTagLogic(mode) {
  tagLogic = mode;
  const btnAnd = document.getElementById('tag-logic-and');
  const btnOr = document.getElementById('tag-logic-or');
  if (btnAnd) btnAnd.classList.toggle('active', mode === 'AND');
  if (btnOr) btnOr.classList.toggle('active', mode === 'OR');
  if (typeof renderScoreDistPanel === 'function') renderScoreDistPanel();
  if (typeof renderGallery === 'function') renderGallery();
}

function toggleTagFilter(tag) {
  if (selectedTags.has(tag)) {
    selectedTags.delete(tag);
  } else {
    selectedTags.add(tag);
  }
  if (typeof currentView !== 'undefined' && currentView !== 'gallery' && typeof switchView === 'function') {
    switchView('gallery');
  }
  updateTagFilterUI();
  if (typeof renderScoreDistPanel === 'function') renderScoreDistPanel();
  if (typeof renderGallery === 'function') renderGallery();
}

function clearAllSelectedTags() {
  selectedTags.clear();
  updateTagFilterUI();
  if (typeof renderScoreDistPanel === 'function') renderScoreDistPanel();
  if (typeof renderGallery === 'function') renderGallery();
}

function onTagSelectChange(sel) {
  const tag = sel.value;
  if (!tag) return;
  selectedTags.add(tag);
  sel.value = '';
  if (typeof currentView !== 'undefined' && currentView !== 'gallery' && typeof switchView === 'function') {
    switchView('gallery');
  }
  updateTagFilterUI();
  if (typeof renderScoreDistPanel === 'function') renderScoreDistPanel();
  if (typeof renderGallery === 'function') renderGallery();
}

function getAllTagsFromItem(item) {
  const set = new Set();
  const tags = item && item.aesthetic_tags;
  if (!tags) return set;
  for (const val of Object.values(tags)) {
    if (Array.isArray(val)) {
      val.forEach(t => set.add(t));
    }
  }
  return set;
}

function getTagColorStyle(tag) {
  if (['차가움', '쿨톤(차가움)', '차가운 톤'].includes(tag)) {
    return 'background:#e0f2fe;color:#0369a1;border:1px solid #bae6fd;';
  }
  if (['따뜻함', '웜톤(따뜻함)', '따뜻한 톤'].includes(tag)) {
    return 'background:#fef3c7;color:#b45309;border:1px solid #fde68a;';
  }
  if (['청량함', '자연색'].includes(tag)) {
    return 'background:#d1fae5;color:#065f46;border:1px solid #a7f3d0;';
  }
  if (['화사함', '파스텔'].includes(tag)) {
    return 'background:#ffe4e6;color:#9f1239;border:1px solid #fecdd3;';
  }
  if (['몽환적', '신비로움', '사이버펑크·네온', '네온·컬러조명'].includes(tag)) {
    return 'background:#f3e8ff;color:#6b21a8;border:1px solid #e9d5ff;';
  }
  if (['다크·누아르', '시네마틱', '로우키(어두움)'].includes(tag)) {
    return 'background:#334155;color:#f8fafc;border:1px solid #475569;';
  }
  if (['하이키(밝음)', '비비드 컬러', '생동감', '역동적'].includes(tag)) {
    return 'background:#ffedd5;color:#c2410c;border:1px solid #fed7aa;';
  }
  return 'background:#f1f5f9;color:#475569;border:1px solid #e2e8f0;';
}

function renderTagPills(tags, maxCount = 4) {
  if (!tags) return '';
  const pills = [];
  for (const [k, v] of Object.entries(tags)) {
    if (Array.isArray(v)) {
      v.forEach(t => {
        const escaped = escapeHtml(t);
        const style = getTagColorStyle(t);
        const isSelected = selectedTags && selectedTags.has(t);
        const selBorder = isSelected ? 'box-shadow:0 0 0 2px #0284c7;font-weight:800;' : '';
        pills.push(`<span class="tag-pill" data-tag-action="toggle" data-tag="${escaped}" style="${style}${selBorder}cursor:pointer;" title="클릭하여 #${escaped} 태그로 필터링">${isSelected ? '✓ ' : ''}${escaped}</span>`);
      });
    }
  }
  if (maxCount > 0 && pills.length > maxCount) {
    const hiddenCount = pills.length - maxCount;
    return pills.slice(0, maxCount).join('') + `<span class="tag-pill" style="background:transparent;border:1px dashed #cbd5e1;color:var(--muted);font-size:0.7rem;">+${hiddenCount}</span>`;
  }
  return pills.join('');
}

function updateTagFilterUI() {
  const pillsContainer = document.getElementById('active-tags-pills');
  const activeBar = document.getElementById('active-tags-container');
  const clearBtn = document.getElementById('btn-clear-tag-filter');

  if (!pillsContainer || !activeBar || !clearBtn) return;

  if (selectedTags.size === 0) {
    activeBar.style.display = 'none';
    clearBtn.style.display = 'none';
  } else {
    activeBar.style.display = 'flex';
    clearBtn.style.display = 'inline-block';
    pillsContainer.innerHTML = Array.from(selectedTags).map(t => {
      const escaped = escapeHtml(t);
      const style = getTagColorStyle(t);
      return `<span class="tag-pill" data-tag-action="toggle" data-tag="${escaped}" style="${style}font-weight:700;display:inline-flex;align-items:center;gap:4px;cursor:pointer;">${escaped} <span style="font-weight:900;color:#ef4444;font-size:0.8rem;" data-tag-remove="${escaped}">×</span></span>`;
    }).join('');
  }

  document.querySelectorAll('.quick-tag-btn').forEach(btn => {
    const t = btn.getAttribute('data-tag');
    btn.classList.toggle('active', selectedTags.has(t));
  });
}

// Global Event Delegation for tag clicks
if (typeof document !== 'undefined') {
  document.addEventListener('click', function(e) {
    const pill = e.target.closest('[data-tag-action="toggle"]');
    if (pill && pill.dataset.tag) {
      e.stopPropagation();
      toggleTagFilter(pill.dataset.tag);
    }
  });
}

function populateTagSelectorAndQuickTags() {
  const tagFreq = {};
  const tagsByCategory = {};

  const dataList = (typeof allData !== 'undefined' && Array.isArray(allData)) ? allData : [];
  dataList.forEach(d => {
    const tags = d.aesthetic_tags || {};
    for (const [ckey, list] of Object.entries(tags)) {
      if (Array.isArray(list)) {
        list.forEach(t => {
          tagFreq[t] = (tagFreq[t] || 0) + 1;
          tagsByCategory[ckey] = tagsByCategory[ckey] || new Set();
          tagsByCategory[ckey].add(t);
        });
      }
    }
  });

  const select = document.getElementById('tag-select-box');
  if (select) {
    let optHtml = '<option value="">+ 전체 태그 목록에서 선택...</option>';
    for (const [ckey, cname] of Object.entries(TAG_CATEGORIES)) {
      const tagSet = tagsByCategory[ckey];
      if (tagSet && tagSet.size > 0) {
        optHtml += `<optgroup label="${cname}">`;
        Array.from(tagSet).sort().forEach(t => {
          const cnt = tagFreq[t] || 0;
          optHtml += `<option value="${t}">${t} (${cnt}장)</option>`;
        });
        optHtml += `</optgroup>`;
      }
    }
    select.innerHTML = optHtml;
  }

  const quickContainer = document.getElementById('quick-popular-tags');
  if (quickContainer) {
    const sortedTags = Object.entries(tagFreq).sort((a, b) => b[1] - a[1]).slice(0, 8);
    quickContainer.innerHTML = sortedTags.map(([t, cnt]) => `
      <button class="filter-btn quick-tag-btn ${selectedTags.has(t) ? 'active' : ''}" 
              data-tag="${t}" 
              style="padding:3px 9px;font-size:0.75rem;" 
              onclick="toggleTagFilter('${t.replace(/'/g, "\\'")}')">
        #${t} <small style="opacity:0.75;">(${cnt})</small>
      </button>
    `).join('');
  }
}

// Global exports
window.TAG_CATEGORIES = TAG_CATEGORIES;
window.selectedTags = selectedTags;
window.tagLogic = tagLogic;
window.setTagLogic = setTagLogic;
window.toggleTagFilter = toggleTagFilter;
window.clearAllSelectedTags = clearAllSelectedTags;
window.onTagSelectChange = onTagSelectChange;
window.getAllTagsFromItem = getAllTagsFromItem;
window.getTagColorStyle = getTagColorStyle;
window.renderTagPills = renderTagPills;
window.updateTagFilterUI = updateTagFilterUI;
window.populateTagSelectorAndQuickTags = populateTagSelectorAndQuickTags;
