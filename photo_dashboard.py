from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sqlite3
import sys
import tempfile
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from photo_analyzer import (
    DEFAULT_DB_PATH,
    MODEL_PRESETS,
    PhotoAnalysis,
    analyze_with_gemini,
    prepare_photo,
    save_analysis,
)
from photo_tag_schema import AESTHETIC_TAG_CATEGORIES, get_score_grade

PORT = 8080


def get_all_analyses(db_path: Path) -> list[dict]:
    if not db_path.is_file():
        return []
    from contextlib import closing
    with closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM photo_analyses ORDER BY id DESC"
        ).fetchall()

        tag_rows = conn.execute(
            "SELECT analysis_id, category_key, tag FROM photo_analysis_tags"
        ).fetchall()

    tags_by_id: dict[int, dict[str, list[str]]] = {}
    for r in tag_rows:
        aid = int(r["analysis_id"])
        ckey = str(r["category_key"])
        tag = str(r["tag"])
        tags_by_id.setdefault(aid, {}).setdefault(ckey, []).append(tag)

    results = []
    for row in rows:
        aid = int(row["id"])
        try:
            analysis_data = json.loads(row["analysis_json"])
            exif_data = json.loads(row["exif_json"])
        except Exception:
            continue

        final_score = float(analysis_data.get("final_score", 0))
        results.append(
            {
                "id": aid,
                "sha256": row["sha256"],
                "filename": row["source_filename"],
                "width": row["width"],
                "height": row["height"],
                "format": row["image_format"],
                "model": row["model"],
                "created_at": row["created_at"],
                "review_status": row["review_status"] if "review_status" in row.keys() else "미검토",
                "user_notes": row["user_notes"] if "user_notes" in row.keys() else "", 
                "final_score": final_score,
                "grade": get_score_grade(final_score),
                "figure_category": analysis_data.get("figure_category", "일반 피규어 촬영"),
                "composition_score": float(analysis_data.get("composition_score", 0)),
                "composition_notes": analysis_data.get("composition_notes", ""),
                "lighting_score": float(analysis_data.get("lighting_score", 0)),
                "lighting_notes": analysis_data.get("lighting_notes", ""),
                "color_score": float(analysis_data.get("color_score", 0)),
                "color_notes": analysis_data.get("color_notes", ""),
                "technique_score": float(analysis_data.get("technique_score", 0)),
                "technique_notes": analysis_data.get("technique_notes", ""),
                "final_reason": analysis_data.get("final_reason", ""),
                "strengths": analysis_data.get("strengths", []),
                "improvements": analysis_data.get("improvements", []),
                "aesthetic_tags": tags_by_id.get(aid, analysis_data.get("aesthetic_tags", {})),
                "exif": exif_data,
            }
        )
    return results


