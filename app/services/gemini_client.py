"""app.services.gemini_client - Google Gemini API client, retries, fallback, and inference functions."""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
import sys
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.config import (
    DEFAULT_MODEL,
    ENV_FILE_PATH,
    FALLBACK_MODEL,
    SNS_CROP_RATIO_CONFIGS,
)


def _get_env_file_path() -> Path:
    import sys
    mod = sys.modules.get("photo_analyzer")
    if mod is not None and hasattr(mod, "ENV_FILE_PATH"):
        return getattr(mod, "ENV_FILE_PATH")
    return ENV_FILE_PATH

from app.db.connection import get_db_connection
from app.models.analysis import CrossCheckOpinion, FastPhotoAnalysis, PhotoAnalysis
from app.models.crop import (
    CropBox,
    CropSet,
    SNSAdvice,
    SNSCaptionAndTags,
)
from app.models.lightroom import LightroomAdvice
from app.prompts import (
    build_all_sns_crops_prompt,
    build_caption_and_tags_prompt,
    build_fast_grader_prompt,
    build_fast_grader_user_prompt,
    build_grader_prompt,
    build_grader_user_prompt,
    build_lightroom_prompt,
    build_single_crop_prompt,
    build_sns_advice_prompt,
    get_fast_grader_system_prompt,
    get_grader_system_prompt,
)
from app.services.image_processor import PreparedPhoto

_CLIENT_LOCK = threading.Lock()
_CLIENT_CACHE: dict[str, Any] = {}
MAX_CONCURRENT_GEMINI_CALLS = 6
_GEMINI_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_GEMINI_CALLS)
_USAGE_LOG_DB: Path | None = None
_THREAD_LOCAL = threading.local()

# Prompt Cache Coordination: prevents cold-cache stampede on concurrent same-photo calls (e.g. sample_count=3)
_GEMINI_COORD_LOCK = threading.Lock()
_GEMINI_PHOTO_LOCKS: dict[str, threading.Lock] = {}
_GEMINI_WARMED_PHOTOS: dict[str, float] = {}
GEMINI_CACHE_WARM_TTL_SECONDS = 300.0


def _get_photo_cache_lock(coord_key: str) -> threading.Lock:
    with _GEMINI_COORD_LOCK:
        lock = _GEMINI_PHOTO_LOCKS.get(coord_key)
        if lock is None:
            lock = threading.Lock()
            _GEMINI_PHOTO_LOCKS[coord_key] = lock
        return lock


def get_last_used_gemini_model() -> str | None:
    """Return the actual Gemini model used in the current thread's most recent call."""
    return getattr(_THREAD_LOCAL, "last_used_model", None)


# Explicit Context Cache Registry: (api_key, model, sha256_of_instruction) -> (cache_name, expire_time_timestamp)
_EXPLICIT_CACHE_LOCK = threading.Lock()
_EXPLICIT_CACHE_STORE: dict[tuple[str, str, str], tuple[str, float]] = {}
EXPLICIT_CACHE_TTL_SECONDS = 1800.0  # 30 minutes


def clear_explicit_gemini_caches() -> None:
    """Clear in-memory registry of explicit cached contents."""
    with _EXPLICIT_CACHE_LOCK:
        _EXPLICIT_CACHE_STORE.clear()


def _clean_schema_for_gemini(schema: Any) -> Any:
    """Recursively strip schema keys unsupported by Gemini generateContent (e.g. additionalProperties)."""
    if hasattr(schema, "model_json_schema"):
        schema = schema.model_json_schema()
    if isinstance(schema, dict):
        return {
            k: _clean_schema_for_gemini(v)
            for k, v in schema.items()
            if k not in ("additionalProperties", "additional_properties")
        }
    elif isinstance(schema, list):
        return [_clean_schema_for_gemini(item) for item in schema]
    return schema


def _convert_input_to_contents(input_payload: list[dict[str, Any]]) -> list[Any]:
    """Convert interactions input_payload to generate_content contents."""
    contents: list[Any] = []
    for item in input_payload:
        itype = item.get("type")
        if itype == "text":
            text_val = item.get("text", "")
            if text_val:
                contents.append(text_val)
        elif itype == "image":
            data = item.get("data")
            mime_type = item.get("mime_type", "image/jpeg")
            if isinstance(data, str):
                raw_bytes = base64.b64decode(data)
            elif isinstance(data, (bytes, bytearray)):
                raw_bytes = bytes(data)
            else:
                raw_bytes = b""
            contents.append(types.Part.from_bytes(data=raw_bytes, mime_type=mime_type))
        else:
            contents.append(item)
    return contents


