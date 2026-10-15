// --- API Client Module (static/js/api.js) ---

const API = {
  async fetchAnalyses(burstDist = 15) {
    const res = await fetch(`/api/analyses?burst_dist=${burstDist}`);
    if (!res.ok) throw new Error(`서버 응답 오류: ${res.status}`);
    return await res.json();
  },

  async fetchUsageStats() {
    const res = await fetch('/api/usage-stats');
    if (!res.ok) throw new Error(`사용 통계 조회 오류: ${res.status}`);
    return await res.json();
  },

  async fetchTagStats(minCount = 1) {
    const res = await fetch(`/api/tag-stats?min_count=${minCount}`);
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
    const res = await fetch('/api/delete-analysis', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids: Array.isArray(ids) ? ids : [ids] })
    });
    return await res.json();
  },

  async exportXmp() {
    const res = await fetch('/api/export-xmp', { method: 'POST' });
    return await res.json();
  },

  async fetchLightroomAdvice(id) {
    const res = await fetch(`/api/post-process-advice/${id}`, { method: 'POST' });
    return await res.json();
  },

  async fetchSnsCrop(id, ratioKey = 'all', force = false) {
    const res = await fetch(`/api/sns-crop/${ratioKey}/${id}${force ? '?force=true' : ''}`, { method: 'POST' });
    return await res.json();
  },

  async fetchSnsCaption(id, force = false) {
    const res = await fetch(`/api/sns-caption/${id}${force ? '?force=true' : ''}`, { method: 'POST' });
    return await res.json();
  },

  async uploadPhoto(formData, force = false) {
    const res = await fetch(`/api/analyze${force ? '?force=true' : ''}`, {
      method: 'POST',
      body: formData
    });
    return await res.json();
  }
};

window.API = API;
