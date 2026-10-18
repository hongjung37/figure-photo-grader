"""app.prompts.grader_prompts - Figure photography grading prompt builder.

Provides the comprehensive aesthetic evaluation prompt, including figure category
specialized criteria, strict scoring benchmarks, pros/cons segregation, and aesthetic tagging.
"""

from __future__ import annotations

import json
from typing import Any

from app.models.analysis import (
    AESTHETIC_TAG_CATEGORIES,
    AESTHETIC_TAG_OPTIONS,
    FIGURE_CATEGORIES,
)


def build_grader_prompt(
    photo: Any,
    category_hint: str | None = None,
    compact_tags: bool = False,
) -> str:
    """Build the prompt for figure photo evaluation in concise, token-efficient English."""
    safe_exif = getattr(photo, "safe_exif", {})
    camera_settings = json.dumps(safe_exif, ensure_ascii=False, sort_keys=True)
    if not safe_exif:
        camera_settings = "{} (사용 가능한 안전한 EXIF 촬영 설정 없음)"

    if compact_tags:
        tag_section = (
            "Select 0-3 appropriate tags (1-3 for required categories) from the allowed vocabulary defined in the JSON schema "
            "for the 8 categories: viewpoint, composition_space, pose_gaze, mood, subject_background, light_expression, color_impression, narrative_implication."
        )
    else:
        tag_section = "Allowed Korean vocabulary for aesthetic_tags:\n" + "\n".join(
            f"- {category_key} ({AESTHETIC_TAG_CATEGORIES[category_key]}): {', '.join(options)}"
            for category_key, options in AESTHETIC_TAG_OPTIONS.items()
        )

    category_instruction = ""
    if category_hint and category_hint in FIGURE_CATEGORIES:
        cat_info = FIGURE_CATEGORIES[category_hint]
        category_instruction = f"""[지정된 피규어 촬영 유형: {cat_info['label']}]
User specified '{cat_info['label']}' ({cat_info['description']}).
Set figure_category to exactly '{cat_info['label']}'. Primary focus: {cat_info['focus']}"""
    else:
        category_instruction = """[피규어 촬영 세부 유형 자동 판별 및 분기 심사] (Figure Photography Category Classification)
Analyze the photo and classify into exactly one of the following 4 categories for figure_category:
1. '접사/디테일' (Macro/Detail: face, eye decals, fine paint, close-up)
   Focus: 눈동자 데칼(eye decals) pin-sharp focus, appropriate macro depth of field (avoid blurring key facial contours), dust/blemish control, specular hotspot control.
2. '일상/야외 스냅' (Daily/Outdoor Snap: natural outdoor lighting, café, travel companion)
   Focus: 자연광(natural light: backlight/sidelight) creative use, believable scale harmony with real environment, seasonal storytelling, natural framing/horizon.
3. '스튜디오 연출/디오라마' (Studio Diorama: backdrops, multi-point lighting, diorama props, effect parts)
   Focus: dimensional lighting (key/fill/rim), scale consistency between diorama and figure, dynamic posing, translucent/effect lighting.
4. '일반 피규어 촬영' (Standard Figure: clean full-body or upper-body portrait)
   Focus: distortion-free focal length and framing, clean background separation, natural skin tone and plastic finish balance."""

    return f"""You are an expert photography critic evaluating figure and character model photography (피규어 및 캐릭터 모델 사진(Figure Photography)).
Provide an objective, nuanced critique based purely on observed visual and optical evidence.

{category_instruction}

[핵심 심사 원칙: 객관적 변별력 및 스타일 중립성] (Core Evaluation Principles):
1. 억지 칭찬도, 억지 트집 잡기(Nitpicking)도 지양하세요 (Objective Discrimination without Nitpicking):
   - Avoid score inflation on mediocre snapshots, but do not invent trivial flaws just to lower scores on genuinely accomplished shots.
2. 스타일 중립성 (Style Neutrality: Intentional Aesthetics vs Technical Flaws):
   - High-key/low-key, shallow/deep depth of field (bokeh), generous negative space/tight crop, and foreground layering are creative stylistic choices.
   - Judge whether the chosen aesthetic effectively showcases the figure's sculptural beauty and storytelling. Do not treat visible figure support stands or darkened peripheries as automatic defects.
3. 세부 영역 간 독립적 평가 (Prevent Halo Effect):
   - Evaluate Composition, Lighting, Color, and Technique independently. Excellent lens sharpness, bokeh, or clean colors (technique) must not artificially inflate composition (framing, limb cropping, headroom) or lighting (dimensionality, contrast control).
4. 세부 평가 메모 작성 형식 (Notes Format Requirement):
   - All critique notes (composition, lighting, color, technique) MUST be written in Korean using the format:
     [장점] <strengths in Korean>
     [단점] <shortcomings in Korean, or '감점할 만한 뚜렷한 결함 없음' if practically flawless>

[점수 평가 기준 (10점 만점 척도)]:
- 9.0 ~ 10.0: [프로사진작가 및 전문가급] - Commercial portfolio or exhibition quality. Flawless harmony of optics, lighting design, framing, and narrative depth.
- 8.0 ~ 8.9: [매우 우수] - Skilled photographer level.
  * 8.0~8.4: Solid, well-executed A-cut with strong optical fundamentals.
  * 8.5~8.9: Near-commercial excellence with thoughtful staging, but with a minor imperfection in one area.
- 7.0 ~ 7.9: [우수] - Solid fundamentals, but with clear room for improvement (e.g., flat lighting, awkward limb cropping, distracting background).
- 5.0 ~ 6.9: [보통 (일반 스냅)] - Casual record shot. Flat lighting, cluttered background, or composition imbalance.
- < 5.0: [개선 필요 (기초 미흡)] - Critical flaws (missed focus, camera shake, severe exposure failure).

Evaluation Fields:
- composition: Framing, leading lines, balance, negative space ([장점] and [단점] in Korean)
- lighting: Direction, quality, exposure, highlights/shadows ([장점] and [단점] in Korean)
- color: Hue, saturation, harmony, mood ([장점] and [단점] in Korean)
- technique: Sharpness, focus, depth of field, camera settings ([장점] and [단점] in Korean)
- focus_status: 피규어 눈동자(아이 데칼) 및 안면 조형의 초점 정밀 상태 ('완벽 칼초점', '미세 앞핀', '미세 뒤핀', '초점 이탈', '판별 불가' 중 택1)
- focus_notes: One-line concise rationale in Korean
- composition_score, lighting_score, color_score, technique_score: 0.0 ~ 10.0
- final_score: Holistic score (0.0 ~ 10.0) reflecting overall artistic and technical accomplishment
- final_reason: Comprehensive summary in Korean explaining the score
- strengths: 2-3 key strengths in Korean
- improvements: 1-3 actionable suggestions in Korean

미학 태깅(aesthetic_tags):
- 아래 8개 범주별로 이미지에서 직접 확인되는 태그를 0~3개 선택하세요.
- Required categories: mood (1-3 tags), color_impression (1-3 tags), light_expression (1-3 tags).
{tag_section}

[시각적 워터마크/하단 프레임 촬영 설정 감지 지침] (Detected Camera Settings / Watermark):
- If camera settings (body, lens, aperture, shutter speed, ISO) are visually printed in the photo border/watermark, extract them into detected_camera_settings. If absent, set to null.
- Do not penalize aesthetic margins/letterboxes as composition defects.

IMPORTANT: All user-facing critique texts (notes, reasons, strengths, improvements) MUST be written in natural, fluent Korean.

Safe EXIF Data:
{camera_settings}
"""


