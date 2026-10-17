"""app.services.multi_llm - Unified multi-provider LLM interface supporting Gemini, OpenAI, and ensemble."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.config import (
    ALL_MODEL_PRESETS,
    DEFAULT_MODEL,
    DEFAULT_OPENAI_MODEL,
    MODEL_PRESETS,
    OPENAI_MODEL_PRESETS,
)
from app.models.analysis import (
    AestheticTags,
    CrossCheckOpinion,
    OpenAICrossCheck,
    PhotoAnalysis,
)
from app.models.crop import CropBox, CropSet, SNSAdvice, SNSCaptionAndTags
from app.models.lightroom import LightroomAdvice
import threading

from app.services.gemini_client import (
    analyze_with_gemini,
    clear_last_used_gemini_model,
    generate_all_sns_crops as generate_all_sns_crops_with_gemini,
    generate_lightroom_advice as generate_lightroom_advice_with_gemini,
    generate_single_sns_crop as generate_single_sns_crop_with_gemini,
    generate_sns_advice as generate_sns_advice_with_gemini,
    generate_sns_caption_and_tags as generate_sns_caption_and_tags_with_gemini,
    get_last_used_gemini_model,
)
from app.services.image_processor import PreparedPhoto
from app.services.openai_client import (
    analyze_with_openai,
    cross_check_with_openai,
    generate_all_sns_crops_with_openai,
    generate_single_sns_crop_with_openai,
    generate_sns_advice_with_openai,
    generate_sns_caption_and_tags_with_openai,
    suggest_lightroom_advice_with_openai,
)

_MULTI_THREAD_LOCAL = threading.local()


def get_effective_analysis_model(requested_model: str) -> str:
    """Return the actual model used during the most recent analyze_photo call in this thread."""
    eff = getattr(_MULTI_THREAD_LOCAL, "effective_model", None)
    return eff if eff else requested_model


def clear_effective_analysis_model() -> None:
    """Clear the thread-local effective model before invoking analyze_photo."""
    _MULTI_THREAD_LOCAL.effective_model = None


def resolve_task_model(model_spec: str | None = None, default_tier: str = "lite") -> tuple[str, str]:
    """Resolve a frontend/CLI model or tier specifier into (provider, resolved_model_id).

    Examples:
      - 'lite' -> ('gemini', 'gemini-3.1-flash-lite')
      - 'standard' -> ('gemini', 'gemini-3.5-flash-lite')
      - 'pro' -> ('gemini', 'gemini-3.8-flash')
      - 'ensemble-pro' -> ('ensemble', 'ensemble(gemini-3.8-flash+gpt-6-luna)')
      - 'luna' / 'gpt-6-luna' -> ('openai', 'gpt-6-luna')
      - 'gpt-4o' -> ('openai', 'gpt-4o')
      - 'gpt-4o-mini' / 'mini' -> ('openai', 'gpt-4o-mini')
    """
    raw = (model_spec or "").strip()
    lower = raw.lower()
    if not lower:
        return ("gemini", MODEL_PRESETS.get(default_tier, DEFAULT_MODEL))

    if lower.startswith("ensemble-"):
        sub_tier = lower[len("ensemble-"):]
        sub_gemini = MODEL_PRESETS.get(sub_tier, MODEL_PRESETS.get("standard", DEFAULT_MODEL))
        return ("ensemble", f"ensemble({sub_gemini}+{DEFAULT_OPENAI_MODEL})")
    if lower == "ensemble" or lower.startswith("ensemble(") or lower.startswith("ensemble:"):
        resolved_ensemble = ALL_MODEL_PRESETS.get(lower, raw)
        return ("ensemble", resolved_ensemble)
    if lower in OPENAI_MODEL_PRESETS and lower not in MODEL_PRESETS:
        return ("openai", OPENAI_MODEL_PRESETS[lower])
    if lower.startswith(("gpt-", "o1", "o3", "o4", "openai:")):
        clean_model = raw.split(":", 1)[1] if lower.startswith("openai:") else raw
        return ("openai", OPENAI_MODEL_PRESETS.get(clean_model.lower(), clean_model))
    if lower in MODEL_PRESETS:
        return ("gemini", MODEL_PRESETS[lower])
    if lower.startswith("gemini"):
        return ("gemini", raw)
    return ("gemini", MODEL_PRESETS.get(default_tier, DEFAULT_MODEL))


def _merge_analyses(g_res: PhotoAnalysis, o_res: Any, model_name: str = DEFAULT_OPENAI_MODEL) -> PhotoAnalysis:
    """Attach OpenAI's independent critique as CrossCheckOpinion to Gemini's primary analysis without score averaging."""
    if isinstance(o_res, OpenAICrossCheck):
        opinion = CrossCheckOpinion(
            model=model_name,
            score=o_res.score,
            reason=o_res.reason,
            strengths=o_res.strengths,
            improvements=o_res.improvements,
            composition_critique=o_res.composition_critique,
            lighting_critique=o_res.lighting_critique,
        )
    elif isinstance(o_res, PhotoAnalysis):
        opinion = CrossCheckOpinion(
            model=model_name,
            score=o_res.final_score,
            reason=o_res.final_reason,
            strengths=o_res.strengths,
            improvements=o_res.improvements,
            composition_critique=o_res.composition_notes,
            lighting_critique=o_res.lighting_notes,
        )
    elif isinstance(o_res, CrossCheckOpinion):
        opinion = o_res
    else:
        opinion = None

    return g_res.model_copy(update={"cross_check_opinion": opinion})


def analyze_photo(
    photo: PreparedPhoto,
    provider: str = "gemini",
    model: str | None = None,
    category_hint: str | None = None,
    api_key: str | None = None,
) -> PhotoAnalysis:
    """Unified entry point for photo evaluation with Gemini or Gemini+OpenAI Cross-Check Ensemble."""
    normalized_provider = (provider or "gemini").strip().lower()
    clear_effective_analysis_model()

    if normalized_provider == "ensemble":
        target_openai_model = DEFAULT_OPENAI_MODEL
        target_gemini_model = MODEL_PRESETS.get("standard", "gemini-3.5-flash-lite")
        if model and not model.startswith("ensemble"):
            target_gemini_model = model
        elif model and model.startswith("ensemble(") and "+" in model:
            inner = model[len("ensemble("):-1]
            parts = inner.split("+", 1)
            if parts[0] and parts[0] != "gemini":
                target_gemini_model = parts[0]
            if len(parts) > 1 and parts[1]:
                target_openai_model = parts[1]

        used_gemini_holder: list[str] = [target_gemini_model]

        def _run_gemini() -> PhotoAnalysis:
            clear_last_used_gemini_model()
            res = analyze_with_gemini(
                photo=photo,
                model=target_gemini_model,
                category_hint=category_hint,
            )
            actual = get_last_used_gemini_model()
            if actual:
                used_gemini_holder[0] = actual
            return res

        with ThreadPoolExecutor(max_workers=2) as executor:
            gemini_fut = executor.submit(_run_gemini)
            openai_fut = executor.submit(
                cross_check_with_openai,
                photo=photo,
                model=target_openai_model,
                category_hint=category_hint,
                api_key=api_key,
            )
            gemini_res = gemini_fut.result()
            openai_res = openai_fut.result()
            _MULTI_THREAD_LOCAL.effective_model = f"ensemble({used_gemini_holder[0]}+{target_openai_model})"
            return _merge_analyses(gemini_res, openai_res, model_name=target_openai_model)

    # Standalone evaluation is exclusively handled by Gemini (fallback to DEFAULT_MODEL if non-Gemini model name passed)
    target_model = model if (model and model.lower().startswith("gemini")) else DEFAULT_MODEL
    clear_last_used_gemini_model()
    res = analyze_with_gemini(
        photo=photo,
        model=target_model,
        category_hint=category_hint,
    )
    actual_gemini = get_last_used_gemini_model() or target_model
    _MULTI_THREAD_LOCAL.effective_model = actual_gemini
    return res


def suggest_lightroom_advice(
    photo: PreparedPhoto,
    analysis: PhotoAnalysis | None = None,
    provider: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
) -> LightroomAdvice:
    """Unified entry point for Lightroom advice with Gemini or OpenAI."""
    if provider is not None and provider.strip().lower() == "openai":
        _, resolved_model = resolve_task_model(model or DEFAULT_OPENAI_MODEL, default_tier="lite")
        if not resolved_model.startswith(("gpt-", "o1", "o3", "o4")):
            resolved_model = OPENAI_MODEL_PRESETS.get(model or "", model or DEFAULT_OPENAI_MODEL)
        return suggest_lightroom_advice_with_openai(
            photo=photo,
            analysis=analysis,
            model=resolved_model,
            api_key=api_key,
        )

    resolved_provider, resolved_model = resolve_task_model(model, default_tier="lite")
    if resolved_provider == "openai":
        return suggest_lightroom_advice_with_openai(
            photo=photo,
            analysis=analysis,
            model=resolved_model,
            api_key=api_key,
        )
    return generate_lightroom_advice_with_gemini(
        photo=photo,
        model=resolved_model,
    )


def suggest_all_sns_crops(
    photo: PreparedPhoto,
    model: str | None = None,
    api_key: str | None = None,
) -> CropSet:
    """Unified entry point for generating all 4 SNS crop ratios + best ratio pick with Gemini or OpenAI."""
    resolved_provider, resolved_model = resolve_task_model(model, default_tier="lite")
    if resolved_provider == "openai":
        return generate_all_sns_crops_with_openai(
            photo=photo,
            model=resolved_model,
            api_key=api_key,
        )
    return generate_all_sns_crops_with_gemini(
        photo=photo,
        model=resolved_model,
    )


def suggest_single_sns_crop(
    photo: PreparedPhoto,
    ratio_key: str,
    model: str | None = None,
    api_key: str | None = None,
) -> CropBox:
    """Unified entry point for generating a single SNS crop ratio with Gemini or OpenAI."""
    resolved_provider, resolved_model = resolve_task_model(model, default_tier="lite")
    if resolved_provider == "openai":
        return generate_single_sns_crop_with_openai(
            photo=photo,
            ratio_key=ratio_key,
            model=resolved_model,
            api_key=api_key,
        )
    return generate_single_sns_crop_with_gemini(
        photo=photo,
        ratio_key=ratio_key,
        model=resolved_model,
    )


def suggest_sns_caption_and_tags(
    photo: PreparedPhoto,
    model: str | None = None,
    api_key: str | None = None,
) -> SNSCaptionAndTags:
    """Unified entry point for generating SNS social caption and hashtags with Gemini or OpenAI."""
    resolved_provider, resolved_model = resolve_task_model(model, default_tier="lite")
    if resolved_provider == "openai":
        return generate_sns_caption_and_tags_with_openai(
            photo=photo,
            model=resolved_model,
            api_key=api_key,
        )
    return generate_sns_caption_and_tags_with_gemini(
        photo=photo,
        model=resolved_model,
    )


def suggest_sns_advice(
    photo: PreparedPhoto,
    model: str | None = None,
    api_key: str | None = None,
) -> SNSAdvice:
    """Unified entry point for generating full SNS advice with Gemini or OpenAI."""
    resolved_provider, resolved_model = resolve_task_model(model, default_tier="lite")
    if resolved_provider == "openai":
        return generate_sns_advice_with_openai(
            photo=photo,
            model=resolved_model,
            api_key=api_key,
        )
    return generate_sns_advice_with_gemini(
        photo=photo,
        model=resolved_model,
    )