DASHBOARD_HTML = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>피규어 포토 그레이더 — Culling & Review 대시보드</title>
<style>
:root {
  --ink: #17233b; --muted: #64748b; --navy: #0f172a; --blue: #3b82f6; --teal: #0d9488;
  --line: #e2e8f0; --paper: #f8fafc; --card: #ffffff; --accent: #6366f1;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--paper); color: var(--ink); font-family: "Pretendard", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; line-height: 1.5; }
header { background: linear-gradient(135deg, #0f172a 0%, #1e293b 60%, #312e81 100%); color: white; padding: 24px 32px; box-shadow: 0 4px 20px rgba(0,0,0,0.12); }
.top-bar { display: flex; justify-content: space-between; align-items: center; max-width: 1400px; margin: 0 auto; flex-wrap: wrap; gap: 16px; }
h1 { margin: 0; font-size: 1.6rem; font-weight: 800; letter-spacing: -0.02em; display: flex; align-items: center; gap: 10px; }
h1 span { font-size: 0.75rem; background: var(--teal); color: white; padding: 3px 9px; border-radius: 999px; font-weight: 600; }
.stats-bar { display: flex; gap: 18px; font-size: 0.88rem; color: #cbd5e1; }
.stats-bar strong { color: white; font-size: 1.15rem; }

.main-container { max-width: 1400px; margin: 24px auto; padding: 0 24px; }
.controls { background: var(--card); border: 1px solid var(--line); border-radius: 16px; padding: 18px 22px; display: flex; flex-wrap: wrap; gap: 16px; align-items: center; justify-content: space-between; box-shadow: 0 2px 10px rgba(0,0,0,0.03); }
.filter-group { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.filter-btn { background: #f1f5f9; border: 1px solid var(--line); padding: 7px 14px; border-radius: 999px; font-size: 0.84rem; font-weight: 600; color: var(--muted); cursor: pointer; transition: all .15s; }
.filter-btn:hover { background: #e2e8f0; color: var(--ink); }
.filter-btn.active { background: var(--navy); color: white; border-color: var(--navy); }
.select-input { padding: 8px 12px; border-radius: 10px; border: 1px solid var(--line); font-size: 0.86rem; background: white; color: var(--ink); font-weight: 500; }

.view-tabs { display: flex; gap: 6px; background: #f1f5f9; padding: 4px; border-radius: 12px; }
.tab-btn { border: none; background: transparent; padding: 6px 14px; border-radius: 8px; font-size: 0.84rem; font-weight: 700; color: var(--muted); cursor: pointer; }
.tab-btn.active { background: white; color: var(--navy); box-shadow: 0 2px 6px rgba(0,0,0,0.06); }

/* Gallery Grid */
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 20px; margin-top: 22px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 18px; overflow: hidden; box-shadow: 0 4px 16px rgba(0,0,0,0.04); transition: transform .15s, box-shadow .15s; display: flex; flex-direction: column; cursor: pointer; }
.card:hover { transform: translateY(-3px); box-shadow: 0 10px 28px rgba(0,0,0,0.08); border-color: #cbd5e1; }
.card-thumb { width: 100%; height: 260px; object-fit: contain; background: #0f172a; display: block; }
.card-body { padding: 18px; flex: 1; display: flex; flex-direction: column; }
.card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 8px; margin-bottom: 10px; }
.card-title { font-size: 1.02rem; font-weight: 700; margin: 0; overflow-wrap: anywhere; }
.score-badge { display: flex; flex-direction: column; align-items: flex-end; }
.score-num { font-size: 1.7rem; font-weight: 900; line-height: 1; color: var(--blue); }
.score-grade { font-size: 0.74rem; font-weight: 700; background: #e0f2fe; color: #0369a1; padding: 2px 8px; border-radius: 999px; margin-top: 4px; }
.mini-scores { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin: 12px 0; background: #f8fafc; padding: 9px; border-radius: 10px; font-size: 0.76rem; text-align: center; }
.mini-scores span { display: block; color: var(--muted); }
.mini-scores strong { display: block; font-size: 0.95rem; color: var(--navy); }
.reason-box { font-size: 0.86rem; color: #475569; margin: 8px 0; line-height: 1.45; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; flex: 1; }
.tag-pills { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; }
.tag-pill { background: #f1f5f9; color: #475569; font-size: 0.72rem; font-weight: 600; padding: 2px 7px; border-radius: 6px; }

/* Comparison Mode */
.compare-container { display: none; margin-top: 22px; }
.compare-selectors { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 18px; }
.compare-box { background: var(--card); border: 1px solid var(--line); border-radius: 18px; padding: 20px; }
.compare-columns { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.compare-col { background: var(--card); border: 1px solid var(--line); border-radius: 18px; overflow: hidden; padding: 20px; box-shadow: 0 4px 16px rgba(0,0,0,0.04); }
.compare-img { width: 100%; max-height: 480px; object-fit: contain; background: #0f172a; border-radius: 12px; }

/* Detail Modal */
.modal-overlay { position: fixed; inset: 0; background: rgba(15,23,42,0.7); backdrop-filter: blur(4px); display: none; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
.modal-content { background: white; border-radius: 24px; max-width: 1050px; width: 100%; max-height: 90vh; overflow-y: auto; padding: 32px; box-shadow: 0 25px 60px rgba(0,0,0,0.25); position: relative; }
.close-btn { position: absolute; top: 20px; right: 24px; font-size: 1.8rem; background: transparent; border: none; cursor: pointer; color: var(--muted); }
.modal-grid { display: grid; grid-template-columns: 1.05fr 1fr; gap: 28px; }
.detail-img { width: 100%; max-height: 520px; object-fit: contain; background: #0f172a; border-radius: 16px; }
.note-item { background: #f8fafc; border-left: 3px solid var(--blue); padding: 12px 16px; border-radius: 0 10px 10px 0; margin-bottom: 12px; font-size: 0.88rem; white-space: pre-wrap; }
.note-item h4 { margin: 0 0 6px; font-size: 0.94rem; display: flex; justify-content: space-between; }
.list-box { background: #f8fafc; padding: 14px 18px; border-radius: 12px; margin-top: 12px; }
.list-box h4 { margin: 0 0 8px; font-size: 0.92rem; }
.list-box ul { margin: 0; padding-left: 20px; font-size: 0.86rem; color: #475569; }

/* Upload Modal */
.upload-btn { background: var(--blue); color: white; border: none; padding: 9px 18px; border-radius: 10px; font-weight: 700; font-size: 0.88rem; cursor: pointer; display: flex; align-items: center; gap: 6px; }
.upload-btn:hover { background: #2563eb; }
.drop-zone { border: 2px dashed #94a3b8; border-radius: 16px; padding: 36px 20px; text-align: center; color: var(--muted); cursor: pointer; margin: 18px 0; transition: border-color .15s; }
.drop-zone:hover { border-color: var(--blue); background: #f8fafc; }

@media (max-width: 850px) {
  .compare-columns, .compare-selectors, .modal-grid { grid-template-columns: 1fr; }
  header { padding: 18px 20px; }
  .main-container { padding: 0 16px; }
}
</style>
</head>
<body>

<header>
  <div class="top-bar">
    <h1>피규어 포토 그레이더 <span>PRO GRADER</span></h1>
    <div class="stats-bar">
      <div>총 사진 <strong id="total-count">0</strong>장</div>
      <div>평균 점수 <strong id="avg-score">0.0</strong>점</div>
      <div>우수(7.0+) <strong id="good-count">0</strong>장</div>
    </div>
    <button class="upload-btn" onclick="openUploadModal()">+ 새 사진 분석하기</button>
  </div>
</header>

<main class="main-container">
  <div class="controls">
    <div class="filter-group">
      <span style="font-size:0.84rem;font-weight:700;color:var(--muted)">등급:</span>
      <button class="filter-btn active" onclick="setFilter('all', this)">전체</button>
      <button class="filter-btn" onclick="setFilter('pro', this)">프로작가급 (9.0+)</button>
      <button class="filter-btn" onclick="setFilter('very_good', this)">매우 우수 (8.0+)</button>
      <button class="filter-btn" onclick="setFilter('good', this)">우수 (7.0+)</button>
      <button class="filter-btn" onclick="setFilter('normal', this)">보통 스냅 (5.0~6.9)</button>
    </div>
    <div class="filter-group" style="margin-top:8px;">
      <span style="font-size:0.84rem;font-weight:700;color:var(--muted)">피규어 유형:</span>
      <button class="filter-btn active cat-btn" onclick="setCatFilter('all', this)">전체 유형</button>
      <button class="filter-btn cat-btn" onclick="setCatFilter('접사/디테일', this)">🔍 접사/디테일</button>
      <button class="filter-btn cat-btn" onclick="setCatFilter('일상/야외 스냅', this)">🌿 일상/야외 스냅</button>
      <button class="filter-btn cat-btn" onclick="setCatFilter('스튜디오 연출/디오라마', this)">🎬 스튜디오 연출</button>
      <button class="filter-btn cat-btn" onclick="setCatFilter('일반 피규어 촬영', this)">📷 일반 촬영</button>
    </div>

    <div style="display:flex;gap:12px;align-items:center;">
      <select class="select-input" id="sort-select" onchange="renderGallery()">
        <option value="score_desc">점수 높은 순</option>
        <option value="score_asc">점수 낮은 순</option>
        <option value="newest">최신 분석 순</option>
        <option value="name">파일명 순</option>
      </select>

      <div class="view-tabs">
        <button class="tab-btn active" id="tab-gallery" onclick="switchView('gallery')">갤러리 뷰</button>
        <button class="tab-btn" id="tab-compare" onclick="switchView('compare')">1:1 비교(Culling)</button>
      </div>
    </div>
  </div>

  <!-- Gallery View -->
  <div class="grid" id="gallery-grid"></div>

  <!-- Comparison View -->
  <div class="compare-container" id="compare-view">
    <div class="compare-selectors">
      <div>
        <label style="font-weight:700;font-size:0.88rem;display:block;margin-bottom:6px;">비교 사진 A (기준컷)</label>
        <select class="select-input" id="comp-a-select" style="width:100%" onchange="updateComparison()"></select>
      </div>
      <div>
        <label style="font-weight:700;font-size:0.88rem;display:block;margin-bottom:6px;">비교 사진 B (비교컷)</label>
        <select class="select-input" id="comp-b-select" style="width:100%" onchange="updateComparison()"></select>
      </div>
    </div>
    <div class="compare-columns" id="compare-content"></div>
  </div>
</main>

<!-- Detail Modal -->
<div class="modal-overlay" id="detail-modal" onclick="closeModal(event)">
  <div class="modal-content" onclick="event.stopPropagation()">
    <button class="close-btn" onclick="closeDetailModal()">&times;</button>
    <div class="modal-grid" id="modal-body"></div>
  </div>
</div>

<!-- Upload Modal -->
<div class="modal-overlay" id="upload-modal" onclick="closeUploadModal(event)">
  <div class="modal-content" style="max-width:550px;" onclick="event.stopPropagation()">
    <button class="close-btn" onclick="closeUploadModal()">&times;</button>
    <h2 style="margin:0 0 10px;">새 피규어 사진 분석</h2>
    <p style="color:var(--muted);font-size:0.88rem;margin:0 0 16px;">사진 파일을 선택하면 피규어 비평 기준에 따라 자동 분석 후 SQLite에 저장합니다.</p>
    
    <label style="font-weight:700;font-size:0.84rem;display:block;margin-bottom:6px;">분석 모델 티어 선택:</label>
    <select class="select-input" id="upload-tier" style="width:100%;margin-bottom:14px;">
      <option value="lite">Flash-Lite (초고속 스크리닝 / 기본)</option>
      <option value="standard">2.5-Flash (균형 잡힌 화질 평가)</option>
      <option value="pro">2.5-Pro (전문가급 심층 비평)</option>
    </select>

    <div class="drop-zone" onclick="document.getElementById('file-input').click()">
      <div style="font-size:2rem;margin-bottom:8px;">📷</div>
      <strong>사진 파일을 클릭하여 선택하거나 드래그하세요</strong>
      <div style="font-size:0.78rem;margin-top:6px;">지원: JPG, PNG, WEBP, MPO</div>
      <input type="file" id="file-input" style="display:none" accept="image/jpeg,image/png,image/webp" onchange="handleFileSelect(event)">
    </div>
    <div id="upload-status" style="font-size:0.88rem;font-weight:600;text-align:center;"></div>
  </div>
</div>

<script>
let allData = [];
let currentFilter = 'all';
let currentCatFilter = 'all';

function setCatFilter(cat, btn) {
  currentCatFilter = cat;
  document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderGallery();
}

async function loadData() {
  const res = await fetch('/api/analyses');
  allData = await res.json();
  updateStats();
  populateCompareSelects();
  renderGallery();
}

function updateStats() {
  document.getElementById('total-count').textContent = allData.length;
  if (!allData.length) return;
  const avg = (allData.reduce((acc, cur) => acc + cur.final_score, 0) / allData.length).toFixed(1);
  const good = allData.filter(d => d.final_score >= 7.0).length;
  document.getElementById('avg-score').textContent = avg;
  document.getElementById('good-count').textContent = good;
}

function setFilter(filter, btn) {
  currentFilter = filter;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderGallery();
}

function filterList(list) {
  let res = list;
  if (currentFilter === 'pro') res = res.filter(d => d.final_score >= 9.0);
  else if (currentFilter === 'very_good') res = res.filter(d => d.final_score >= 8.0 && d.final_score < 9.0);
  else if (currentFilter === 'good') res = res.filter(d => d.final_score >= 7.0 && d.final_score < 8.0);
  else if (currentFilter === 'normal') res = res.filter(d => d.final_score >= 5.0 && d.final_score < 7.0);

  if (currentCatFilter !== 'all') {
    res = res.filter(d => d.figure_category === currentCatFilter);
  }
  return res;
}

function sortList(list) {
  const sort = document.getElementById('sort-select').value;
  return [...list].sort((a, b) => {
    if (sort === 'score_desc') return b.final_score - a.final_score;
    if (sort === 'score_asc') return a.final_score - b.final_score;
    if (sort === 'newest') return b.id - a.id;
    if (sort === 'name') return a.filename.localeCompare(b.filename);
    return 0;
  });
}

function renderGallery() {
  const container = document.getElementById('gallery-grid');
  const filtered = sortList(filterList(allData));
  if (!filtered.length) {
    container.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:60px;color:var(--muted)">해당 조건의 분석 사진이 없습니다.</div>';
    return;
  }
  container.innerHTML = filtered.map(item => `
    <article class="card" onclick="openDetailModal(${item.id})">
      <img class="card-thumb" src="/api/image/${item.id}" alt="${item.filename}" loading="lazy">
      <div class="card-body">
        <div class="card-header">
          <div>
            <h3 class="card-title">${item.filename}</h3>
            <span style="display:inline-block;margin-top:4px;font-size:0.75rem;font-weight:700;color:#4f46e5;background:#eef2ff;padding:2px 7px;border-radius:6px;">${item.figure_category}</span>
          </div>
          <div class="score-badge">
            <span class="score-num">${item.final_score.toFixed(1)}</span>
            <span class="score-grade">${item.grade}</span>
          </div>
        </div>
        <div class="mini-scores">
          <div><span>구도</span><strong>${item.composition_score.toFixed(1)}</strong></div>
          <div><span>조명</span><strong>${item.lighting_score.toFixed(1)}</strong></div>
          <div><span>색감</span><strong>${item.color_score.toFixed(1)}</strong></div>
          <div><span>기술</span><strong>${item.technique_score.toFixed(1)}</strong></div>
        </div>
        <div class="reason-box">${item.final_reason}</div>
        <div class="tag-pills">
          ${renderTagPills(item.aesthetic_tags)}
        </div>
      </div>
    </article>
  `).join('');
}

function renderTagPills(tags) {
  if (!tags) return '';
  const pills = [];
  for (const [k, v] of Object.entries(tags)) {
    if (Array.isArray(v)) {
      v.forEach(t => pills.push(`<span class="tag-pill">${t}</span>`));
    }
  }
  return pills.slice(0, 4).join('');
}

function openDetailModal(id) {
  const item = allData.find(d => d.id === id);
  if (!item) return;
  const modal = document.getElementById('detail-modal');
  const body = document.getElementById('modal-body');

  body.innerHTML = `
    <div>
      <img class="detail-img" src="/api/image/${item.id}" alt="${item.filename}">
      <div style="margin-top:14px;font-size:0.84rem;color:var(--muted)">
        <div><b>해상도:</b> ${item.width} × ${item.height}px (${item.format})</div>
        <div><b>분석 모델:</b> ${item.model} · <b>분석시각:</b> ${item.created_at}</div>
        ${renderExifSummary(item.exif)}
      </div>
    </div>
    <div>
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px;">
        <div>
          <h2 style="margin:0;">${item.filename}</h2>
          <span class="score-grade" style="font-size:0.86rem;padding:4px 12px;">${item.grade}</span>
        </div>
        <div style="text-align:right;">
          <div style="font-size:2.8rem;font-weight:900;color:var(--blue);line-height:1;">${item.final_score.toFixed(1)}</div>
          <small style="color:var(--muted)">10점 만점</small>
        </div>
      </div>

      <div style="background:#eef2ff;padding:12px 16px;border-radius:12px;margin-bottom:16px;font-size:0.9rem;color:#3730a3">
        <b>종합 총평:</b> ${item.final_reason}
      </div>

      <div class="note-item">
        <h4><span>📐 구도 평가</span> <strong>${item.composition_score.toFixed(1)}</strong></h4>
        <div>${item.composition_notes}</div>
      </div>
      <div class="note-item">
        <h4><span>💡 조명/노출 평가</span> <strong>${item.lighting_score.toFixed(1)}</strong></h4>
        <div>${item.lighting_notes}</div>
      </div>
      <div class="note-item">
        <h4><span>🎨 색감/톤 평가</span> <strong>${item.color_score.toFixed(1)}</strong></h4>
        <div>${item.color_notes}</div>
      </div>
      <div class="note-item">
        <h4><span>📷 촬영 기술 평가</span> <strong>${item.technique_score.toFixed(1)}</strong></h4>
        <div>${item.technique_notes}</div>
      </div>

      <div class="list-box">
        <h4 style="color:var(--teal)">✓ 주요 장점</h4>
        <ul>${item.strengths.map(s => `<li>${s}</li>`).join('')}</ul>
      </div>
      <div class="list-box" style="margin-top:8px;">
        <h4 style="color:#e11d48">✗ 단점 및 다음 촬영 개선점</h4>
        <ul>${item.improvements.map(i => `<li>${i}</li>`).join('')}</ul>
      </div>
    </div>
  `;
  modal.style.display = 'flex';
}

function renderExifSummary(exif) {
  if (!exif || !Object.keys(exif).length) return '<div style="margin-top:4px;"><b>EXIF:</b> 안전 촬영 메타데이터 없음</div>';
  const parts = [];
  if (exif.Make || exif.Model) parts.push(`${exif.Make || ''} ${exif.Model || ''}`.trim());
  if (exif.FNumber) parts.push(`F/${exif.FNumber}`);
  if (exif.ExposureTime) parts.push(`${exif.ExposureTime}s`);
  if (exif.ISOSpeedRatings) parts.push(`ISO ${exif.ISOSpeedRatings}`);
  if (exif.FocalLength) parts.push(`${exif.FocalLength}mm`);
  return `<div style="margin-top:4px;"><b>촬영 설정:</b> ${parts.join(' · ')}</div>`;
}

function closeDetailModal() { document.getElementById('detail-modal').style.display = 'none'; }
function closeModal(e) { if (e.target.id === 'detail-modal') closeDetailModal(); }

function switchView(mode) {
  if (mode === 'gallery') {
    document.getElementById('gallery-grid').style.display = 'grid';
    document.getElementById('compare-view').style.display = 'none';
    document.getElementById('tab-gallery').classList.add('active');
    document.getElementById('tab-compare').classList.remove('active');
  } else {
    document.getElementById('gallery-grid').style.display = 'none';
    document.getElementById('compare-view').style.display = 'block';
    document.getElementById('tab-gallery').classList.remove('active');
    document.getElementById('tab-compare').classList.add('active');
    updateComparison();
  }
}

function populateCompareSelects() {
  const selA = document.getElementById('comp-a-select');
  const selB = document.getElementById('comp-b-select');
  const options = allData.map(d => `<option value="${d.id}">${d.filename} (${d.final_score.toFixed(1)}점 - ${d.grade})</option>`).join('');
  selA.innerHTML = options;
  selB.innerHTML = options;
  if (allData.length > 1) selB.selectedIndex = 1;
}

function updateComparison() {
  const idA = parseInt(document.getElementById('comp-a-select').value);
  const idB = parseInt(document.getElementById('comp-b-select').value);
  const a = allData.find(d => d.id === idA);
  const b = allData.find(d => d.id === idB);
  if (!a || !b) return;

  const content = document.getElementById('compare-content');
  content.innerHTML = [a, b].map((item, idx) => `
    <div class="compare-col">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
        <h3 style="margin:0;">사진 ${idx === 0 ? 'A' : 'B'}: ${item.filename}</h3>
        <span class="score-grade">${item.grade}</span>
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
      <div style="background:#f8fafc;padding:12px;border-radius:10px;font-size:0.88rem;margin-bottom:12px;">
        <b>한줄 총평:</b> ${item.final_reason}
      </div>
      <div class="list-box">
        <h4 style="color:var(--teal)">✓ 주요 장점</h4>
        <ul>${item.strengths.map(s => `<li>${s}</li>`).join('')}</ul>
      </div>
      <div class="list-box" style="margin-top:8px;">
        <h4 style="color:#e11d48">✗ 단점 및 아쉬운 점</h4>
        <ul>${item.improvements.map(i => `<li>${i}</li>`).join('')}</ul>
      </div>
    </div>
  `).join('');
}

function openUploadModal() {
  document.getElementById('upload-modal').style.display = 'flex';
  document.getElementById('upload-status').textContent = '';
}
function closeUploadModal(e) {
  if (!e || e.target.id === 'upload-modal') {
    document.getElementById('upload-modal').style.display = 'none';
  }
}

async function handleFileSelect(e) {
  const file = e.target.files[0];
  if (!file) return;
  const tier = document.getElementById('upload-tier').value;
  const status = document.getElementById('upload-status');
  status.textContent = 'Gemini API 분석 중입니다 (수 초 소요)...';
  status.style.color = 'var(--blue)';

  const formData = new FormData();
  formData.append('image', file);
  formData.append('tier', tier);

  try {
    const res = await fetch('/api/analyze', { method: 'POST', body: formData });
    const result = await res.json();
    if (result.success) {
      status.textContent = `분석 완료! (${result.analysis.final_score.toFixed(1)}점)`;
      status.style.color = 'var(--teal)';
      setTimeout(() => {
        closeUploadModal();
        loadData();
      }, 1000);
    } else {
      status.textContent = `오류: ${result.error}`;
      status.style.color = '#e11d48';
    }
  } catch (err) {
    status.textContent = `업로드 실패: ${err.message}`;
    status.style.color = '#e11d48';
  }
}

window.addEventListener('DOMContentLoaded', loadData);
</script>
</body>
</html>
"""


class DashboardRequestHandler(SimpleHTTPRequestHandler):
    db_path: Path = DEFAULT_DB_PATH

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
            return

        if path == "/api/analyses":
            data = get_all_analyses(self.db_path)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        if path.startswith("/api/image/"):
            try:
                record_id = int(path.split("/")[-1])
                # Check SQLite record and return uploaded photo bytes if stored or re-read from test_photo
                with closing(sqlite3.connect(self.db_path)) as conn:
                    row = conn.execute(
                        "SELECT source_filename FROM photo_analyses WHERE id = ?", (record_id,)
                    ).fetchone()
                if row:
                    fname = row[0]
                    # Search for photo file locally
                    for search_dir in (Path("test_photo"), Path("."), Path("outputs")):
                        cand = search_dir / fname
                        if cand.is_file():
                            mime, _ = mimetypes.guess_type(str(cand))
                            data = cand.read_bytes()
                            self.send_response(HTTPStatus.OK)
                            self.send_header("Content-Type", mime or "image/jpeg")
                            self.send_header("Content-Length", str(len(data)))
                            self.end_headers()
                            self.wfile.write(data)
                            return
            except Exception:
                pass
            # Return transparent placeholder if not found
            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
            return

        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/analyze":
            try:
                content_type = self.headers.get("Content-Type", "")
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)

                # Parse multipart form data
                boundary = content_type.split("boundary=")[-1].strip()
                parts = body.split(f"--{boundary}".encode("utf-8"))

                file_bytes = None
                filename = "uploaded.webp"
                tier = "lite"

                for part in parts:
                    if b'name="tier"' in part:
                        tier = part.split(b"\r\n\r\n")[1].split(b"\r\n")[0].decode("utf-8")
                    elif b'name="image"' in part:
                        header, data = part.split(b"\r\n\r\n", 1)
                        data = data.rstrip(b"\r\n")
                        file_bytes = data
                        for line in header.split(b"\r\n"):
                            if b"filename=" in line:
                                fn_raw = line.split(b'filename="')[-1].split(b'"')[0]
                                filename = fn_raw.decode("utf-8", errors="replace")

                if not file_bytes:
                    raise ValueError("사진 파일이 전달되지 않았습니다.")

                with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix, delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                    tmp.write(file_bytes)

                try:
                    photo = prepare_photo(tmp_path)
                    photo = prepare_photo(tmp_path).__dict__
                    photo["source_filename"] = filename
                    from photo_analyzer import PreparedPhoto
                    prepared = PreparedPhoto(**photo)
                    model = MODEL_PRESETS.get(tier, MODEL_PRESETS["lite"])
                    category_hint = None
                    if category_param and category_param != "auto":
                        category_hint = category_param
                    analysis = analyze_with_gemini(prepared, model=model, category_hint=category_hint)
                    record_id = save_analysis(self.db_path, prepared, model, analysis)
                finally:
                    tmp_path.unlink(missing_ok=True)

                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                res = {
                    "success": True,
                    "record_id": record_id,
                    "analysis": analysis.model_dump(mode="json"),
                }
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode("utf-8"))
                return
            except Exception as exc:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(exc)}).encode("utf-8"))
                return

        self.send_response(HTTPStatus.NOT_FOUND)
        self.end_headers()


def run_dashboard(port: int = PORT, db_path: Path = DEFAULT_DB_PATH) -> None:
    DashboardRequestHandler.db_path = db_path.resolve()
    server = HTTPServer(("0.0.0.0", port), DashboardRequestHandler)
    print(f"============================================================")
    print(f" 피규어 포토 그레이더 Culling 대시보드 서버가 시작되었습니다.")
    print(f" 접속 주소: http://localhost:{port}")
    print(f" 연동 DB: {db_path.resolve()}")
    print(f" 종료하려면 Ctrl+C를 누르세요.")
    print(f"============================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n대시보드 서버를 종료합니다.")
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="피규어 사진 Culling & Review Web 대시보드를 실행합니다.")
    parser.add_argument("--port", type=int, default=PORT, help=f"웹 서버 포트 (기본값: {PORT})")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH, help=f"연동할 SQLite DB 경로 (기본값: {DEFAULT_DB_PATH.name})")
    args = parser.parse_args(argv)
    run_dashboard(port=args.port, db_path=args.db)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