def _get_or_create_cached_content(
    client: Any,
    model: str,
    system_instruction: str,
    api_key: str | None = None,
) -> str | None:
    """Return or lazily create a cached content resource name for model & system_instruction."""
    is_mock = type(client).__module__.startswith("unittest.mock") or type(
        getattr(client, "caches", None)
    ).__module__.startswith("unittest.mock")
    if is_mock and not getattr(client, "_force_explicit_cache", False):
        return None
    if not hasattr(client, "caches"):
        return None

    instr_hash = hashlib.sha256(system_instruction.encode("utf-8")).hexdigest()
    resolved_key = (api_key or getattr(client, "_api_key", None) or "").strip()
    cache_key = (resolved_key, model, instr_hash)
    now = time.monotonic()

    with _EXPLICIT_CACHE_LOCK:
        entry = _EXPLICIT_CACHE_STORE.get(cache_key)
        if entry:
            c_name, exp_at = entry
            if exp_at > now + 60.0:
                return c_name

    with _EXPLICIT_CACHE_LOCK:
        entry = _EXPLICIT_CACHE_STORE.get(cache_key)
        if entry:
            c_name, exp_at = entry
            if exp_at > now + 60.0:
                return c_name

        try:
            cache = client.caches.create(
                model=model,
                config=types.CreateCachedContentConfig(
                    system_instruction=system_instruction,
                    ttl=f"{int(EXPLICIT_CACHE_TTL_SECONDS)}s",
                ),
            )
            raw_name = getattr(cache, "name", None)
            if not isinstance(raw_name, str):
                return None
            _EXPLICIT_CACHE_STORE[cache_key] = (raw_name, now + EXPLICIT_CACHE_TTL_SECONDS)
            print(
                f"[Gemini Cache] 명시적 컨텍스트 캐시 생성 완료: {raw_name} (모델: {model}, TTL: {int(EXPLICIT_CACHE_TTL_SECONDS)}s)",
                file=sys.stderr,
            )
            return raw_name
        except Exception as exc:
            print(f"[Gemini Cache] 명시적 캐시 생성 생략 ({model}): {exc}", file=sys.stderr)
            return None


def clear_last_used_gemini_model() -> None:
    """Reset the thread-local last used Gemini model before starting an analysis."""
    _THREAD_LOCAL.last_used_model = None


def _get_client(api_key: str) -> genai.Client:
    """Return a process-wide genai client (one per API key) instead of rebuilding per call."""
    with _CLIENT_LOCK:
        client = _CLIENT_CACHE.get(api_key)
        if client is None:
            client = genai.Client(api_key=api_key)
            _CLIENT_CACHE[api_key] = client
        return client


def _dispatch_call_gemini_interaction(*args: Any, **kwargs: Any) -> str:
    mod = sys.modules.get("photo_analyzer")
    if mod is not None and hasattr(mod, "_call_gemini_interaction"):
        fn = getattr(mod, "_call_gemini_interaction")
        if fn is not _call_gemini_interaction:
            return fn(*args, **kwargs)
    return _call_gemini_interaction(*args, **kwargs)


def _dispatch_get_client(api_key: str) -> Any:
    mod = sys.modules.get("photo_analyzer")
    if mod is not None and hasattr(mod, "_get_client"):
        fn = getattr(mod, "_get_client")
        if fn is not _get_client:
            return fn(api_key)
    return _get_client(api_key)


def set_usage_log_db(db_path: str | Path | None) -> None:
    """Enable API usage logging into the given SQLite DB (None disables it)."""
    global _USAGE_LOG_DB
    _USAGE_LOG_DB = Path(db_path) if db_path else None


