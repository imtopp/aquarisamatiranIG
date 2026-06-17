import os
import tempfile
import zipfile
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from nixfw import config


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _linux_fallback() -> str:
    for p in ["/usr/share/fonts/truetype/nunito/Nunito-Regular.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
              "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"]:
        if Path(p).exists():
            return p
    return ""


def _get_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    FONT_URL = "https://github.com/google/fonts/raw/main/ofl/nunito/"

    font_map = {
        "nunito_bold": ("Nunito-ExtraBold.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
        "nunito": ("Nunito-Regular.ttf", "C:/Windows/Fonts/segoeui.ttf"),
    }

    url_name, fallback = font_map.get(name, (None, "C:/Windows/Fonts/segoeui.ttf"))
    if not Path(fallback).exists():
        fallback = _linux_fallback() or fallback
    if url_name is None:
        return ImageFont.truetype(fallback, size)

    cache_dir = Path(tempfile.gettempdir()) / "aquarisamatir_fonts"
    cache_path = cache_dir / url_name

    if not cache_path.exists():
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            url = FONT_URL + url_name
            r = requests.get(url, timeout=15)
            if r.status_code == 200:
                cache_path.write_bytes(r.content)
        except Exception:
            pass

    if cache_path.exists():
        try:
            return ImageFont.truetype(str(cache_path), size)
        except Exception:
            pass

    return ImageFont.truetype(fallback, size)


def _get_symbol_font(size: int) -> ImageFont.FreeTypeFont:
    """Coba Segoe UI Symbol (font symbol bawaan Windows) — fallback ke Noto/DejaVu di Linux."""
    candidates = [
        "C:/Windows/Fonts/seguisym.ttf",
        "C:/Windows/Fonts/seguiemj.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansSymbols-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        p = Path(path)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    return ImageFont.load_default()


_EMOJI_RANGES = [
    (0x1F300, 0x1F9FF), (0x2600, 0x27BF), (0x2700, 0x27BF),
    (0x1F600, 0x1F64F), (0x1F680, 0x1F6FF), (0x2300, 0x23FF),
    (0xFE00, 0xFE0F), (0x200D, 0x200D), (0x1FA00, 0x1FAFF),
    (0x1F900, 0x1F9FF), (0x2B00, 0x2BFF), (0x2E00, 0x2E7F),
    (0x3000, 0x303F), (0x3200, 0x32FF), (0x3300, 0x33FF),
    (0xFE10, 0xFE1F), (0xFF00, 0xFFEF),
    (0x1F1E6, 0x1F1FF),
]


def _is_emoji_or_special(char: str) -> bool:
    cp = ord(char)
    return any(lo <= cp <= hi for lo, hi in _EMOJI_RANGES)


def _get_emoji_font(size: int) -> ImageFont.FreeTypeFont | None:
    # Prioritize downloaded font (COLRv1 — renders color without embedded_color on Pillow 10.4+)
    font_url = "https://raw.githubusercontent.com/googlefonts/noto-emoji/main/fonts/NotoColorEmoji.ttf"
    cache_dir = Path(tempfile.gettempdir()) / "aquarisamatiran_emoji_fonts"
    cache_path = cache_dir / "NotoColorEmoji.ttf"
    if not cache_path.exists():
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            r = requests.get(font_url, timeout=60)
            if r.status_code == 200:
                cache_path.write_bytes(r.content)
        except Exception:
            pass
    for try_path in [cache_path]:
        try:
            return ImageFont.truetype(str(try_path), size)
        except Exception:
            pass

    # Fallback: system emoji fonts
    candidates = [
        "C:/Windows/Fonts/seguiemj.ttf",
        "C:/Windows/Fonts/seguisym.ttf",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/opentype/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",
        "/usr/share/fonts/opentype/noto/NotoEmoji-Regular.ttf",
        "/usr/share/fonts/noto/NotoColorEmoji.ttf",
        "/usr/share/fonts/noto/NotoEmoji-Regular.ttf",
    ]
    for d in ["/usr/share/fonts/truetype/noto", "/usr/share/fonts/opentype/noto",
              "/usr/share/fonts/truetype", "/usr/share/fonts/opentype"]:
        dp = Path(d)
        if dp.is_dir():
            for f in dp.rglob("*[Ee]moji*"):
                p = str(f)
                if p not in candidates:
                    candidates.append(p)
    for path in candidates:
        p = Path(path)
        if p.exists():
            try:
                f = ImageFont.truetype(str(p), size)
                print(f"[debug] _get_emoji_font loaded: {p} (size={size})", flush=True)
                return f
            except Exception as e:
                print(f"[debug] _get_emoji_font fail {p}: {e}", flush=True)
                continue
    print("[debug] _get_emoji_font: no font found!", flush=True)
    return None


def draw_text_fallback(draw, xy, text, font_primary, font_fallback, fill):
    """Render text with emoji fallback — emoji pake emoji font, sisanya pake primary."""
    if font_fallback is None:
        draw.text(xy, text, fill=fill, font=font_primary)
        return

    x, y = xy
    chunks = []
    current = ""
    current_is_emoji = None

    # Calculate baseline alignment: offset so emoji sits on same baseline as Nunito
    prim_ascent, prim_descent = font_primary.getmetrics()
    fall_ascent, fall_descent = font_fallback.getmetrics()
    y_offset = prim_ascent - fall_ascent

    for char in text:
        is_emoji = _is_emoji_or_special(char)
        if current_is_emoji is None:
            current_is_emoji = is_emoji

        if is_emoji != current_is_emoji:
            if current:
                chunks.append((current, font_fallback if current_is_emoji else font_primary))
            current = char
            current_is_emoji = is_emoji
        else:
            current += char

    if current:
        chunks.append((current, font_fallback if current_is_emoji else font_primary))

    for chunk, fnt in chunks:
        is_emoji_chunk = fnt == font_fallback
        ey = y + (y_offset if is_emoji_chunk else 0)
        draw.text((x, ey), chunk, fill=fill, font=fnt)
        bb = draw.textbbox((0, 0), chunk, font=fnt)
        x += bb[2] - bb[0]


def draw_rounded_rect(draw, xy, radius, fill):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill)


def draw_gradient_bg(size, color_top, color_bottom):
    W, H = size
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")

    ct = _hex_to_rgb(color_top)
    cb = _hex_to_rgb(color_bottom)

    for y in range(H):
        t = y / H
        r = int(ct[0] + (cb[0] - ct[0]) * t)
        g = int(ct[1] + (cb[1] - ct[1]) * t)
        b = int(ct[2] + (cb[2] - ct[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

    return img


def wrap_text(text, font, max_width, draw):
    words = text.split()
    lines = []
    current = ""
    for w in words:
        test = f"{current} {w}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        w_px = bbox[2] - bbox[0]
        if w_px <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines


def draw_tag_pills(draw, tags, x, y, font, palette=None):
    if palette is None:
        palette = config.PALETTE
    tag_bg = _hex_to_rgb(palette["tag_bg"])
    text_color = _hex_to_rgb(palette["text_main"])
    accent = _hex_to_rgb(palette["accent"])
    pad_x, pad_y, radius = 14, 6, 14
    cx = x

    for tag in tags:
        bbox = draw.textbbox((0, 0), tag, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        pill_w = tw + pad_x * 2
        pill_h = th + pad_y * 2
        draw_rounded_rect(draw, (cx, y, cx + pill_w, y + pill_h), radius, tag_bg + (220,))
        draw.rectangle((cx + 4, y + pill_h // 2 - 1, cx + 8, y + pill_h // 2 + 1), fill=accent)
        tx = cx + pad_x + 10
        ty = y + pad_y
        draw.text((tx, ty), tag, fill=text_color + (255,), font=font)
        cx += pill_w + 10

    return cx
