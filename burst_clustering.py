"""burst_clustering.py - Backward compatibility shim re-exporting from app.services.burst_detector."""

from app.services.burst_detector import (
    are_burst_pair,
    are_filenames_sequential,
    cluster_burst_groups,
    parse_photo_time,
)

__all__ = [
    "are_burst_pair",
    "are_filenames_sequential",
    "cluster_burst_groups",
    "parse_photo_time",
]