def _log_api_usage(
    task: str,
    requested_model: str,
    used_model: str,
    attempts: int,
    duration_ms: int,
    input_tokens: int | None,
    output_tokens: int | None,
    success: bool,
    error: str | None,
    cached_tokens: int | None = None,
) -> None:
    """Best-effort usage record; logging failures must never break an analysis."""
    db_path = _USAGE_LOG_DB
    if db_path is None:
        try:
            from app.config import DEFAULT_DB_PATH
            db_path = DEFAULT_DB_PATH if DEFAULT_DB_PATH.exists() else None
        except Exception:
            db_path = None
    if db_path is None:
        return
    try:
        with closing(get_db_connection(db_path, timeout=10.0)) as connection, connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS api_usage_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    task TEXT NOT NULL,
                    requested_model TEXT NOT NULL,
                    used_model TEXT NOT NULL,
                    fallback INTEGER NOT NULL,
                    attempts INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    cached_tokens INTEGER,
                    success INTEGER NOT NULL,
                    error TEXT
                )"""
            )
            try:
                connection.execute("ALTER TABLE api_usage_log ADD COLUMN cached_tokens INTEGER")
            except Exception:
                pass
            try:
                connection.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_created ON api_usage_log(created_at)")
            except Exception:
                pass

            def _clean_int(val: Any) -> int | None:
                if val is None or isinstance(val, bool):
                    return None
                if isinstance(val, (int, float)):
                    return int(val)
                try:
                    return int(val)
                except (ValueError, TypeError):
                    return None

            connection.execute(
                """INSERT INTO api_usage_log (
                    created_at, task, requested_model, used_model, fallback, attempts,
                    duration_ms, input_tokens, output_tokens, cached_tokens, success, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    task,
                    requested_model,
                    used_model,
                    1 if used_model != requested_model else 0,
                    attempts,
                    duration_ms,
                    _clean_int(input_tokens),
                    _clean_int(output_tokens),
                    _clean_int(cached_tokens),
                    1 if success else 0,
                    (error or "")[:500] or None,
                ),
            )
    except Exception as log_exc:
        print(f"[api_usage_log] 기록 실패: {log_exc}", file=sys.stderr)


