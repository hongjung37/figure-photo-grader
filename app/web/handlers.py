from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import tempfile
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.config import (
    DEFAULT_DB_PATH,
    MODEL_PRESETS,
    PORT,
    PROJECT_ROOT,
    SNS_CROP_RATIO_CONFIGS,
    STATIC_DIR,
    TEMPLATES_DIR,
)
from app.db import (
    delete_analyses,
    ensure_db_columns,
    ensure_tag_tables,
    find_existing_analysis,
    get_all_analyses,
    get_analyses_and_tags_for_export,
    get_analysis_row_by_id,
    get_photo_thumbnail_and_hash,
    get_tag_stats,
    save_analysis,
    update_lr_advice,
    update_photo_thumbnail,
    update_review_status,
    update_sns_advice,
    update_user_score,
)
from app.models.analysis import AESTHETIC_TAG_CATEGORIES, AESTHETIC_TAG_OPTIONS, PhotoAnalysis, get_score_grade
from app.models.crop import CropBox, SNSAdvice
from app.models.lightroom import LightroomAdvice
from app.services.burst_detector import (
    are_burst_pair,
    are_filenames_sequential,
    cluster_burst_groups,
    parse_photo_time,
)
from app.services.gemini_client import (
    analyze_with_gemini,
    generate_all_sns_crops,
    generate_lightroom_advice,
    generate_single_sns_crop,
    generate_sns_advice,
    generate_sns_caption_and_tags,
    get_usage_stats,
    set_usage_log_db,
)
from app.services.image_processor import (
    PreparedPhoto,
    compute_dhash_from_bytes,
    dhash_from_sqlite,
    dhash_to_sqlite,
    get_original_photo_path,
    hamming_distance,
    make_thumbnail_bytes,
    prepare_photo,
)


def load_template_file(rel_path: str) -> str:
    path = PROJECT_ROOT / rel_path
    return path.read_text(encoding="utf-8") if path.is_file() else ""


_INDEX_HTML = load_template_file("templates/index.html")
_DASHBOARD_CSS = load_template_file("static/dashboard.css")
_API_JS = load_template_file("static/js/api.js")
_TAG_FILTER_JS = load_template_file("static/js/tag_filter.js")
_CROP_VIEWER_JS = load_template_file("static/js/crop_viewer.js")
_DASHBOARD_JS = load_template_file("static/dashboard.js")
DASHBOARD_HTML = (
    _INDEX_HTML
    + "\n<style>\n"
    + _DASHBOARD_CSS
    + "\n</style>\n"
    + "\n<script>\n"
    + _API_JS
    + "\n"
    + _TAG_FILTER_JS
    + "\n"
    + _CROP_VIEWER_JS
    + "\n"
    + _DASHBOARD_JS
    + "\n</script>\n"
)

