from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sqlite3
import sys
import tempfile
from contextlib import closing
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from photo_analyzer import (
    DEFAULT_DB_PATH,
    MODEL_PRESETS,
    CropBox,
    LightroomAdvice,
    PhotoAnalysis,
    PreparedPhoto,
    SNSAdvice,
    analyze_with_gemini,
    compute_dhash_from_bytes,
    generate_lightroom_advice,
    generate_sns_advice,
    hamming_distance,
    prepare_photo,
    save_analysis,
)
from photo_tag_schema import AESTHETIC_TAG_CATEGORIES, get_score_grade

PORT = 8080


def ensure_db_columns(db_path: Path) -> None:
    if not db_path.is_file():
        return
    with closing(sqlite3.connect(db_path)) as conn, conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(photo_analyses)").fetchall()]
        if "thumbnail" not in cols:
            conn.execute("ALTER TABLE photo_analyses ADD COLUMN thumbnail BLOB")
        if "lr_advice_json" not in cols:
            conn.execute("ALTER TABLE photo_analyses ADD COLUMN lr_advice_json TEXT")
        if "sns_advice_json" not in cols:
            conn.execute("ALTER TABLE photo_analyses ADD COLUMN sns_advice_json TEXT")
        if "review_status" not in cols:
            conn.execute("ALTER TABLE photo_analyses ADD COLUMN review_status TEXT DEFAULT '미검토'")
        if "user_notes" not in cols:
            conn.execute("ALTER TABLE photo_analyses ADD COLUMN user_notes TEXT DEFAULT ''")
        if "dhash" not in cols:
            conn.execute("ALTER TABLE photo_analyses ADD COLUMN dhash INTEGER")

        missing = conn.execute(
            "SELECT id, thumbnail FROM photo_analyses WHERE dhash IS NULL AND thumbnail IS NOT NULL"
        ).fetchall()
        for mid, mthumb in missing:
            try:
                dh = compute_dhash_from_bytes(mthumb)
                conn.execute("UPDATE photo_analyses SET dhash = ? WHERE id = ?", (dh, mid))
            except Exception:
                pass


def cluster_burst_groups(analyses: list[dict], max_hamming_dist: int = 12) -> list[dict]:
    """Cluster photos into Burst Groups based on perceptual dHash similarity.
    Selects Best Pick (1st place) and tags B-cuts with concrete drop reasons.
    """
    if not analyses:
        return []

    n = len(analyses)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_j] = root_i

    for i in range(n):
        h1 = analyses[i].get("dhash")
        if h1 is None:
            continue
        for j in range(i + 1, n):
            h2 = analyses[j].get("dhash")
            if h2 is None:
                continue
            dist = bin(h1 ^ h2).count("1")
            if dist <= max_hamming_dist:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for idx in range(n):
        r = find(idx)
        groups.setdefault(r, []).append(idx)

    focus_priority = {
        "완벽 칼초점": 1,
        "미세 앞핀": 2,
        "미세 뒤핀": 2,
        "판별 불가": 3,
        "초점 이탈": 4,
    }

    for root_id, member_indices in groups.items():
        if len(member_indices) >= 2:
            sorted_indices = sorted(
                member_indices,
                key=lambda idx: (
                    analyses[idx].get("final_score", 0),
                    -focus_priority.get(analyses[idx].get("focus_status", "완벽 칼초점"), 3),
                    analyses[idx].get("technique_score", 0),
                ),
                reverse=True,
            )
            group_id = f"burst_{min(analyses[idx]['id'] for idx in member_indices)}"
            best_idx = sorted_indices[0]
            best_item = analyses[best_idx]

            for rank, idx in enumerate(sorted_indices, start=1):
                item = analyses[idx]
                item["is_burst"] = True
                item["burst_group_id"] = group_id
                item["burst_rank"] = rank
                item["burst_total"] = len(sorted_indices)

                if rank == 1:
                    item["is_best_pick"] = True
                    item["drop_reason"] = ""
                else:
                    item["is_best_pick"] = False
                    best_f = best_item.get("focus_status", "완벽 칼초점")
                    cur_f = item.get("focus_status", "완벽 칼초점")
                    if best_f == "완벽 칼초점" and cur_f != "완벽 칼초점":
                        item["drop_reason"] = f"초점 핀 열세 ({cur_f})"
                    elif (best_item.get("lighting_score", 0) - item.get("lighting_score", 0)) >= 0.4:
                        diff = best_item.get("lighting_score", 0) - item.get("lighting_score", 0)
                        item["drop_reason"] = f"조명/노출 밸런스 열세 (-{diff:.1f}점)"
                    elif (best_item.get("composition_score", 0) - item.get("composition_score", 0)) >= 0.4:
                        diff = best_item.get("composition_score", 0) - item.get("composition_score", 0)
                        item["drop_reason"] = f"구도 안정성 열세 (-{diff:.1f}점)"
                    elif (best_item.get("technique_score", 0) - item.get("technique_score", 0)) >= 0.4:
                        diff = best_item.get("technique_score", 0) - item.get("technique_score", 0)
                        item["drop_reason"] = f"기술/선예도 디테일 열세 (-{diff:.1f}점)"
                    else:
                        score_diff = best_item.get("final_score", 0) - item.get("final_score", 0)
                        item["drop_reason"] = f"종합 점수 차이 (-{score_diff:.1f}점)" if score_diff > 0 else "미세 디테일 차이"
        else:
            idx = member_indices[0]
            analyses[idx]["is_burst"] = False
            analyses[idx]["is_best_pick"] = False
            analyses[idx]["burst_group_id"] = None
            analyses[idx]["burst_rank"] = 1
            analyses[idx]["burst_total"] = 1
            analyses[idx]["drop_reason"] = ""

    return analyses




def make_thumbnail_bytes(image_path_or_bytes: Path | bytes, max_dim: int = 800, quality: int = 82) -> bytes:
    import io
    from PIL import Image, ImageOps
    if isinstance(image_path_or_bytes, (str, Path)):
        img = Image.open(image_path_or_bytes)
    else:
        img = Image.open(io.BytesIO(image_path_or_bytes))
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="WEBP", quality=quality)
    return out.getvalue()


