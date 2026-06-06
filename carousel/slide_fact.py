from PIL import Image, ImageDraw

import config
from carousel.composer import (
    _hex_to_rgb, _get_font, draw_gradient_bg, draw_tag_pills, wrap_text,
)


def build_fact_slide(fact: dict, subject_img: Image.Image | None, palette: dict | None = None) -> Image.Image:
    W, H = config.SLIDE_SIZE
    if palette is None:
        palette = config.PALETTE

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
        draw.text((text_x, ty), line, fill=text_main + (255,), font=font_title)
        ty += 76

    # Separator
    sep_y = ty + 16
    draw.rectangle((text_x, sep_y, text_x + text_max_w, sep_y + 2), fill=accent + (180,))
    ty = sep_y + 30

    # Description
    desc = fact.get("description", "")
    body_lines = wrap_text(desc, font_body, text_max_w, draw)
    for line in body_lines:
        draw.text((text_x, ty), line, fill=text_main + (255,), font=font_body)
        ty += 58

    # Tags
    tags = fact.get("tags", [])
    if tags:
        draw_tag_pills(draw, tags, text_x, H - 100, font_tags, palette)

    return bg.convert("RGB")
