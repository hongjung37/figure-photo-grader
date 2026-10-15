from __future__ import annotations

"""Compatibility shim for app.db.repository."""

import app.db.repository as _mod
from app.db.repository import *

__all__ = [k for k in dir(_mod) if not k.startswith("__")]
