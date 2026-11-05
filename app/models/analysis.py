"""app.models.analysis - Data models for photo evaluation and aesthetic tags."""

from __future__ import annotations

import difflib
import json
import re
import sys
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AESTHETIC_TAG_CATEGORIES = {
    "shot_scale": "프레이밍 배율",
    "camera_angle": "카메라 앵글",
    "light_direction": "주광 방향",
    "light_quality": "빛의 성질",
    "depth_of_field": "피사계 심도",
    "color_tone": "노출 및 색조",
}

AESTHETIC_TAG_OPTIONS = {
    "shot_scale": (
        "접사(페이스/디테일)", "바스트샷(상반신)", "풀샷(전신)", "와이드(공간/배경 중심)",
    ),
    "camera_angle": (
        "아이레벨(눈높이)", "로우앵글(앙각)", "하이앵글(부감)", "더치앵글(기울임)",
    ),
    "light_direction": (
        "순광(정면광)", "측광(사광)", "역광/림라이트", "탑라이트(상단광)", "전방위 확산광",
    ),
    "light_quality": (
        "소프트(부드러운 확산광)", "하드(강한 직사광/대비)", "컬러/네온조명", "일상 앰비언트광",
    ),
    "depth_of_field": (
        "극얕은심도(배경완전흐림)", "중간심도(배경형태인식)", "깊은심도(팬포커스)",
    ),
    "color_tone": (
        "하이키/웜톤", "하이키/쿨톤", "로우키/웜톤", "로우키/쿨톤", "뉴트럴(표준톤)",
    ),
}


class AestheticTags(BaseModel):
    """Controlled physical photography recipe tags used for filtering and insights."""

    model_config = ConfigDict(extra="ignore")

    shot_scale: str = Field(default="", description="프레이밍 배율")
    camera_angle: str = Field(default="", description="카메라 앵글")
    light_direction: str = Field(default="", description="주광 방향")
    light_quality: str = Field(default="", description="빛의 성질")
    depth_of_field: str = Field(default="", description="피사계 심도")
    color_tone: str = Field(default="", description="노출 및 색조")

    @classmethod
    def empty(cls) -> AestheticTags:
        """Build empty values for older analyses or unassigned tags."""
        return cls(
            shot_scale="",
            camera_angle="",
            light_direction="",
            light_quality="",
            depth_of_field="",
            color_tone="",
        )

    @field_validator(*AESTHETIC_TAG_OPTIONS.keys(), mode="before")
    @classmethod
    def validate_recipe_tag(cls, value: Any, info: Any) -> str:
        if isinstance(value, (list, tuple)):
            if len(value) > 1:
                raise ValueError(f"단일 선택 태그입니다. 여러 개를 지정할 수 없습니다: {value}")
            value = value[0] if value else ""
        if value is None or value == "":
            return ""
        if not isinstance(value, str):
            raise ValueError(f"문자열 태그여야 합니다: {value!r}")
        value = value.strip()
        allowed = AESTHETIC_TAG_OPTIONS[info.field_name]
        if value in allowed:
            return value
        raise ValueError(f"허용되지 않은 태그입니다: {value!r} (허용 목록: {', '.join(allowed)})")


SCORE_GRADE_BENCHMARKS = (
    (9.0, "프로사진작가 및 전문가급"),
    (8.0, "매우 우수"),
    (7.0, "우수"),
    (5.0, "보통 (일반 스냅)"),
    (0.0, "개선 필요 (기초 미흡)"),
)


def get_score_grade(score: float | int) -> str:
    """Return a descriptive grade label based on standardized 10-point scale criteria."""
    value = float(score)
    for threshold, label in SCORE_GRADE_BENCHMARKS:
        if value >= threshold:
            return label
    return "개선 필요 (기초 미흡)"


