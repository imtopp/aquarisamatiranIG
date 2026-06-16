"""Thin wrapper — re-exports everything from nixfw.curriculum.manager for backward compat."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import nixfw.curriculum.manager as _base

for _attr in dir(_base):
    if not _attr.startswith("__"):
        globals()[_attr] = getattr(_base, _attr)

del _base, _attr
