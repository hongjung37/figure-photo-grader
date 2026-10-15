"""app.services - Core domain services for Gemini API, image processing, burst detection, and XMP."""

from app.services.burst_detector import (
    are_burst_pair,
    are_filenames_sequential,
    cluster_burst_groups,
    parse_photo_time,
)
from app.services.gemini_client import (
    analyze_with_gemini,
    generate_all_sns_crops,
    generate_lightroom_advice,
    generate_single_sns_crop,
    generate_sns_advice,
    generate_sns_caption_and_tags,
    get_usage_stats,
    set_usage_log_db,
)
from app.services.image_processor import (
    PreparedPhoto,
    compute_dhash_from_bytes,
    dhash_from_sqlite,
    dhash_to_sqlite,
    extract_safe_exif,
    get_original_photo_path,
    hamming_distance,
    make_thumbnail_bytes,
    prepare_photo,
    save_original_photo,
)
from app.services.batch_service import run_batch_pipeline
from app.services.xmp_service import (
    generate_xmp_xml,
    score_to_rating_and_label,
    write_xmp_sidecar,
)

__all__ = [
    "are_burst_pair",
    "are_filenames_sequential",
    "cluster_burst_groups",
    "parse_photo_time",
    "analyze_with_gemini",
    "generate_all_sns_crops",
    "generate_lightroom_advice",
    "generate_single_sns_crop",
    "generate_sns_advice",
    "generate_sns_caption_and_tags",
    "get_usage_stats",
    "set_usage_log_db",
    "PreparedPhoto",
    "compute_dhash_from_bytes",
    "dhash_from_sqlite",
    "dhash_to_sqlite",
    "extract_safe_exif",
    "get_original_photo_path",
    "hamming_distance",
    "make_thumbnail_bytes",
    "prepare_photo",
    "save_original_photo",
    "generate_xmp_xml",
    "score_to_rating_and_label",
    "write_xmp_sidecar",
    "run_batch_pipeline",
]
