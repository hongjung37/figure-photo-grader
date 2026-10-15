from __future__ import annotations

"""Compatibility shim for app.exporters.html_exporter."""

import app.exporters.html_exporter as _mod
from app.exporters.html_exporter import *

__all__ = [k for k in dir(_mod) if not k.startswith("__")]
