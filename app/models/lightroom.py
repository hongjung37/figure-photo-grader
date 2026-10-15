"""app.models.lightroom - Pydantic model for Adobe Lightroom slider recommendations."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LightroomAdvice(BaseModel):
    """Pydantic model for on-demand Adobe Lightroom post-processing slider recommendations."""

    model_config = ConfigDict(extra="forbid")

    exposure: float = Field(description="노출 슬라이더 추천값 (-5.00 ~ +5.00, 소수점 둘째자리)")
    contrast: int = Field(description="대비 슬라이더 추천값 (-100 ~ +100)")
    highlights: int = Field(description="밝은 영역 (하이라이트) 추천값 (-100 ~ +100)")
    shadows: int = Field(description="어두운 영역 (그림자) 추천값 (-100 ~ +100)")
    whites: int = Field(description="흰색 계열 추천값 (-100 ~ +100)")
    blacks: int = Field(description="검정 계열 추천값 (-100 ~ +100)")
    texture: int = Field(description="텍스처 슬라이더 추천값 (-100 ~ +100)")
    clarity: int = Field(description="명료도 (부분 대비) 추천값 (-100 ~ +100)")
    dehaze: int = Field(description="디헤이즈 추천값 (-100 ~ +100)")
    vibrance: int = Field(description="활기 슬라이더 추천값 (-100 ~ +100)")
    saturation: int = Field(description="채도 슬라이더 추천값 (-100 ~ +100)")
    temp_tint_notes: str = Field(description="화이트밸런스/색온도/색조 가이드 (예: 5200K 유지, 틴트 +4 등)")
    retouching_guide: str = Field(description="피규어 특성에 맞춘 마스킹 및 세부 후보정 팁 (아이 데칼 캐치라이트 살리기, 피부 번들거림 방지 등)")

    @field_validator("exposure", mode="before")
    @classmethod
    def validate_exposure(cls, v: Any) -> float:
        try:
            flt_val = float(v)
        except (TypeError, ValueError):
            raise ValueError(f"exposure는 실수여야 합니다: {v}")
        if not -5.0 <= flt_val <= 5.0:
            raise ValueError(f"exposure는 -5.00 ~ +5.00 범위여야 합니다: {flt_val}")
        return round(flt_val, 2)

    @field_validator(
        "contrast",
        "highlights",
        "shadows",
        "whites",
        "blacks",
        "texture",
        "clarity",
        "dehaze",
        "vibrance",
        "saturation",
        mode="before",
    )
    @classmethod
    def validate_slider_range(cls, v: Any, info: Any) -> int:
        try:
            int_val = round(float(v))
        except (TypeError, ValueError):
            raise ValueError(f"{info.field_name}는 정수여야 합니다: {v}")
        if not -100 <= int_val <= 100:
            raise ValueError(f"{info.field_name}는 -100 ~ +100 범위여야 합니다: {int_val}")
        return int_val