def get_usage_stats(
    db_path: str | Path,
    period: str = "all",
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    """Aggregate api_usage_log by task and by model for the dashboard.

    Args:
        db_path: Path to SQLite database.
        period: Time window filter ('all', 'today', 'yesterday', '24h', '7d', '30d', 'custom').
        date_from: Start date in YYYY-MM-DD (inclusive, local timezone).
        date_to: End date in YYYY-MM-DD (inclusive, local timezone).
    """
    path = Path(db_path)
    period_norm = str(period).strip().lower() if period else "all"
    valid_periods = ("today", "yesterday", "24h", "7d", "30d", "all", "custom")
    if period_norm not in valid_periods:
        period_norm = "all"

    d_from_str = str(date_from).strip() if date_from else None
    d_to_str = str(date_to).strip() if date_to else None
    if d_from_str or d_to_str:
        if period_norm == "all":
            period_norm = "custom"

    empty: dict[str, Any] = {
        "period": period_norm,
        "date_from": d_from_str,
        "date_to": d_to_str,
        "cutoff_at": None,
        "cutoff_from_iso": None,
        "cutoff_to_iso": None,
        "total_calls": 0,
        "total_cached_tokens": 0,
        "cache_hit_rate": 0.0,
        "by_task": [],
        "by_model": [],
        "recent": [],
    }
    if not path.is_file():
        return empty
    with closing(get_db_connection(path)) as connection:
        connection.row_factory = sqlite3.Row
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='api_usage_log'"
        ).fetchone()
        if not exists:
            return empty

        try:
            connection.execute("CREATE INDEX IF NOT EXISTS idx_api_usage_created ON api_usage_log(created_at)")
        except Exception:
            pass

        now_utc = datetime.now(timezone.utc)
        now_local = datetime.now().astimezone()
        local_tz = now_local.tzinfo
        today_local = now_local.date()

        from_iso: str | None = None
        to_iso: str | None = None

        if d_from_str or d_to_str:
            if d_from_str:
                try:
                    df = datetime.strptime(d_from_str[:10], "%Y-%m-%d").date()
                    dt_start = datetime.combine(df, datetime.min.time()).replace(tzinfo=local_tz)
                    from_iso = dt_start.astimezone(timezone.utc).isoformat(timespec="seconds")
                except Exception:
                    pass
            if d_to_str:
                try:
                    dt = datetime.strptime(d_to_str[:10], "%Y-%m-%d").date()
                    dt_end = datetime.combine(dt, datetime.max.time().replace(microsecond=0)).replace(tzinfo=local_tz)
                    to_iso = dt_end.astimezone(timezone.utc).isoformat(timespec="seconds")
                except Exception:
                    pass
        elif period_norm == "today":
            dt_start = datetime.combine(today_local, datetime.min.time()).replace(tzinfo=local_tz)
            from_iso = dt_start.astimezone(timezone.utc).isoformat(timespec="seconds")
        elif period_norm == "yesterday":
            yest_date = today_local - timedelta(days=1)
            dt_start = datetime.combine(yest_date, datetime.min.time()).replace(tzinfo=local_tz)
            dt_end = datetime.combine(yest_date, datetime.max.time().replace(microsecond=0)).replace(tzinfo=local_tz)
            from_iso = dt_start.astimezone(timezone.utc).isoformat(timespec="seconds")
            to_iso = dt_end.astimezone(timezone.utc).isoformat(timespec="seconds")
        elif period_norm == "24h":
            from_iso = (now_utc - timedelta(hours=24)).isoformat(timespec="seconds")
        elif period_norm == "7d":
            from_iso = (now_utc - timedelta(days=7)).isoformat(timespec="seconds")
        elif period_norm == "30d":
            from_iso = (now_utc - timedelta(days=30)).isoformat(timespec="seconds")

        where_parts: list[str] = []
        params: list[Any] = []
        if from_iso:
            where_parts.append("created_at >= ?")
            params.append(from_iso)
        if to_iso:
            where_parts.append("created_at <= ?")
            params.append(to_iso)

        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""

        by_task = [
            dict(r)
            for r in connection.execute(
                f"""SELECT task,
                          COUNT(*) AS calls,
                          SUM(success) AS successes,
                          SUM(fallback) AS fallbacks,
                          SUM(attempts - 1) AS retries,
                          COALESCE(SUM(input_tokens), 0) AS input_tokens,
                          COALESCE(SUM(output_tokens), 0) AS output_tokens,
                          COALESCE(SUM(cached_tokens), 0) AS cached_tokens,
                          CAST(AVG(duration_ms) AS INTEGER) AS avg_ms
                   FROM api_usage_log {where_clause} GROUP BY task ORDER BY calls DESC""",
                params,
            ).fetchall()
        ]
        by_model = [
            dict(r)
            for r in connection.execute(
                f"""SELECT used_model,
                          COUNT(*) AS calls,
                          SUM(success) AS successes,
                          SUM(fallback) AS fallbacks,
                          SUM(attempts - 1) AS retries,
                          COALESCE(SUM(input_tokens), 0) AS input_tokens,
                          COALESCE(SUM(output_tokens), 0) AS output_tokens,
                          COALESCE(SUM(cached_tokens), 0) AS cached_tokens,
                          CAST(AVG(duration_ms) AS INTEGER) AS avg_ms
                   FROM api_usage_log {where_clause} GROUP BY used_model ORDER BY calls DESC""",
                params,
            ).fetchall()
        ]
        recent = [
            dict(r)
            for r in connection.execute(
                f"""SELECT created_at, task, requested_model, used_model, fallback, attempts, duration_ms,
                          input_tokens, output_tokens, cached_tokens, success, error
                   FROM api_usage_log {where_clause} ORDER BY id DESC LIMIT 30""",
                params,
            ).fetchall()
        ]
        total_in = sum(t["input_tokens"] for t in by_task)
        total_cached = sum(t["cached_tokens"] for t in by_task)
        cache_hit_rate = round((total_cached / total_in * 100), 1) if total_in > 0 else 0.0
        return {
            "period": period_norm,
            "date_from": d_from_str,
            "date_to": d_to_str,
            "cutoff_at": from_iso,
            "cutoff_from_iso": from_iso,
            "cutoff_to_iso": to_iso,
            "total_calls": sum(t["calls"] for t in by_task),
            "total_cached_tokens": total_cached,
            "cache_hit_rate": cache_hit_rate,
            "by_task": by_task,
            "by_model": by_model,
            "recent": recent,
        }


def _extract_usage(interaction: Any) -> tuple[int | None, int | None, int | None]:
    usage = getattr(interaction, "usage", None)
    if usage is None:
        usage = getattr(interaction, "usage_metadata", None)
    if usage is None:
        return None, None, None
    raw_cached = getattr(usage, "total_cached_tokens", None)
    if raw_cached is None:
        raw_cached = getattr(usage, "cached_content_token_count", None)
    cached_tok: int | None = None
    if isinstance(raw_cached, int):
        cached_tok = raw_cached
    elif raw_cached is not None:
        try:
            cached_tok = int(raw_cached)
        except (ValueError, TypeError):
            cached_tok = None
    raw_in = getattr(usage, "total_input_tokens", None)
    if raw_in is None:
        raw_in = getattr(usage, "prompt_token_count", None)
    raw_out = getattr(usage, "total_output_tokens", None)
    if raw_out is None:
        raw_out = getattr(usage, "candidates_token_count", None)
    return (
        raw_in,
        raw_out,
        cached_tok,
    )


