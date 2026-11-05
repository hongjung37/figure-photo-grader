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
    OPENAI_IMAGE_MAX_EDGE,
    OPENAI_IMAGE_QUALITY,
    OPENAI_MODEL_PRESETS,
    SNS_CROP_RATIO_CONFIGS,
)
from app.models.analysis import (
    CrossCheckOpinion,
    FastPhotoAnalysis,
    OpenAICrossCheck,
    PhotoAnalysis,
)
from app.models.crop import CropBox, CropSet, SNSAdvice, SNSCaptionAndTags
from app.models.lightroom import LightroomAdvice
from app.prompts import (
    build_all_sns_crops_prompt,
    build_caption_and_tags_prompt,
    build_cross_check_prompt,
    build_cross_check_user_prompt,
    build_fast_grader_prompt,
    build_fast_grader_user_prompt,
    build_grader_prompt,
    build_grader_user_prompt,
    build_lightroom_prompt,
    build_single_crop_prompt,
    build_sns_advice_prompt,
    get_cross_check_system_prompt,
    get_fast_grader_system_prompt,
    get_grader_system_prompt,
)
from app.services.gemini_client import (
    _get_env_file_path,
    _log_api_usage,
)
from app.services.image_processor import PreparedPhoto

T = TypeVar("T")

_CLIENT_LOCK = threading.Lock()
_CLIENT_CACHE: dict[str, OpenAI] = {}
MAX_CONCURRENT_OPENAI_CALLS = int(os.environ.get("OPENAI_MAX_CONCURRENCY", "50"))
_OPENAI_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_OPENAI_CALLS)

# Prompt Cache Coordination: prevents cold-cache thundering herd and replica spillover on concurrent bursts
_CACHE_COORD_LOCK = threading.Lock()
_CACHE_KEY_LOCKS: dict[str, threading.Lock] = {}
_CACHE_WARM_UNTIL: dict[str, float] = {}
_CACHE_LAST_LAUNCH: dict[str, float] = {}
CACHE_TTL_WARM_SECONDS = 240.0
PREFILL_STAGGER_SECONDS = 1.8


def _get_cache_key_lock(coord_key: str) -> threading.Lock:
    with _CACHE_COORD_LOCK:
        lock = _CACHE_KEY_LOCKS.get(coord_key)
        if lock is None:
            lock = threading.Lock()
            _CACHE_KEY_LOCKS[coord_key] = lock
        return lock


def _get_client(api_key: str, base_url: str | None = None) -> OpenAI:
    """Return a process-wide OpenAI client (cached per API key and base_url)."""
    clean_key = api_key.strip()
    resolved_base_url = (base_url or os.environ.get("OPENAI_BASE_URL", "")).strip() or None
    cache_key = f"{clean_key}:{resolved_base_url}"
    with _CLIENT_LOCK:
        client = _CLIENT_CACHE.get(cache_key)
        if client is None:
            kwargs: dict[str, Any] = {"api_key": clean_key, "timeout": 35.0, "max_retries": 1}
            if resolved_base_url:
                kwargs["base_url"] = resolved_base_url
            client = OpenAI(**kwargs)
            _CLIENT_CACHE[cache_key] = client
        return client


def _resolve_api_key(explicit_key: str | None = None) -> str:
    """Resolve OpenAI API key from arguments or .env / environment variables."""
    if explicit_key:
        return explicit_key.strip()
    load_dotenv(dotenv_path=_get_env_file_path(), override=False)
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY를 .env 파일 또는 환경변수에 설정해 주세요.")
    return api_key.strip()


def _format_openai_error(model: str, exc: Exception) -> RuntimeError:
    err_str = str(exc)
    if "401" in err_str or "invalid_api_key" in err_str:
        return RuntimeError(f"OpenAI API 키가 유효하지 않습니다. OPENAI_API_KEY를 확인해 주세요. ({exc})")
    if "429" in err_str or "rate_limit" in err_str or "insufficient_quota" in err_str:
        return RuntimeError(
            f"OpenAI API 할당량 초과 또는 속도 제한이 발생했습니다. 모델: {model} ({exc})"
        )
    return RuntimeError(f"OpenAI API 호출 중 오류가 발생했습니다. 모델: {model} | 내용: {exc}")


