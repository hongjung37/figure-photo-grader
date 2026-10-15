"""db - Backward compatibility shim re-exporting from app.db."""

from app.db import (
    delete_analyses,
    ensure_db_columns,
    ensure_tag_tables,
    find_existing_analysis,
    get_all_analyses,
    get_analyses_and_tags_for_export,
    get_analysis_row_by_id,
    get_photo_thumbnail_and_hash,
    get_tag_stats,
    save_analysis,
    sync_analysis_tags,
    update_lr_advice,
    update_photo_thumbnail,
    update_review_status,
    update_sns_advice,
    update_user_score,
)

__all__ = [
    "delete_analyses",
    "ensure_db_columns",
    "ensure_tag_tables",
    "find_existing_analysis",
    "get_all_analyses",
    "get_analyses_and_tags_for_export",
    "get_analysis_row_by_id",
    "get_photo_thumbnail_and_hash",
    "get_tag_stats",
    "save_analysis",
    "sync_analysis_tags",
    "update_lr_advice",
    "update_photo_thumbnail",
    "update_review_status",
    "update_sns_advice",
    "update_user_score",
]
