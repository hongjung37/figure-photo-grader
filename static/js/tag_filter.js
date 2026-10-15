// --- Tag Filter & Insights Module (static/js/tag_filter.js) ---

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
let insightsMinCount = 2;
let insightsRatingMode = 'ai'; // 'ai', 'user', 'diff'

function setTagLogic(mode) {
  tagLogic = mode;
  const btnAnd = document.getElementById('tag-logic-and');
  const btnOr = document.getElementById('tag-logic-or');
  if (btnAnd) btnAnd.classList.toggle('active', mode === 'AND');
  if (btnOr) btnOr.classList.toggle('active', mode === 'OR');
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
  if (typeof renderGallery === 'function') renderGallery();
}

function clearAllSelectedTags() {
  selectedTags.clear();
  updateTagFilterUI();
  if (typeof renderGallery === 'function') renderGallery();
}

function updateTagFilterUI() {
  const bar = document.getElementById('selected-tags-bar');
  const list = document.getElementById('selected-tags-list');
  if (!bar || !list) return;

  if (selectedTags.size === 0) {
    bar.style.display = 'none';
    list.innerHTML = '';
  } else {
    bar.style.display = 'flex';
    list.innerHTML = Array.from(selectedTags).map(tag => `
      <span class="active-tag-chip" onclick="toggleTagFilter('${tag.replace(/'/g, "\\'")}')">
        ${typeof escapeHtml === 'function' ? escapeHtml(tag) : tag} &times;
      </span>
    `).join('');
  }

  document.querySelectorAll('.tag-filter-chip').forEach(el => {
    const t = el.getAttribute('data-tag');
    if (selectedTags.has(t)) {
      el.classList.add('selected');
    } else {
      el.classList.remove('selected');
    }
  });
}

window.TAG_CATEGORIES = TAG_CATEGORIES;
window.selectedTags = selectedTags;
window.setTagLogic = setTagLogic;
window.toggleTagFilter = toggleTagFilter;
window.clearAllSelectedTags = clearAllSelectedTags;
window.updateTagFilterUI = updateTagFilterUI;
