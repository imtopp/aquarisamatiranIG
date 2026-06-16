"""Aquarisamatiran — Instagram Manager CLI (thin wrapper)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nixfw.cli.commands import (
    _find_curriculum_key_by_slug,
    _add_schedule_entry,
    _update_curriculum_content,
    main as _main,
)

if __name__ == "__main__":
    _main()
