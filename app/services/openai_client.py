"""app.services.openai_client - OpenAI API client, retries, structured outputs, and inference functions."""

from __future__ import annotations

import base64
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, TypeVar

from dotenv import load_dotenv
from openai import OpenAI

from app.config import (
    DEFAULT_OPENAI_MODEL,
    ENV_FILE_PATH,
    OPENAI_MODEL_PRESETS,
)
from app.models.analysis import PhotoAnalysis
from app.models.lightroom import LightroomAdvice
from app.prompts import (
    build_grader_prompt,
    build_lightroom_prompt,
)
from app.services.gemini_client import (
    _get_env_file_path,
    _log_api_usage,
)
from app.services.image_processor import PreparedPhoto

T = TypeVar("T")

_CLIENT_LOCK = threading.Lock()
_CLIENT_CACHE: dict[str, OpenAI] = {}
MAX_CONCURRENT_OPENAI_CALLS = 3
_OPENAI_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_OPENAI_CALLS)


def _get_client(api_key: str) -> OpenAI:
    """Return a process-wide OpenAI client (cached per API key)."""
    with _CLIENT_LOCK:
        client = _CLIENT_CACHE.get(api_key)
        if client is None:
            client = OpenAI(api_key=api_key)
            _CLIENT_CACHE[api_key] = client
        return client


def _resolve_api_key(explicit_key: str | None = None) -> str:
    """Resolve OpenAI API key from arguments or .env / environment variables."""
    if explicit_key:
        return explicit_key
    load_dotenv(dotenv_path=_get_env_file_path(), override=False)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY를 .env 파일 또는 환경변수에 설정해 주세요.")
    return api_key


def _format_openai_error(model: str, exc: Exception) -> RuntimeError:
    err_str = str(exc)
    if "401" in err_str or "invalid_api_key" in err_str:
        return RuntimeError(f"OpenAI API 키가 유효하지 않습니다. OPENAI_API_KEY를 확인해 주세요. ({exc})")
    if "429" in err_str or "rate_limit" in err_str or "insufficient_quota" in err_str:
        return RuntimeError(
            f"OpenAI API 할당량 초과 또는 속도 제한이 발생했습니다. 모델: {model} ({exc})"
        )
    return RuntimeError(f"OpenAI API 호출 중 오류가 발생했습니다. 모델: {model} | 내용: {exc}")


def _call_openai_structured(
    client: OpenAI,
    model: str,
    prompt_text: str,
    photo: PreparedPhoto | None,
    response_model: type[T],
    task_desc: str,
    max_retries: int = 3,
) -> T:
    """Call OpenAI chat completion with Structured Outputs, concurrency control, and backoff retries."""
    t0 = time.perf_counter()
    attempts = 0
    backoff = 2.0

    def _elapsed_ms() -> int:
        return int((time.perf_counter() - t0) * 1000)

    # Build multimodal content payload
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt_text}]
    if photo is not None:
        b64_image = base64.b64encode(photo.upload_bytes).decode("utf-8")
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{photo.upload_mime_type};base64,{b64_image}",
            },
        })

    messages = [{"role": "user", "content": content}]

    for attempt in range(1, max_retries + 1):
        attempts = attempt
        try:
            with _OPENAI_SEMAPHORE:
                completion = client.beta.chat.completions.parse(
                    model=model,
                    messages=messages,
                    response_format=response_model,
                )

            choice = completion.choices[0]
            if getattr(choice.message, "refusal", None):
                raise RuntimeError(f"OpenAI가 요청을 거부했습니다: {choice.message.refusal}")

            parsed = choice.message.parsed
            if parsed is None:
                raise RuntimeError(f"OpenAI가 {task_desc} 정형 결과를 생성하지 못했습니다.")

            in_tok = completion.usage.prompt_tokens if completion.usage else None
            out_tok = completion.usage.completion_tokens if completion.usage else None

            _log_api_usage(
                task=task_desc,
                requested_model=model,
                used_model=model,
                attempts=attempts,
                duration_ms=_elapsed_ms(),
                input_tokens=in_tok,
                output_tokens=out_tok,
                success=True,
                error=None,
            )
            return parsed

        except Exception as exc:
            err_msg = str(exc)
            is_transient = any(
                code in err_msg
                for code in ("429", "rate_limit", "500", "502", "503", "504", "timeout")
            ) and ("insufficient_quota" not in err_msg)

            if is_transient and attempt < max_retries:
                print(
                    f"[OpenAI 재시도 {attempt}/{max_retries}] API 일시적 지연 ({model}). {backoff:.1f}초 후 재시도합니다...",
                    file=sys.stderr,
                )
                time.sleep(backoff)
                backoff *= 1.5
            else:
                _log_api_usage(
                    task=task_desc,
                    requested_model=model,
                    used_model=model,
                    attempts=attempts,
                    duration_ms=_elapsed_ms(),
                    input_tokens=None,
                    output_tokens=None,
                    success=False,
                    error=err_msg,
                )
                raise _format_openai_error(model, exc) from exc

    _log_api_usage(
        task=task_desc,
        requested_model=model,
        used_model=model,
        attempts=attempts,
        duration_ms=_elapsed_ms(),
        input_tokens=None,
        output_tokens=None,
        success=False,
        error="retries exhausted",
    )
    raise RuntimeError(f"{task_desc} 처리 중 알 수 없는 오류로 완료하지 못했습니다.")


def analyze_with_openai(
    photo: PreparedPhoto,
    model: str = DEFAULT_OPENAI_MODEL,
    category_hint: str | None = None,
    api_key: str | None = None,
) -> PhotoAnalysis:
    """Analyze figure photo with OpenAI and return strictly validated PhotoAnalysis."""
    key = _resolve_api_key(api_key)
    client = _get_client(key)
    resolved_model = OPENAI_MODEL_PRESETS.get(model, model)
    prompt_text = build_grader_prompt(photo, category_hint=category_hint)

    return _call_openai_structured(
        client=client,
        model=resolved_model,
        prompt_text=prompt_text,
        photo=photo,
        response_model=PhotoAnalysis,
        task_desc="OpenAI 사진 분석",
    )


def suggest_lightroom_advice_with_openai(
    photo: PreparedPhoto,
    analysis: PhotoAnalysis,
    model: str = DEFAULT_OPENAI_MODEL,
    api_key: str | None = None,
) -> LightroomAdvice:
    """Generate Lightroom advice with OpenAI for the evaluated photo."""
    key = _resolve_api_key(api_key)
    client = _get_client(key)
    resolved_model = OPENAI_MODEL_PRESETS.get(model, model)
    prompt_text = build_lightroom_prompt()

    return _call_openai_structured(
        client=client,
        model=resolved_model,
        prompt_text=prompt_text,
        photo=photo,
        response_model=LightroomAdvice,
        task_desc="OpenAI 라이트룸 보정 추천",
    )
