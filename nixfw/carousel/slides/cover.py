from PIL import Image, ImageDraw

from nixfw import config
from nixfw.carousel.composer import (
    _hex_to_rgb, _get_font, draw_gradient_bg, wrap_text,
    draw_text_fallback, _get_emoji_font,
)


def build_cover(facts: dict, subject_img: Image.Image | None, bg_image: Image.Image | None = None) -> Image.Image:
    W, H = config.SLIDE_SIZE
    palette = config.PALETTE

    if bg_image:
        bg = bg_image.copy()
    else:
        bg = draw_gradient_bg((W, H), palette["bg_dark"], palette["bg_card"])
    draw = ImageDraw.Draw(bg, "RGBA")

    accent2 = _hex_to_rgb(palette["accent2"])
    text_main = _hex_to_rgb(palette["text_main"])
    text_sub = _hex_to_rgb(palette["text_sub"])
    accent = _hex_to_rgb(palette["accent"])

    font_handle = _get_font("nunito", 28)
    font_title = _get_font("nunito_bold", 56)
    font_subtitle = _get_font("nunito", 30)
    font_tagline = _get_font("nunito", 28)
    font_emoji = _get_emoji_font(56)
    font_emoji_sub = _get_emoji_font(30)

    # Handle
    draw.text((40, 60), config.IG_HANDLE, fill=accent + (255,), font=font_handle)

    # Subject image
    img_y = 160
    if subject_img:
        img_w, img_h = subject_img.size
        img_x = (W - img_w) // 2
        bg.paste(subject_img, (img_x, img_y), subject_img)
        img_y += img_h + 20
    else:
        img_y += 140

    # Subtitle / tagline
    subtitle = facts.get("subtitle", "")
    ct_y = img_y + 10
    if subtitle:
        draw_text_fallback(draw, ((W - draw.textbbox((0, 0), subtitle, font=font_subtitle)[2]) // 2, ct_y), subtitle, font_subtitle, font_emoji_sub, fill=text_sub + (255,))
        ct_y += 50

    # Display name (large title)
    display = facts.get("display_name") or facts.get("topic", "")
    lines = wrap_text(display, font_title, W - 80, draw)
    ly = ct_y + 10
    for line in lines:
        bb = draw.textbbox((0, 0), line, font=font_title)
        lw = bb[2] - bb[0]
        draw_text_fallback(draw, ((W - lw) // 2, ly), line, font_title, font_emoji, fill=accent2 + (255,))
        ly += 70

    # Scientific name
    scientific = facts.get("scientific_name", "")
    if scientific and scientific not in ("N/A", "None", ""):
        bbox = draw.textbbox((0, 0), scientific, font=font_subtitle)
        sw = bbox[2] - bbox[0]
        draw.text(((W - sw) // 2, ly + 10), scientific, fill=text_sub + (255,), font=font_subtitle)
        ly += 50

    # Teaser
    n = len(facts.get("facts", []))
    teaser = f"{n} Fakta Menarik yang Wajib Kamu Tahu!"
    bbox = draw.textbbox((0, 0), teaser, font=font_tagline)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) // 2, H - 120), teaser, fill=text_main + (255,), font=font_tagline)

    # Decorative line
    deco_y = H - 140
    line_w = 200
    draw.line([((W - line_w) // 2, deco_y), ((W + line_w) // 2, deco_y)],
              fill=accent2 + (180,), width=2)

    return bg.convert("RGB")