def _prepare_openai_image_payload(
    photo: PreparedPhoto,
    max_edge: int = OPENAI_IMAGE_MAX_EDGE,
) -> tuple[str, str]:
    """Resize photo for OpenAI to reduce vision token consumption while preserving fine details."""
    import io
    from PIL import Image

    if photo.width <= max_edge and photo.height <= max_edge:
        b64_image = base64.b64encode(photo.upload_bytes).decode("utf-8")
        return b64_image, photo.upload_mime_type

    try:
        img = Image.open(io.BytesIO(photo.upload_bytes))
        img.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        elif img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg

        out = io.BytesIO()
        img.save(out, format="JPEG", quality=OPENAI_IMAGE_QUALITY, optimize=True)
        b64_image = base64.b64encode(out.getvalue()).decode("utf-8")
        return b64_image, "image/jpeg"
    except Exception:
        b64_image = base64.b64encode(photo.upload_bytes).decode("utf-8")
        return b64_image, photo.upload_mime_type


def _call_openai_structured(
    client: OpenAI,
    model: str,
    prompt_text: str | None = None,
    photo: PreparedPhoto | None = None,
    response_model: type[T] = Any,
    task_desc: str = "OpenAI 태스크",
    max_retries: int = 3,
    system_prompt: str | None = None,
    user_prompt: str | None = None,
) -> T:
    """Call OpenAI chat completion with Structured Outputs, concurrency control, and backoff retries.

    Supports 2-tier prompt structure (static system prompt + dynamic user payload)
    for high-efficiency OpenAI Prompt Caching prefix matching.
    """
    t0 = time.perf_counter()
    attempts = 0
    backoff = 2.0

    def _elapsed_ms() -> int:
        return int((time.perf_counter() - t0) * 1000)

    # Build multimodal messages payload:
    # 2-Tier structure: [Static System Prompt + Schema] -> [User Text] -> [Image URL]
    # Preserves the full cross-photo prefix across different photos AND full image prefix on same-photo multi-sampling.
    if system_prompt:
        user_content: list[dict[str, Any]] = []
        u_text = user_prompt or prompt_text or ""
        if u_text:
            user_content.append({"type": "text", "text": u_text})
        if photo is not None:
            b64_image, mime_type = _prepare_openai_image_payload(photo)
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{b64_image}",
                },
            })
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
    else:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt_text or user_prompt or ""}]
        if photo is not None:
            b64_image, mime_type = _prepare_openai_image_payload(photo)
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime_type};base64,{b64_image}",
                },
            })
        messages = [{"role": "user", "content": content}]

    cache_key = f"photo-eval-{getattr(response_model, '__name__', 'default')}"
    coord_key = f"{model}:{cache_key}"
    photo_sha = getattr(photo, "sha256", None) if photo is not None else None
    photo_coord_key = f"{coord_key}:{photo_sha}" if photo_sha else None
    is_real_client = isinstance(client, OpenAI)
    u_text_for_warmup = (user_prompt or prompt_text or "") if system_prompt else ""

    def _warm_prefix_cache() -> None:
        """Write a text-only KV cache checkpoint at [system_prompt + static_user_header] so all subsequent photos hit cross-photo cache."""
        if not system_prompt or photo is None:
            return
        try:
            from openai.lib._pydantic import to_strict_json_schema
            static_user_prefix = (
                u_text_for_warmup.split("\n- 촬영 관련 안전 EXIF:", 1)[0]
                if u_text_for_warmup
                else "[평가 대상 피규어 사진 정보]"
            ).strip()
            fmt = {
                "type": "json_schema",
                "json_schema": {
                    "name": getattr(response_model, "__name__", "Response"),
                    "strict": True,
                    "schema": to_strict_json_schema(response_model),
                },
            }
            w_comp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": static_user_prefix},
                ],
                response_format=fmt,
                max_completion_tokens=16,
            )
            w_details = getattr(w_comp.usage, "prompt_tokens_details", None) if w_comp.usage else None
            w_written = getattr(w_details, "cache_write_tokens", None) if w_details else None
            w_cached = getattr(w_details, "cached_tokens", None) if w_details else None
            print(
                f"[OpenAI Cache Warmup] {task_desc} ({model}) | 프리픽스 체크포인트 준비 완료 (write={w_written}, cached={w_cached})",
                file=sys.stderr,
            )
            time.sleep(0.4)
        except Exception as warm_exc:
            print(f"[OpenAI Cache Warmup] 생략 ({warm_exc})", file=sys.stderr)

    def _execute_completion() -> Any:
        try:
            comp = client.beta.chat.completions.parse(
                model=model,
                messages=messages,
                response_format=response_model,
            )
            choice = comp.choices[0]
            if getattr(choice.message, "refusal", None):
                raise RuntimeError(f"OpenAI가 요청을 거부했습니다: {choice.message.refusal}")
            return comp, choice.message.parsed
        except Exception as parse_err:
            # Do not swallow auth or quota errors
            err_s = str(parse_err)
            if any(c in err_s for c in ("401", "invalid_api_key", "insufficient_quota")):
                raise
            # Fallback to standard chat completions with JSON mode for custom gateways
            import json as _json
            schema_instruction = (
                "반드시 아래 JSON 스키마를 준수하는 순수 JSON 객체만 응답하세요:\n"
                f"{_json.dumps(response_model.model_json_schema(), ensure_ascii=False)}"
            )
            if system_prompt and len(messages) >= 2:
                fallback_messages = [
                    {"role": "system", "content": f"{system_prompt}\n\n{schema_instruction}"},
                    messages[1],
                ]
            else:
                fallback_messages = [
                    {"role": "system", "content": schema_instruction},
                    *messages,
                ]
            comp = client.chat.completions.create(
                model=model,
                messages=fallback_messages,
                response_format={"type": "json_object"},
            )
            choice = comp.choices[0]
            raw_content = choice.message.content or ""
            if hasattr(response_model, "from_llm_json"):
                parsed_obj = response_model.from_llm_json(raw_content)
            else:
                parsed_obj = response_model.model_validate_json(raw_content)
            return comp, parsed_obj

    for attempt in range(1, max_retries + 1):
        attempts = attempt
        try:
            with _OPENAI_SEMAPHORE:
                if is_real_client:
                    # Level 1: Cross-Photo Prefix Checkpoint Warmup & Stagger
                    key_lock = _get_cache_key_lock(coord_key)
                    with key_lock:
                        now = time.monotonic()
                        is_prefix_warm = now < _CACHE_WARM_UNTIL.get(coord_key, 0.0)
                        if not is_prefix_warm and system_prompt and photo is not None:
                            _warm_prefix_cache()
                            now = time.monotonic()
                            _CACHE_WARM_UNTIL[coord_key] = now + CACHE_TTL_WARM_SECONDS
                            _CACHE_LAST_LAUNCH[coord_key] = now
                        else:
                            elapsed = now - _CACHE_LAST_LAUNCH.get(coord_key, 0.0)
                            if elapsed < PREFILL_STAGGER_SECONDS:
                                time.sleep(PREFILL_STAGGER_SECONDS - elapsed)
                            _CACHE_LAST_LAUNCH[coord_key] = time.monotonic()

                    # Level 2: Same-Photo (SHA256) Coordination for sample_count=3 / concurrent same-photo calls
                    if photo_coord_key:
                        photo_lock = _get_cache_key_lock(photo_coord_key)
                        photo_lock.acquire()
                        try:
                            now_p = time.monotonic()
                            is_photo_warm = now_p < _CACHE_WARM_UNTIL.get(photo_coord_key, 0.0)
                            if not is_photo_warm:
                                completion, parsed = _execute_completion()
                                finish_p = time.monotonic()
                                _CACHE_WARM_UNTIL[photo_coord_key] = finish_p + CACHE_TTL_WARM_SECONDS
                                _CACHE_WARM_UNTIL[coord_key] = finish_p + CACHE_TTL_WARM_SECONDS
                        finally:
                            photo_lock.release()
                        if is_photo_warm:
                            completion, parsed = _execute_completion()
                            with _CACHE_COORD_LOCK:
                                finish_p = time.monotonic()
                                _CACHE_WARM_UNTIL[photo_coord_key] = finish_p + CACHE_TTL_WARM_SECONDS
                                _CACHE_WARM_UNTIL[coord_key] = finish_p + CACHE_TTL_WARM_SECONDS
                    else:
                        completion, parsed = _execute_completion()
                else:
                    completion, parsed = _execute_completion()

            if parsed is None:
                raise RuntimeError(f"OpenAI가 {task_desc} 정형 결과를 생성하지 못했습니다.")

            in_tok = completion.usage.prompt_tokens if (completion.usage and isinstance(completion.usage.prompt_tokens, int)) else None
            out_tok = completion.usage.completion_tokens if (completion.usage and isinstance(completion.usage.completion_tokens, int)) else None
            cached_tok = None
            if completion.usage and hasattr(completion.usage, "prompt_tokens_details") and completion.usage.prompt_tokens_details:
                raw_cached = getattr(completion.usage.prompt_tokens_details, "cached_tokens", None)
                if isinstance(raw_cached, int):
                    cached_tok = raw_cached
                elif raw_cached is not None:
                    try:
                        cached_tok = int(raw_cached)
                    except (ValueError, TypeError):
                        cached_tok = None

            if isinstance(cached_tok, int) and isinstance(in_tok, int) and in_tok > 0:
                cache_pct = (cached_tok / in_tok) * 100
                print(
                    f"[OpenAI Cache] {task_desc} ({model}) | 총 입력: {in_tok:,} 토큰 | 캐시 적중: {cached_tok:,} 토큰 ({cache_pct:.1f}%)",
                    file=sys.stderr,
                )
                if cached_tok == 0 and is_real_client and system_prompt and photo is not None:
                    # Remote KV prefix was evicted early; re-warm checkpoint for subsequent requests
                    with _get_cache_key_lock(coord_key):
                        _warm_prefix_cache()
                        _CACHE_WARM_UNTIL[coord_key] = time.monotonic() + CACHE_TTL_WARM_SECONDS

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
                cached_tokens=cached_tok,
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