FIGURE_CATEGORIES = {
    "macro": {
        "label": "접사/디테일",
        "description": "피규어의 얼굴, 눈동자, 무기, 의상 등 세부 조형과 도색 디테일을 초근접 촬영한 사진",
        "focus": "눈동자 데칼의 칼초점, 코/귀가 날아가지 않는 적절한 매크로 심도, 미세 먼지 및 도색 마감 통제, 번들거리는 반사광(핫스팟) 제어",
    },
    "snap": {
        "label": "일상/야외 스냅",
        "description": "야외 출사, 여행 동행, 카페 등 실제 일상 환경 속에서 피규어가 상호작용하는 스냅 사진",
        "focus": "자연광(역광/측광)의 창의적 활용, 실제 환경과 피규어의 자연스러운 스케일감 조화, 계절감 및 일상적 서사/분위기, 자연스러운 여백",
    },
    "staging": {
        "label": "스튜디오 연출/디오라마",
        "description": "배경지, 다각도 조명, 디오라마 세트, 이펙트 파츠를 활용해 극적인 세계관이나 액션 씬을 연출한 사진",
        "focus": "다각도 조명(키/필/림라이트)의 드라마틱한 입체감과 명암비, 디오라마와 피규어의 정교한 스케일 일치, 역동적인 포징, 이펙트 파츠 투과광 연출",
    },
    "general": {
        "label": "일반 피규어 촬영",
        "description": "피규어 본체 전신 또는 상반신을 중심으로 단정하게 담아낸 스탠다드 촬영",
        "focus": "피규어 원형의 왜곡 없는 렌즈 화각과 프레이밍, 단정한 배경 분리, 자연스러운 광택 및 피부톤 밸런스",
    },
}

FIGURE_CATEGORY_CHOICES = tuple(cat["label"] for cat in FIGURE_CATEGORIES.values())
FigureCategoryType = Literal[
    "접사/디테일",
    "일상/야외 스냅",
    "스튜디오 연출/디오라마",
    "일반 피규어 촬영",
]

FOCUS_STATUS_OPTIONS = (
    "완벽 칼초점",
    "미세 앞핀",
    "미세 뒤핀",
    "초점 이탈",
    "판별 불가",
)
FocusStatusType = Literal[
    "완벽 칼초점",
    "미세 앞핀",
    "미세 뒤핀",
    "초점 이탈",
    "판별 불가",
]


FOCUS_KEYWORD_MAP: dict[str, str] = {
    "칼초점": "완벽 칼초점",
    "완벽": "완벽 칼초점",
    "앞핀": "미세 앞핀",
    "전핀": "미세 앞핀",
    "뒤핀": "미세 뒤핀",
    "후핀": "미세 뒤핀",
    "이탈": "초점 이탈",
    "나감": "초점 이탈",
    "블러": "초점 이탈",
    "불가": "판별 불가",
    "판별불가": "판별 불가",
    "판별 불가": "판별 불가",
}

FIGURE_CATEGORY_KEYWORD_MAP: dict[str, str] = {
    "접사": "접사/디테일",
    "디테일": "접사/디테일",
    "매크로": "접사/디테일",
    "야외": "일상/야외 스냅",
    "스냅": "일상/야외 스냅",
    "일상": "일상/야외 스냅",
    "디오라마": "스튜디오 연출/디오라마",
    "스튜디오": "스튜디오 연출/디오라마",
    "연출": "스튜디오 연출/디오라마",
    "일반": "일반 피규어 촬영",
    "스탠다드": "일반 피규어 촬영",
}

KEYWORD_MAPS: dict[str, dict[str, str]] = {
    "focus_status": FOCUS_KEYWORD_MAP,
    "figure_category": FIGURE_CATEGORY_KEYWORD_MAP,
}