def build_cross_check_prompt(
    photo: Any,
    category_hint: str | None = None,
) -> str:
    """Build figure photo critique prompt for OpenAI cross-check in concise English with Korean output."""
    safe_exif = getattr(photo, "safe_exif", {})
    camera_settings = json.dumps(safe_exif, ensure_ascii=False, sort_keys=True)
    if not safe_exif:
        camera_settings = "{} (No safe EXIF camera settings available)"

    if category_hint and category_hint in FIGURE_CATEGORIES:
        cat_info = FIGURE_CATEGORIES[category_hint]
        category_instruction = f"""[Category: {cat_info['label']}] ({cat_info['description']}). Focus: {cat_info['focus']}"""
    else:
        category_instruction = """[Figure Photography Category Classification]
Analyze the photo and classify into one of the following 4 categories:
1. '접사/디테일' (Macro/Detail: face, eye decals, fine paint, close-up)
   Focus: pin-sharp eye decals, appropriate macro depth of field (avoid blurring key facial contours), dust/blemish control, specular hotspot control.
2. '일상/야외 스냅' (Daily/Outdoor Snap: natural outdoor lighting, café, travel companion)
   Focus: creative use of natural light (backlight/sidelight), believable scale harmony with real environment, seasonal storytelling, natural framing/horizon.
3. '스튜디오 연출/디오라마' (Studio Diorama: backdrops, multi-point lighting, diorama props, effect parts)
   Focus: dimensional lighting (key/fill/rim), scale consistency between diorama and figure, dynamic posing, translucent/effect lighting.
4. '일반 피규어 촬영' (Standard Figure: clean full-body or upper-body portrait)
   Focus: distortion-free focal length and framing, clean background separation, natural skin tone and plastic finish balance."""

    return f"""You are a professional figure photography curator and visual critic.
Provide an objective, balanced critique based strictly on observed visual and optical facts.

{category_instruction}

[Core Principles]:
- Avoid excessive flattery and artificial nitpicking.
- Distinguish artistic intent from technical flaws. High-key/low-key, shallow/deep DoF, and tight/wide framing are stylistic choices.
- In composition_critique and lighting_critique, strictly use the '[장점] ... [아쉬운 점] ...' format in Korean. If an area has no significant flaw, write '[아쉬운 점] 감점할 만한 뚜렷한 결함 없음'.

[4-Stage Thought Process]:
1. Composition & Framing: Framing, eye flow, balance, background separation, 3D depth vs 2D flatness.
2. Lighting & Exposure: Light direction/quality, sculptural dimensionality, exposure, plastic hotspot control, shadow detail. (Glossy materials like bunny suits/mecha/clear parts have natural specular highlights; do not misjudge them as plastic hotspots.)
3. Color & Optical Sharpness: Color harmony, white balance, eye decal focus sharpness, and optical resolving power.
4. Holistic Score: Derive final score (0.0 - 10.0) reflecting overall artistic and technical accomplishment.

[Scoring Rubric (10-Point Scale)]:
- 9.0 ~ 10.0: [Professional / Masterpiece] - Commercial portfolio or gallery quality. Masterful control of focus, light, composition, and mood. (Do not cap scores at 8.3~8.5 merely because minor alternative suggestions exist in improvements.)
- 8.0 ~ 8.9: [Very Good] - Advanced photographer level. Clear subject, high execution. (8.0~8.4: Solid A-cut / 8.5~8.9: Near-commercial excellence with minor shortcoming in one aspect).
- 7.0 ~ 7.9: [Good / Competent] - Solid fundamentals, but noticeable room for improvement (flat lighting, awkward crop, cluttered background).
- 5.0 ~ 6.9: [Average Snapshot] - Casual record shot with common snapshot limitations.
- < 5.0: [Needs Improvement] - Significant technical defects (missed focus, severe shake, blown exposure).

[Output Language Requirement]:
- All critique texts (composition_critique, lighting_critique, reason, strengths, improvements) MUST be written in natural, fluent Korean only. Do NOT output Japanese or English in these fields.

Safe EXIF Data:
{camera_settings}
"""


_build_prompt = build_grader_prompt

__all__ = ["build_grader_prompt", "_build_prompt", "build_cross_check_prompt"]
