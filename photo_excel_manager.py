from __future__ import annotations

"""Compatibility shim for app.exporters.excel_exporter."""

import app.exporters.excel_exporter as _mod
from app.exporters.excel_exporter import *

__all__ = [k for k in dir(_mod) if not k.startswith("__")]

if __name__ == "__main__":
    raise SystemExit(main())
