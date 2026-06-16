"""Update bio page thin wrapper — delegates to nixfw.bio.generator."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
sys.stdout.reconfigure(encoding='utf-8')

from nixfw.bio.generator import update_bio

if __name__ == "__main__":
    update_bio(account="aquarisamatiran")
