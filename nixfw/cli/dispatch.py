"""CLI command dispatch — delegates to nixfw.cli.commands."""
import sys
from nixfw.account import set_active_account
from nixfw.cli.commands import main

if __name__ == "__main__":
    if "--account" in sys.argv:
        idx = sys.argv.index("--account")
        if idx + 1 < len(sys.argv):
            name = sys.argv.pop(idx + 1)
            sys.argv.pop(idx)
            set_active_account(name)
    main()
