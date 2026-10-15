"""app.models.analysis - Data models for photo evaluation and aesthetic tags."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

AESTHETIC_TAG_CATEGORIES = {
    "viewpoint": "시점",
    "composition_space": "구도·공간",
    "pose_gaze": "포즈·시선",
    "mood": "분위기",
    "subject_background": "피사체-배경 관계",
    "light_expression": "빛 표현",
    "color_impression": "색조 인상",
    "narrative_implication": "이야기 암시",
}

AESTHETIC_TAG_OPTIONS = {
    "viewpoint": (
        "정면", "측면", "후면", "사선", "아이레벨", "로우 앵글", "하이 앵글",
        "탑뷰", "버드아이뷰", "웜즈아이뷰", "오버숄더",
    ),
    "composition_space": (
        "중앙 구도", "삼분할 구도", "대칭 구도", "프레임 인 프레임", "여백 강조",
        "클로즈업", "미디엄샷", "와이드샷", "원근 강조", "레이어드 공간", "얕은 심도", "깊은 심도",
    ),
    "pose_gaze": (
        "정면 응시", "시선 분산", "시선 회피", "시선 상향", "시선 하향", "자연스러운 동작",
        "정지 포즈", "걷는 중", "앉은 자세", "뒷모습",
    ),
    "mood": (
        "차가움", "따뜻함", "청량함", "화사함", "고요함", "생동감", "몽환적", "신비로움",
        "다크·누아르", "사이버펑크·네온", "레트로·빈티지", "시네마틱", "평온함", "쓸쓸함",
        "고독함", "친밀함", "웅장함", "장난스러움", "역동적", "서정적", "긴장감",
    ),
    "subject_background": (
        "배경과 분리", "배경과 조화", "배경 단순", "배경 복잡", "자연스러운 맥락", "환경과 상호작용", "디오라마 일체감",
    ),
    "light_expression": (
        "자연광", "스튜디오 조명", "역광", "측광", "순광", "확산광", "강한 명암", "부드러운 그림자", "실루엣",
        "하이라이트 강조", "저조도", "림라이트", "네온·컬러조명",
    ),
    "color_impression": (
        "따뜻한 톤", "차가운 톤", "쿨톤(차가움)", "웜톤(따뜻함)", "파스텔", "비비드 컬러",
        "저채도", "고채도", "모노톤", "자연색", "강한 색 대비", "하이키(밝음)", "로우키(어두움)",
    ),
    "narrative_implication": (
        "일상의 순간", "여행 기록", "관찰자 시점", "인물 중심", "풍경 서사", "특정 상황 암시",
        "관계 암시", "열린 결말 느낌", "정적인 장면", "결정적 순간",
    ),
}


class AestheticTags(BaseModel):
    """Controlled, category-based visual tags used for filtering and summaries."""

    model_config = ConfigDict(extra="forbid")

    viewpoint: list[str] = Field(description="시점 태그")
    composition_space: list[str] = Field(description="구도·공간 태그")
    pose_gaze: list[str] = Field(description="포즈·시선 태그")
    mood: list[str] = Field(description="분위기 태그")
    subject_background: list[str] = Field(description="피사체-배경 관계 태그")
    light_expression: list[str] = Field(description="빛 표현 태그")
    color_impression: list[str] = Field(description="색조 인상 태그")
    narrative_implication: list[str] = Field(description="이야기 암시 태그")

    @classmethod
    def empty(cls) -> AestheticTags:
        """Build empty values for older analyses created before tagging existed."""
        return cls(**{category_key: [] for category_key in AESTHETIC_TAG_OPTIONS})

    @field_validator(*AESTHETIC_TAG_OPTIONS.keys())
    @classmethod
    def validate_controlled_vocabulary(cls, values: list[str], info: Any) -> list[str]:
        if len(values) > 3:
            raise ValueError("각 태그 범주에는 최대 3개까지 입력할 수 있습니다.")
        if any(not value or value.strip() != value for value in values):
            raise ValueError("태그는 공백 없이 정해진 표기 그대로 입력해야 합니다.")
        if len(set(values)) != len(values):
            raise ValueError("같은 태그를 한 범주에 중복 입력할 수 없습니다.")
        allowed = AESTHETIC_TAG_OPTIONS[info.field_name]
        invalid = [value for value in values if value not in allowed]
        if invalid:
            raise ValueError(f"허용되지 않은 태그입니다: {', '.join(invalid)}")
        return values


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


class PhotoAnalysis(BaseModel):
    """Strict JSON model returned by Gemini and stored in SQLite."""

    model_config = ConfigDict(extra="forbid")

    composition_score: float = Field(description="구도 점수 (0~10). 7점: 우수, 8점: 매우 우수, 9점: 프로사진작가 및 전문가급")
    composition_notes: str = Field(description="구도 평가. 반드시 '[장점]'과 '[단점]'을 명확히 구분하여 서술")
    lighting_score: float = Field(description="조명 점수 (0~10). 7점: 우수, 8점: 매우 우수, 9점: 프로사진작가 및 전문가급")
    lighting_notes: str = Field(description="빛의 방향/노출/명암 평가. 반드시 '[장점]'과 '[단점]'을 명확히 구분하여 서술")
    color_score: float = Field(description="색감 점수 (0~10). 7점: 우수, 8점: 매우 우수, 9점: 프로사진작가 및 전문가급")
    color_notes: str = Field(description="색조/채도/조화 평가. 반드시 '[장점]'과 '[단점]'을 명확히 구분하여 서술")
    technique_score: float = Field(description="촬영 기술 점수 (0~10). 7점: 우수, 8점: 매우 우수, 9점: 프로사진작가 및 전문가급")
    technique_notes: str = Field(description="초점/선명도/설정 적절성 평가. 반드시 '[장점]'과 '[단점]'을 명확히 구분하여 서술")
    final_score: float = Field(description="사진 전체 최종 종합 점수 (0~10). 7점: 우수, 8점: 매우 우수, 9점: 프로사진작가 및 전문가급")
    final_reason: str = Field(description="최종 점수 근거. 장점과 단점을 균형 있게 분석하고 해당 점수를 부여한 명확한 이유 제시")
    strengths: list[str] = Field(description="사진의 주요 장점 목록 (실제 돋보이는 핵심 강점)")
    improvements: list[str] = Field(description="사진의 단점, 아쉬운 점 및 다음 촬영을 위한 개선점 목록")
    figure_category: str = Field(
        default="일반 피규어 촬영",
        description="피규어 사진 하위 유형: '접사/디테일', '일상/야외 스냅', '스튜디오 연출/디오라마', '일반 피규어 촬영' 중 택1",
    )
    detected_camera_settings: dict[str, str] | None = Field(
        default=None,
        description="사진 하단 프레임이나 워터마크에 인쇄된 시각적 촬영 설정(카메라, 조리개, 셔터, ISO, 렌즈 등) 추출 결과. 없거나 불확실하면 null",
    )
    focus_status: str = Field(
        default="완벽 칼초점",
        description="피규어 눈동자/페이스 초점 핀 정밀 판정: '완벽 칼초점', '미세 앞핀', '미세 뒤핀', '초점 이탈', '판별 불가' 중 택1",
    )
    focus_notes: str = Field(
        default="",
        description="초점이 맞은 부위(눈동자, 의상, 배경 등) 및 심도 상태에 대한 1줄 분석 근거",
    )
    aesthetic_tags: AestheticTags = Field(
        default_factory=AestheticTags.empty,
        description="시각적 근거에 기반한 범주별 미학 태그",
    )

    @classmethod
    def model_json_schema(cls, *args: Any, **kwargs: Any) -> dict[str, Any]:
        schema = super().model_json_schema(*args, **kwargs)
        tag_properties = schema.get("$defs", {}).get("AestheticTags", {}).get("properties", {})
        for category_key, allowed_tags in AESTHETIC_TAG_OPTIONS.items():
            field_schema = tag_properties.get(category_key)
            if isinstance(field_schema, dict):
                field_schema["items"] = {"type": "string", "enum": list(allowed_tags)}
        required = list(schema.get("required", []))
        if "aesthetic_tags" not in required:
            required.append("aesthetic_tags")
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

FOCUS_STATUS_OPTIONS = (
    "완벽 칼초점",
    "미세 앞핀",
    "미세 뒤핀",
    "초점 이탈",
    "판별 불가",
)

