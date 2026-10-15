"""photo_tag_schema.py - Backward compatibility shim re-exporting from app.models.analysis."""

from app.models.analysis import (
    AESTHETIC_TAG_CATEGORIES,
    AESTHETIC_TAG_OPTIONS,
    FIGURE_CATEGORIES,
    FIGURE_CATEGORY_CHOICES,
    FOCUS_STATUS_OPTIONS,
    SCORE_GRADE_BENCHMARKS,
    AestheticTags,
    PhotoAnalysis,
    get_score_grade,
)

__all__ = [
    "AESTHETIC_TAG_CATEGORIES",
    "AESTHETIC_TAG_OPTIONS",
    "FIGURE_CATEGORIES",
    "FIGURE_CATEGORY_CHOICES",
    "FOCUS_STATUS_OPTIONS",
    "SCORE_GRADE_BENCHMARKS",
    "AestheticTags",
    "PhotoAnalysis",
    "get_score_grade",
]
