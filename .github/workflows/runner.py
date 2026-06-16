"""Runner thin wrapper — delegates to nixfw.runner."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.stdout.reconfigure(encoding='utf-8')

from dotenv import load_dotenv
load_dotenv()

from nixfw.runner import run

if __name__ == "__main__":
    run(account="aquarisamatiran")
