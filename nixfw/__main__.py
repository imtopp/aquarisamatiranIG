"""NixFW — CLI entry point."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nixfw.cli.dispatch import main

if __name__ == "__main__":
    main()
