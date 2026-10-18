// --- API Client Module (static/js/api.js) ---

const DEFAULT_AI_MODEL_SETTINGS = {
  photo_grading: 'luna',
  lightroom_advice: 'lite',
  sns_crop: 'lite',
  sns_caption: 'lite',
  median_sampling: 'false'
};

const TASK_MODEL_OPTIONS = [
  { value: 'lite', label: '⚡ Flash-Lite 3.1 (초고속)', shortLabel: '⚡ Flash-Lite 3.1' },
  { value: 'standard', label: '🔍 Flash-Lite 3.5 (표준)', shortLabel: '🔍 Flash-Lite 3.5' },
  { value: 'pro', label: '💎 Flash 3.8 (고화질 심층)', shortLabel: '💎 Flash 3.8' },
  { value: 'luna', label: '🌙 GPT-6 Luna (OpenAI)', shortLabel: '🌙 GPT-6 Luna' }
];

const ModelSettings = {
  load() {
    try {
      const raw = localStorage.getItem('ai_model_settings');
      if (!raw) return { ...DEFAULT_AI_MODEL_SETTINGS };
      const parsed = JSON.parse(raw);
      return {
        photo_grading: parsed.photo_grading || DEFAULT_AI_MODEL_SETTINGS.photo_grading,
        lightroom_advice: parsed.lightroom_advice || DEFAULT_AI_MODEL_SETTINGS.lightroom_advice,
        sns_crop: parsed.sns_crop || DEFAULT_AI_MODEL_SETTINGS.sns_crop,
        sns_caption: parsed.sns_caption || DEFAULT_AI_MODEL_SETTINGS.sns_caption,
        median_sampling: parsed.median_sampling != null ? String(parsed.median_sampling) : DEFAULT_AI_MODEL_SETTINGS.median_sampling
      };
    } catch (e) {
      return { ...DEFAULT_AI_MODEL_SETTINGS };
    }
  },

  save(settings) {
    const merged = { ...this.load(), ...settings };
    try {
      localStorage.setItem('ai_model_settings', JSON.stringify(merged));
    } catch (e) {}
    return merged;
  },

  get(taskKey) {
    const current = this.load();
    return current[taskKey] || DEFAULT_AI_MODEL_SETTINGS[taskKey] || 'lite';
  },

  set(taskKey, modelValue) {
    return this.save({ [taskKey]: modelValue });
  },

  formatBadge(modelStr) {
    if (!modelStr) return '';
    const s = String(modelStr).toLowerCase();
    if (s.startsWith('ensemble') || s.includes('+')) {
      let gLabel = 'Lite 3.5';
      if (s.includes('3.8') || s.includes('pro')) gLabel = 'Flash 3.8';
      else if (s.includes('3.7')) gLabel = 'Flash 3.7';
      else if (s.includes('3.6')) gLabel = 'Flash 3.6';
      else if (s.includes('3.1') || s.includes('lite)')) gLabel = 'Lite 3.1';
      else if (s.includes('3.5')) gLabel = 'Lite 3.5';
      return `🤝 ${gLabel} + Luna`;
    }
    if (s.includes('luna')) return '🌙 GPT-6 Luna';
    if (s.includes('3.8') || s === 'pro') return '💎 Flash 3.8';
    if (s.includes('3.7') || s === 'flash-3.7') return '🚀 Flash 3.7';
    if (s.includes('3.6') || s === 'flash-3.6') return '🧪 Flash 3.6';
    if (s.includes('3.5') || s === 'standard') return '🔍 Flash-Lite 3.5';
    if (s.includes('3.1') || s === 'lite') return '⚡ Flash-Lite 3.1';
    if (s.includes('gpt-4o-mini') || s === 'mini') return '🤖 GPT-4o mini';
    if (s.includes('gpt-4o')) return '🤖 GPT-4o';
    return modelStr;
  },

  renderOptionsHtml(selectedValue) {
    const sel = selectedValue || 'lite';
    let html = TASK_MODEL_OPTIONS.map(opt =>
      `<option value="${opt.value}" ${opt.value === sel ? 'selected' : ''}>${opt.label}</option>`
    ).join('');
    if (sel && !TASK_MODEL_OPTIONS.some(opt => opt.value === sel)) {
      html += `<option value="${sel}" selected>${this.formatBadge(sel)}</option>`;
    }
    return html;
  }
};

window.ModelSettings = ModelSettings;
window.TASK_MODEL_OPTIONS = TASK_MODEL_OPTIONS;

const API = {
  async fetchAnalyses(burstDist = 15) {
    const res = await fetch(`/api/analyses?burst_dist=${burstDist}&_t=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`서버 응답 오류: ${res.status}`);
    return await res.json();
  },

  async fetchUsageStats() {
    const res = await fetch(`/api/usage-stats?_t=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`사용 통계 조회 오류: ${res.status}`);
    return await res.json();
  },

  async fetchTagStats(minCount = 1) {
    const res = await fetch(`/api/tag-stats?min_count=${minCount}&_t=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`태그 통계 조회 오류: ${res.status}`);
    return await res.json();
  },

  async updateStatus(id, status) {
    const res = await fetch('/api/update-status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, status })
    });
    return await res.json();
  },

  async ratePhoto(id, userScore) {
    const res = await fetch('/api/rate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, user_score: userScore })
    });
    return await res.json();
  },

  async deleteAnalyses(ids) {
    const recordIds = Array.isArray(ids) ? ids : [ids];
    const res = await fetch('/api/delete-analysis', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: recordIds, id: recordIds[0] })
    });
    return await res.json();
  },

  async exportXmp() {
    const res = await fetch('/api/export-xmp', { method: 'POST' });
    return await res.json();
  },

  async fetchLightroomAdvice(id, force = false, model = '') {
    const chosenModel = model || ModelSettings.get('lightroom_advice');
    const params = new URLSearchParams();
    if (force) params.set('force', 'true');
    if (chosenModel) params.set('model', chosenModel);
    const qs = params.toString() ? `?${params.toString()}` : '';
    const res = await fetch(`/api/post-process-advice/${id}${qs}`, { method: 'POST' });
    return await res.json();
  },

  async fetchSnsCrop(id, ratioKey = 'all', force = false, model = '') {
    const chosenModel = model || ModelSettings.get('sns_crop');
    const params = new URLSearchParams();
    if (force) params.set('force', 'true');
    if (chosenModel) params.set('model', chosenModel);
    const qs = params.toString() ? `?${params.toString()}` : '';
    const res = await fetch(`/api/sns-crop/${ratioKey}/${id}${qs}`, { method: 'POST' });
    return await res.json();
  },

  async fetchSnsCaption(id, force = false, model = '') {
    const chosenModel = model || ModelSettings.get('sns_caption');
    const params = new URLSearchParams();
    if (force) params.set('force', 'true');
    if (chosenModel) params.set('model', chosenModel);
    const qs = params.toString() ? `?${params.toString()}` : '';
    const res = await fetch(`/api/sns-caption/${id}${qs}`, { method: 'POST' });
    return await res.json();
  },

  async uploadPhoto(formData, force = false) {
    const res = await fetch(`/api/analyze${force ? '?force=true' : ''}`, {
      method: 'POST',
      body: formData
    });
    return await res.json();
  },

  async reanalyzePhoto(id, mode = 'cross_check_only', tier = 'standard', category = 'auto', sampleCount = 1) {
    const res = await fetch('/api/reanalyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, mode, tier, category, sample_count: sampleCount })
    });
    return await res.json();
  }
};

window.API = API;

