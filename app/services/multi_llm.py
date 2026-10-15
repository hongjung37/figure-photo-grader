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
    suggest_lightroom_advice_with_openai,
)


def _merge_analyses(g_res: PhotoAnalysis, o_res: PhotoAnalysis) -> PhotoAnalysis:
    """Synthesize results from multiple LLMs by averaging numeric scores and combining insights."""
    avg_composition = round((g_res.composition_score + o_res.composition_score) / 2.0, 1)
    avg_lighting = round((g_res.lighting_score + o_res.lighting_score) / 2.0, 1)
    avg_color = round((g_res.color_score + o_res.color_score) / 2.0, 1)
    avg_technique = round((g_res.technique_score + o_res.technique_score) / 2.0, 1)
    avg_final = round((g_res.final_score + o_res.final_score) / 2.0, 1)

    # Merge aesthetic tags uniquely per category (limit to 3)
    def _merge_tag_list(l1: list[str], l2: list[str]) -> list[str]:
        merged = []
        for item in l1 + l2:
            if item not in merged:
                merged.append(item)
            if len(merged) == 3:
                break
        return merged

    combined_tags = AestheticTags(
        viewpoint=_merge_tag_list(g_res.aesthetic_tags.viewpoint, o_res.aesthetic_tags.viewpoint),
        composition_space=_merge_tag_list(g_res.aesthetic_tags.composition_space, o_res.aesthetic_tags.composition_space),
        pose_gaze=_merge_tag_list(g_res.aesthetic_tags.pose_gaze, o_res.aesthetic_tags.pose_gaze),
        mood=_merge_tag_list(g_res.aesthetic_tags.mood, o_res.aesthetic_tags.mood),
        subject_background=_merge_tag_list(g_res.aesthetic_tags.subject_background, o_res.aesthetic_tags.subject_background),
        light_expression=_merge_tag_list(g_res.aesthetic_tags.light_expression, o_res.aesthetic_tags.light_expression),
        color_impression=_merge_tag_list(g_res.aesthetic_tags.color_impression, o_res.aesthetic_tags.color_impression),
        narrative_implication=_merge_tag_list(g_res.aesthetic_tags.narrative_implication, o_res.aesthetic_tags.narrative_implication),
    )

    # Combine strengths and improvements
    merged_strengths = list(dict.fromkeys(g_res.strengths + o_res.strengths))[:5]
    merged_improvements = list(dict.fromkeys(g_res.improvements + o_res.improvements))[:5]

    combined_reason = (
        f"[앙상블 종합: 평균 {avg_final:.1f}점] "
        f"[Gemini: {g_res.final_score:.1f}점] {g_res.final_reason} | "
        f"[OpenAI: {o_res.final_score:.1f}점] {o_res.final_reason}"
    )

    return PhotoAnalysis(
        composition_score=avg_composition,
        composition_notes=g_res.composition_notes or o_res.composition_notes,
        lighting_score=avg_lighting,
        lighting_notes=g_res.lighting_notes or o_res.lighting_notes,
        color_score=avg_color,
        color_notes=g_res.color_notes or o_res.color_notes,
        technique_score=avg_technique,
        technique_notes=g_res.technique_notes or o_res.technique_notes,
        final_score=avg_final,
        final_reason=combined_reason,
        strengths=merged_strengths,
        improvements=merged_improvements,
        figure_category=g_res.figure_category,
        focus_status=g_res.focus_status,
        focus_notes=g_res.focus_notes or o_res.focus_notes,
        detected_camera_settings=g_res.detected_camera_settings or o_res.detected_camera_settings,
        aesthetic_tags=combined_tags,
    )


def analyze_photo(
    photo: PreparedPhoto,
    provider: str = "gemini",
    model: str | None = None,
    category_hint: str | None = None,
    api_key: str | None = None,
) -> PhotoAnalysis:
    """Unified entry point for photo evaluation with Gemini, OpenAI, or Ensemble."""
    normalized_provider = (provider or "gemini").strip().lower()

    if normalized_provider == "openai":
        target_model = model or DEFAULT_OPENAI_MODEL
        return analyze_with_openai(
            photo=photo,
            model=target_model,
            category_hint=category_hint,
            api_key=api_key,
        )

    if normalized_provider == "ensemble":
        with ThreadPoolExecutor(max_workers=2) as executor:
            gemini_fut = executor.submit(
                analyze_with_gemini,
                photo=photo,
                model=model or DEFAULT_MODEL,
                category_hint=category_hint,
            )
            openai_fut = executor.submit(
                analyze_with_openai,
                photo=photo,
                model=DEFAULT_OPENAI_MODEL,
                category_hint=category_hint,
                api_key=api_key,
            )
            gemini_res = gemini_fut.result()
            openai_res = openai_fut.result()
            return _merge_analyses(gemini_res, openai_res)

    # Default to Gemini
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