def _format_gemini_error(model: str, exc: Exception) -> RuntimeError:
    err_msg = str(exc)
    if "429" in err_msg or "ResourceExhausted" in err_msg or "quota" in err_msg.lower():
        return RuntimeError(
            f"[{model}] 호출 실패: 프로젝트의 API 할당량(Quota/Rate Limit)을 초과했습니다. "
            f"잠시 후 다시 시도하시거나 '--tier lite'(gemini-3.5-flash-lite)를 사용해 보세요. (상세: {err_msg})"
        )
    elif "404" in err_msg or "not found" in err_msg.lower() or "no longer available" in err_msg.lower():
        return RuntimeError(
            f"[{model}] 호출 실패: 해당 모델은 현재 프로젝트/API 키에서 지원되지 않거나 사용이 중단되었습니다. "
            f"'--tier lite'(gemini-3.5-flash-lite) 또는 standard를 권장합니다. (상세: {err_msg})"
        )
    elif "503" in err_msg or "high demand" in err_msg.lower() or "unavailable" in err_msg.lower():
        return RuntimeError(
            f"[{model}] 호출 실패: Google Gemini API 서버가 일시적 트래픽 급증(503 과부하) 상태입니다. "
            f"잠시 후 다시 시도하시거나 standard/lite 모드를 사용해 보세요. (상세: {err_msg})"
        )
    return RuntimeError(f"[{model}] Gemini API 호출 중 오류 발생: {err_msg}")


def _call_gemini_interaction(
    client: genai.Client,
    model: str,
    input_payload: list[dict[str, Any]],
    schema: Any,
    task_desc: str,
    system_instruction: str | None = None,
    api_key: str | None = None,
) -> str:
    """Execute Gemini request via explicit cached generate_content or interactions.create with fallback."""
    active_model = model
    max_retries = 3
    backoff = 2.0
    started = time.monotonic()
    attempts = 0

    def _elapsed_ms() -> int:
        return int((time.monotonic() - started) * 1000)

    for attempt in range(1, max_retries + 1):
        attempts += 1
        try:
            with _GEMINI_SEMAPHORE:
                cache_name = None
                if (
                    system_instruction
                    and hasattr(client, "caches")
                    and hasattr(client, "models")
                ):
                    cache_name = _get_or_create_cached_content(
                        client=client,
                        model=active_model,
                        system_instruction=system_instruction,
                        api_key=api_key,
                    )

                if cache_name and hasattr(client, "models"):
                    contents = _convert_input_to_contents(input_payload)
                    cleaned_schema = _clean_schema_for_gemini(schema)
                    config = types.GenerateContentConfig(
                        cached_content=cache_name,
                        response_mime_type="application/json",
                        response_schema=cleaned_schema,
                    )
                    resp = client.models.generate_content(
                        model=active_model,
                        contents=contents,
                        config=config,
                    )
                    output_text = resp.text
                    in_tok, out_tok, cached_tok = _extract_usage(resp)
                else:
                    kwargs: dict[str, Any] = {
                        "model": active_model,
                        "input": input_payload,
                        "response_format": {
                            "type": "text",
                            "mime_type": "application/json",
                            "schema": schema,
                        },
                        "store": False,
                    }
                    if system_instruction:
                        kwargs["system_instruction"] = system_instruction
                    interaction = client.interactions.create(**kwargs)
                    output_text = interaction.output_text
                    in_tok, out_tok, cached_tok = _extract_usage(interaction)

            if not output_text:
                raise RuntimeError(f"Gemini가 {task_desc} JSON 결과를 반환하지 않았습니다.")
            _THREAD_LOCAL.last_used_model = active_model
            _log_api_usage(
                task_desc,
                model,
                active_model,
                attempts,
                _elapsed_ms(),
                in_tok,
                out_tok,
                True,
                None,
                cached_tokens=cached_tok,
            )
            if isinstance(cached_tok, int) and isinstance(in_tok, int) and in_tok > 0 and cached_tok > 0:
                cache_pct = (cached_tok / in_tok) * 100
                print(
                    f"[Gemini Cache] {task_desc} ({active_model}) | 총 입력: {in_tok:,} 토큰 | 캐시 히트: {cached_tok:,} 토큰 ({cache_pct:.1f}%)",
                    file=sys.stderr,
                )
            return output_text
        except Exception as exc:
            err_msg = str(exc)
            if "cached_content" in err_msg.lower() or "cachedcontent" in err_msg.lower():
                clear_explicit_gemini_caches()
            is_model_unavailable = any(
                marker in err_msg
                for marker in ("404", "NOT_FOUND", "not found", "model not found", "does not exist")
            )
            is_transient = any(
                code in err_msg
                for code in ("503", "429", "high demand", "ResourceExhausted", "UNAVAILABLE", "service_unavailable")
            )
            if (is_model_unavailable or is_transient) and active_model != FALLBACK_MODEL:
                print(
                    f"[{active_model}] 지원되지 않거나 일시적으로 사용할 수 없는 모델 감지 -> "
                    f"대체 안정 모델({FALLBACK_MODEL})로 자동 전환합니다...",
                    file=sys.stderr,
                )
                active_model = FALLBACK_MODEL
                time.sleep(1.0)
                continue
            if is_transient and attempt < max_retries:
                print(
                    f"[재시도 {attempt}/{max_retries}] API 일시적 지연 ({active_model}). {backoff:.1f}초 후 재시도합니다...",
                    file=sys.stderr,
                )
                time.sleep(backoff)
                backoff *= 1.5
            else:
                _log_api_usage(task_desc, model, active_model, attempts, _elapsed_ms(), None, None, False, err_msg)
                raise _format_gemini_error(active_model, exc) from exc
    _log_api_usage(task_desc, model, active_model, attempts, _elapsed_ms(), None, None, False, "retries exhausted")
    raise RuntimeError(f"{task_desc} 처리 중 알 수 없는 오류로 완료하지 못했습니다.")


