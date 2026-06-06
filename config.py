import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-3.5-flash"

IG_HANDLE = "@aquarisamatiran"
SLIDE_SIZE = (1080, 1080)
PHOTO_DIR = Path("resource") / "photos"

PALETTE = {
    "bg_dark": "#0D1B2A",
    "bg_card": "#1B2E45",
    "accent": "#00C9A7",
    "accent2": "#FFD166",
    "text_main": "#F0F4F8",
    "text_sub": "#8BAFC7",
    "tag_bg": "#0A3D62",
}

FONT_PATHS = {
    "nunito_bold": None,
    "nunito": None,
}