def _heal_choice(
    value: Any,
    allowed_choices: tuple[str, ...],
    fallback: str | None = None,
    field_name: str = "field",
    cutoff: float = 0.65,
) -> str | None:
    if not isinstance(value, str):
        return fallback
    cleaned = value.strip()
    if cleaned in allowed_choices:
        return cleaned

    # 1. Exact choice substring match
    for choice in allowed_choices:
        if choice in cleaned:
            print(f"[Self-Healing] {field_name} 포함일치 교정: {value!r} -> {choice!r}", file=sys.stderr)
            return choice

    # 1b. Stem / prefix match before parentheses (e.g. '측광' -> '측광(사광)', '소프트' -> '소프트(부드러운 확산광)')
    for choice in allowed_choices:
        stem = choice.split("(")[0].strip()
        if stem and (cleaned == stem or stem in cleaned or (len(cleaned) >= 2 and cleaned in stem)):
            print(f"[Self-Healing] {field_name} 어간일치 교정: {value!r} -> {choice!r}", file=sys.stderr)
            return choice
    for choice in allowed_choices:
        if len(cleaned) >= 2 and cleaned in choice:
            print(f"[Self-Healing] {field_name} 부분일치 교정: {value!r} -> {choice!r}", file=sys.stderr)
            return choice

    # 2. Distinct keyword mapping dictionary
    mapping = KEYWORD_MAPS.get(field_name, {})
    for kw, target_choice in mapping.items():
        if kw in cleaned and target_choice in allowed_choices:
            print(f"[Self-Healing] {field_name} 키워드매핑 교정: {value!r} -> {target_choice!r}", file=sys.stderr)
            return target_choice

    # 3. Difflib close matches with cutoff
    matches = difflib.get_close_matches(cleaned, allowed_choices, n=1, cutoff=cutoff)
    if matches:
        print(f"[Self-Healing] {field_name} 유사도 교정: {value!r} -> {matches[0]!r}", file=sys.stderr)
        return matches[0]

    # 4. Fallback
    if fallback is not None:
        print(f"[Self-Healing] {field_name} 비정상 값 기본 대체: {value!r} -> {fallback!r}", file=sys.stderr)
        return fallback
    return None


def heal_analysis_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Defensively sanitize and repair LLM output dict before strict Pydantic validation."""
    if not isinstance(data, dict):
        return {}

    healed = dict(data)

    # 1. Heal focus_status
    raw_focus = healed.get("focus_status")
    if raw_focus not in FOCUS_STATUS_OPTIONS:
        healed["focus_status"] = _heal_choice(
            raw_focus,
            FOCUS_STATUS_OPTIONS,
            fallback="판별 불가",
            field_name="focus_status",
            cutoff=0.6,
        )

    # 2. Heal figure_category
    raw_cat = healed.get("figure_category")
    if raw_cat not in FIGURE_CATEGORY_CHOICES:
        healed["figure_category"] = _heal_choice(
            raw_cat,
            FIGURE_CATEGORY_CHOICES,
            fallback="일반 피규어 촬영",
            field_name="figure_category",
            cutoff=0.6,
        )

    # 3. Clamp scores (0.0 to 10.0)
    for score_field in (
        "composition_score",
        "lighting_score",
        "color_score",
        "technique_score",
        "final_score",
    ):
        raw_val = healed.get(score_field)
        try:
            val = float(raw_val)
        except (TypeError, ValueError):
            print(f"[Self-Healing] {score_field} 비정상 점수 기본값(7.0) 대체: {raw_val!r}", file=sys.stderr)
            val = 7.0
        clamped = max(0.0, min(10.0, round(val, 1)))
        if clamped != val:
            print(f"[Self-Healing] {score_field} 점수 범위 조정: {val} -> {clamped}", file=sys.stderr)
        healed[score_field] = clamped

    # 4. Heal aesthetic_tags (Physical 6-Recipe Categorical Tags)
    raw_tags = healed.get("aesthetic_tags")
    if isinstance(raw_tags, dict):
        healed_tags: dict[str, str] = {}
        for cat_key, allowed_options in AESTHETIC_TAG_OPTIONS.items():
            val = raw_tags.get(cat_key)
            if isinstance(val, (list, tuple)):
                val = val[0] if val else ""
            elif not isinstance(val, str):
                val = str(val or "")
            val_str = val.strip()
            if val_str in allowed_options:
                healed_tags[cat_key] = val_str
            else:
                choice = _heal_choice(
                    val_str,
                    allowed_options,
                    fallback=allowed_options[0],
                    field_name=f"tag[{cat_key}]",
                    cutoff=0.6,
                )
                healed_tags[cat_key] = choice or allowed_options[0]
        healed["aesthetic_tags"] = healed_tags
    elif raw_tags is None:
        healed["aesthetic_tags"] = AestheticTags.empty().model_dump()

    # 5. Ensure text fields are strings
    for str_field in (
        "composition_notes",
        "lighting_notes",
        "color_notes",
        "technique_notes",
        "final_reason",
        "focus_notes",
    ):
        if str_field not in healed or healed[str_field] is None:
            healed[str_field] = ""

    # 6. Ensure list fields are lists
    for list_field in ("strengths", "improvements"):
        v = healed.get(list_field)
        if isinstance(v, str):
            healed[list_field] = [v]
        elif not isinstance(v, (list, tuple)):
            healed[list_field] = []

    healed.pop("analysis_mode", None)

    return healed


def heal_fast_analysis_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Defensively sanitize and repair lightweight LLM output dict before FastPhotoAnalysis validation."""
    if not isinstance(data, dict):
        return {}

    healed: dict[str, Any] = {}

    raw_focus = data.get("focus_status")
    if raw_focus in FOCUS_STATUS_OPTIONS:
        healed["focus_status"] = raw_focus
    else:
        healed["focus_status"] = _heal_choice(
            raw_focus,
            FOCUS_STATUS_OPTIONS,
            fallback="판별 불가",
            field_name="focus_status",
            cutoff=0.6,
        )

    raw_cat = data.get("figure_category")
    if raw_cat in FIGURE_CATEGORY_CHOICES:
        healed["figure_category"] = raw_cat
    else:
        healed["figure_category"] = _heal_choice(
            raw_cat,
            FIGURE_CATEGORY_CHOICES,
            fallback="일반 피규어 촬영",
            field_name="figure_category",
            cutoff=0.6,
        )

    for score_field in (
        "composition_score",
        "lighting_score",
        "color_score",
        "technique_score",
        "final_score",
    ):
        raw_val = data.get(score_field)
        try:
            val = float(raw_val)
        except (TypeError, ValueError):
            val = 7.0
        if 10.0 < val <= 100.0:
            val = round(val / 10.0, 1)
        healed[score_field] = max(0.0, min(10.0, round(val, 1)))

    raw_summary = data.get("quick_summary")
    healed["quick_summary"] = str(raw_summary).strip() if raw_summary is not None else ""

    raw_reason = data.get("final_reason")
    healed["final_reason"] = str(raw_reason).strip() if raw_reason is not None else ""

    return healed



