from __future__ import annotations

"""Compatibility shim for app packages.

All core functionality has been refactored into:
- app.config: configurations and constants
- app.models: data models and schemas
- app.prompts: AI prompts
- app.services: business logic (Gemini, image processing, batch, XMP)
- app.db: repository and database connection
- app.exporters: Excel and HTML exporters
"""

import argparse
import sys
from pathlib import Path
from typing import Any

from google import genai
from PIL import Image

# Re-exports from app.config
from app.config import (
    DEFAULT_DB_PATH,
    DEFAULT_MODEL,
    DEFAULT_TIER,
    ENV_FILE_PATH,
    EXIF_IFD_ID,
    EXIF_IFD_TAG_NAMES,
    FALLBACK_MODEL,
    MAX_BASE64_IMAGE_BYTES,
    MAX_IMAGE_EDGE,
    MODEL_PRESETS,
    OPENAI_MODEL_PRESETS,
    DEFAULT_OPENAI_MODEL,
    ALL_MODEL_PRESETS,
    ORIGINALS_DIR_NAME,
    PORT,
    SAFE_EXIF_FIELDS,
    SNS_CROP_RATIO_CONFIGS,
    SUPPORTED_FORMATS,
    UPLOAD_EXIF_FIELDS,
)

# Re-exports from app.models
from app.models.analysis import (
    AESTHETIC_TAG_CATEGORIES,
    AESTHETIC_TAG_OPTIONS,
    FIGURE_CATEGORIES,
    FIGURE_CATEGORY_CHOICES,
    SCORE_GRADE_BENCHMARKS,
    AestheticTags,
    CrossCheckOpinion,
    PhotoAnalysis,
    get_score_grade,
)
from app.models.crop import (
    CropBox,
    CropSet,
    SNSAdvice,
    SNSCaptionAndTags,
)
from app.models.lightroom import LightroomAdvice

# Re-exports from app.prompts
from app.prompts.caption_prompts import build_caption_and_tags_prompt
from app.prompts.crop_prompts import (
    build_all_sns_crops_prompt,
    build_single_crop_prompt,
    build_sns_advice_prompt,
)
from app.prompts.grader_prompts import (
    _build_prompt,
    build_grader_prompt,
)
from app.prompts.lightroom_prompts import build_lightroom_prompt

# Re-exports from app.services
import app.services.gemini_client as _gemini_client
from app.services.batch_service import run_batch_pipeline
from app.services.burst_detector import (
    are_burst_pair,
    are_filenames_sequential,
    cluster_burst_groups,
    parse_photo_time,
)
from app.services.gemini_client import (
    _call_gemini_interaction,
    _get_client,
    analyze_with_gemini,
    generate_all_sns_crops,
    generate_lightroom_advice,
    generate_single_sns_crop,
    generate_sns_advice,
    generate_sns_caption_and_tags,
    get_usage_stats,
    set_usage_log_db,
)
from app.services.openai_client import (
    analyze_with_openai,
    suggest_lightroom_advice_with_openai,
)
from app.services.multi_llm import (
    analyze_photo,
    suggest_lightroom_advice,
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
from app.services.xmp_service import (
    generate_xmp_xml,
    score_to_rating_and_label,
    write_xmp_sidecar,
)

# Re-exports from app.db
from app.db.connection import (
    ensure_db_columns,
    ensure_tag_tables,
    sync_analysis_tags,
)
from app.db.repository import (
    delete_analyses,
    find_existing_analysis,
    get_all_analyses,
    get_analyses_and_tags_for_export,
    get_analysis_row_by_id,
    get_photo_thumbnail_and_hash,
    get_tag_stats,
    save_analysis,
    update_lr_advice,
    update_photo_thumbnail,
    update_review_status,
    update_sns_advice,
    update_user_score,
)

# Re-exports from app.exporters
from app.exporters.html_exporter import (
    render_batch_comparison_html,
    render_html_report,
    save_html_report,
)

# Pointer to client cache for mock testing
_CLIENT_CACHE = _gemini_client._CLIENT_CACHE


# CLI parser and main entrypoint
from app.cli import build_parser, cli_main as main


if __name__ == "__main__":
    raise SystemExit(main())
