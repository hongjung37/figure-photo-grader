from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import re
import sys
import tempfile
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.config import (
    DEFAULT_DB_PATH,
    DEFAULT_OPENAI_MODEL,
    MAX_UPLOAD_SIZE,
    MODEL_PRESETS,
    OPENAI_MODEL_PRESETS,
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
    get_analysis_by_id,
    get_analysis_row_by_id,
    get_photo_thumbnail_and_hash,
    get_tag_stats,
    save_analysis,
    update_analysis,
    update_cross_check_opinion,
    update_lr_advice,
    update_photo_thumbnail,
    update_review_status,
    update_sns_advice,
    update_user_score,
)
from app.models.analysis import (
    AESTHETIC_TAG_CATEGORIES,
    AESTHETIC_TAG_OPTIONS,
    CrossCheckOpinion,
    PhotoAnalysis,
    get_score_grade,
)
from app.models.crop import CropBox, SNSAdvice
from app.models.lightroom import LightroomAdvice
from app.services.burst_detector import (
    are_burst_pair,
    are_filenames_sequential,
    cluster_burst_groups,
    parse_photo_time,
)
from app.services.gemini_client import (
    get_usage_stats,
    set_usage_log_db,
)
from app.services.multi_llm import (
    analyze_photo,
    resolve_task_model,
    suggest_all_sns_crops,
    suggest_lightroom_advice as _multi_llm_suggest_lightroom_advice,
    suggest_single_sns_crop,
    suggest_sns_advice,
    suggest_sns_caption_and_tags,
)

# Backward-compatibility alias for tests patching app.web.handlers.generate_lightroom_advice
generate_lightroom_advice = _multi_llm_suggest_lightroom_advice


def suggest_lightroom_advice(*args, **kwargs):
    return generate_lightroom_advice(*args, **kwargs)

from app.services.image_processor import (
    PreparedPhoto,
    compute_dhash_from_bytes,
    dhash_from_sqlite,
    dhash_to_sqlite,
    get_original_photo_path,
    hamming_distance,
    make_thumbnail_bytes,
    prepare_photo,
    prepare_photo_from_bytes,
)


def load_template_file(rel_path: str) -> str:
    path = PROJECT_ROOT / rel_path
    return path.read_text(encoding="utf-8") if path.is_file() else ""


_INDEX_HTML = load_template_file("templates/index.html")
_DASHBOARD_CSS = load_template_file("static/dashboard.css")
_API_JS = load_template_file("static/js/api.js")
_TAG_FILTER_JS = load_template_file("static/js/tag_filter.js")
_CROP_VIEWER_JS = load_template_file("static/js/crop_viewer.js")
_TOURNAMENT_JS = load_template_file("static/js/tournament.js")
_TAG_INSIGHTS_JS = load_template_file("static/js/tag_insights.js")
_MODALS_JS = load_template_file("static/js/modals.js")
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
    + _TOURNAMENT_JS
    + "\n"
    + _TAG_INSIGHTS_JS
    + "\n"
    + _MODALS_JS
    + "\n"
    + _DASHBOARD_JS
    + "\n</script>\n"
)


_FILE_HASH_CACHE: dict[tuple[str, int, float], str] = {}


def _get_file_sha256(path: Path) -> str:
    """Calculate and cache SHA-256 hash using chunked streaming."""
    try:
        st = path.stat()
        cache_key = (str(path), st.st_size, st.st_mtime)
        cached = _FILE_HASH_CACHE.get(cache_key)
        if cached is not None:
            return cached
        digest = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        h = digest.hexdigest()
        if len(_FILE_HASH_CACHE) > 500:
            _FILE_HASH_CACHE.clear()
        _FILE_HASH_CACHE[cache_key] = h
        return h
    except OSError:
        return ""