def analyze_with_gemini(
    photo: PreparedPhoto,
    model: str = DEFAULT_MODEL,
    category_hint: str | None = None,
    analysis_mode: str = "full",
) -> PhotoAnalysis:
    """Analyze figure photo and return strictly validated PhotoAnalysis."""
    load_dotenv(dotenv_path=_get_env_file_path(), override=False)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY를 .env 파일 또는 환경변수에 설정해 주세요.")

    is_fast = (analysis_mode or "full").strip().lower() == "fast"
    if is_fast:
        system_instruction = get_fast_grader_system_prompt()
        user_prompt_text = build_fast_grader_user_prompt(photo, category_hint=category_hint)
        target_schema = FastPhotoAnalysis.model_json_schema()
        task_label = "사진 경량 분석"
    else:
        system_instruction = get_grader_system_prompt()
        user_prompt_text = build_grader_user_prompt(photo, category_hint=category_hint)
        target_schema = PhotoAnalysis.model_json_schema()
        task_label = "사진 분석"

    client = _dispatch_get_client(api_key)
    input_payload = [
        {"type": "text", "text": user_prompt_text},
        {
            "type": "image",
            "data": base64.b64encode(photo.upload_bytes).decode("ascii"),
            "mime_type": photo.upload_mime_type,
        },
    ]
    photo_sha = getattr(photo, "sha256", None)
    coord_key = f"{model}:{photo_sha}:{analysis_mode}" if photo_sha else None

    if coord_key:
        photo_lock = _get_photo_cache_lock(coord_key)
        with photo_lock:
            output_text = _dispatch_call_gemini_interaction(
                client=client,
                model=model,
                input_payload=input_payload,
                schema=target_schema,
                task_desc=task_label,
                system_instruction=system_instruction,
                api_key=api_key,
            )
            with _GEMINI_COORD_LOCK:
                _GEMINI_WARMED_PHOTOS[coord_key] = time.monotonic() + GEMINI_CACHE_WARM_TTL_SECONDS
    else:
        output_text = _dispatch_call_gemini_interaction(
            client=client,
            model=model,
            input_payload=input_payload,
            schema=target_schema,
            task_desc=task_label,
            system_instruction=system_instruction,
            api_key=api_key,
        )
    if is_fast:
        return FastPhotoAnalysis.from_llm_json(output_text).to_photo_analysis()
    return PhotoAnalysis.from_llm_json(output_text)