def _load_prepared_photo_for_record(db_path: Path, row: dict[str, Any] | Any) -> PreparedPhoto:
    """Load PreparedPhoto prioritizing high-res photo_originals, then local files, then DB thumbnail."""
    sha256 = row["sha256"]
    fname = row["source_filename"]

    # 1. High-resolution stored original
    for mime_type in ("image/jpeg", "image/png", "image/webp"):
        orig_path = get_original_photo_path(db_path, sha256, mime_type)
        if orig_path.is_file():
            prep = prepare_photo(orig_path)
            from dataclasses import replace
            return replace(prep, source_filename=fname, sha256=sha256)

    # 2. Local candidate paths
    candidate_paths = [
        Path("test_photo") / fname,
        Path(fname),
        Path("test_photo") / Path(fname).name,
    ]
    found_file = next((p for p in candidate_paths if p.is_file()), None)
    if found_file:
        prep = prepare_photo(found_file)
        from dataclasses import replace
        return replace(prep, source_filename=fname, sha256=sha256)

    # 3. DB thumbnail fallback
    if row["thumbnail"]:
        return PreparedPhoto(
            source_filename=fname,
            sha256=sha256,
            width=row["width"],
            height=row["height"],
            image_format="WEBP",
            safe_exif={},
            upload_bytes=row["thumbnail"],
            upload_mime_type="image/webp",
        )

    raise ValueError(f"사진 파일 '{fname}'을 찾을 수 없으며 DB 썸네일도 없습니다.")


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
                row = get_photo_thumbnail_and_hash(self.db_path, record_id)
                if row:
                    thumb_blob, fname, sha256 = row
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
                            update_photo_thumbnail(self.db_path, record_id, thumb_bytes)
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
                from app.exporters.excel_exporter import REVIEW_STATUSES
                if new_status not in REVIEW_STATUSES:
                    raise ValueError(f"유효하지 않은 검토 상태입니다: {new_status}")
                update_review_status(self.db_path, record_id, new_status)
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
                update_user_score(self.db_path, record_id, user_score)
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
                delete_analyses(self.db_path, record_ids)
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": True, "deleted_ids": record_ids, "count": len(record_ids)}).encode("utf-8"))
                return
            except Exception as exc:
                self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(exc)}).encode("utf-8"))
                return

        if parsed.path == "/api/export-xmp":
            try:
                from app.services.xmp_service import write_xmp_sidecar
                exported_count = 0
                rows, tags_by_id = get_analyses_and_tags_for_export(self.db_path)

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
                row = get_analysis_row_by_id(self.db_path, record_id)
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

                prepared = _load_prepared_photo_for_record(self.db_path, row)

                advice = generate_lightroom_advice(prepared, model=MODEL_PRESETS["lite"])
                advice_dict = advice.model_dump(mode="json")
                advice_json = json.dumps(advice_dict, ensure_ascii=False)

                update_lr_advice(self.db_path, record_id, advice_json)

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

                row = get_analysis_row_by_id(self.db_path, record_id)
                if not row:
                    raise ValueError(f"레코드 ID {record_id}를 찾을 수 없습니다.")

                cached_advice: dict[str, Any] = {}
                if "sns_advice_json" in row.keys() and row["sns_advice_json"]:
                    try:
                        cached_advice = json.loads(row["sns_advice_json"])
                    except Exception:
                        cached_advice = {}

                has_original_cache = (
                    "best_ratio_key" in cached_advice
                    and bool(cached_advice.get("original_tip"))
                )
                is_cached = (
                    (ratio_key == "original" and has_original_cache)
                    or (ratio_key != "original" and ratio_key in cached_advice and bool(cached_advice.get(ratio_key)))
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

                prepared = _load_prepared_photo_for_record(self.db_path, row)

                if ratio_key in ("all", "original"):
                    crop_set = generate_all_sns_crops(prepared, model=MODEL_PRESETS["lite"])
                    for key, box in crop_set.model_dump(mode="json").items():
                        cached_advice[key] = box
                    crop_dict = cached_advice.get(ratio_key) if ratio_key != "all" else cached_advice.get("instagram_crop_4_5", {})
                elif ratio_key not in SNS_CROP_RATIO_CONFIGS:
                    raise ValueError(f"지원하지 않는 SNS 크롭 비율 키입니다: {ratio_key}")
                elif force:
                    # Explicit regenerate: refresh all crops and recommendations together in ONE call
                    # so that crop boxes, best_ratio_key, best_ratio_reason, and original_tip remain 100% consistent.
                    crop_set = generate_all_sns_crops(prepared, model=MODEL_PRESETS["lite"])
                    for key, box in crop_set.model_dump(mode="json").items():
                        cached_advice[key] = box
                    crop_dict = cached_advice[ratio_key]
                else:
                    # First crop request for this photo: get all 4 ratios + best pick in ONE call and cache them,
                    # so the other ratio buttons need no further API calls.
                    crop_set = generate_all_sns_crops(prepared, model=MODEL_PRESETS["lite"])
                    for key, box in crop_set.model_dump(mode="json").items():
                        cached_advice[key] = box
                    crop_dict = cached_advice[ratio_key]
                advice_json = json.dumps(cached_advice, ensure_ascii=False)

                update_sns_advice(self.db_path, record_id, advice_json)

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

                row = get_analysis_row_by_id(self.db_path, record_id)
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

                prepared = _load_prepared_photo_for_record(self.db_path, row)

                cap = generate_sns_caption_and_tags(prepared, model=MODEL_PRESETS["lite"])
                cached_advice["social_caption"] = cap.social_caption
                cached_advice["hashtags"] = cap.hashtags
                advice_json = json.dumps(cached_advice, ensure_ascii=False)

                update_sns_advice(self.db_path, record_id, advice_json)

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
                row = get_analysis_row_by_id(self.db_path, record_id)
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

                prepared = _load_prepared_photo_for_record(self.db_path, row)

                advice = generate_sns_advice(prepared, model=MODEL_PRESETS["lite"])
                advice_dict = advice.model_dump(mode="json")
                advice_json = json.dumps(advice_dict, ensure_ascii=False)

                update_sns_advice(self.db_path, record_id, advice_json)

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
