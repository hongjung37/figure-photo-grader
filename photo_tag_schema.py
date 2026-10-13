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
        "고요함", "생동감", "고독함", "따뜻함", "긴장감", "몽환적", "평온함", "쓸쓸함",
        "친밀함", "웅장함", "장난스러움", "역동적",
    ),
    "subject_background": (
        "배경과 분리", "배경과 조화", "배경 단순", "배경 복잡", "자연스러운 맥락", "환경과 상호작용",
    ),
    "light_expression": (
        "역광", "측광", "순광", "확산광", "강한 명암", "부드러운 그림자", "실루엣",
        "하이라이트 강조", "저조도",
    ),
    "color_impression": (
        "따뜻한 톤", "차가운 톤", "저채도", "고채도", "모노톤", "파스텔", "자연색", "강한 색 대비",
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