class CrossCheckOpinion(BaseModel):
    """Independent second opinion / critique provided by a secondary LLM (e.g. OpenAI GPT-6 Luna)."""

    model_config = ConfigDict(extra="ignore")

    model: str = Field(default="gpt-6-luna", description="보조 비평 모델명 (예: gpt-6-luna)")
    score: float = Field(description="보조 모델이 부여한 종합 점수 (0.0~10.0)")
    reason: str = Field(description="보조 모델의 종합 비평 및 총평")
    strengths: list[str] = Field(default_factory=list, description="보조 모델이 본 주요 강점")
    improvements: list[str] = Field(default_factory=list, description="보조 모델이 제안하는 개선점")
    composition_critique: str = Field(default="", description="구도 및 프레이밍 비평")
    lighting_critique: str = Field(default="", description="조명 및 명암 비평")
    focus_status: str | None = Field(default=None, description="보조 모델이 판정한 눈동자 초점 상태")
    composition_score: float | None = Field(default=None, description="보조 모델 구도 점수")
    lighting_score: float | None = Field(default=None, description="보조 모델 조명 점수")
    color_score: float | None = Field(default=None, description="보조 모델 색감 점수")
    technique_score: float | None = Field(default=None, description="보조 모델 기술 점수")

    @field_validator("score", mode="before")
    @classmethod
    def validate_and_scale_score(cls, value: Any) -> float:
        try:
            val = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"점수는 숫자여야 합니다: {value!r}") from exc
        if 10.0 < val <= 100.0:
            val = round(val / 10.0, 1)
        clamped = max(0.0, min(10.0, round(val, 1)))
        return clamped


