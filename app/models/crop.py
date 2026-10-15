"""app.models.crop - Pydantic models for SNS crops, ratios, and social captions."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CropBox(BaseModel):
    """Normalized bounding box coordinates (0.0 to 1.0) and rationale for social media cropping."""

    model_config = ConfigDict(extra="forbid")

    ymin: float = Field(description="크롭 영역 상단 Y (0.0 ~ 1.0)")
    xmin: float = Field(description="크롭 영역 좌측 X (0.0 ~ 1.0)")
    ymax: float = Field(description="크롭 영역 하단 Y (0.0 ~ 1.0)")
    xmax: float = Field(description="크롭 영역 우측 X (0.0 ~ 1.0)")
    ratio_label: str = Field(description="비율 라벨 (예: '4:5 (인스타 세로)', '1:1 (정방형)', '16:9 (X 가로)', '3:4 (X 세로)')")
    composition_tip: str = Field(description="해당 비율 크롭 시 피규어 시선/여백/프레이밍 의도 및 연출 팁")

    @model_validator(mode="after")
    def validate_coordinates(self) -> CropBox:
        if not (0.0 <= self.ymin < self.ymax <= 1.0):
            raise ValueError(
                f"ymin과 ymax는 0.0 <= ymin < ymax <= 1.0 범위여야 합니다: ymin={self.ymin}, ymax={self.ymax}"
            )
        if not (0.0 <= self.xmin < self.xmax <= 1.0):
            raise ValueError(
                f"xmin과 xmax는 0.0 <= xmin < xmax <= 1.0 범위여야 합니다: xmin={self.xmin}, xmax={self.xmax}"
            )
        return self


class CropSet(BaseModel):
    """All four SNS crop recommendations and AI best ratio recommendation produced by a single Gemini call."""

    model_config = ConfigDict(extra="forbid")

    instagram_crop_4_5: CropBox
    instagram_crop_1_1: CropBox
    x_crop_16_9: CropBox
    x_crop_3_4: CropBox
    best_ratio_key: str = Field(
        default="instagram_crop_4_5",
        description="AI 자체 선정 최적 비율 키: 'original'(크롭 불필요/원본 최적), 'instagram_crop_4_5', 'instagram_crop_1_1', 'x_crop_16_9', 'x_crop_3_4' 중 택1",
    )
    best_ratio_reason: str = Field(
        default="",
        description="해당 비율(또는 원본 유지)을 최적의 구도로 선정한 구체적인 시각적/미학적 근거 1~2줄",
    )
    original_tip: str = Field(
        default="",
        description="원본 프레이밍(노크롭) 상태의 피규어 구도/여백/공간감에 대한 분석 및 연출 코멘트 1~2줄",
    )


class SNSCaptionAndTags(BaseModel):
    """Pydantic model for on-demand SNS caption & hashtags generation."""

    model_config = ConfigDict(extra="forbid")

    social_caption: str = Field(description="인스타 및 X 피드용 감성적인 짧은 캡션 (2~3줄, 이모지 포함)")
    hashtags: list[str] = Field(description="피규어 특화 추천 해시태그 목록 (#피규어, #figurephotography 등 8~12개)")


class SNSAdvice(BaseModel):
    """Pydantic model for on-demand SNS platform crops (Instagram, X) and social captions."""

    model_config = ConfigDict(extra="forbid")

    instagram_crop_4_5: CropBox | None = Field(default=None, description="인스타그램 피드 표준 4:5 세로 크롭 영역 (ymin, xmin, ymax, xmax)")
    instagram_crop_1_1: CropBox | None = Field(default=None, description="인스타그램 1:1 정방형 크롭 영역")
    x_crop_16_9: CropBox | None = Field(default=None, description="X(트위터) 타임라인 최적화 16:9 가로 크롭 영역")
    x_crop_3_4: CropBox | None = Field(default=None, description="X(트위터) 세로 최적화 3:4 크롭 영역")
    best_ratio_key: str | None = Field(
        default=None,
        description="AI 자체 선정 최적 비율 키: 'original'(크롭 불필요/원본 최적), 'instagram_crop_4_5', 'instagram_crop_1_1', 'x_crop_16_9', 'x_crop_3_4' 중 택1",
    )
    best_ratio_reason: str | None = Field(
        default=None,
        description="해당 비율(또는 원본 유지)을 최적의 구도로 선정한 구체적인 시각적/미학적 근거 1~2줄",
    )
    original_tip: str | None = Field(
        default=None,
        description="원본 프레이밍(노크롭) 상태의 피규어 구도/여백/공간감에 대한 분석 및 연출 코멘트 1~2줄",
    )
    social_caption: str | None = Field(default=None, description="인스타 및 X 피드용 감성적인 짧은 캡션 (2~3줄, 이모지 포함)")
    hashtags: list[str] = Field(default_factory=list, description="피규어 특화 추천 해시태그 목록")