def get_all_analyses(db_path: Path) -> list[dict]:
    if not db_path.is_file():
        return []
    ensure_db_columns(db_path)
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

        lr_advice = None
        if "lr_advice_json" in row.keys() and row["lr_advice_json"]:
            try:
                lr_advice = json.loads(row["lr_advice_json"])
            except Exception:
                pass

        sns_advice = None
        if "sns_advice_json" in row.keys() and row["sns_advice_json"]:
            try:
                sns_advice = json.loads(row["sns_advice_json"])
            except Exception:
                pass

        dhash_val = row["dhash"] if "dhash" in row.keys() and row["dhash"] is not None else None
        if dhash_val is None and row["thumbnail"]:
            try:
                dhash_val = compute_dhash_from_bytes(row["thumbnail"])
            except Exception:
                dhash_val = None

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
                "focus_status": analysis_data.get("focus_status", "완벽 칼초점"),
                "focus_notes": analysis_data.get("focus_notes", ""),
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
                "detected_camera_settings": analysis_data.get("detected_camera_settings"),
                "lr_advice": lr_advice,
                "sns_advice": sns_advice,
                "exif": exif_data,
                "dhash": dhash_val,
            }
        )
    return cluster_burst_groups(results)


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
.modal-content { background: white; border-radius: 24px; max-width: 1240px; width: 100%; max-height: 90vh; overflow-y: auto; padding: 32px; box-shadow: 0 25px 60px rgba(0,0,0,0.25); position: relative; }
.close-btn { position: absolute; top: 20px; right: 24px; font-size: 1.8rem; background: transparent; border: none; cursor: pointer; color: var(--muted); }
.modal-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 28px; align-items: start; }
.zoom-wrap { position: relative; overflow: hidden; border-radius: 16px; background: #0f172a; cursor: zoom-in; }
.detail-img { width: 100%; max-height: 520px; object-fit: contain; display: block; transition: transform 0.15s ease-out; transform-origin: center center; }
.detail-img.zoomed { transform: scale(2.4); cursor: zoom-out; }
.zoom-hint { position: absolute; bottom: 10px; right: 12px; background: rgba(0,0,0,0.7); color: #e2e8f0; font-size: 0.74rem; padding: 4px 10px; border-radius: 999px; pointer-events: none; }
.kbd-hint { font-size: 0.74rem; color: #94a3b8; margin-top: 8px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.kbd-key { background: #334155; color: #f1f5f9; padding: 1px 6px; border-radius: 4px; font-weight: 700; font-family: monospace; }
.note-item { background: #f8fafc; border-left: 3px solid var(--blue); padding: 7px 12px; border-radius: 0 8px 8px 0; margin-bottom: 6px; font-size: 0.82rem; line-height: 1.4; white-space: pre-wrap; }
.note-item h4 { margin: 0 0 2px; font-size: 0.86rem; display: flex; justify-content: space-between; }
.list-box { background: #f8fafc; padding: 8px 12px; border-radius: 8px; margin-top: 6px; }
.list-box h4 { margin: 0 0 3px; font-size: 0.86rem; }
.list-box ul { margin: 0; padding-left: 18px; font-size: 0.80rem; line-height: 1.35; color: #475569; }
.lr-metric { background: white; border: 1px solid #e2e8f0; border-radius: 8px; padding: 6px 8px; text-align: center; }
.lr-metric span { display: block; font-size: 0.70rem; color: var(--muted); margin-bottom: 1px; }
.lr-metric strong { display: block; font-size: 0.90rem; color: #1e293b; font-weight: 700; }

/* Score Summary Card & Bars */
.score-summary-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 10px 14px; margin-bottom: 8px; }
.score-bars-list { display: flex; flex-direction: column; gap: 6px; }
.score-bar-row { display: flex; flex-direction: column; gap: 2px; }
.score-bar-label { display: flex; justify-content: space-between; font-size: 0.81rem; }
.score-bar-label span { font-weight: 600; color: #334155; }
.score-bar-label strong { font-weight: 800; font-size: 0.85rem; }
.score-bar-track { background: #e2e8f0; height: 7px; border-radius: 999px; overflow: hidden; position: relative; }
.score-bar-fill { height: 100%; border-radius: 999px; transition: width 0.35s ease; }
.score-bar-comp { background: linear-gradient(90deg, #3b82f6, #60a5fa); }
.score-bar-light { background: linear-gradient(90deg, #f59e0b, #fbbf24); }
.score-bar-color { background: linear-gradient(90deg, #ec4899, #f472b6); }
.score-bar-tech { background: linear-gradient(90deg, #10b981, #34d399); }

/* Burst Culling Badges & Banner */
.badge-best-pick { display: inline-block; background: linear-gradient(135deg, #059669 0%, #10b981 100%); color: white; font-size: 0.72rem; font-weight: 700; padding: 2px 8px; border-radius: 6px; box-shadow: 0 2px 4px rgba(5,150,105,0.2); }
.badge-b-cut { display: inline-block; background: #fff1f2; color: #e11d48; border: 1px solid #fecdd3; font-size: 0.72rem; font-weight: 700; padding: 2px 8px; border-radius: 6px; }
.burst-banner { background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 12px; padding: 10px 14px; margin-bottom: 6px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.burst-banner.is-b-cut { background: #fff1f2; border-color: #fecdd3; }
.burst-thumb-link { width: 36px; height: 36px; border-radius: 8px; object-fit: cover; border: 2px solid #cbd5e1; cursor: pointer; transition: all .15s; }
.burst-thumb-link:hover { transform: scale(1.1); }
.burst-thumb-link.current { border-color: #2563eb; box-shadow: 0 0 0 2px rgba(37,99,235,0.4); }
.burst-thumb-link.is-best { border-color: #10b981; }

/* Crop Overlay Box */
.crop-box-overlay {
  position: absolute;
  border: 2px solid #38bdf8;
  box-shadow: 0 0 0 9999px rgba(15, 23, 42, 0.65);
  pointer-events: none;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  display: none;
  z-index: 5;
  box-sizing: border-box;
}
.crop-box-overlay::before {
  content: '';
  position: absolute;
  top: 33.333%; bottom: 33.333%; left: 0; right: 0;
  border-top: 1px dashed rgba(255,255,255,0.45);
  border-bottom: 1px dashed rgba(255,255,255,0.45);
}
.crop-box-overlay::after {
  content: '';
  position: absolute;
  left: 33.333%; right: 33.333%; top: 0; bottom: 0;
  border-left: 1px dashed rgba(255,255,255,0.45);
  border-right: 1px dashed rgba(255,255,255,0.45);
}
.crop-overlay-badge {
  position: absolute;
  top: 8px;
  left: 8px;
  background: rgba(3, 105, 161, 0.9);
  color: #f0f9ff;
  padding: 3px 8px;
  border-radius: 6px;
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.02em;
  pointer-events: none;
  box-shadow: 0 2px 6px rgba(0,0,0,0.35);
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.crop-ratio-btn {
  background: white; border: 1px solid var(--line);
  padding: 6px 12px; border-radius: 8px; font-size: 0.8rem; font-weight: 600;
  color: var(--muted); cursor: pointer; transition: all .15s;
}
.crop-ratio-btn:hover { background: #e0f2fe; color: #0284c7; }
.crop-ratio-btn.active { background: #0284c7; color: white; border-color: #0284c7; }



/* Upload Modal */
.upload-btn { background: var(--blue); color: white; border: none; padding: 9px 18px; border-radius: 10px; font-weight: 700; font-size: 0.88rem; cursor: pointer; display: flex; align-items: center; gap: 6px; transition: background .15s; }
.upload-btn:hover { background: #2563eb; }
.drop-zone { border: 2px dashed #94a3b8; border-radius: 16px; padding: 28px 20px; text-align: center; color: var(--muted); cursor: pointer; margin: 18px 0; transition: all .15s; }
.drop-zone:hover, .drop-zone.drag-over { border-color: var(--blue); background: #f0f7ff; }


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
    <div style="display:flex;gap:10px;align-items:center;">
      <button class="upload-btn" style="background:#0d9488;" onclick="exportAllXmp(this)">📥 라이트룸 XMP 내보내기</button>
      <button class="upload-btn" onclick="openUploadModal()">+ 새 사진 분석하기</button>
    </div>
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
    <div class="filter-group" style="margin-top:8px;">
      <span style="font-size:0.84rem;font-weight:700;color:var(--muted)">연사 선별(B-1):</span>
      <button class="filter-btn active burst-btn" onclick="setBurstFilter('all', this)">전체 컷</button>
      <button class="filter-btn burst-btn" onclick="setBurstFilter('best_only', this)" style="color:#065f46;">👑 Best Pick만 보기</button>
      <button class="filter-btn burst-btn" onclick="setBurstFilter('stack', this)" style="color:#0369a1;">🗂️ 연사 묶어보기 (Stack)</button>
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
    <select class="select-input" id="upload-tier" style="width:100%;margin-bottom:12px;">
      <option value="lite">Flash-Lite (초고속 스크리닝 / 기본)</option>
      <option value="standard">2.5-Flash (균형 잡힌 화질 평가)</option>
      <option value="pro">3.1-Pro (전문가급 심층 비평)</option>
    </select>

    <label style="font-weight:700;font-size:0.84rem;display:block;margin-bottom:6px;">피규어 촬영 세부 유형:</label>
    <select class="select-input" id="upload-category" style="width:100%;margin-bottom:14px;">
      <option value="auto">자동 판별 (Gemini가 사진을 분석하여 자동 분류)</option>
      <option value="macro">🔍 접사/디테일 (도색, 접합선, 데칼 초점 심사)</option>
      <option value="snap">🌿 일상/야외 스냅 (배경 조화, 자연광, 생활감 심사)</option>
      <option value="staging">🎬 스튜디오 연출/디오라마 (드라마틱 조명, 콘트라스트)</option>
      <option value="general">📷 일반 피규어 촬영 (기본 전시/조형 중심)</option>
    </select>

    <div class="drop-zone" id="drop-zone" ondragover="handleDragOver(event)" ondragleave="handleDragLeave(event)" ondrop="handleDrop(event)">
      <div style="font-size:2.2rem;margin-bottom:6px;">📁</div>
      <strong style="font-size:0.95rem;">사진 파일(들) 또는 폴더를 드래그하여 놓으세요</strong>
      <div style="font-size:0.78rem;margin:6px 0 14px;color:var(--muted)">폴더를 통째로 놓으면 하위 사진까지 자동 탐색 (JPG, PNG, WEBP, MPO 지원)</div>
      <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap;" onclick="event.stopPropagation()">
        <button type="button" class="upload-btn" style="padding:7px 14px;font-size:0.82rem;" onclick="document.getElementById('file-input-multi').click()">📸 여러 사진 선택</button>
        <button type="button" class="upload-btn" style="background:#0d9488;padding:7px 14px;font-size:0.82rem;" onclick="document.getElementById('folder-input').click()">📁 폴더 통째로 선택</button>
      </div>
      <input type="file" id="file-input-multi" style="display:none" accept="image/jpeg,image/png,image/webp" multiple onchange="handleFilesSelect(this.files)">
      <input type="file" id="folder-input" style="display:none" webkitdirectory directory multiple onchange="handleFilesSelect(this.files)">
    </div>

    <div id="progress-container" style="display:none;margin-top:16px;">
      <div style="display:flex;justify-content:space-between;font-size:0.84rem;margin-bottom:6px;">
        <span id="progress-text" style="font-weight:700;color:var(--navy);">분석 준비 중...</span>
        <span id="progress-percent" style="font-weight:700;color:var(--blue);">0%</span>
      </div>
      <div style="background:#e2e8f0;border-radius:999px;height:10px;overflow:hidden;">
        <div id="progress-bar" style="background:linear-gradient(90deg, #3b82f6, #0d9488);height:100%;width:0%;transition:width 0.2s;"></div>
      </div>
      <div id="progress-current-file" style="font-size:0.78rem;color:var(--muted);margin-top:6px;overflow-wrap:anywhere;"></div>
    </div>
    <div id="upload-status" style="font-size:0.88rem;font-weight:600;text-align:center;margin-top:12px;"></div>
  </div>
</div>

<script>
let allData = [];
let currentFilter = 'all';
let currentCatFilter = 'all';
let currentDetailId = null;

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

let currentBurstFilter = 'all'; // 'all', 'best_only', 'stack'
let expandedBurstGroups = new Set();

function setBurstFilter(mode, btn) {
  currentBurstFilter = mode;
  document.querySelectorAll('.burst-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderGallery();
}

function toggleExpandBurstGroup(groupId, e) {
  if (e) e.stopPropagation();
  if (expandedBurstGroups.has(groupId)) {
    expandedBurstGroups.delete(groupId);
  } else {
    expandedBurstGroups.add(groupId);
  }
  renderGallery();
}

function setFilter(filter, btn) {
  currentFilter = filter;
  document.querySelectorAll('.filter-btn:not(.burst-btn):not(.cat-btn)').forEach(b => b.classList.remove('active'));
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

  if (currentBurstFilter === 'best_only') {
    res = res.filter(d => !d.is_burst || d.is_best_pick);
  } else if (currentBurstFilter === 'stack') {
    res = res.filter(d => !d.is_burst || d.is_best_pick || expandedBurstGroups.has(d.burst_group_id));
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
            <span style="display:inline-block;margin-top:4px;margin-left:4px;font-size:0.75rem;font-weight:700;color:#0d9488;background:#f0fdfa;padding:2px 7px;border-radius:6px;">🎯 ${item.focus_status || '완벽 칼초점'}</span>
            ${item.is_burst ? (item.is_best_pick ?
              `<span class="badge-best-pick" style="display:inline-block;margin-top:4px;margin-left:4px;">👑 Best Pick (${item.burst_total}장 1위)</span>` :
              `<span class="badge-b-cut" style="display:inline-block;margin-top:4px;margin-left:4px;" title="${item.drop_reason}">⚠️ B컷 (${item.drop_reason})</span>`
            ) : ''}
            ${item.sns_advice ? '<span style="display:inline-block;margin-top:4px;margin-left:4px;font-size:0.75rem;font-weight:700;color:#0284c7;background:#e0f2fe;padding:2px 7px;border-radius:6px;">📱 SNS크롭</span>' : ''}
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
        ${currentBurstFilter === 'stack' && item.is_burst && item.is_best_pick ? `
          <div style="margin-top:8px;padding-top:8px;border-top:1px dashed var(--line);display:flex;justify-content:space-between;align-items:center;" onclick="event.stopPropagation()">
            <span style="font-size:0.74rem;color:var(--muted);font-weight:600;">🗂️ 연사 묶음 (${item.burst_total}장)</span>
            <button class="filter-btn" style="padding:2px 8px;font-size:0.72rem;background:#f0f9ff;border-color:#bae6fd;color:#0369a1;" onclick="toggleExpandBurstGroup('${item.burst_group_id}', event)">
              ${expandedBurstGroups.has(item.burst_group_id) ? '▲ B컷 접기' : `▼ B컷 ${item.burst_total - 1}장 펼치기`}
            </button>
          </div>
        ` : ''}
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

function renderBurstThumbnails(groupId, currentId) {
  if (!groupId) return '';
  const groupItems = allData.filter(d => d.burst_group_id === groupId).sort((a, b) => a.burst_rank - b.burst_rank);
  return groupItems.map(m => `
    <img src="/api/image/${m.id}"
         class="burst-thumb-link ${m.id === currentId ? 'current' : ''} ${m.is_best_pick ? 'is-best' : ''}"
         title="${m.is_best_pick ? '👑 1위 Best Pick' : `${m.burst_rank}위 B컷 (${m.drop_reason})`}"
         onclick="event.stopPropagation(); openDetailModal(${m.id})">
  `).join('');
}

function openDetailModal(id) {
  const item = allData.find(d => d.id === id);
  if (!item) return;
  currentDetailId = id;
  const modal = document.getElementById('detail-modal');
  const body = document.getElementById('modal-body');

  body.innerHTML = `
    ${item.is_burst ? `
      <div class="burst-banner ${item.is_best_pick ? '' : 'is-b-cut'}" style="grid-column: 1 / -1;">
        <div style="display:flex;align-items:center;gap:10px;">
          <span style="font-size:1.4rem;">${item.is_best_pick ? '👑' : '🗂️'}</span>
          <div>
            <div style="font-size:0.92rem;font-weight:800;color:${item.is_best_pick ? '#065f46' : '#991b1b'};">
              ${item.is_best_pick ? `👑 연사 묶음 베스트 컷 (총 ${item.burst_total}장 중 1위 선정)` : `⚠️ 연사 묶음 B컷 (${item.burst_rank}/${item.burst_total}위 · 탈락 사유: ${item.drop_reason})`}
            </div>
            <div style="font-size:0.77rem;color:var(--muted);">동일 구도 및 포즈로 연속 촬영된 연사 세트 중 AI 디테일(초점·조명·완성도) 비교 결과입니다.</div>
          </div>
        </div>
        <div style="display:flex;gap:6px;align-items:center;">
          <span style="font-size:0.78rem;font-weight:700;color:var(--muted);">묶음 컷:</span>
          ${renderBurstThumbnails(item.burst_group_id, item.id)}
        </div>
      </div>
    ` : ''}

    <div>
      <div class="zoom-wrap" id="zoom-wrap-container" onclick="toggleZoom(event)" onmousemove="panZoom(event)">
        <img class="detail-img" id="detail-modal-img" src="/api/image/${item.id}" alt="${item.filename}" onload="repositionCropOverlay()">
        <div class="crop-box-overlay" id="crop-box-overlay">
          <span class="crop-overlay-badge" id="crop-overlay-badge"></span>
        </div>
        <span class="zoom-hint">🔍 클릭하여 초점/데칼 2.4배 확대</span>
      </div>
      <div class="kbd-hint">
        <span>단축키:</span>
        <span><span class="kbd-key">←</span>/<span class="kbd-key">J</span> 이전</span>
        <span><span class="kbd-key">→</span>/<span class="kbd-key">K</span> 다음</span>
        <span><span class="kbd-key">Space</span> 줌 토글</span>
        <span><span class="kbd-key">Esc</span> 닫기</span>
      </div>
      <div style="margin-top:12px;font-size:0.84rem;color:var(--muted)">
        <div><b>해상도:</b> ${item.width} × ${item.height}px (${item.format})</div>
        <div><b>분석 모델:</b> ${item.model} · <b>분석시각:</b> ${item.created_at}</div>
        ${renderExifSummary(item.exif, item.detected_camera_settings)}
      </div>

      <div style="display:flex;gap:8px;margin-top:14px;margin-bottom:12px;flex-wrap:wrap;">
        <button class="filter-btn" style="background:#312e81;color:white;border-color:#312e81;padding:5px 12px;font-size:0.8rem;" onclick="document.getElementById('lr-advice-box-section').scrollIntoView({behavior:'smooth'})">🛠️ 라이트룸 보정값 바로가기</button>
        <button class="filter-btn" style="background:#0284c7;color:white;border-color:#0284c7;padding:5px 12px;font-size:0.8rem;" onclick="document.getElementById('sns-advice-box-section').scrollIntoView({behavior:'smooth'})">📱 SNS 크롭 & 캡션 바로가기</button>
      </div>

      <!-- Adobe Lightroom Advice Box (사진 바로 아래 배치) -->
      <div class="lr-advice-box" id="lr-advice-box-section" style="margin-top:12px;background:#f8fafc;border:1px solid #cbd5e1;border-radius:14px;padding:16px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
          <h3 style="margin:0;font-size:1.02rem;display:flex;align-items:center;gap:6px;">
            <span style="background:#312e81;color:white;padding:2px 7px;border-radius:4px;font-size:0.78rem;">Lr</span>
            Adobe Lightroom 추천 보정 수치
          </h3>
          <button class="filter-btn" style="background:#4f46e5;color:white;border-color:#4f46e5;" onclick="requestLrAdvice(${item.id}, this)">
            ${item.lr_advice ? '🔄 보정 수치 다시 제안' : '🛠️ 라이트룸 보정 수치 제안 받기'}
          </button>
        </div>
        <div id="lr-advice-content">
          ${renderLrAdviceContent(item.lr_advice)}
        </div>
      </div>

      <!-- SNS Crop & Caption Advice Box (사진 바로 아래 배치) -->
      <div class="sns-advice-box" id="sns-advice-box-section" style="margin-top:16px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:14px;padding:16px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;flex-wrap:wrap;gap:8px;">
          <h3 style="margin:0;font-size:1.02rem;display:flex;align-items:center;gap:6px;color:#0369a1;">
            <span style="background:#0284c7;color:white;padding:2px 7px;border-radius:4px;font-size:0.78rem;">SNS</span>
            인스타 · X(트위터) 규격 크롭 & 캡션 제안
          </h3>
          <button class="filter-btn" style="background:#0284c7;color:white;border-color:#0284c7;" onclick="requestSnsAdvice(${item.id}, this)">
            ${item.sns_advice ? '🔄 크롭/캡션 다시 제안' : '📱 SNS 크롭 & 캡션 제안 받기'}
          </button>
        </div>
        <div id="sns-advice-content">
          ${renderSnsAdviceContent(item.sns_advice, item.id)}
        </div>
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

      <div style="background:#eef2ff;padding:8px 12px;border-radius:10px;margin-bottom:8px;font-size:0.84rem;line-height:1.42;color:#3730a3">
        <b>종합 총평:</b> ${item.final_reason}
      </div>

      <!-- 세부 평가 요소 점수 요약 그래프 (우측 상단) -->
      <div class="score-summary-card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <h3 style="margin:0;font-size:0.94rem;font-weight:800;color:var(--navy);display:flex;align-items:center;gap:6px;">
            📊 세부 평가 요소 점수 요약
          </h3>
          <span style="font-size:0.74rem;color:var(--muted);font-weight:600;">10점 만점 기준</span>
        </div>
        <div class="score-bars-list">
          <div class="score-bar-row">
            <div class="score-bar-label">
              <span>📐 구도 (Composition)</span>
              <strong style="color:#2563eb;">${item.composition_score.toFixed(1)} <small style="color:var(--muted);font-weight:500;">/ 10</small></strong>
            </div>
            <div class="score-bar-track">
              <div class="score-bar-fill score-bar-comp" style="width:${Math.min(100, Math.max(0, item.composition_score * 10))}%;"></div>
            </div>
          </div>
          <div class="score-bar-row">
            <div class="score-bar-label">
              <span>💡 조명/노출 (Lighting)</span>
              <strong style="color:#d97706;">${item.lighting_score.toFixed(1)} <small style="color:var(--muted);font-weight:500;">/ 10</small></strong>
            </div>
            <div class="score-bar-track">
              <div class="score-bar-fill score-bar-light" style="width:${Math.min(100, Math.max(0, item.lighting_score * 10))}%;"></div>
            </div>
          </div>
          <div class="score-bar-row">
            <div class="score-bar-label">
              <span>🎨 색감/톤 (Color)</span>
              <strong style="color:#db2777;">${item.color_score.toFixed(1)} <small style="color:var(--muted);font-weight:500;">/ 10</small></strong>
            </div>
            <div class="score-bar-track">
              <div class="score-bar-fill score-bar-color" style="width:${Math.min(100, Math.max(0, item.color_score * 10))}%;"></div>
            </div>
          </div>
          <div class="score-bar-row">
            <div class="score-bar-label">
              <span>📷 촬영 기술 (Technique)</span>
              <strong style="color:#059669;">${item.technique_score.toFixed(1)} <small style="color:var(--muted);font-weight:500;">/ 10</small></strong>
            </div>
            <div class="score-bar-track">
              <div class="score-bar-fill score-bar-tech" style="width:${Math.min(100, Math.max(0, item.technique_score * 10))}%;"></div>
            </div>
          </div>
        </div>
      </div>

      <!-- 세부 평가 요소별 코멘트 (그래프 바로 아래) -->
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
      <div class="note-item" style="border-left: 3px solid #6366f1;">
        <h4><span>🎯 피규어 눈동자/페이스 초점 핀</span> <strong style="color:#4f46e5;">${item.focus_status || '완벽 칼초점'}</strong></h4>
        <div>${item.focus_notes ? item.focus_notes : '눈동자 아이 데칼 및 안면 조형 핀 상태 양호'}</div>
      </div>

      <div class="list-box">
        <h4 style="color:var(--teal)">✓ 주요 장점</h4>
        <ul>${item.strengths.map(s => `<li>${s}</li>`).join('')}</ul>
      </div>
      <div class="list-box" style="margin-top:6px;">
        <h4 style="color:#e11d48">✗ 단점 및 다음 촬영 개선점</h4>
        <ul>${item.improvements.map(i => `<li>${i}</li>`).join('')}</ul>
      </div>

      <div style="margin-top:8px;">
        <span style="font-size:0.78rem;font-weight:700;color:var(--muted);display:block;margin-bottom:4px;">🏷️ 분위기 & 스타일 태그</span>
        <div class="tag-pills">
          ${renderTagPills(item.aesthetic_tags)}
        </div>
      </div>
    </div>
  `;
  modal.style.display = 'flex';
  currentCropBox = null;
  const overlay = document.getElementById('crop-box-overlay');
  if (overlay) overlay.style.display = 'none';
}

let currentCropBox = null;
let currentCropRatioKey = null;

function renderSnsAdviceContent(advice, recordId) {
  if (!advice) {
    return `<div style="font-size:0.86rem;color:var(--muted);text-align:center;padding:14px 0;">
      아직 생성된 SNS 제안이 없습니다. 위의 <b>[📱 SNS 크롭 & 캡션 제안 받기]</b> 버튼을 누르면 AI가 인스타그램(4:5, 1:1) 및 X(16:9, 3:4) 최적 크롭 영역과 감성 캡션·해시태그를 온디맨드로 분석합니다.
    </div>`;
  }

  return `
    <div>
      <div style="font-size:0.84rem;font-weight:700;color:#0369a1;margin-bottom:6px;">📐 크롭 비율 선택 (클릭 시 사진 위에 프레임 표시):</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px;">
        <button class="crop-ratio-btn active" id="btn-crop-instagram_crop_4_5" onclick="selectCropRatio('instagram_crop_4_5', ${recordId})">📸 인스타 4:5 (세로피드)</button>
        <button class="crop-ratio-btn" id="btn-crop-instagram_crop_1_1" onclick="selectCropRatio('instagram_crop_1_1', ${recordId})">🟦 인스타 1:1 (정방형)</button>
        <button class="crop-ratio-btn" id="btn-crop-x_crop_16_9" onclick="selectCropRatio('x_crop_16_9', ${recordId})">🐦 X 16:9 (가로타임라인)</button>
        <button class="crop-ratio-btn" id="btn-crop-x_crop_3_4" onclick="selectCropRatio('x_crop_3_4', ${recordId})">📱 X 3:4 (모바일세로)</button>
        <button class="crop-ratio-btn" style="color:#ef4444;" onclick="clearCropOverlay()">❌ 오버레이 숨기기</button>
      </div>

      <div id="crop-tip-box" style="background:white;padding:12px 14px;border-radius:10px;font-size:0.85rem;border:1px solid #e0f2fe;margin-bottom:14px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <b id="crop-tip-title" style="color:#0369a1;">${advice.instagram_crop_4_5.ratio_label}</b>
          <button class="upload-btn" id="btn-crop-download" style="padding:4px 10px;font-size:0.78rem;background:#0284c7;" onclick="downloadCroppedImage('instagram_crop_4_5', ${recordId})">✂️ 이 비율로 잘라 다운로드</button>
        </div>
        <div id="crop-tip-desc" style="color:#334155;">${advice.instagram_crop_4_5.composition_tip}</div>
      </div>

      <div style="background:white;padding:12px 14px;border-radius:10px;font-size:0.85rem;border:1px solid #e0f2fe;margin-bottom:10px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <b style="color:#0369a1;">✍️ SNS 감성 캡션:</b>
          <button class="filter-btn" style="padding:2px 8px;font-size:0.75rem;" onclick="copyCaption(${recordId}, this)">📋 캡션 복사</button>
        </div>
        <div style="color:#1e293b;white-space:pre-wrap;background:#f8fafc;padding:8px 12px;border-radius:6px;">${advice.social_caption}</div>
      </div>

      <div style="background:white;padding:12px 14px;border-radius:10px;font-size:0.85rem;border:1px solid #e0f2fe;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <b style="color:#0369a1;">🏷️ 추천 해시태그:</b>
          <button class="filter-btn" style="padding:2px 8px;font-size:0.75rem;" onclick="copyHashtags(${recordId}, this)">📋 전체 복사</button>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:6px;">
          ${advice.hashtags.map(t => `<span class="tag-pill" style="background:#e0f2fe;color:#0369a1;">${t}</span>`).join('')}
        </div>
      </div>
    </div>
  `;
}

const TARGET_CROP_RATIOS = {
  instagram_crop_4_5: { name: 'Instagram 4:5', tag: '인스타 4:5 (세로피드)', w: 4, h: 5, ratio: 4 / 5 },
  instagram_crop_1_1: { name: 'Instagram 1:1', tag: '인스타 1:1 (정방형)', w: 1, h: 1, ratio: 1.0 },
  x_crop_16_9: { name: 'X 16:9', tag: 'X 16:9 (가로타임라인)', w: 16, h: 9, ratio: 16 / 9 },
  x_crop_3_4: { name: 'X 3:4', tag: 'X 3:4 (모바일세로)', w: 3, h: 4, ratio: 3 / 4 }
};

function getImageRenderedRect(img) {
  if (!img) return null;
  const cW = img.clientWidth;
  const cH = img.clientHeight;
  const nW = img.naturalWidth || 1;
  const nH = img.naturalHeight || 1;
  if (!cW || !cH) return null;

  const containerRatio = cW / cH;
  const imgRatio = nW / nH;
  let rW, rH, offX, offY;

  if (imgRatio > containerRatio) {
    rW = cW;
    rH = cW / imgRatio;
    offX = 0;
    offY = (cH - rH) / 2;
  } else {
    rH = cH;
    rW = cH * imgRatio;
    offX = (cW - rW) / 2;
    offY = 0;
  }

  return {
    left: img.offsetLeft + offX,
    top: img.offsetTop + offY,
    width: rW,
    height: rH,
    naturalW: nW,
    naturalH: nH
  };
}

function calculateExactCrop(ratioKey, box, naturalW, naturalH) {
  const target = TARGET_CROP_RATIOS[ratioKey] || { name: '1:1', tag: '1:1', w: 1, h: 1, ratio: 1.0 };
  const targetRatio = target.ratio;

  const cx = ((box.xmin + box.xmax) / 2) * naturalW;
  const cy = ((box.ymin + box.ymax) / 2) * naturalH;

  const rawW = Math.max(1, (box.xmax - box.xmin) * naturalW);
  const rawH = Math.max(1, (box.ymax - box.ymin) * naturalH);

  let cropW, cropH;
  if (rawW / rawH > targetRatio) {
    cropW = rawW;
    cropH = cropW / targetRatio;
  } else {
    cropH = rawH;
    cropW = cropH * targetRatio;
  }

  if (cropW > naturalW) {
    cropW = naturalW;
    cropH = cropW / targetRatio;
  }
  if (cropH > naturalH) {
    cropH = naturalH;
    cropW = cropH * targetRatio;
  }
  if (cropW > naturalW) {
    cropW = naturalW;
    cropH = cropW / targetRatio;
  }

  let sx = cx - cropW / 2;
  let sy = cy - cropH / 2;

  if (sx < 0) sx = 0;
  if (sx + cropW > naturalW) sx = naturalW - cropW;
  if (sy < 0) sy = 0;
  if (sy + cropH > naturalH) sy = naturalH - cropH;

  sx = Math.max(0, sx);
  sy = Math.max(0, sy);

  let intH = Math.max(1, Math.floor(cropH));
  let intW = Math.max(1, Math.round(intH * targetRatio));

  if (intW > naturalW) {
    intW = Math.floor(naturalW);
    intH = Math.max(1, Math.round(intW / targetRatio));
  }
  if (intH > naturalH) {
    intH = Math.floor(naturalH);
    intW = Math.max(1, Math.round(intH * targetRatio));
  }

  const intSx = Math.max(0, Math.min(naturalW - intW, Math.round(sx)));
  const intSy = Math.max(0, Math.min(naturalH - intH, Math.round(sy)));

  return {
    target,
    sx: intSx,
    sy: intSy,
    sw: intW,
    sh: intH,
    normX: intSx / naturalW,
    normY: intSy / naturalH,
    normW: intW / naturalW,
    normH: intH / naturalH
  };
}

function selectCropRatio(ratioKey, recordId) {
  const item = allData.find(d => d.id === recordId);
  if (!item || !item.sns_advice) return;
  const box = item.sns_advice[ratioKey];
  if (!box) return;

  currentCropBox = box;
  currentCropRatioKey = ratioKey;

  document.querySelectorAll('.crop-ratio-btn').forEach(b => b.classList.remove('active'));
  const activeBtn = document.getElementById(`btn-crop-${ratioKey}`);
  if (activeBtn) activeBtn.classList.add('active');

  const titleEl = document.getElementById('crop-tip-title');
  const descEl = document.getElementById('crop-tip-desc');
  const dlBtn = document.getElementById('btn-crop-download');
  if (titleEl) titleEl.textContent = box.ratio_label;
  if (descEl) descEl.textContent = box.composition_tip;
  if (dlBtn) dlBtn.setAttribute('onclick', `downloadCroppedImage('${ratioKey}', ${recordId})`);

  repositionCropOverlay();
}

function clearCropOverlay() {
  currentCropBox = null;
  currentCropRatioKey = null;
  document.querySelectorAll('.crop-ratio-btn').forEach(b => b.classList.remove('active'));
  const overlay = document.getElementById('crop-box-overlay');
  if (overlay) overlay.style.display = 'none';
}

function repositionCropOverlay() {
  const overlay = document.getElementById('crop-box-overlay');
  const img = document.getElementById('detail-modal-img');
  if (!overlay || !img || !currentCropBox || !currentCropRatioKey) {
    if (overlay) overlay.style.display = 'none';
    return;
  }
  if (img.classList.contains('zoomed')) {
    overlay.style.display = 'none';
    return;
  }

  const rect = getImageRenderedRect(img);
  if (!rect || rect.width <= 0 || rect.height <= 0) {
    overlay.style.display = 'none';
    return;
  }

  const crop = calculateExactCrop(currentCropRatioKey, currentCropBox, rect.naturalW, rect.naturalH);
  if (!crop) {
    overlay.style.display = 'none';
    return;
  }

  const top = Math.round(rect.top + crop.normY * rect.height);
  const left = Math.round(rect.left + crop.normX * rect.width);
  const width = Math.round(crop.normW * rect.width);
  const height = Math.round(crop.normH * rect.height);

  overlay.style.top = `${top}px`;
  overlay.style.left = `${left}px`;
  overlay.style.width = `${width}px`;
  overlay.style.height = `${height}px`;
  overlay.style.display = 'block';

  const badge = document.getElementById('crop-overlay-badge');
  if (badge) {
    badge.textContent = `${crop.target.tag} (${crop.sw}×${crop.sh})`;
  }
}

window.addEventListener('resize', repositionCropOverlay);

async function downloadCroppedImage(ratioKey, recordId) {
  const item = allData.find(d => d.id === recordId);
  if (!item || !item.sns_advice) return;
  const box = item.sns_advice[ratioKey];
  if (!box) return;

  const img = new Image();
  img.crossOrigin = 'anonymous';
  img.src = `/api/image/${recordId}`;
  await new Promise((resolve, reject) => {
    img.onload = resolve;
    img.onerror = reject;
  });

  const origW = img.naturalWidth || 1;
  const origH = img.naturalHeight || 1;
  const crop = calculateExactCrop(ratioKey, box, origW, origH);
  if (!crop || crop.sw <= 0 || crop.sh <= 0) return;

  const canvas = document.createElement('canvas');
  canvas.width = crop.sw;
  canvas.height = crop.sh;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(img, crop.sx, crop.sy, crop.sw, crop.sh, 0, 0, crop.sw, crop.sh);

  const safeName = item.filename.replace(/\\.[^/.]+$/, '');
  const outName = `${safeName}_${ratioKey.replace('crop_', '')}_${crop.sw}x${crop.sh}.png`;
  canvas.toBlob((blob) => {
    if (!blob) return;
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = outName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 'image/png');
}

async function copyText(text, btn) {
  try {
    await navigator.clipboard.writeText(text);
    const orig = btn.textContent;
    btn.textContent = '✓ 복사됨!';
    setTimeout(() => { btn.textContent = orig; }, 1500);
  } catch (err) {
    prompt('텍스트 복사:', text);
  }
}

async function copyCaption(recordId, btn) {
  const item = allData.find(d => d.id === recordId);
  if (!item || !item.sns_advice) return;
  await copyText(item.sns_advice.social_caption, btn);
}

async function copyHashtags(recordId, btn) {
  const item = allData.find(d => d.id === recordId);
  if (!item || !item.sns_advice) return;
  await copyText(item.sns_advice.hashtags.join(' '), btn);
}


async function requestSnsAdvice(recordId, btn) {
  const origText = btn.textContent;
  btn.textContent = 'Gemini 크롭 분석 중...';
  btn.disabled = true;
  try {
    const res = await fetch(`/api/sns-advice/${recordId}`, { method: 'POST' });
    const data = await res.json();
    if (data.success && data.advice) {
      const item = allData.find(d => d.id === recordId);
      if (item) {
        item.sns_advice = data.advice;
        openDetailModal(recordId);
        setTimeout(() => { selectCropRatio('instagram_crop_4_5', recordId); }, 250);
      }
    } else {
      alert(`SNS 제안 실패: ${data.error || '알 수 없는 오류'}`);
      btn.textContent = origText;
      btn.disabled = false;
    }
  } catch (err) {
    alert(`오류: ${err.message}`);
    btn.textContent = origText;
    btn.disabled = false;
  }
}

function renderLrAdviceContent(advice) {
  if (!advice) {
    return `<div style="font-size:0.86rem;color:var(--muted);text-align:center;padding:14px 0;">
      아직 생성된 보정 수치가 없습니다. 위의 <b>[🛠️ 라이트룸 보정 수치 제안 받기]</b> 버튼을 누르면 AI가 노출·명암·화이트밸런스 수치를 온디맨드로 분석합니다.
    </div>`;
  }
  return `
    <div style="display:grid;grid-template-columns:repeat(auto-fit, minmax(130px, 1fr));gap:8px;margin-bottom:12px;">
      <div class="lr-metric"><span>노출 (Exposure)</span><strong>${advice.exposure > 0 ? '+' : ''}${advice.exposure.toFixed(2)} EV</strong></div>
      <div class="lr-metric"><span>대비 (Contrast)</span><strong>${advice.contrast > 0 ? '+' : ''}${advice.contrast}</strong></div>
      <div class="lr-metric"><span>하이라이트</span><strong>${advice.highlights > 0 ? '+' : ''}${advice.highlights}</strong></div>
      <div class="lr-metric"><span>그림자 (Shadows)</span><strong>${advice.shadows > 0 ? '+' : ''}${advice.shadows}</strong></div>
      <div class="lr-metric"><span>흰색 계열 (Whites)</span><strong>${advice.whites > 0 ? '+' : ''}${advice.whites}</strong></div>
      <div class="lr-metric"><span>검정 계열 (Blacks)</span><strong>${advice.blacks > 0 ? '+' : ''}${advice.blacks}</strong></div>
      <div class="lr-metric"><span>텍스처 (Texture)</span><strong>${advice.texture > 0 ? '+' : ''}${advice.texture}</strong></div>
      <div class="lr-metric"><span>명료도 (Clarity)</span><strong>${advice.clarity > 0 ? '+' : ''}${advice.clarity}</strong></div>
      <div class="lr-metric"><span>디헤이즈 (Dehaze)</span><strong>${advice.dehaze > 0 ? '+' : ''}${advice.dehaze}</strong></div>
      <div class="lr-metric"><span>활기 (Vibrance)</span><strong>${advice.vibrance > 0 ? '+' : ''}${advice.vibrance}</strong></div>
      <div class="lr-metric"><span>채도 (Saturation)</span><strong>${advice.saturation > 0 ? '+' : ''}${advice.saturation}</strong></div>
    </div>
    <div style="background:white;padding:10px 14px;border-radius:8px;font-size:0.84rem;margin-bottom:8px;border:1px solid #e2e8f0;">
      <b style="color:#0369a1">🌡️ 화이트밸런스/색조:</b> ${advice.temp_tint_notes}
    </div>
    <div style="background:white;padding:10px 14px;border-radius:8px;font-size:0.84rem;border:1px solid #e2e8f0;">
      <b style="color:#4f46e5">🎨 마스킹 및 세부 후보정 팁:</b> ${advice.retouching_guide}
    </div>
  `;
}

async function requestLrAdvice(recordId, btn) {
  const origText = btn.textContent;
  btn.textContent = 'Gemini 분석 중...';
  btn.disabled = true;
  try {
    const res = await fetch(`/api/post-process-advice/${recordId}`, { method: 'POST' });
    const data = await res.json();
    if (data.success && data.advice) {
      const item = allData.find(d => d.id === recordId);
      if (item) {
        item.lr_advice = data.advice;
        openDetailModal(recordId);
      }
    } else {
      alert(`보정 수치 제안 실패: ${data.error || '알 수 없는 오류'}`);
      btn.textContent = origText;
      btn.disabled = false;
    }
  } catch (err) {
    alert(`오류: ${err.message}`);
    btn.textContent = origText;
    btn.disabled = false;
  }
}



function renderExifSummary(exif, detectedSettings) {
  const parts = [];
  if (exif && Object.keys(exif).length) {
    if (exif.Make || exif.Model) parts.push(`${exif.Make || ''} ${exif.Model || ''}`.trim());
    if (exif.FNumber) parts.push(`F/${exif.FNumber}`);
    if (exif.ExposureTime) parts.push(`${exif.ExposureTime}s`);
    if (exif.ISOSpeedRatings) parts.push(`ISO ${exif.ISOSpeedRatings}`);
    if (exif.FocalLength) parts.push(`${exif.FocalLength}mm`);
  }
  let html = '';
  if (parts.length) {
    html += `<div style="margin-top:4px;"><b>촬영 설정(EXIF):</b> ${parts.join(' · ')}</div>`;
  } else {
    html += '<div style="margin-top:4px;color:var(--muted);"><b>EXIF:</b> 파일 메타데이터 없음</div>';
  }

  if (detectedSettings && typeof detectedSettings === 'object' && Object.keys(detectedSettings).length) {
    const dParts = [];
    for (const [k, v] of Object.entries(detectedSettings)) {
      if (v) dParts.push(`${v}`);
    }
    if (dParts.length) {
      html += `<div style="margin-top:6px;background:#eef2ff;color:#4338ca;padding:4px 10px;border-radius:6px;font-size:0.8rem;display:inline-block;border:1px solid #c7d2fe;"><b>🔍 워터마크 감지 스펙:</b> ${dParts.join(' · ')}</div>`;
    }
  }
  return html;
}

function closeDetailModal() {
  document.getElementById('detail-modal').style.display = 'none';
  currentDetailId = null;
}
function closeModal(e) { if (e.target.id === 'detail-modal') closeDetailModal(); }

function toggleZoom(e) {
  const img = document.getElementById('detail-modal-img');
  if (!img) return;
  img.classList.toggle('zoomed');
  if (img.classList.contains('zoomed') && e) {
    panZoom(e);
  } else {
    img.style.transformOrigin = 'center center';
  }
  repositionCropOverlay();
}

function panZoom(e) {
  const img = document.getElementById('detail-modal-img');
  if (!img || !img.classList.contains('zoomed')) return;
  const rect = img.getBoundingClientRect();
  const x = Math.max(0, Math.min(100, ((e.clientX - rect.left) / rect.width) * 100));
  const y = Math.max(0, Math.min(100, ((e.clientY - rect.top) / rect.height) * 100));
  img.style.transformOrigin = `${x}% ${y}%`;
}

function navigateDetail(dir) {
  const modal = document.getElementById('detail-modal');
  if (modal.style.display !== 'flex' || currentDetailId === null) return;
  const filtered = sortList(filterList(allData));
  const idx = filtered.findIndex(d => d.id === currentDetailId);
  if (idx === -1) return;
  const nextIdx = idx + dir;
  if (nextIdx >= 0 && nextIdx < filtered.length) {
    openDetailModal(filtered[nextIdx].id);
  }
}

async function exportAllXmp(btn) {
  const origText = btn ? btn.textContent : '';
  if (btn) {
    btn.textContent = 'XMP 생성 중...';
    btn.disabled = true;
  }
  try {
    const res = await fetch('/api/export-xmp', { method: 'POST' });
    const data = await res.json();
    if (data.success) {
      alert(`총 ${data.count}개 사진의 Lightroom / Capture One 호환 XMP 사이드카 생성이 완료되었습니다!\n라이트룸에서 폴더를 새로고침하면 별점(1~5)과 색상 라벨이 즉시 표시됩니다.`);
    } else {
      alert(`XMP 내보내기 실패: ${data.error}`);
    }
  } catch (err) {
    alert(`오류: ${err.message}`);
  } finally {
    if (btn) {
      btn.textContent = origText;
      btn.disabled = false;
    }
  }
}

window.addEventListener('keydown', (e) => {
  if (['input', 'textarea', 'select'].includes(document.activeElement?.tagName?.toLowerCase())) return;
  if (e.key === 'Escape') {
    closeDetailModal();
    closeUploadModal();
  } else if (e.key === 'ArrowRight' || e.key === 'k') {
    navigateDetail(1);
  } else if (e.key === 'ArrowLeft' || e.key === 'j') {
    navigateDetail(-1);
  } else if (e.key === ' ' || e.code === 'Space') {
    const modal = document.getElementById('detail-modal');
    if (modal.style.display === 'flex') {
      e.preventDefault();
      toggleZoom();
    }
  }
});

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

async function getFilesFromEntry(entry) {
  if (entry.isFile) {
    return new Promise((resolve) => {
      entry.file(f => resolve([f]), () => resolve([]));
    });
  } else if (entry.isDirectory) {
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
      const fList = await getFilesFromEntry(child);
      subFiles.push(...fList);
    }
    return subFiles;
  }
  return [];
}

let isBatchUploading = false;

function openUploadModal() {
  document.getElementById('upload-modal').style.display = 'flex';
  document.getElementById('upload-status').textContent = '';
  document.getElementById('progress-container').style.display = 'none';
  document.getElementById('progress-bar').style.width = '0%';
  document.getElementById('progress-percent').textContent = '0%';
  document.getElementById('progress-text').textContent = '';
  document.getElementById('progress-current-file').textContent = '';
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
  const tier = document.getElementById('upload-tier').value;
  const category = document.getElementById('upload-category').value;
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

  for (let i = 0; i < total; i++) {
    const file = files[i];
    const currentNum = i + 1;
    const pct = Math.round(((i) / total) * 100);
    progPercent.textContent = `${pct}%`;
    progBar.style.width = `${pct}%`;
    progText.textContent = `[${currentNum} / ${total}장] Gemini 분석 진행 중...`;
    progFile.textContent = `현재 분석 파일: ${file.name} (${(file.size / 1024 / 1024).toFixed(1)}MB)`;

    const formData = new FormData();
    formData.append('image', file, file.name);
    formData.append('tier', tier);
    formData.append('category', category);

    try {
      const res = await fetch('/api/analyze', { method: 'POST', body: formData });
      const result = await res.json();
      if (result.success) {
        successCount++;
        status.textContent = `✓ [${currentNum}/${total}] ${file.name} 완료 (${result.analysis.final_score.toFixed(1)}점 - ${result.analysis.figure_category})`;
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
                from contextlib import closing
                with closing(sqlite3.connect(self.db_path)) as conn:
                    row = conn.execute(
                        "SELECT thumbnail, source_filename FROM photo_analyses WHERE id = ?", (record_id,)
                    ).fetchone()
                    if row:
                        thumb_blob, fname = row[0], row[1]
                        if thumb_blob:
                            self.send_response(HTTPStatus.OK)
                            self.send_header("Content-Type", "image/webp")
                            self.send_header("Content-Length", str(len(thumb_blob)))
                            self.send_header("Cache-Control", "public, max-age=86400")
                            self.end_headers()
                            self.wfile.write(thumb_blob)
                            return

                        # Fallback: search local files, generate thumbnail and cache into DB
                        for search_dir in (Path("test_photo"), Path("."), Path("outputs")):
                            cand = search_dir / fname
                            if cand.is_file():
                                thumb_bytes = make_thumbnail_bytes(cand)
                                conn.execute("UPDATE photo_analyses SET thumbnail = ? WHERE id = ?", (thumb_bytes, record_id))
                                conn.commit()
                                self.send_response(HTTPStatus.OK)
                                self.send_header("Content-Type", "image/webp")
                                self.send_header("Content-Length", str(len(thumb_bytes)))
                                self.send_header("Cache-Control", "public, max-age=86400")
                                self.end_headers()
                                self.wfile.write(thumb_bytes)
                                return
            except Exception:
                pass
            # Placeholder SVG if image is not found
            svg = (
                '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300" viewBox="0 0 400 300">'
                '<rect width="100%" height="100%" fill="#0f172a"/>'
                '<text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="#64748b" font-size="16" font-family="sans-serif">사진 미리보기 없음</text>'
                '</svg>'
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(svg)))
            self.end_headers()
            self.wfile.write(svg)
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
                category_param = "auto"

                for part in parts:
                    if b'name="tier"' in part:
                        tier = part.split(b"\r\n\r\n")[1].split(b"\r\n")[0].decode("utf-8").strip()
                    elif b'name="category"' in part:
                        category_param = part.split(b"\r\n\r\n")[1].split(b"\r\n")[0].decode("utf-8").strip()
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
                    photo_obj = prepare_photo(tmp_path)
                    prepared = PreparedPhoto(
                        source_filename=filename,
                        sha256=photo_obj.sha256,
                        width=photo_obj.width,
                        height=photo_obj.height,
                        image_format=photo_obj.image_format,
                        safe_exif=photo_obj.safe_exif,
                        upload_bytes=photo_obj.upload_bytes,
                        upload_mime_type=photo_obj.upload_mime_type,
                        thumbnail_bytes=photo_obj.thumbnail_bytes,
                    )
                    model = MODEL_PRESETS.get(tier, MODEL_PRESETS["lite"])
                    category_hint = category_param if category_param != "auto" else None
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

        if parsed.path == "/api/export-xmp":
            try:
                from photo_xmp_manager import write_xmp_sidecar
                exported_count = 0
                with closing(sqlite3.connect(self.db_path)) as conn:
                    conn.row_factory = sqlite3.Row
                    rows = conn.execute("SELECT * FROM photo_analyses").fetchall()
                    tag_rows = conn.execute("SELECT analysis_id, tag FROM photo_analysis_tags").fetchall()
                tags_by_id = {}
                for r in tag_rows:
                    tags_by_id.setdefault(int(r["analysis_id"]), []).append(str(r["tag"]))

                for r in rows:
                    aid = int(r["id"])
                    fname = r["source_filename"]
                    analysis_data = json.loads(r["analysis_json"])
                    # Search candidate locations
                    target_dir = Path("test_photo") if (Path("test_photo") / fname).is_file() else Path(".")
                    target_file = target_dir / fname
                    xmp_file = target_file.with_suffix(".xmp")
                    write_xmp_sidecar(
                        photo_path=target_file,
                        score=float(analysis_data.get("final_score", 0)),
                        reason=analysis_data.get("final_reason", ""),
                        figure_category=analysis_data.get("figure_category", "일반 피규어 촬영"),
                        tags=tags_by_id.get(aid, []),
                        strengths=analysis_data.get("strengths", []),
                        improvements=analysis_data.get("improvements", []),
                        target_xmp_path=xmp_file,
                    )
                    exported_count += 1

                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "count": exported_count}).encode("utf-8"))
                return
            except Exception as exc:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(exc)}).encode("utf-8"))
                return

        if parsed.path.startswith("/api/post-process-advice/"):
            try:
                record_id = int(parsed.path.split("/")[-1])
                ensure_db_columns(self.db_path)
                with closing(sqlite3.connect(self.db_path)) as conn:
                    conn.row_factory = sqlite3.Row
                    row = conn.execute("SELECT * FROM photo_analyses WHERE id = ?", (record_id,)).fetchone()
                    if not row:
                        raise ValueError(f"레코드 ID {record_id}를 찾을 수 없습니다.")

                    # 이미 캐시가 있으면 즉시 반환 (API 호출 방지)
                    if "lr_advice_json" in row.keys() and row["lr_advice_json"]:
                        cached_advice = json.loads(row["lr_advice_json"])
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.end_headers()
                        self.wfile.write(json.dumps({"success": True, "advice": cached_advice, "cached": True}, ensure_ascii=False).encode("utf-8"))
                        return

                    fname = row["source_filename"]
                    candidate_paths = [
                        Path("test_photo") / fname,
                        Path(fname),
                        Path("test_photo") / Path(fname).name,
                    ]
                    found_file = next((p for p in candidate_paths if p.is_file()), None)
                    if found_file:
                        prepared = prepare_photo(found_file)
                    elif row["thumbnail"]:
                        prepared = PreparedPhoto(
                            source_filename=fname,
                            sha256=row["sha256"],
                            width=row["width"],
                            height=row["height"],
                            image_format="WEBP",
                            safe_exif={},
                            upload_bytes=row["thumbnail"],
                            upload_mime_type="image/webp",
                        )
                    else:
                        raise ValueError(f"사진 파일 '{fname}'을 찾을 수 없으며 DB 썸네일도 없습니다.")

                    advice = generate_lightroom_advice(prepared, model=MODEL_PRESETS["lite"])
                    advice_dict = advice.model_dump(mode="json")
                    advice_json = json.dumps(advice_dict, ensure_ascii=False)

                    with conn:
                        conn.execute("UPDATE photo_analyses SET lr_advice_json = ? WHERE id = ?", (advice_json, record_id))

                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "advice": advice_dict, "cached": False}, ensure_ascii=False).encode("utf-8"))
                    return
            except Exception as exc:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(exc)}).encode("utf-8"))
                return

        if parsed.path.startswith("/api/sns-advice/"):
            try:
                record_id = int(parsed.path.split("/")[-1])
                ensure_db_columns(self.db_path)
                with closing(sqlite3.connect(self.db_path)) as conn:
                    conn.row_factory = sqlite3.Row
                    row = conn.execute("SELECT * FROM photo_analyses WHERE id = ?", (record_id,)).fetchone()
                    if not row:
                        raise ValueError(f"레코드 ID {record_id}를 찾을 수 없습니다.")

                    # 이미 캐시가 있으면 즉시 반환 (API 호출 방지)
                    if "sns_advice_json" in row.keys() and row["sns_advice_json"]:
                        cached_advice = json.loads(row["sns_advice_json"])
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.end_headers()
                        self.wfile.write(json.dumps({"success": True, "advice": cached_advice, "cached": True}, ensure_ascii=False).encode("utf-8"))
                        return

                    fname = row["source_filename"]
                    candidate_paths = [
                        Path("test_photo") / fname,
                        Path(fname),
                        Path("test_photo") / Path(fname).name,
                    ]
                    found_file = next((p for p in candidate_paths if p.is_file()), None)
                    if found_file:
                        prepared = prepare_photo(found_file)
                    elif row["thumbnail"]:
                        prepared = PreparedPhoto(
                            source_filename=fname,
                            sha256=row["sha256"],
                            width=row["width"],
                            height=row["height"],
                            image_format="WEBP",
                            safe_exif={},
                            upload_bytes=row["thumbnail"],
                            upload_mime_type="image/webp",
                        )
                    else:
                        raise ValueError(f"사진 파일 '{fname}'을 찾을 수 없으며 DB 썸네일도 없습니다.")

                    advice = generate_sns_advice(prepared, model=MODEL_PRESETS["lite"])
                    advice_dict = advice.model_dump(mode="json")
                    advice_json = json.dumps(advice_dict, ensure_ascii=False)

                    with conn:
                        conn.execute("UPDATE photo_analyses SET sns_advice_json = ? WHERE id = ?", (advice_json, record_id))

                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "advice": advice_dict, "cached": False}, ensure_ascii=False).encode("utf-8"))
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