class OpenAICrossCheck(BaseModel):
    """Lightweight structured output model for OpenAI second-opinion critique (no aesthetic tags)."""

    model_config = ConfigDict(extra="forbid")

    composition_critique: str = Field(
        description="구도, 프레이밍, 여백, 배경 분리 및 공간적 깊이감(3D 입체감 vs 2D 평면감)에 대한 객관적 평가 (반드시 '[장점]'과 '[아쉬운 점]' 구분 선행 작성)"
    )
    lighting_critique: str = Field(
        description="빛의 방향과 질, 조형 입체감, 노출, 반사광(핫스팟) 및 그림자 디테일에 대한 객관적 평가 (반드시 '[장점]'과 '[아쉬운 점]' 구분 선행 작성)"
    )
    score: float = Field(
        description="구도·조명 비평을 종합한 최종 점수 (0.0~10.0). 기준점 6.8~7.2(스탠다드), 7.5~8.2(수작), 8.3~8.9(화보), 9.0~9.4(마스터피스), 9.5~10.0(더 레전드). 프로급 완성도 수작은 8점 후반에 머물지 말고 9.0~9.4점 적극 부여(+0.1~+0.3 시너지 반영)"
    )
    reason: str = Field(
        description="구도·조명·색감·기술의 시각적 근거를 종합한 객관적 총평 및 해당 점수를 부여한 명확한 이유"
    )
    strengths: list[str] = Field(
        description="사진에서 실제로 돋보이는 핵심 강점 목록 (1~3개, 억지로 부풀리지 말 것)"
    )
    improvements: list[str] = Field(
        description="사진의 실제 한계점 및 다음 촬영을 위한 구체적 개선 조언 목록 (1~3개, 억지 트집 지양)"
    )

    @field_validator("score", mode="before")
    @classmethod
    def validate_and_scale_score(cls, value: Any) -> float:
        try:
            val = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"점수는 숫자여야 합니다: {value!r}") from exc
        if 10.0 < val <= 100.0:
            val = round(val / 10.0, 1)
        clamped = max(0.0, min(10.0, round(val, 1)))
        return clamped


