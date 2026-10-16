"""app.services.multi_llm - Unified multi-provider LLM interface supporting Gemini, OpenAI, and ensemble."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.config import (
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
from app.models.lightroom import LightroomAdvice
from app.services.gemini_client import (
    analyze_with_gemini,
    generate_lightroom_advice as generate_lightroom_advice_with_gemini,
)
from app.services.image_processor import PreparedPhoto
from app.services.openai_client import (
    analyze_with_openai,
    cross_check_with_openai,
    suggest_lightroom_advice_with_openai,
)


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

        with ThreadPoolExecutor(max_workers=2) as executor:
            gemini_fut = executor.submit(
                analyze_with_gemini,
                photo=photo,
                model=target_gemini_model,
                category_hint=category_hint,
            )
            openai_fut = executor.submit(
                cross_check_with_openai,
                photo=photo,
                model=target_openai_model,
                category_hint=category_hint,
                api_key=api_key,
            )
            gemini_res = gemini_fut.result()
            openai_res = openai_fut.result()
            return _merge_analyses(gemini_res, openai_res, model_name=target_openai_model)

    # Standalone evaluation is exclusively handled by Gemini
    target_model = model or DEFAULT_MODEL
    return analyze_with_gemini(
        photo=photo,
        model=target_model,
        category_hint=category_hint,
    )


def suggest_lightroom_advice(
    photo: PreparedPhoto,
    analysis: PhotoAnalysis,
    provider: str = "gemini",
    model: str | None = None,
    api_key: str | None = None,
) -> LightroomAdvice:
    """Unified entry point for Lightroom advice with Gemini or OpenAI."""
    normalized_provider = (provider or "gemini").strip().lower()
    if normalized_provider == "openai":
        return suggest_lightroom_advice_with_openai(
            photo=photo,
            analysis=analysis,
            model=model or DEFAULT_OPENAI_MODEL,
            api_key=api_key,
        )
    return suggest_lightroom_advice_with_gemini(
        photo=photo,
        analysis=analysis,
        model=model or DEFAULT_MODEL,
    )
