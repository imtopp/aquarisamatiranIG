import os
import tempfile
import zipfile
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

import config


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def _get_font(name: str, size: int) -> ImageFont.FreeTypeFont:
    FONT_URL = "https://github.com/google/fonts/raw/main/ofl/nunito/"

    font_map = {
        "nunito_bold": ("Nunito-ExtraBold.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
        "nunito": ("Nunito-Regular.ttf", "C:/Windows/Fonts/segoeui.ttf"),
    }

    url_name, fallback = font_map.get(name, (None, "C:/Windows/Fonts/segoeui.ttf"))
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
    """Coba Segoe UI Symbol (font symbol bawaan Windows) — fallback ke regular."""
    candidates = [
        "C:/Windows/Fonts/seguisym.ttf",
        "C:/Windows/Fonts/seguiemj.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
    ]
    for path in candidates:
        p = Path(path)
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size)
            except Exception:
                continue
    return ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", size)


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