class PhotoAnalysis(BaseModel):
    """Strict JSON model returned by Gemini and stored in SQLite."""

    model_config = ConfigDict(extra="forbid")

    figure_category: FigureCategoryType = Field(
        default="일반 피규어 촬영",
        description="피규어 사진 하위 유형: '접사/디테일', '일상/야외 스냅', '스튜디오 연출/디오라마', '일반 피규어 촬영' 중 택1",
    )
    focus_status: FocusStatusType = Field(
        default="완벽 칼초점",
        description="피규어 눈동자/페이스 초점 핀 정밀 판정: '완벽 칼초점', '미세 앞핀', '미세 뒤핀', '초점 이탈', '판별 불가' 중 택1",
    )
    focus_notes: str = Field(
        default="",
        description="초점이 맞은 부위(눈동자, 의상, 배경 등) 및 심도 상태에 대한 1줄 분석 근거 및 5대 체크리스트 요약",
    )
    detected_camera_settings: dict[str, str] | None = Field(
        default=None,
        description="사진 하단 프레임이나 워터마크에 인쇄된 시각적 촬영 설정(카메라, 조리개, 셔터, ISO, 렌즈 등) 추출 결과. 없거나 불확실하면 null",
    )
    composition_notes: str = Field(description="구도 평가. 반드시 '[장점]'과 '[단점]'을 명확히 구분하여 서술")
    composition_score: float = Field(description="구도 점수 (0~10). 기준점 6.8~7.2: 깔끔한 스탠다드, 7.5~8.2: 수작, 8.3~8.9: 고완성도 화보, 9.0~9.4: 마스터피스, 9.5~10.0: 더 레전드")
    lighting_notes: str = Field(description="빛의 방향/노출/명암 평가. 반드시 '[장점]'과 '[단점]'을 명확히 구분하여 서술")
    lighting_score: float = Field(description="조명 점수 (0~10). 기준점 6.8~7.2: 깔끔한 스탠다드, 7.5~8.2: 수작, 8.3~8.9: 고완성도 화보, 9.0~9.4: 마스터피스, 9.5~10.0: 더 레전드")
    color_notes: str = Field(description="색조/채도/조화 평가. 반드시 '[장점]'과 '[단점]'을 명확히 구분하여 서술")
    color_score: float = Field(description="색감 점수 (0~10). 기준점 6.8~7.2: 깔끔한 스탠다드, 7.5~8.2: 수작, 8.3~8.9: 고완성도 화보, 9.0~9.4: 마스터피스, 9.5~10.0: 더 레전드")
    technique_notes: str = Field(description="초점/선명도/설정 적절성 평가. 반드시 '[장점]'과 '[단점]'을 명확히 구분하여 서술")
    technique_score: float = Field(description="촬영 기술 점수 (0~10). 기준점 6.8~7.2: 깔끔한 스탠다드, 7.5~8.2: 수작, 8.3~8.9: 고완성도 화보, 9.0~9.4: 마스터피스, 9.5~10.0: 더 레전드")
    final_score: float = Field(description="사진 전체 최종 종합 점수 (0~10). 단순 평균이 아닌 전체 임팩트 반영(프로급 수작은 8점대에 주저하지 말고 9.0~9.4점 적극 부여, 치명 결함 시 하방 견인)")
    final_reason: str = Field(description="최종 점수 근거. 장점과 단점을 균형 있게 분석하고 해당 점수를 부여한 명확한 이유 제시")
    strengths: list[str] = Field(description="사진의 주요 장점 목록 (실제 돋보이는 핵심 강점)")
    improvements: list[str] = Field(description="사진의 단점, 아쉬운 점 및 다음 촬영을 위한 개선점 목록")
    aesthetic_tags: AestheticTags = Field(
        default_factory=AestheticTags.empty,
        description="시각적 근거에 기반한 범주별 미학 태그",
    )
    cross_check_opinion: CrossCheckOpinion | None = Field(
        default=None,
        description="크로스 체크/앙상블 시 보조 LLM의 독립적인 평가 의견 (태그/점수 평균 대신 추가 의견으로 제공)",
    )

    @property
    def analysis_mode(self) -> Literal["full", "fast"]:
        """Return 'fast' when detailed domain notes and pros/cons lists are omitted, else 'full'."""
        has_notes = any(
            bool(val and val.strip())
            for val in (
                self.composition_notes,
                self.lighting_notes,
                self.color_notes,
                self.technique_notes,
            )
        )
        has_lists = bool(self.strengths) or bool(self.improvements)
        return "full" if (has_notes or has_lists) else "fast"

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        schema = super().model_json_schema(*args, **kwargs)
        properties = schema.get("properties", {})
        if "focus_status" in properties:
            properties["focus_status"]["enum"] = list(FOCUS_STATUS_OPTIONS)
        if "figure_category" in properties:
            properties["figure_category"]["enum"] = list(FIGURE_CATEGORY_CHOICES)
        tag_properties = schema.get("$defs", {}).get("AestheticTags", {}).get("properties", {})
        for category_key, allowed_tags in AESTHETIC_TAG_OPTIONS.items():
            field_schema = tag_properties.get(category_key)
            if isinstance(field_schema, dict):
                field_schema["type"] = "string"
                field_schema["enum"] = list(allowed_tags)
        tag_def = schema.get("$defs", {}).get("AestheticTags", {})
        if isinstance(tag_def, dict):
            tag_def["required"] = list(AESTHETIC_TAG_OPTIONS.keys())
        required = list(schema.get("required", []))
        for req_field in ("figure_category", "focus_status", "focus_notes", "aesthetic_tags"):
            if req_field not in required:
                required.append(req_field)
        schema["required"] = required
        return schema

    @field_validator(
        "composition_score",
        "lighting_score",
        "color_score",
        "technique_score",
        "final_score",
    )
    @classmethod
    def score_must_be_between_zero_and_ten(cls, value: float) -> float:
        if not 0 <= value <= 10:
            raise ValueError("점수는 0 이상 10 이하여야 합니다.")
        return value

    @field_validator("figure_category")
    @classmethod
    def validate_figure_category(cls, value: str) -> str:
        if value not in FIGURE_CATEGORY_CHOICES:
            raise ValueError(f"허용되지 않은 피규어 카테고리입니다: '{value}'. 허용: {FIGURE_CATEGORY_CHOICES}")
        return value

    @field_validator("focus_status")
    @classmethod
    def validate_focus_status(cls, value: str) -> str:
        if value not in FOCUS_STATUS_OPTIONS:
            raise ValueError(f"허용되지 않은 초점 상태입니다: '{value}'. 허용: {FOCUS_STATUS_OPTIONS}")
        return value

    @classmethod
    def from_llm_json(cls, raw_text: str | bytes | bytearray) -> PhotoAnalysis:
        """Parse raw LLM output text, extracting JSON and applying self-healing normalization."""
        if isinstance(raw_text, (bytes, bytearray)):
            text = raw_text.decode("utf-8", errors="replace")
        else:
            text = str(raw_text)

        cleaned = text.strip()
        if "```" in cleaned:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
            if match:
                cleaned = match.group(1).strip()

        if not (cleaned.startswith("{") and cleaned.endswith("}")):
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start : end + 1]

        data = json.loads(cleaned)
        healed_data = heal_analysis_payload(data)
        return cls.model_validate(healed_data)


