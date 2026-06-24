from PIL import Image, ImageDraw

from nixfw import config as nixfw_config
from nixfw.carousel.composer import (
    _hex_to_rgb, _get_font, draw_gradient_bg, draw_tag_pills, wrap_text,
    draw_text_fallback, _get_emoji_font,
)


def build_fact_slide(fact: dict, subject_img: Image.Image | None, palette: dict | None = None,
                     bg_image: Image.Image | None = None,
                     handle: str | None = None) -> Image.Image:
    W, H = nixfw_config.SLIDE_SIZE
    if palette is None:
        palette = nixfw_config.PALETTE
    if handle is None:
        handle = nixfw_config.IG_HANDLE

    if bg_image:
        bg = bg_image.copy()
    else:
        bg = draw_gradient_bg((W, H), palette["bg_dark"], palette["bg_card"])
    draw = ImageDraw.Draw(bg, "RGBA")

    accent2 = _hex_to_rgb(palette["accent2"])
    text_main = _hex_to_rgb(palette["text_main"])
    text_sub = _hex_to_rgb(palette["text_sub"])
    accent = _hex_to_rgb(palette["accent"])

    font_num = _get_font("nunito_bold", 80)
    font_title = _get_font("nunito_bold", 64)
    font_body = _get_font("nunito", 48)
    font_small = _get_font("nunito", 24)
    font_tags = _get_font("nunito", 26)
    font_watermark = _get_font("nunito", 18)
    font_emoji = _get_emoji_font(64)

    # Fact number (top left)
    num = fact.get("number", "01")
    draw.text((40, 60), num, fill=accent2 + (255,), font=font_num)

    # Image on right side, vertically centered
    img_size = 300
    img_gap = 30
    text_x = 40
    text_max_w = W - 80
    if subject_img:
        img_x = W - 60 - img_size
        img_y = (H - img_size) // 2
        img_resized = subject_img.resize((img_size, img_size), Image.LANCZOS)
        bg.paste(img_resized, (img_x, img_y), img_resized)
        text_max_w = img_x - img_gap - text_x

    # Title
    title = fact.get("title", "")
    title_lines = wrap_text(title, font_title, text_max_w, draw)
    ty = 170
    for line in title_lines:
        draw_text_fallback(draw, (text_x, ty), line, font_title, font_emoji, fill=text_main + (255,))
        ty += 76

    # Separator
    sep_y = ty + 16
    draw.rectangle((text_x, sep_y, text_x + text_max_w, sep_y + 2), fill=accent + (180,))
    ty = sep_y + 30

    # Description
    desc = fact.get("description", "")
    body_lines = wrap_text(desc, font_body, text_max_w, draw)
    for line in body_lines:
        draw_text_fallback(draw, (text_x, ty), line, font_body, font_emoji, fill=text_main + (255,))
        ty += 58

    # Tags
    tags = fact.get("tags", [])
    if tags:
        draw_tag_pills(draw, tags, text_x, H - 100, font_tags, palette)

    # Watermark
    hb = draw.textbbox((0, 0), handle, font=font_watermark)
    hw = hb[2] - hb[0]
    draw.text((W - 40 - hw, H - 30), handle, fill=accent + (100,), font=font_watermark)

    return bg.convert("RGB")
