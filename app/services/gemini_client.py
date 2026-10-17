"""app.services.gemini_client - Google Gemini API client, retries, fallback, and inference functions."""

from __future__ import annotations

import base64
import os
import sqlite3
import sys
import threading
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai

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
from app.models.analysis import PhotoAnalysis
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
    build_grader_prompt,
    build_lightroom_prompt,
    build_single_crop_prompt,
    build_sns_advice_prompt,
)
from app.services.image_processor import PreparedPhoto

_CLIENT_LOCK = threading.Lock()
_CLIENT_CACHE: dict[str, Any] = {}
MAX_CONCURRENT_GEMINI_CALLS = 3
_GEMINI_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_GEMINI_CALLS)
_USAGE_LOG_DB: Path | None = None
_THREAD_LOCAL = threading.local()


def get_last_used_gemini_model() -> str | None:
    """Return the actual Gemini model used in the current thread's most recent call."""
    return getattr(_THREAD_LOCAL, "last_used_model", None)


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
) -> None:
    """Best-effort usage record; logging failures must never break an analysis."""
    db_path = _USAGE_LOG_DB
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
                    success INTEGER NOT NULL,
                    error TEXT
                )"""
            )
            connection.execute(
                """INSERT INTO api_usage_log (
                    created_at, task, requested_model, used_model, fallback, attempts,
                    duration_ms, input_tokens, output_tokens, success, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    task,
                    requested_model,
                    used_model,
                    1 if used_model != requested_model else 0,
                    attempts,
                    duration_ms,
                    input_tokens,
                    output_tokens,
                    1 if success else 0,
                    (error or "")[:500] or None,
                ),
            )
    except Exception as log_exc:
        print(f"[api_usage_log] 기록 실패: {log_exc}", file=sys.stderr)


def get_usage_stats(db_path: str | Path) -> dict[str, Any]:
    """Aggregate api_usage_log by task and by model for the dashboard."""
    path = Path(db_path)
    empty: dict[str, Any] = {"total_calls": 0, "by_task": [], "by_model": [], "recent": []}
    if not path.is_file():
        return empty
    with closing(get_db_connection(path)) as connection:
        connection.row_factory = sqlite3.Row
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='api_usage_log'"
        ).fetchone()
        if not exists:
            return empty
        by_task = [
            dict(r)
            for r in connection.execute(
                """SELECT task,
                          COUNT(*) AS calls,
                          SUM(success) AS successes,
                          SUM(fallback) AS fallbacks,
                          SUM(attempts - 1) AS retries,
                          COALESCE(SUM(input_tokens), 0) AS input_tokens,
                          COALESCE(SUM(output_tokens), 0) AS output_tokens,
                          CAST(AVG(duration_ms) AS INTEGER) AS avg_ms
                   FROM api_usage_log GROUP BY task ORDER BY calls DESC"""
            ).fetchall()
        ]
        by_model = [
            dict(r)
            for r in connection.execute(
                """SELECT used_model,
                          COUNT(*) AS calls,
                          SUM(success) AS successes,
                          SUM(fallback) AS fallbacks,
                          SUM(attempts - 1) AS retries,
                          COALESCE(SUM(input_tokens), 0) AS input_tokens,
                          COALESCE(SUM(output_tokens), 0) AS output_tokens,
                          CAST(AVG(duration_ms) AS INTEGER) AS avg_ms
                   FROM api_usage_log GROUP BY used_model ORDER BY calls DESC"""
            ).fetchall()
        ]
        recent = [
            dict(r)
            for r in connection.execute(
                """SELECT created_at, task, requested_model, used_model, fallback, attempts, duration_ms,
                          input_tokens, output_tokens, success, error
                   FROM api_usage_log ORDER BY id DESC LIMIT 30"""
            ).fetchall()
        ]
        return {
            "total_calls": sum(t["calls"] for t in by_task),
            "by_task": by_task,
            "by_model": by_model,
            "recent": recent,
        }


def _extract_usage(interaction: Any) -> tuple[int | None, int | None]:
    usage = getattr(interaction, "usage", None)
    if usage is None:
        return None, None
    return (
        getattr(usage, "total_input_tokens", None),
        getattr(usage, "total_output_tokens", None),
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
) -> str:
    """Execute Gemini interactions.create with fallback for unavailable models and transient errors."""
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
                interaction = client.interactions.create(
                    model=active_model,
                    input=input_payload,
                    response_format={
                        "type": "text",
                        "mime_type": "application/json",
                        "schema": schema,
                    },
                    store=False,
                )
            output_text = interaction.output_text
            if not output_text:
                raise RuntimeError(f"Gemini가 {task_desc} JSON 결과를 반환하지 않았습니다.")
            in_tok, out_tok = _extract_usage(interaction)
            _THREAD_LOCAL.last_used_model = active_model
            _log_api_usage(task_desc, model, active_model, attempts, _elapsed_ms(), in_tok, out_tok, True, None)
            return output_text
        except Exception as exc:
            err_msg = str(exc)
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
) -> PhotoAnalysis:
    """Analyze figure photo and return strictly validated PhotoAnalysis."""
    load_dotenv(dotenv_path=_get_env_file_path(), override=False)
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY를 .env 파일 또는 환경변수에 설정해 주세요.")

    client = _dispatch_get_client(api_key)
    input_payload = [
        {"type": "text", "text": build_grader_prompt(photo, category_hint=category_hint)},
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
        schema=PhotoAnalysis.model_json_schema(),
        task_desc="사진 분석",
    )
    return PhotoAnalysis.from_llm_json(output_text)


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