def cross_check_with_gemini(
    photo: PreparedPhoto,
    model: str = DEFAULT_MODEL,
    category_hint: str | None = None,
    api_key: str | None = None,
    analysis_mode: str = "fast",
) -> CrossCheckOpinion:
    """Generate a second-opinion critique from Gemini (Fast mode by default)."""
    load_dotenv(dotenv_path=_get_env_file_path(), override=False)
    resolved_key = (api_key or os.environ.get("GEMINI_API_KEY") or "").strip()
    if not resolved_key:
        raise RuntimeError("GEMINI_API_KEY를 .env 파일 또는 환경변수에 설정해 주세요.")

    is_fast = (analysis_mode or "fast").strip().lower() == "fast"
    if is_fast:
        system_instruction = get_fast_grader_system_prompt()
        user_prompt_text = build_fast_grader_user_prompt(photo, category_hint=category_hint)
        target_schema = FastPhotoAnalysis.model_json_schema()
        task_label = "Gemini 크로스 체크(경량)"
    else:
        system_instruction = get_grader_system_prompt()
        user_prompt_text = build_grader_user_prompt(photo, category_hint=category_hint)
        target_schema = PhotoAnalysis.model_json_schema()
        task_label = "Gemini 크로스 체크"

    client = _dispatch_get_client(resolved_key)
    input_payload = [
        {"type": "text", "text": user_prompt_text},
        {
            "type": "image",
            "data": base64.b64encode(photo.upload_bytes).decode("ascii"),
            "mime_type": photo.upload_mime_type,
        },
    ]
    photo_sha = getattr(photo, "sha256", None)
    coord_key = f"{model}:{photo_sha}:{analysis_mode}" if photo_sha else None

    if coord_key:
        photo_lock = _get_photo_cache_lock(coord_key)
        with photo_lock:
            output_text = _dispatch_call_gemini_interaction(
                client=client,
                model=model,
                input_payload=input_payload,
                schema=target_schema,
                task_desc=task_label,
                system_instruction=system_instruction,
                api_key=resolved_key,
            )
            with _GEMINI_COORD_LOCK:
                _GEMINI_WARMED_PHOTOS[coord_key] = time.monotonic() + GEMINI_CACHE_WARM_TTL_SECONDS
    else:
        output_text = _dispatch_call_gemini_interaction(
            client=client,
            model=model,
            input_payload=input_payload,
            schema=target_schema,
            task_desc=task_label,
            system_instruction=system_instruction,
            api_key=resolved_key,
        )
    if is_fast:
        fast_analysis = FastPhotoAnalysis.from_llm_json(output_text)
        return fast_analysis.to_cross_check_opinion(model_name=model)
    full_analysis = PhotoAnalysis.from_llm_json(output_text)
    return CrossCheckOpinion(
        model=model,
        score=full_analysis.final_score,
        reason=full_analysis.final_reason,
        strengths=full_analysis.strengths,
        improvements=full_analysis.improvements,
        composition_critique=full_analysis.composition_notes,
        lighting_critique=full_analysis.lighting_notes,
        focus_status=full_analysis.focus_status,
    )


def generate_lightroom_advice(photo: PreparedPhoto, model: str = DEFAULT_MODEL) -> LightroomAdvice:
    """Generate on-demand Adobe Lightroom post-processing slider recommendations."""
    load_dotenv(dotenv_path=_get_env_file_path(), override=False)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY를 .env 파일 또는 환경변수에 설정해 주세요.")

    prompt = build_lightroom_prompt()
    client = _dispatch_get_client(api_key)
    input_payload = [
        {"type": "text", "text": prompt},
        {
            "type": "image",
            "data": base64.b64encode(photo.upload_bytes).decode("ascii"),
            "mime_type": photo.upload_mime_type,
        },
    ]
    output_text = _dispatch_call_gemini_interaction(
        client=client,
        model=model,
        input_payload=input_payload,
        schema=LightroomAdvice.model_json_schema(),
        task_desc="Lightroom 보정 제안",
    )
    return LightroomAdvice.model_validate_json(output_text)


