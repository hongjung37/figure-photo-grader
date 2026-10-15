"""db package - Database access layer for photo analysis dashboard."""

from db.repository import (
    delete_analyses,
    ensure_db_columns,
    find_existing_analysis,
    get_all_analyses,
    get_analyses_and_tags_for_export,
    get_analysis_row_by_id,
    get_photo_thumbnail_and_hash,
    get_tag_stats,
    update_lr_advice,
    update_photo_thumbnail,
    update_review_status,
    update_sns_advice,
    update_user_score,
)

__all__ = [
    "delete_analyses",
    "ensure_db_columns",
    "find_existing_analysis",
    "get_all_analyses",
    "get_analyses_and_tags_for_export",
    "get_analysis_row_by_id",
    "get_photo_thumbnail_and_hash",
    "get_tag_stats",
    "update_lr_advice",
    "update_photo_thumbnail",
    "update_review_status",
    "update_sns_advice",
    "update_user_score",
]
