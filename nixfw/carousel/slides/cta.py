from PIL import Image, ImageDraw
from pathlib import Path

from nixfw import config as nixfw_config
from nixfw.carousel.composer import (
    _hex_to_rgb, _get_font, _get_symbol_font, draw_gradient_bg, wrap_text,
    draw_text_fallback, _get_emoji_font,
)


_ICON_CHARS = {
    "Like": "\u2665",
    "Save": "\u2605",
    "Comment": "\u2709",
}


def build_cta_slide(facts: dict, subject_img: Image.Image | None, palette: dict | None = None,
                    bg_image: Image.Image | None = None,
                    handle: str | None = None, resource_dir: Path | None = None) -> Image.Image:
    W, H = nixfw_config.SLIDE_SIZE
    if palette is None:
        palette = nixfw_config.PALETTE
    if handle is None:
        handle = nixfw_config.IG_HANDLE
    if resource_dir is None:
        resource_dir = nixfw_config.RESOURCE_DIR

    if bg_image:
        bg = bg_image.copy()
    else:
        bg = draw_gradient_bg((W, H), palette["bg_dark"], palette["bg_card"])
    draw = ImageDraw.Draw(bg, "RGBA")

    accent2 = _hex_to_rgb(palette["accent2"])
    text_main = _hex_to_rgb(palette["text_main"])
    accent = _hex_to_rgb(palette["accent"])

    font_large = _get_font("nunito_bold", 44)
    font_cta = _get_font("nunito_bold", 38)
    font_handle = _get_font("nunito_bold", 52)
    font_body = _get_font("nunito", 30)
    font_icon_label = _get_font("nunito", 26)
    font_emoji = _get_emoji_font(38)

    # Subject image (smaller, center) — fallback ke logo kalo ga ada gambar
    img_to_show = subject_img
    if img_to_show is None:
        logo_path = resource_dir / "logo" / "logo-cta-square.png"
        if logo_path.exists():
            try:
                img_to_show = Image.open(logo_path).convert("RGBA")
            except Exception:
                pass
    if img_to_show:
        small_img = img_to_show.resize((280, 280), Image.LANCZOS)
        img_x = (W - 280) // 2
        bg.paste(small_img, (img_x, 120), small_img)
        img_bottom = 120 + 280 + 30
    else:
        img_bottom = 120

    # "Suka konten ini?"
    suka = "Suka konten ini?"
    font_suka = font_large
    bbox = draw.textbbox((0, 0), suka, font=font_suka)
    suka_w = bbox[2] - bbox[0]
    suka_h = bbox[3] - bbox[1]
    suka_y = img_bottom
    draw.text(((W - suka_w) // 2, suka_y), suka, fill=text_main + (255,), font=font_suka)

    # Like / Save / Comment — pake symbol font (Segoe UI Symbol)
    gap = 80
    icons_y = suka_y + suka_h + gap
    items = ["Like", "Save", "Comment"]
    spacing = 200
    total_w = len(items) * spacing
    start_x = (W - total_w) // 2
    font_symbol = _get_symbol_font(36)
    label_gap = 12

    for i, item in enumerate(items):
        cx = start_x + i * spacing + spacing // 2
        symbol = _ICON_CHARS.get(item, "?")
        sb = draw.textbbox((0, 0), symbol, font=font_symbol)
        sw = sb[2] - sb[0]
        sh = sb[3] - sb[1]
        draw.text((cx - sw // 2, icons_y), symbol, fill=accent + (230,), font=font_symbol)
        label_y = icons_y + sh + label_gap
        lb = draw.textbbox((0, 0), item, font=font_icon_label)
        lw = lb[2] - lb[0]
        draw.text((cx - lw // 2, label_y), item, fill=text_main + (255,), font=font_icon_label)

    # Handle highlight
    handle_gap = 80
    handle_y = label_y + (lb[3] - lb[1]) + handle_gap
    bbox = draw.textbbox((0, 0), handle, font=font_handle)
    hw = bbox[2] - bbox[0]
    hh = bbox[3] - bbox[1]
    draw.text(((W - hw) // 2, handle_y), handle, fill=accent + (255,), font=font_handle)

    # CTA text
    cta_gap = 80
    cta_y = handle_y + hh + cta_gap
    cta = facts.get("cta_text", f"Follow {handle}")
    cta_lines = cta.replace("\\n", "\n").split("\n")
    for line in cta_lines:
        bb = draw.textbbox((0, 0), line, font=font_cta)
        cw = bb[2] - bb[0]
        draw_text_fallback(draw, ((W - cw) // 2, cta_y), line, font_cta, font_emoji, fill=text_main + (255,))
        cta_y += 46

    return bg.convert("RGB")