def _find_local_photo_path(filename: str, expected_sha256: str | None = None) -> Path | None:
    """Find a project-local photo without depending on the process working directory."""
    safe_name = Path(str(filename).replace("\\", "/")).name
    if not safe_name or safe_name in {".", ".."}:
        return None
    allowed_dirs = [
        (PROJECT_ROOT / "test_photo").resolve(),
        PROJECT_ROOT.resolve(),
        (PROJECT_ROOT / "outputs").resolve(),
    ]
    for base in allowed_dirs:
        candidate = (base / safe_name).resolve()
        try:
            if candidate.is_relative_to(base) and candidate.is_file():
                if expected_sha256:
                    if _get_file_sha256(candidate) != expected_sha256:
                        continue
                return candidate
        except (ValueError, OSError):
            continue
    return None


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
    found_file = _find_local_photo_path(fname, expected_sha256=sha256)
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


class DashboardRequestHandler(BaseHTTPRequestHandler):
    db_path: Path = DEFAULT_DB_PATH

    # --- HTTP Response & Body Helpers ---

    def _send_json(self, status: HTTPStatus | int, payload: dict[str, Any] | list[Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def _send_json_ok(self, payload: dict[str, Any] | list[Any]) -> None:
        self._send_json(HTTPStatus.OK, payload)

    def _send_json_error(self, status: HTTPStatus | int, message: str) -> None:
        self._send_json(status, {"success": False, "error": message})

    def _read_json_body(self, max_bytes: int = 1024 * 1024) -> dict[str, Any]:
        raw_len = self.headers.get("Content-Length")
        if raw_len is None:
            raise ValueError("Content-Length 헤더가 필요합니다.")
        try:
            content_length = int(raw_len)
        except ValueError as exc:
            raise ValueError("유효하지 않은 Content-Length입니다.") from exc
        if content_length <= 0 or content_length > max_bytes:
            raise ValueError(f"허용된 요청 본문 크기(1~{max_bytes} bytes)를 벗어났습니다.")
        body = self.rfile.read(content_length)
        data = json.loads(body.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON 객체 형식의 요청 본문이 필요합니다.")
        return data

    @staticmethod
    def _parse_multipart_form(body: bytes, content_type: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "tier": "standard",
            "provider": "gemini",
            "category": "auto",
            "filename": "uploaded.webp",
            "image": None,
        }
        boundary_match = re.search(r"boundary=([^;]+)", content_type)
        if not boundary_match:
            return result
        boundary_str = boundary_match.group(1).strip().strip("\"'")
        boundary = boundary_str.encode("utf-8")
        parts = body.split(b"--" + boundary)

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
                result["tier"] = data.decode("utf-8", errors="replace").strip()
            elif b'name="provider"' in header:
                result["provider"] = data.decode("utf-8", errors="replace").strip()
            elif b'name="category"' in header:
                result["category"] = data.decode("utf-8", errors="replace").strip()
            elif b'name="image"' in header:
                result["image"] = data
                for line in header.split(b"\r\n"):
                    if b"filename=" in line:
                        fn_raw = line.split(b'filename="')[-1].split(b'"')[0]
                        result["filename"] = Path(
                            fn_raw.decode("utf-8", errors="replace").replace("\\", "/")
                        ).name or "uploaded.webp"
        return result

    # --- GET Handlers ---

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            return self._handle_get_index()

        if path.startswith("/static/"):
            return self._handle_get_static(path)

        if path == "/api/analyses":
            return self._handle_get_analyses(parsed.query)

        if path == "/api/usage-stats":
            return self._handle_get_usage_stats()

        if path == "/api/tag-stats":
            return self._handle_get_tag_stats(parsed.query)

        if path.startswith("/api/image/"):
            return self._handle_get_image(path, parsed.query)

        self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def _handle_get_index(self) -> None:
        index_file = TEMPLATES_DIR / "index.html"
        if index_file.is_file():
            html_bytes = index_file.read_bytes()
        else:
            html_bytes = DASHBOARD_HTML.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html_bytes)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(html_bytes)

    def _handle_get_static(self, path: str) -> None:
        rel_file = path[len("/static/"):]
        static_root = STATIC_DIR.resolve()
        target_file = (static_root / rel_file).resolve()
        if target_file.is_relative_to(static_root) and target_file.is_file():
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

    def _handle_get_analyses(self, query_str: str) -> None:
        query = parse_qs(query_str)
        try:
            burst_dist = int(query.get("burst_dist", ["15"])[0])
        except Exception:
            burst_dist = 15
        data = get_all_analyses(self.db_path, max_hamming_dist=burst_dist)
        self._send_json_ok(data)

    def _handle_get_usage_stats(self) -> None:
        data = get_usage_stats(self.db_path)
        self._send_json_ok(data)

    def _handle_get_tag_stats(self, query_str: str) -> None:
        query = parse_qs(query_str)
        try:
            min_count = max(1, int(query.get("min_count", ["1"])[0]))
        except Exception:
            min_count = 1
        data = get_tag_stats(self.db_path, min_count=min_count)
        self._send_json_ok(data)

    def _handle_get_image(self, path: str, query_str: str) -> None:
        try:
            record_id = int(path.split("/")[-1])
            wants_original = parse_qs(query_str).get("original", ["0"])[0].lower() in ("1", "true", "yes")
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

                cand = _find_local_photo_path(fname, expected_sha256=sha256)
                if cand:
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

    # --- POST Handlers & Router ---

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            if path == "/api/analyze":
                return self._handle_post_analyze(parsed)
            if path == "/api/reanalyze":
                return self._handle_post_reanalyze()
            if path == "/api/update-status":
                return self._handle_post_update_status()
            if path == "/api/rate":
                return self._handle_post_rate()
            if path == "/api/delete-analysis":
                return self._handle_post_delete_analysis()
            if path == "/api/export-xmp":
                return self._handle_post_export_xmp()

            if path.startswith("/api/post-process-advice/"):
                record_id = int(path.rstrip("/").split("/")[-1])
                return self._handle_post_post_process_advice(record_id, parsed.query)

            if path.startswith("/api/sns-crop/"):
                parts = path.strip("/").split("/")
                if len(parts) < 4:
                    raise ValueError("올바른 API 경로 형식이 아닙니다. (/api/sns-crop/<ratio_key>/<record_id>)")
                ratio_key = parts[2]
                record_id = int(parts[3])
                return self._handle_post_sns_crop(ratio_key, record_id, parsed.query)

            if path.startswith("/api/sns-caption/"):
                record_id = int(path.rstrip("/").split("/")[-1])
                return self._handle_post_sns_caption(record_id, parsed.query)

            if path.startswith("/api/sns-advice/"):
                record_id = int(path.rstrip("/").split("/")[-1])
                return self._handle_post_sns_advice(record_id, parsed.query)

            self.send_response(HTTPStatus.NOT_FOUND)
            self.end_headers()
        except (ValueError, KeyError, TypeError) as exc:
            status = HTTPStatus.NOT_FOUND if "찾을 수 없습니다" in str(exc) else HTTPStatus.BAD_REQUEST
            self._send_json_error(status, str(exc))
        except Exception as exc:
            import traceback
            print(f"[{path} ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            self._send_json_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def _handle_post_analyze(self, parsed: Any) -> None:
        content_type = self.headers.get("Content-Type", "")
        content_length_header = self.headers.get("Content-Length")
        if content_length_header is None:
            self.send_error(HTTPStatus.LENGTH_REQUIRED, "Content-Length header is required")
            return
        try:
            content_length = int(content_length_header)
        except ValueError:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length header")
            return
        if content_length < 0:
            self.send_error(HTTPStatus.BAD_REQUEST, "Invalid Content-Length header")
            return
        if content_length > MAX_UPLOAD_SIZE:
            self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Upload request is too large")
            return
        body = self.rfile.read(content_length)

        form_data = self._parse_multipart_form(body, content_type)
        file_bytes = form_data.get("image")
        filename = form_data.get("filename", "uploaded.webp")
        tier = form_data.get("tier", "standard")
        provider = form_data.get("provider", "gemini")
        category_param = form_data.get("category", "auto")

        if not file_bytes:
            raise ValueError("사진 파일이 전달되지 않았습니다.")

        prepared = prepare_photo_from_bytes(file_bytes, filename=filename)
        force_reanalyze = parse_qs(parsed.query).get("force", ["false"])[0].lower() in ("1", "true", "yes")
        active_spec = "ensemble" if (tier == "ensemble" or provider.lower() == "ensemble") else tier
        active_provider, model = resolve_task_model(active_spec, default_tier="standard")

        existing = None if force_reanalyze else find_existing_analysis(self.db_path, prepared.sha256, model=model)
        if existing is not None:
            record_id, analysis_dict = existing
            duplicate = True
        else:
            category_hint = category_param if category_param != "auto" else None
            analysis = analyze_photo(prepared, provider=active_provider, model=model, category_hint=category_hint)
            record_id = save_analysis(self.db_path, prepared, model, analysis)
            analysis_dict = analysis.model_dump(mode="json")
            duplicate = False

        self._send_json_ok({
            "success": True,
            "record_id": record_id,
            "analysis": analysis_dict,
            "duplicate": duplicate,
        })

    def _handle_post_reanalyze(self) -> None:
        data = self._read_json_body()
        record_id = int(data.get("id"))
        mode = str(data.get("mode", "cross_check_only"))
        tier = str(data.get("tier", "standard"))
        category_param = str(data.get("category", "auto"))

        row = get_analysis_row_by_id(self.db_path, record_id)
        if not row:
            raise ValueError(f"레코드 ID {record_id}를 찾을 수 없습니다.")

        prepared = _load_prepared_photo_for_record(self.db_path, row)
        category_hint = category_param if category_param != "auto" else None

        if mode == "cross_check_only":
            from app.services.openai_client import cross_check_with_openai
            from app.models.analysis import OpenAICrossCheck
            openai_res = cross_check_with_openai(
                photo=prepared,
                model=DEFAULT_OPENAI_MODEL,
                category_hint=category_hint,
            )
            if isinstance(openai_res, OpenAICrossCheck):
                opinion = CrossCheckOpinion(
                    model=DEFAULT_OPENAI_MODEL,
                    score=openai_res.score,
                    reason=openai_res.reason,
                    strengths=openai_res.strengths,
                    improvements=openai_res.improvements,
                    composition_critique=openai_res.composition_critique,
                    lighting_critique=openai_res.lighting_critique,
                )
            elif isinstance(openai_res, CrossCheckOpinion):
                opinion = openai_res
            else:
                raise RuntimeError(f"예상치 못한 OpenAI 응답 형태: {type(openai_res)}")

            updated_record = update_cross_check_opinion(self.db_path, record_id, opinion)
        else:
            active_provider, model = resolve_task_model(tier, default_tier="standard")
            new_analysis = analyze_photo(
                prepared,
                provider=active_provider,
                model=model,
                category_hint=category_hint,
            )
            updated_record = update_analysis(self.db_path, record_id, model, new_analysis)

        if not updated_record:
            raise RuntimeError("데이터베이스 갱신 후 분석 레코드를 불러오지 못했습니다.")

        self._send_json_ok({"success": True, "analysis": updated_record})

    def _handle_post_update_status(self) -> None:
        data = self._read_json_body()
        record_id = int(data.get("id"))
        new_status = str(data.get("status", "토너먼트 1위"))
        from app.exporters.excel_exporter import REVIEW_STATUSES
        if new_status not in REVIEW_STATUSES:
            self._send_json_error(HTTPStatus.BAD_REQUEST, f"유효하지 않은 검토 상태입니다: {new_status}")
            return
        if not update_review_status(self.db_path, record_id, new_status):
            self._send_json_error(HTTPStatus.NOT_FOUND, f"레코드 ID {record_id}를 찾을 수 없습니다.")
            return
        self._send_json_ok({"success": True})

    def _handle_post_rate(self) -> None:
        data = self._read_json_body()
        record_id = int(data.get("id"))
        raw_score = data.get("user_score")
        user_score = None
        if raw_score is not None and str(raw_score).strip() != "":
            user_score = max(0.0, min(10.0, round(float(raw_score), 1)))
        if not update_user_score(self.db_path, record_id, user_score):
            self._send_json_error(HTTPStatus.NOT_FOUND, f"레코드 ID {record_id}를 찾을 수 없습니다.")
            return
        self._send_json_ok({"success": True, "id": record_id, "user_score": user_score})

    def _handle_post_delete_analysis(self) -> None:
        data = self._read_json_body()
        record_ids = []
        if "ids" in data:
            record_ids = [int(i) for i in data["ids"]]
        elif "id" in data:
            record_ids = [int(data["id"])]
        if not record_ids:
            self._send_json_error(HTTPStatus.BAD_REQUEST, "삭제할 기록 ID가 지정되지 않았습니다.")
            return
        unique_record_ids = list(dict.fromkeys(record_ids))
        deleted_ids = delete_analyses(self.db_path, unique_record_ids)
        if len(deleted_ids) != len(unique_record_ids):
            missing_ids = sorted(set(unique_record_ids) - set(deleted_ids))
            self._send_json_error(HTTPStatus.NOT_FOUND, f"존재하지 않는 레코드 ID입니다: {missing_ids}")
            return
        self._send_json_ok({"success": True, "deleted_ids": deleted_ids, "count": len(deleted_ids)})

    def _handle_post_export_xmp(self) -> None:
        from app.services.xmp_service import write_xmp_sidecar
        exported_count = 0
        skipped_files: list[str] = []
        rows, tags_by_id = get_analyses_and_tags_for_export(self.db_path)

        for r in rows:
            aid = int(r["id"])
            fname = r["source_filename"]
            sha256 = r.get("sha256")
            analysis_data = json.loads(r["analysis_json"])
            target_file = _find_local_photo_path(fname, expected_sha256=sha256)
            if target_file is None and sha256:
                for mime_type in ("image/jpeg", "image/png", "image/webp"):
                    orig_path = get_original_photo_path(self.db_path, sha256, mime_type)
                    if orig_path.is_file():
                        target_file = orig_path
                        break
            if target_file is None:
                skipped_files.append(fname)
                continue
            xmp_file = target_file.with_suffix(".xmp")
            try:
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
            except Exception as sidecar_exc:
                skipped_files.append(f"{fname} ({sidecar_exc})")

        self._send_json_ok({"success": True, "count": exported_count, "skipped": skipped_files})

    def _handle_post_post_process_advice(self, record_id: int, query_string: str) -> None:
        query = parse_qs(query_string)
        force = query.get("force", ["false"])[0].lower() in ("true", "1", "yes")
        model_param = query.get("model", ["lite"])[0]
        provider_type, resolved_model = resolve_task_model(model_param, default_tier="lite")

        row = get_analysis_row_by_id(self.db_path, record_id)
        if not row:
            raise ValueError(f"레코드 ID {record_id}를 찾을 수 없습니다.")

        if not force and "lr_advice_json" in row.keys() and row["lr_advice_json"]:
            try:
                cached_advice = json.loads(row["lr_advice_json"])
                self._send_json_ok({
                    "success": True,
                    "advice": cached_advice,
                    "used_model": cached_advice.get("used_model", MODEL_PRESETS["lite"]),
                    "cached": True,
                })
                return
            except Exception:
                pass

        prepared = _load_prepared_photo_for_record(self.db_path, row)
        advice = suggest_lightroom_advice(prepared, model=resolved_model)
        advice_dict = advice.model_dump(mode="json")
        advice_dict["used_model"] = resolved_model
        advice_json = json.dumps(advice_dict, ensure_ascii=False)

        update_lr_advice(self.db_path, record_id, advice_json)

        self._send_json_ok({
            "success": True,
            "advice": advice_dict,
            "used_model": resolved_model,
            "cached": False,
        })

    def _handle_post_sns_crop(self, ratio_key: str, record_id: int, query_string: str) -> None:
        query = parse_qs(query_string)
        force = query.get("force", ["false"])[0].lower() in ("true", "1", "yes")
        model_param = query.get("model", ["lite"])[0]
        provider_type, resolved_model = resolve_task_model(model_param, default_tier="lite")

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
            self._send_json_ok({
                "success": True,
                "ratio_key": ratio_key,
                "crop_box": cached_advice.get(ratio_key),
                "advice": cached_advice,
                "used_model": cached_advice.get("crop_model", MODEL_PRESETS["lite"]),
                "cached": True,
            })
            return

        if ratio_key not in SNS_CROP_RATIO_CONFIGS and ratio_key not in ("all", "original"):
            raise ValueError(f"지원하지 않는 SNS 크롭 비율 키입니다: {ratio_key}")

        prepared = _load_prepared_photo_for_record(self.db_path, row)

        if force and ratio_key not in ("all", "original") and cached_advice:
            single_box = suggest_single_sns_crop(prepared, ratio_key=ratio_key, model=resolved_model)
            cached_advice[ratio_key] = single_box.model_dump(mode="json")
            crop_dict = cached_advice[ratio_key]
        else:
            crop_set = suggest_all_sns_crops(prepared, model=resolved_model)
            for key, box in crop_set.model_dump(mode="json").items():
                cached_advice[key] = box
            crop_dict = cached_advice.get(ratio_key) if ratio_key != "all" else cached_advice.get("instagram_crop_4_5", {})

        cached_advice["crop_model"] = resolved_model
        advice_json = json.dumps(cached_advice, ensure_ascii=False)

        update_sns_advice(self.db_path, record_id, advice_json)

        self._send_json_ok({
            "success": True,
            "ratio_key": ratio_key,
            "crop_box": crop_dict,
            "advice": cached_advice,
            "used_model": resolved_model,
            "cached": False,
        })

    def _handle_post_sns_caption(self, record_id: int, query_string: str) -> None:
        query = parse_qs(query_string)
        force = query.get("force", ["false"])[0].lower() in ("true", "1", "yes")
        model_param = query.get("model", ["lite"])[0]
        provider_type, resolved_model = resolve_task_model(model_param, default_tier="lite")

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
            self._send_json_ok({
                "success": True,
                "social_caption": cached_advice["social_caption"],
                "hashtags": cached_advice.get("hashtags", []),
                "advice": cached_advice,
                "used_model": cached_advice.get("caption_model", MODEL_PRESETS["lite"]),
                "cached": True,
            })
            return

        prepared = _load_prepared_photo_for_record(self.db_path, row)

        cap = suggest_sns_caption_and_tags(prepared, model=resolved_model)
        cached_advice["social_caption"] = cap.social_caption
        cached_advice["hashtags"] = cap.hashtags
        cached_advice["caption_model"] = resolved_model
        advice_json = json.dumps(cached_advice, ensure_ascii=False)

        update_sns_advice(self.db_path, record_id, advice_json)

        self._send_json_ok({
            "success": True,
            "social_caption": cap.social_caption,
            "hashtags": cap.hashtags,
            "advice": cached_advice,
            "used_model": resolved_model,
            "cached": False,
        })

    def _handle_post_sns_advice(self, record_id: int, query_string: str) -> None:
        query = parse_qs(query_string)
        force = query.get("force", ["false"])[0].lower() in ("true", "1", "yes")
        model_param = query.get("model", ["lite"])[0]
        provider_type, resolved_model = resolve_task_model(model_param, default_tier="lite")

        row = get_analysis_row_by_id(self.db_path, record_id)
        if not row:
            raise ValueError(f"레코드 ID {record_id}를 찾을 수 없습니다.")

        if not force and "sns_advice_json" in row.keys() and row["sns_advice_json"]:
            cached_advice = json.loads(row["sns_advice_json"])
            self._send_json_ok({"success": True, "advice": cached_advice, "cached": True})
            return

        prepared = _load_prepared_photo_for_record(self.db_path, row)

        advice = suggest_sns_advice(prepared, model=resolved_model)
        advice_dict = advice.model_dump(mode="json")
        advice_dict["crop_model"] = resolved_model
        advice_dict["caption_model"] = resolved_model
        advice_json = json.dumps(advice_dict, ensure_ascii=False)

        update_sns_advice(self.db_path, record_id, advice_json)

        self._send_json_ok({
            "success": True,
            "advice": advice_dict,
            "used_model": resolved_model,
            "cached": False,
        })

