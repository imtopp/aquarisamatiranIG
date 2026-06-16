"""Telegram bot — thin wrapper for nixfw.bot.bot"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import nixfw.bot.bot as _base

for _attr in dir(_base):
    if not _attr.startswith("__"):
        globals()[_attr] = getattr(_base, _attr)

del _base, _attr

if __name__ == "__main__":
    main()
