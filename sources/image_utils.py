from io import BytesIO

import requests
from PIL import Image, ImageEnhance, ImageFilter


def download_image(url: str) -> Image.Image | None:
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200:
            return Image.open(BytesIO(r.content)).convert("RGBA")
    except Exception as e:
        print(f"   ⚠️  Download gagal: {e}")
    return None


def apply_cartoon_effect(img: Image.Image) -> Image.Image:
    img = img.filter(ImageFilter.SMOOTH_MORE)
    enhancer = ImageEnhance.Color(img)
    img = enhancer.enhance(1.8)
    enhancer = ImageEnhance.Contrast(img)
    img = enhancer.enhance(1.2)
    return img


def prepare_subject_image(url: str, size: tuple = (400, 400)) -> Image.Image | None:
    img = download_image(url)
    if img is None:
        return None

    img = apply_cartoon_effect(img)

    # Fit within target size without cropping — letterbox kalo perlu
    img.thumbnail(size, Image.LANCZOS)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    x = (size[0] - img.width) // 2
    y = (size[1] - img.height) // 2
    canvas.paste(img, (x, y), img)

    return canvas