def cross_check_with_openai(
    photo: PreparedPhoto,
    model: str = DEFAULT_OPENAI_MODEL,
    category_hint: str | None = None,
    api_key: str | None = None,
    analysis_mode: str = "fast",
) -> CrossCheckOpinion:
    """Generate a lightweight second-opinion critique from OpenAI (Fast mode by default).

    Uses 2-tier prompt structure (static system instructions + dynamic user payload)
    to achieve maximum OpenAI Prompt Caching efficiency across batch evaluations.
    """
    key = _resolve_api_key(api_key)
    client = _get_client(key)
    resolved_model = OPENAI_MODEL_PRESETS.get(model, model)
    is_fast = (analysis_mode or "fast").strip().lower() == "fast"

    if is_fast:
        system_prompt = get_fast_grader_system_prompt()
        user_prompt = build_fast_grader_user_prompt(photo, category_hint=category_hint)
        fast_res = _call_openai_structured(
            client=client,
            model=resolved_model,
            photo=photo,
            response_model=FastPhotoAnalysis,
            task_desc="OpenAI 크로스 체크(경량)",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        if isinstance(fast_res, FastPhotoAnalysis):
            return fast_res.to_cross_check_opinion(model_name=resolved_model)
        if isinstance(fast_res, CrossCheckOpinion):
            return fast_res
        return fast_res

    system_prompt = get_cross_check_system_prompt()
    user_prompt = build_cross_check_user_prompt(photo, category_hint=category_hint)

    full_res = _call_openai_structured(
        client=client,
        model=resolved_model,
        photo=photo,
        response_model=OpenAICrossCheck,
        task_desc="OpenAI 크로스 체크 비평",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    if isinstance(full_res, OpenAICrossCheck):
        return CrossCheckOpinion(
            model=resolved_model,
            score=full_res.score,
            reason=full_res.reason,
            strengths=full_res.strengths,
            improvements=full_res.improvements,
            composition_critique=full_res.composition_critique,
            lighting_critique=full_res.lighting_critique,
        )
    return full_res


def analyze_with_openai(
    photo: PreparedPhoto,
    model: str = DEFAULT_OPENAI_MODEL,
    category_hint: str | None = None,
    api_key: str | None = None,
    analysis_mode: str = "full",
) -> PhotoAnalysis:
    """Analyze figure photo with OpenAI and return strictly validated PhotoAnalysis.

    Uses 2-tier prompt structure (static system instructions + dynamic user payload)
    to achieve maximum OpenAI Prompt Caching efficiency across batch evaluations.
    """
    key = _resolve_api_key(api_key)
    client = _get_client(key)
    resolved_model = OPENAI_MODEL_PRESETS.get(model, model)
    is_fast = (analysis_mode or "full").strip().lower() == "fast"
    if is_fast:
        system_prompt = get_fast_grader_system_prompt()
        user_prompt = build_fast_grader_user_prompt(photo, category_hint=category_hint)
        fast_res = _call_openai_structured(
            client=client,
            model=resolved_model,
            photo=photo,
            response_model=FastPhotoAnalysis,
            task_desc="OpenAI 사진 경량 분석",
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        if isinstance(fast_res, FastPhotoAnalysis):
            return fast_res.to_photo_analysis()
        if isinstance(fast_res, PhotoAnalysis):
            return fast_res.model_copy(
                update={
                    "composition_notes": "",
                    "lighting_notes": "",
                    "color_notes": "",
                    "technique_notes": "",
                    "focus_notes": "",
                    "strengths": [],
                    "improvements": [],
                }
            )

    system_prompt = get_grader_system_prompt(compact_tags=True, analysis_mode="full")
    user_prompt = build_grader_user_prompt(photo, category_hint=category_hint)

    return _call_openai_structured(
        client=client,
        model=resolved_model,
        photo=photo,
        response_model=PhotoAnalysis,
        task_desc="OpenAI 사진 분석",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )


def suggest_lightroom_advice_with_openai(
    photo: PreparedPhoto,
    analysis: PhotoAnalysis | None = None,
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
        task_desc="Lightroom 보정 제안",
    )


def generate_all_sns_crops_with_openai(
    photo: PreparedPhoto,
    model: str = DEFAULT_OPENAI_MODEL,
    api_key: str | None = None,
) -> CropSet:
    """Generate the 4 SNS crop boxes and AI best ratio recommendation in ONE call via OpenAI."""
    key = _resolve_api_key(api_key)
    client = _get_client(key)
    resolved_model = OPENAI_MODEL_PRESETS.get(model, model)

    ratio_lines = []
    for r_key, cfg in SNS_CROP_RATIO_CONFIGS.items():
        ratio_lines.append(
            f"- {r_key}: {cfg['name']} ({cfg['aspect']}, 목표 픽셀 종횡비 {cfg['w'] / cfg['h']:.4f})\n"
            f"  가이드: {cfg['guide']}\n"
            f"  ratio_label: '{cfg['name']} ({cfg['aspect']})'"
        )
    ratio_block = "\n".join(ratio_lines)
    prompt_text = build_all_sns_crops_prompt(photo, ratio_block)

    return _call_openai_structured(
        client=client,
        model=resolved_model,
        prompt_text=prompt_text,
        photo=photo,
        response_model=CropSet,
        task_desc="SNS 크롭 4종 일괄 제안",
    )


def generate_single_sns_crop_with_openai(
    photo: PreparedPhoto,
    ratio_key: str,
    model: str = DEFAULT_OPENAI_MODEL,
    api_key: str | None = None,
) -> CropBox:
    """Generate a single focused SNS crop recommendation via OpenAI."""
    if ratio_key not in SNS_CROP_RATIO_CONFIGS:
        raise ValueError(f"지원하지 않는 SNS 크롭 비율 키입니다: {ratio_key}")

    cfg = SNS_CROP_RATIO_CONFIGS[ratio_key]
    key = _resolve_api_key(api_key)
    client = _get_client(key)
    resolved_model = OPENAI_MODEL_PRESETS.get(model, model)
    prompt_text = build_single_crop_prompt(photo, ratio_key, cfg)

    return _call_openai_structured(
        client=client,
        model=resolved_model,
        prompt_text=prompt_text,
        photo=photo,
        response_model=CropBox,
        task_desc=f"{cfg['name']} 크롭 제안",
    )


def generate_sns_caption_and_tags_with_openai(
    photo: PreparedPhoto,
    model: str = DEFAULT_OPENAI_MODEL,
    api_key: str | None = None,
) -> SNSCaptionAndTags:
    """Generate social caption and hashtags on-demand via OpenAI."""
    key = _resolve_api_key(api_key)
    client = _get_client(key)
    resolved_model = OPENAI_MODEL_PRESETS.get(model, model)
    prompt_text = build_caption_and_tags_prompt(photo)

    return _call_openai_structured(
        client=client,
        model=resolved_model,
        prompt_text=prompt_text,
        photo=photo,
        response_model=SNSCaptionAndTags,
        task_desc="SNS 캡션 및 해시태그",
    )


def generate_sns_advice_with_openai(
    photo: PreparedPhoto,
    model: str = DEFAULT_OPENAI_MODEL,
    api_key: str | None = None,
) -> SNSAdvice:
    """Generate full SNS crops and captions via OpenAI."""
    key = _resolve_api_key(api_key)
    client = _get_client(key)
    resolved_model = OPENAI_MODEL_PRESETS.get(model, model)
    prompt_text = build_sns_advice_prompt(photo)

    return _call_openai_structured(
        client=client,
        model=resolved_model,
        prompt_text=prompt_text,
        photo=photo,
        response_model=SNSAdvice,
        task_desc="SNS 크롭 및 캡션 제안",
    )

