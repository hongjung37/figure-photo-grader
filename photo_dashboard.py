from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import datetime
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from burst_clustering import (
    are_burst_pair,
    are_filenames_sequential,
    cluster_burst_groups,
    parse_photo_time,
)
from photo_analyzer import (
    DEFAULT_DB_PATH,
    MODEL_PRESETS,
    SNS_CROP_RATIO_CONFIGS,
    CropBox,
    LightroomAdvice,
    PhotoAnalysis,
    PreparedPhoto,
    SNSAdvice,
    analyze_with_gemini,
    compute_dhash_from_bytes,
    dhash_from_sqlite,
    dhash_to_sqlite,
    ensure_tag_tables,
    generate_lightroom_advice,
    generate_all_sns_crops,
    generate_single_sns_crop,
    generate_sns_advice,
    generate_sns_caption_and_tags,
    get_usage_stats,
    hamming_distance,
    prepare_photo,
    get_original_photo_path,
    save_analysis,
    set_usage_log_db,
)
from photo_tag_schema import AESTHETIC_TAG_CATEGORIES, AESTHETIC_TAG_OPTIONS, get_score_grade

PORT = 8080


def find_existing_analysis(db_path: Path, sha256: str) -> tuple[int, dict] | None:
    """Return (record_id, analysis dict) of the latest stored analysis with the same file hash."""
    if not db_path.is_file():
        return None
    with closing(sqlite3.connect(db_path)) as conn:
        try:
            row = conn.execute(
                "SELECT id, analysis_json FROM photo_analyses WHERE sha256 = ? ORDER BY id DESC LIMIT 1",
                (sha256,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    if not row:
        return None
    try:
        return int(row[0]), json.loads(row[1])
    except (TypeError, ValueError):
        return None


def ensure_db_columns(db_path: Path) -> None:
    if not db_path.is_file():
        return
    with closing(sqlite3.connect(db_path)) as conn, conn:
        ensure_tag_tables(conn)
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
        if "user_score" not in cols:
            conn.execute("ALTER TABLE photo_analyses ADD COLUMN user_score REAL")

        missing = conn.execute(
            "SELECT id, thumbnail FROM photo_analyses WHERE dhash IS NULL AND thumbnail IS NOT NULL"
        ).fetchall()
        for mid, mthumb in missing:
            try:
                dh = compute_dhash_from_bytes(mthumb)
                conn.execute("UPDATE photo_analyses SET dhash = ? WHERE id = ?", (dhash_to_sqlite(dh), mid))
            except Exception:
                pass


# Note: are_filenames_sequential, parse_photo_time, are_burst_pair, and
# cluster_burst_groups are imported from burst_clustering.py and re-exported here.




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


def get_all_analyses(db_path: Path, max_hamming_dist: int = 15) -> list[dict]:
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
        if dhash_val is not None:
            dhash_val = dhash_from_sqlite(dhash_val)
        elif row["thumbnail"]:
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
                "user_score": float(row["user_score"]) if "user_score" in row.keys() and row["user_score"] is not None else None,
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
    return cluster_burst_groups(results, max_hamming_dist=max_hamming_dist)


def get_tag_stats(db_path: Path, min_count: int = 1) -> dict:
    """Aggregate statistics by aesthetic tag, including AI scores and user ratings."""
    ensure_db_columns(db_path)
    analyses = get_all_analyses(db_path)

    total_photos = len(analyses)
    user_rated_photos = sum(1 for a in analyses if a.get("user_score") is not None)

    tag_data: dict[tuple[str, str], dict] = {}

    for a in analyses:
        tags_dict = a.get("aesthetic_tags") or {}
        ai_score = float(a.get("final_score") or 0.0)
        u_score = a.get("user_score")
        light_score = float(a.get("lighting_score") or 0.0)
        comp_score = float(a.get("composition_score") or 0.0)
        tech_score = float(a.get("technique_score") or 0.0)
        color_score = float(a.get("color_score") or 0.0)

        for cat_key, t_list in tags_dict.items():
            if not isinstance(t_list, list):
                continue
            cat_name = AESTHETIC_TAG_CATEGORIES.get(cat_key, cat_key)
            for t in t_list:
                key = (cat_key, t)
                if key not in tag_data:
                    tag_data[key] = {
                        "category_key": cat_key,
                        "category_name": cat_name,
                        "tag": t,
                        "count": 0,
                        "ai_scores": [],
                        "user_scores": [],
                        "lighting_scores": [],
                        "composition_scores": [],
                        "technique_scores": [],
                        "color_scores": [],
                    }
                td = tag_data[key]
                td["count"] += 1
                td["ai_scores"].append(ai_score)
                if u_score is not None:
                    td["user_scores"].append(float(u_score))
                td["lighting_scores"].append(light_score)
                td["composition_scores"].append(comp_score)
                td["technique_scores"].append(tech_score)
                td["color_scores"].append(color_score)

    items = []
    for (cat_key, t), td in tag_data.items():
        if td["count"] < min_count:
            continue
        avg_ai = sum(td["ai_scores"]) / len(td["ai_scores"]) if td["ai_scores"] else 0.0
        avg_user = (sum(td["user_scores"]) / len(td["user_scores"])) if td["user_scores"] else None
        avg_light = sum(td["lighting_scores"]) / len(td["lighting_scores"]) if td["lighting_scores"] else 0.0
        avg_comp = sum(td["composition_scores"]) / len(td["composition_scores"]) if td["composition_scores"] else 0.0
        avg_tech = sum(td["technique_scores"]) / len(td["technique_scores"]) if td["technique_scores"] else 0.0
        avg_color = sum(td["color_scores"]) / len(td["color_scores"]) if td["color_scores"] else 0.0

        score_diff = round(avg_user - avg_ai, 2) if avg_user is not None else None

        items.append({
            "category_key": cat_key,
            "category_name": td["category_name"],
            "tag": t,
            "count": td["count"],
            "avg_ai_score": round(avg_ai, 2),
            "avg_user_score": round(avg_user, 2) if avg_user is not None else None,
            "score_diff": score_diff,
            "user_rated_count": len(td["user_scores"]),
            "avg_lighting_score": round(avg_light, 2),
            "avg_composition_score": round(avg_comp, 2),
            "avg_technique_score": round(avg_tech, 2),
            "avg_color_score": round(avg_color, 2),
        })

    items.sort(key=lambda x: x["avg_ai_score"], reverse=True)

    top_ai_tags = items[:5]
    bottom_ai_tags = sorted(items, key=lambda x: x["avg_ai_score"])[:5] if len(items) >= 2 else []

    with_user = [x for x in items if x["avg_user_score"] is not None]
    top_user_fav_tags = sorted(with_user, key=lambda x: (x["score_diff"] or 0), reverse=True)[:5]

    categories_dict: dict[str, list] = {}
    for it in items:
        categories_dict.setdefault(it["category_key"], []).append(it)

    return {
        "total_photos": total_photos,
        "user_rated_photos": user_rated_photos,
        "total_unique_tags": len(tag_data),
        "filtered_tags_count": len(items),
        "min_count": min_count,
        "all_tags": items,
        "top_ai_tags": top_ai_tags,
        "bottom_ai_tags": bottom_ai_tags,
        "top_user_fav_tags": top_user_fav_tags,
        "categories": categories_dict,
        "category_names": AESTHETIC_TAG_CATEGORIES,
    }


TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"


def load_template_file(rel_path: str) -> str:
    path = Path(__file__).resolve().parent / rel_path
    return path.read_text(encoding="utf-8") if path.is_file() else ""


# Backward compatibility for existing tests checking strings in DASHBOARD_HTML:
_INDEX_HTML = load_template_file("templates/index.html")
_DASHBOARD_CSS = load_template_file("static/dashboard.css")
_DASHBOARD_JS = load_template_file("static/dashboard.js")
DASHBOARD_HTML = (
    _INDEX_HTML
    + "\n<style>\n"
    + _DASHBOARD_CSS
    + "\n</style>\n"
    + "\n<script>\n"
    + _DASHBOARD_JS
    + "\n</script>\n"
)


class DashboardRequestHandler(SimpleHTTPRequestHandler):
    db_path: Path = DEFAULT_DB_PATH

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            index_file = TEMPLATES_DIR / "index.html"
            if index_file.is_file():
                html_bytes = index_file.read_bytes()
            else:
                html_bytes = DASHBOARD_HTML.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html_bytes)))
            self.end_headers()
            self.wfile.write(html_bytes)
            return

        if path.startswith("/static/"):
            rel_file = path[len("/static/"):]
            target_file = (STATIC_DIR / rel_file).resolve()
            if target_file.is_file() and STATIC_DIR in target_file.parents:
                content = target_file.read_bytes()
                mime = "text/css; charset=utf-8" if target_file.suffix == ".css" else "application/javascript; charset=utf-8"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(content)
                return
            self.send_error(HTTPStatus.NOT_FOUND, "Static file not found")
            return

        if parsed.path == "/api/analyses":
            query = parse_qs(parsed.query)
            try:
                burst_dist = int(query.get("burst_dist", ["15"])[0])
            except Exception:
                burst_dist = 15
            data = get_all_analyses(self.db_path, max_hamming_dist=burst_dist)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        if parsed.path == "/api/usage-stats":
            data = get_usage_stats(self.db_path)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        if parsed.path == "/api/tag-stats":
            query = parse_qs(parsed.query)
            try:
                min_count = max(1, int(query.get("min_count", ["1"])[0]))
            except Exception:
                min_count = 1
            data = get_tag_stats(self.db_path, min_count=min_count)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            return

        if path.startswith("/api/image/"):
            try:
                record_id = int(path.split("/")[-1])
                wants_original = parse_qs(parsed.query).get("original", ["0"])[0].lower() in ("1", "true", "yes")
                from contextlib import closing
                with closing(sqlite3.connect(self.db_path)) as conn:
                    row = conn.execute(
                        "SELECT thumbnail, source_filename, sha256 FROM photo_analyses WHERE id = ?", (record_id,)
                    ).fetchone()
                    if row:
                        thumb_blob, fname, sha256 = row[0], row[1], row[2]
                        if wants_original:
                            for mime_type in ("image/jpeg", "image/png", "image/webp"):
                                original_path = get_original_photo_path(self.db_path, sha256, mime_type)
                                if original_path.is_file():
                                    image_bytes = original_path.read_bytes()
                                    self.send_response(HTTPStatus.OK)
                                    self.send_header("Content-Type", mime_type)
                                    self.send_header("Content-Length", str(len(image_bytes)))
                                    self.send_header("Cache-Control", "public, max-age=86400")
                                    self.end_headers()
                                    self.wfile.write(image_bytes)
                                    return
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
                boundary_raw = content_type.split("boundary=")[-1].strip()
                boundary = boundary_raw.strip('"\'')
                parts = body.split(f"--{boundary}".encode("utf-8"))

                file_bytes = None
                filename = "uploaded.webp"
                tier = "lite"
                category_param = "auto"

                for part in parts:
                    if b"\r\n\r\n" not in part:
                        continue
                    header, data = part.split(b"\r\n\r\n", 1)
                    if data.endswith(b"\r\n"):
                        data = data[:-2]
                    if data.endswith(b"--"):
                        data = data[:-2]
                    if data.endswith(b"\r\n"):
                        data = data[:-2]

                    if b'name="tier"' in header:
                        tier = data.decode("utf-8", errors="replace").strip()
                    elif b'name="category"' in header:
                        category_param = data.decode("utf-8", errors="replace").strip()
                    elif b'name="image"' in header:
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
                        dhash=photo_obj.dhash,
                    )
                    force_reanalyze = parse_qs(parsed.query).get("force", ["false"])[0].lower() in ("1", "true", "yes")
                    existing = None if force_reanalyze else find_existing_analysis(self.db_path, prepared.sha256)
                    if existing is not None:
                        record_id, analysis_dict = existing
                        duplicate = True
                    else:
                        model = MODEL_PRESETS.get(tier, MODEL_PRESETS["lite"])
                        category_hint = category_param if category_param != "auto" else None
                        analysis = analyze_with_gemini(prepared, model=model, category_hint=category_hint)
                        record_id = save_analysis(self.db_path, prepared, model, analysis)
                        analysis_dict = analysis.model_dump(mode="json")
                        duplicate = False
                finally:
                    tmp_path.unlink(missing_ok=True)

                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                res = {
                    "success": True,
                    "record_id": record_id,
                    "analysis": analysis_dict,
                    "duplicate": duplicate,
                }
                self.wfile.write(json.dumps(res, ensure_ascii=False).encode("utf-8"))
                return
            except Exception as exc:
                import traceback
                print(f"[/api/analyze ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8"))
                return

        if parsed.path == "/api/update-status":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                data = json.loads(body.decode("utf-8"))
                record_id = int(data.get("id"))
                new_status = str(data.get("status", "토너먼트 1위"))
                from photo_excel_manager import REVIEW_STATUSES
                if new_status not in REVIEW_STATUSES:
                    raise ValueError(f"유효하지 않은 검토 상태입니다: {new_status}")
                ensure_db_columns(self.db_path)
                with closing(sqlite3.connect(self.db_path)) as conn, conn:
                    conn.execute("UPDATE photo_analyses SET review_status = ? WHERE id = ?", (new_status, record_id))
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode("utf-8"))
                return
            except Exception as exc:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(exc)}).encode("utf-8"))
                return

        if parsed.path == "/api/rate":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                data = json.loads(body.decode("utf-8"))
                record_id = int(data.get("id"))
                raw_score = data.get("user_score")
                user_score = None
                if raw_score is not None and str(raw_score).strip() != "":
                    user_score = max(0.0, min(10.0, round(float(raw_score), 1)))
                ensure_db_columns(self.db_path)
                with closing(sqlite3.connect(self.db_path)) as conn, conn:
                    conn.execute("UPDATE photo_analyses SET user_score = ? WHERE id = ?", (user_score, record_id))
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "id": record_id, "user_score": user_score}, ensure_ascii=False).encode("utf-8"))
                return
            except Exception as exc:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(exc)}).encode("utf-8"))
                return

        if parsed.path == "/api/delete-analysis":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                data = json.loads(body.decode("utf-8"))
                record_ids = []
                if "ids" in data:
                    record_ids = [int(i) for i in data["ids"]]
                elif "id" in data:
                    record_ids = [int(data["id"])]
                if not record_ids:
                    raise ValueError("삭제할 기록 ID가 지정되지 않았습니다.")
                ensure_db_columns(self.db_path)
                with closing(sqlite3.connect(self.db_path)) as conn, conn:
                    conn.execute("PRAGMA foreign_keys = ON")
                    placeholders = ",".join("?" for _ in record_ids)
                    rows = conn.execute(
                        f"SELECT sha256 FROM photo_analyses WHERE id IN ({placeholders})",
                        record_ids,
                    ).fetchall()
                    conn.execute(f"DELETE FROM photo_analysis_tags WHERE analysis_id IN ({placeholders})", record_ids)
                    conn.execute(f"DELETE FROM photo_analyses WHERE id IN ({placeholders})", record_ids)
                    remaining_hashes = {
                        row[0]
                        for row in conn.execute("SELECT sha256 FROM photo_analyses").fetchall()
                    }
                    for row in rows:
                        if row[0] in remaining_hashes:
                            continue
                        for mime_type in ("image/jpeg", "image/png", "image/webp"):
                            original_path = get_original_photo_path(self.db_path, row[0], mime_type)
                            original_path.unlink(missing_ok=True)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "deleted_ids": record_ids, "count": len(record_ids)}).encode("utf-8"))
                return
            except Exception as exc:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8"))
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

        if parsed.path.startswith("/api/sns-crop/"):
            try:
                parts = parsed.path.strip("/").split("/")
                if len(parts) < 4:
                    raise ValueError("올바른 API 경로 형식이 아닙니다. (/api/sns-crop/<ratio_key>/<record_id>)")
                ratio_key = parts[2]
                record_id = int(parts[3])
                query = parse_qs(parsed.query)
                force = query.get("force", ["false"])[0].lower() in ("true", "1", "yes")

                ensure_db_columns(self.db_path)
                with closing(sqlite3.connect(self.db_path)) as conn:
                    conn.row_factory = sqlite3.Row
                    row = conn.execute("SELECT * FROM photo_analyses WHERE id = ?", (record_id,)).fetchone()
                    if not row:
                        raise ValueError(f"레코드 ID {record_id}를 찾을 수 없습니다.")

                    cached_advice: dict[str, Any] = {}
                    if "sns_advice_json" in row.keys() and row["sns_advice_json"]:
                        try:
                            cached_advice = json.loads(row["sns_advice_json"])
                        except Exception:
                            cached_advice = {}

                    is_cached = (
                        (ratio_key == "original" and "best_ratio_key" in cached_advice)
                        or (ratio_key in cached_advice and cached_advice[ratio_key])
                    )
                    if not force and is_cached:
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "success": True,
                            "ratio_key": ratio_key,
                            "crop_box": cached_advice.get(ratio_key),
                            "advice": cached_advice,
                            "cached": True,
                        }, ensure_ascii=False).encode("utf-8"))
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

                    if ratio_key in ("all", "original"):
                        crop_set = generate_all_sns_crops(prepared, model=MODEL_PRESETS["lite"])
                        for key, box in crop_set.model_dump(mode="json").items():
                            cached_advice[key] = box
                        crop_dict = cached_advice.get(ratio_key) if ratio_key != "all" else cached_advice.get("instagram_crop_4_5", {})
                    elif ratio_key not in SNS_CROP_RATIO_CONFIGS:
                        raise ValueError(f"지원하지 않는 SNS 크롭 비율 키입니다: {ratio_key}")
                    elif force:
                        # Explicit regenerate: refresh only the requested ratio.
                        crop_box = generate_single_sns_crop(prepared, ratio_key=ratio_key, model=MODEL_PRESETS["lite"])
                        cached_advice[ratio_key] = crop_box.model_dump(mode="json")
                        crop_dict = cached_advice[ratio_key]
                    else:
                        # First crop request for this photo: get all 4 ratios in ONE call and cache them,
                        # so the other ratio buttons need no further API calls.
                        crop_set = generate_all_sns_crops(prepared, model=MODEL_PRESETS["lite"])
                        for key, box in crop_set.model_dump(mode="json").items():
                            if key in ("best_ratio_key", "best_ratio_reason", "original_tip") or key == ratio_key or not cached_advice.get(key):
                                cached_advice[key] = box
                        crop_dict = cached_advice[ratio_key]
                    advice_json = json.dumps(cached_advice, ensure_ascii=False)

                    with conn:
                        conn.execute("UPDATE photo_analyses SET sns_advice_json = ? WHERE id = ?", (advice_json, record_id))

                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": True,
                        "ratio_key": ratio_key,
                        "crop_box": crop_dict,
                        "advice": cached_advice,
                        "cached": False,
                    }, ensure_ascii=False).encode("utf-8"))
                    return
            except Exception as exc:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(exc)}).encode("utf-8"))
                return

        if parsed.path.startswith("/api/sns-caption/"):
            try:
                record_id = int(parsed.path.split("/")[-1])
                query = parse_qs(parsed.query)
                force = query.get("force", ["false"])[0].lower() in ("true", "1", "yes")

                ensure_db_columns(self.db_path)
                with closing(sqlite3.connect(self.db_path)) as conn:
                    conn.row_factory = sqlite3.Row
                    row = conn.execute("SELECT * FROM photo_analyses WHERE id = ?", (record_id,)).fetchone()
                    if not row:
                        raise ValueError(f"레코드 ID {record_id}를 찾을 수 없습니다.")

                    cached_advice: dict[str, Any] = {}
                    if "sns_advice_json" in row.keys() and row["sns_advice_json"]:
                        try:
                            cached_advice = json.loads(row["sns_advice_json"])
                        except Exception:
                            cached_advice = {}

                    if not force and "social_caption" in cached_advice and cached_advice["social_caption"]:
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            "success": True,
                            "social_caption": cached_advice["social_caption"],
                            "hashtags": cached_advice.get("hashtags", []),
                            "advice": cached_advice,
                            "cached": True,
                        }, ensure_ascii=False).encode("utf-8"))
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

                    cap = generate_sns_caption_and_tags(prepared, model=MODEL_PRESETS["lite"])
                    cached_advice["social_caption"] = cap.social_caption
                    cached_advice["hashtags"] = cap.hashtags
                    advice_json = json.dumps(cached_advice, ensure_ascii=False)

                    with conn:
                        conn.execute("UPDATE photo_analyses SET sns_advice_json = ? WHERE id = ?", (advice_json, record_id))

                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": True,
                        "social_caption": cap.social_caption,
                        "hashtags": cap.hashtags,
                        "advice": cached_advice,
                        "cached": False,
                    }, ensure_ascii=False).encode("utf-8"))
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
    set_usage_log_db(DashboardRequestHandler.db_path)
    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardRequestHandler)
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