def generate_sns_advice(photo: PreparedPhoto, model: str = DEFAULT_MODEL) -> SNSAdvice:
    """Generate on-demand SNS platform crop coordinates and social captions for Instagram & X."""
    load_dotenv(dotenv_path=_get_env_file_path(), override=False)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY를 .env 파일 또는 환경변수에 설정해 주세요.")

    prompt = build_sns_advice_prompt(photo)
    client = _dispatch_get_client(api_key)
    input_payload = [
        {"type": "text", "text": prompt},
        {
            "type": "image",
            "data": base64.b64encode(photo.upload_bytes).decode("ascii"),
            "mime_type": photo.upload_mime_type,
        },
    ]
    output_text = _dispatch_call_gemini_interaction(
        client=client,
        model=model,
        input_payload=input_payload,
        schema=SNSAdvice.model_json_schema(),
        task_desc="SNS 크롭 및 캡션 제안",
    )
    return SNSAdvice.model_validate_json(output_text)


def generate_single_sns_crop(photo: PreparedPhoto, ratio_key: str, model: str = DEFAULT_MODEL) -> CropBox:
    """Generate a single focused SNS crop recommendation for a specific aspect ratio."""
    if ratio_key not in SNS_CROP_RATIO_CONFIGS:
        raise ValueError(f"지원하지 않는 SNS 크롭 비율 키입니다: {ratio_key}")

    cfg = SNS_CROP_RATIO_CONFIGS[ratio_key]
    load_dotenv(dotenv_path=_get_env_file_path(), override=False)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY를 .env 파일 또는 환경변수에 설정해 주세요.")

    prompt = build_single_crop_prompt(photo, ratio_key, cfg)
    client = _dispatch_get_client(api_key)
    input_payload = [
        {"type": "text", "text": prompt},
        {
            "type": "image",
            "data": base64.b64encode(photo.upload_bytes).decode("ascii"),
            "mime_type": photo.upload_mime_type,
        },
    ]
    output_text = _dispatch_call_gemini_interaction(
        client=client,
        model=model,
        input_payload=input_payload,
        schema=CropBox.model_json_schema(),
        task_desc=f"{cfg['name']} 크롭 제안",
    )
    return CropBox.model_validate_json(output_text)


def generate_all_sns_crops(photo: PreparedPhoto, model: str = DEFAULT_MODEL) -> CropSet:
    """Generate the 4 SNS crop boxes and AI best ratio recommendation in ONE call."""
    load_dotenv(dotenv_path=_get_env_file_path(), override=False)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY를 .env 파일 또는 환경변수에 설정해 주세요.")

    ratio_lines = []
    for key, cfg in SNS_CROP_RATIO_CONFIGS.items():
        ratio_lines.append(
            f"- {key}: {cfg['name']} ({cfg['aspect']}, 목표 픽셀 종횡비 {cfg['w'] / cfg['h']:.4f})\n"
            f"  가이드: {cfg['guide']}\n"
            f"  ratio_label: '{cfg['name']} ({cfg['aspect']})'"
        )
    ratio_block = "\n".join(ratio_lines)

    prompt = build_all_sns_crops_prompt(photo, ratio_block)
    client = _dispatch_get_client(api_key)
    input_payload = [
        {"type": "text", "text": prompt},
        {
            "type": "image",
            "data": base64.b64encode(photo.upload_bytes).decode("ascii"),
            "mime_type": photo.upload_mime_type,
        },
    ]
    output_text = _dispatch_call_gemini_interaction(
        client=client,
        model=model,
        input_payload=input_payload,
        schema=CropSet.model_json_schema(),
        task_desc="SNS 크롭 4종 일괄 제안",
    )
    return CropSet.model_validate_json(output_text)


def generate_sns_caption_and_tags(photo: PreparedPhoto, model: str = DEFAULT_MODEL) -> SNSCaptionAndTags:
    """Generate social caption and hashtags on-demand without re-analyzing crops."""
    load_dotenv(dotenv_path=_get_env_file_path(), override=False)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY를 .env 파일 또는 환경변수에 설정해 주세요.")

    prompt = build_caption_and_tags_prompt(photo)
    client = _dispatch_get_client(api_key)
    input_payload = [
        {"type": "text", "text": prompt},
        {
            "type": "image",
            "data": base64.b64encode(photo.upload_bytes).decode("ascii"),
            "mime_type": photo.upload_mime_type,
        },
    ]
    output_text = _dispatch_call_gemini_interaction(
        client=client,
        model=model,
        input_payload=input_payload,
        schema=SNSCaptionAndTags.model_json_schema(),
        task_desc="SNS 캡션 및 해시태그",
    )
    return SNSCaptionAndTags.model_validate_json(output_text)