class FastPhotoAnalysis(BaseModel):
    """Lightweight culling schema returning 5 scores, category, focus status, and 1-sentence reason."""

    model_config = ConfigDict(extra="forbid")

    figure_category: FigureCategoryType = Field(
        default="일반 피규어 촬영",
        description="피규어 사진 하위 유형: '접사/디테일', '일상/야외 스냅', '스튜디오 연출/디오라마', '일반 피규어 촬영' 중 택1",
    )
    focus_status: FocusStatusType = Field(
        default="완벽 칼초점",
        description="피규어 눈동자/페이스 초점 핀 정밀 판정: '완벽 칼초점', '미세 앞핀', '미세 뒤핀', '초점 이탈', '판별 불가' 중 택1",
    )
    quick_summary: str = Field(
        default="",
        description="점수 책정 전 5대 광학·구도 체크리스트 선행 검증(Micro-CoT): '[강점: 핵심 시각적 근거 2가지 이상] [감점: 실제 기술적 감점 요인 또는 없음(5대 체크리스트 무결점 통과)]' (사소한 연출 제안은 감점 적지 말고 '없음' 처리)",
    )
    composition_score: float = Field(description="구도 점수 (0~10). 기준점 6.8~7.2: 깔끔한 스탠다드, 7.5~8.2: 수작, 8.3~8.9: 고완성도 화보, 9.0~9.4: 마스터피스, 9.5~10.0: 더 레전드")
    lighting_score: float = Field(description="조명 점수 (0~10). 기준점 6.8~7.2: 깔끔한 스탠다드, 7.5~8.2: 수작, 8.3~8.9: 고완성도 화보, 9.0~9.4: 마스터피스, 9.5~10.0: 더 레전드")
    color_score: float = Field(description="색감 점수 (0~10). 기준점 6.8~7.2: 깔끔한 스탠다드, 7.5~8.2: 수작, 8.3~8.9: 고완성도 화보, 9.0~9.4: 마스터피스, 9.5~10.0: 더 레전드")
    technique_score: float = Field(description="촬영 기술 점수 (0~10). 기준점 6.8~7.2: 깔끔한 스탠다드, 7.5~8.2: 수작, 8.3~8.9: 고완성도 화보, 9.0~9.4: 마스터피스, 9.5~10.0: 더 레전드")
    final_score: float = Field(description="사진 전체 최종 종합 점수 (0~10). 단순 평균이 아닌 전체 임팩트 반영(프로급 수작은 8점대에 주저하지 말고 9.0~9.4점 적극 부여, 치명 결함 시 하방 견인)")
    final_reason: str = Field(
        description="최종 점수 핵심 사유 1문장 (80자 이내, [핵심 강점 1개] + [결정적 감점/보완 요인 1개] 요약)"
    )

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        schema = super().model_json_schema(*args, **kwargs)
        properties = schema.get("properties", {})
        if "focus_status" in properties:
            properties["focus_status"]["enum"] = list(FOCUS_STATUS_OPTIONS)
        if "figure_category" in properties:
            properties["figure_category"]["enum"] = list(FIGURE_CATEGORY_CHOICES)
        required = list(schema.get("required", []))
        for req_field in ("figure_category", "focus_status"):
            if req_field not in required:
                required.append(req_field)
        schema["required"] = required
        return schema

    @field_validator(
        "composition_score",
        "lighting_score",
        "color_score",
        "technique_score",
        "final_score",
    )
    @classmethod
    def score_must_be_between_zero_and_ten(cls, value: float) -> float:
        if not 0 <= value <= 10:
            raise ValueError("점수는 0 이상 10 이하여야 합니다.")
        return value

    @field_validator("figure_category")
    @classmethod
    def validate_figure_category(cls, value: str) -> str:
        if value not in FIGURE_CATEGORY_CHOICES:
            raise ValueError(f"허용되지 않은 피규어 카테고리입니다: '{value}'. 허용: {FIGURE_CATEGORY_CHOICES}")
        return value

    @field_validator("focus_status")
    @classmethod
    def validate_focus_status(cls, value: str) -> str:
        if value not in FOCUS_STATUS_OPTIONS:
            raise ValueError(f"허용되지 않은 초점 상태입니다: '{value}'. 허용: {FOCUS_STATUS_OPTIONS}")
        return value

    @classmethod
    def from_llm_json(cls, raw_text: str | bytes | bytearray) -> FastPhotoAnalysis:
        """Parse raw lightweight LLM output text, extracting JSON and applying self-healing."""
        if isinstance(raw_text, (bytes, bytearray)):
            text = raw_text.decode("utf-8", errors="replace")
        else:
            text = str(raw_text)

        cleaned = text.strip()
        if "```" in cleaned:
            match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned)
            if match:
                cleaned = match.group(1).strip()

        if not (cleaned.startswith("{") and cleaned.endswith("}")):
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start != -1 and end != -1 and end > start:
                cleaned = cleaned[start : end + 1]

        data = json.loads(cleaned)
        healed_data = heal_fast_analysis_payload(data)
        return cls.model_validate(healed_data)

    def to_photo_analysis(self) -> PhotoAnalysis:
        """Convert FastPhotoAnalysis into a full PhotoAnalysis record with empty notes/tags (fast mode)."""
        return PhotoAnalysis(
            composition_score=self.composition_score,
            composition_notes="",
            lighting_score=self.lighting_score,
            lighting_notes="",
            color_score=self.color_score,
            color_notes="",
            technique_score=self.technique_score,
            technique_notes="",
            final_score=self.final_score,
            final_reason=self.final_reason,
            strengths=[],
            improvements=[],
            figure_category=self.figure_category,
            detected_camera_settings=None,
            focus_status=self.focus_status,
            focus_notes=self.quick_summary or "",
            aesthetic_tags=AestheticTags.empty(),
        )

    def to_cross_check_opinion(self, model_name: str) -> CrossCheckOpinion:
        """Convert FastPhotoAnalysis into a CrossCheckOpinion for second-opinion display."""
        strengths: list[str] = []
        improvements: list[str] = []

        qs = self.quick_summary or ""
        s_match = re.search(r"\[강점:\s*([^\]]+)\]", qs)
        i_match = re.search(r"\[감점:\s*([^\]]+)\]", qs)

        if s_match:
            strengths.append(s_match.group(1).strip())
        if i_match:
            val = i_match.group(1).strip()
            if val and "없음" not in val:
                improvements.append(val)

        if not strengths and self.focus_status:
            strengths.append(f"초점: {self.focus_status}")

        if not improvements and self.final_reason:
            improvements.append(self.final_reason)

        reason_text = self.final_reason or self.quick_summary or "경량 교차 검증 완료"

        return CrossCheckOpinion(
            model=model_name,
            score=self.final_score,
            reason=reason_text,
            strengths=strengths,
            improvements=improvements,
            composition_critique="",
            lighting_critique="",
            focus_status=self.focus_status,
            composition_score=self.composition_score,
            lighting_score=self.lighting_score,
            color_score=self.color_score,
            technique_score=self.technique_score,
        )



