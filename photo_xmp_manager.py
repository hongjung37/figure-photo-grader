"""photo_xmp_manager.py - Backward compatibility shim re-exporting from app.services.xmp_service."""

from app.services.xmp_service import (
    generate_xmp_xml,
    score_to_rating_and_label,
    write_xmp_sidecar,
)

__all__ = [
    "generate_xmp_xml",
    "score_to_rating_and_label",
    "write_xmp_sidecar",
]
