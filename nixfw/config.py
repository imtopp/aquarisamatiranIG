import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Literal

from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.5-flash"

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
AGENTS_MD = PROJECT_ROOT / "AGENTS.md"
DB_PATH = PROJECT_ROOT / "bot" / "chat_history.db"

IG_HANDLE = "@aquarisamatiran"
ACCOUNT_NAME = "aquarisamatiran"
GH_REPO = "imtopp/aquarisamatiranIG"
SLIDE_SIZE = (1080, 1080)

# Fallback paths (used when account context is unavailable)
RESOURCE_DIR = PROJECT_ROOT / "accounts" / "aquarisamatiran" / "resource"
PHOTO_DIR = RESOURCE_DIR / "photos"

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


@dataclass
class ContentType:
    label: str
    instruction: str
    slide_structure: list
    has_scientific_name: bool = False
    pexels_desc: str = ""
    tags_hint: str = ""
    prompt_extra: str = ""
    json_schema_extra: str = ""


DEFAULT_CONTENT_TYPES: dict[str, ContentType] = {
    "edu": ContentType(
        label="Edukasi & Fakta",
        instruction="Buat konten edukatif yang informatif, ilmiah, dan mudah dipahami pemula",
        slide_structure=[
            "Hook/Judul — bikin penasaran",
            "Detail & Fakta — jelaskan intinya",
            "Fakta tambahan atau contoh",
            "Rangkuman + CTA — kesimpulan + ajak diskusi",
        ],
        json_schema_extra='"scientific_name": "..."',
        tags_hint="informasi teknis relevan",
    ),
    "story": ContentType(
        label="Kisah & Perjalanan",
        instruction="Ceritakan pengalaman pribadi yang relateable, naratif, penuh emosi",
        slide_structure=[
            "Pembuka — bikin penasaran",
            "Konflik/Masalah — apa yang terjadi",
            "Proses — gimana ngatasinnya",
            "Pelajaran + CTA — apa yang dipetik + ajak sharing",
        ],
        tags_hint="momen, proses, pelajaran",
    ),
    "humor": ContentType(
        label="Lucu & Ringan",
        instruction="Buat konten lucu, ringan, relatable dengan bumbu humor yang natural",
        slide_structure=[
            "Hook lucu — langsung ngakak",
            "Situasi — gambaran realitanya",
            "Plot twist — yang bikin tambah lucu",
            "Punchline + CTA — closing lucu + ajak ketawa bareng",
        ],
        tags_hint="lucu, relatable, situasi",
    ),
    "tips": ContentType(
        label="Tips & Trik",
        instruction="Beri tips praktis, step-by-step, solutif dan actionable",
        slide_structure=[
            "Hook/Judul — masalah apa yang dipecahin",
            "Tips 1-3 — langsung ke inti",
            "Tips lanjutan atau kesalahan umum",
            "Kesimpulan + CTA — rangkuman + ajak diskusi",
        ],
        json_schema_extra='"difficulty": "pemula/mahir"',
        tags_hint="tips, trik, solusi, rekomendasi",
    ),
    "review": ContentType(
        label="Review & Rekomendasi",
        instruction="Review produk/tempat/layanan, jujur, plus-minus, dan rekomendasi",
        slide_structure=[
            "Hook — masalah apa yang dipecahin",
            "Apa ini — kenalan dengan produk/tempatnya",
            "Kenapa bagus — fitur unggulan, plus-minus",
            "Kesimpulan + CTA — worth it atau engga? + ajak diskusi",
        ],
        tags_hint="spesifikasi, harga, plus minus, rekomendasi",
    ),
    "custom": ContentType(
        label="Custom",
        instruction="Buat konten sesuai arahan berikut di slide pertama",
        slide_structure=[
            "Slide 1 — sesuai arahan",
            "Slide 2",
            "Slide 3",
            "Slide 4",
        ],
    ),
}


@dataclass
class NicheProfile:
    """Profile untuk satu niche — ganti nilai ini buat beda topik."""
    handle: str = IG_HANDLE
    niche_name: str = "aquascape & aquarium"
    expert_role: str = "ahli aquaristik"
    education_label: str = "edukasi aquarium"
    mission_blurb: str = (
        "blak-blakan soal proses & kegagalan (bukan cuma hasil rapih), "
        "serta edukatif/inspiratif biar followers ngerasa dapet value."
    )
    pexels_query_suffix: str = "aquarium"
    pexels_image_desc: str = "aquascape/aquarium, ikan tropis"
    photo_description: str = "foto aquascape/aquarium"
    tags_hint: str = "pH, suhu, ukuran, dll"
    has_scientific_name: bool = True
    image_providers: list = field(default_factory=lambda: ["pexels"])
    cta_template: str = "Follow {handle}\nuntuk edukasi aquarium\nsetiap minggu!"
    bg_theme: str = "aquascape"
    content_types: dict = field(default_factory=lambda: dict(DEFAULT_CONTENT_TYPES))


_NICHE_REGISTRY: dict[str, NicheProfile] = {
    "aquascape": NicheProfile(image_providers=["wikimedia", "inaturalist", "pexels"]),
    "food": NicheProfile(
        niche_name="masakan & resep",
        expert_role="chef & food blogger",
        education_label="edukasi memasak",
        pexels_query_suffix="food",
        pexels_image_desc="makanan, masakan, bahan dapur",
        photo_description="foto masakan/makanan",
        tags_hint="kalori, porsi, waktu masak, bahan utama",
        has_scientific_name=False,
        cta_template="Follow {handle}\nuntuk resep masakan\nsetiap minggu!",
        bg_theme="minimal",
        content_types={
            **DEFAULT_CONTENT_TYPES,
            "recipe": ContentType(
                label="Resep Masakan",
                instruction="Buat resep lengkap, step-by-step, dengan tips memasak",
                slide_structure=[
                    "Hook — kenapa resep ini spesial",
                    "Bahan-bahan — apa aja yg diperlukan",
                    "Cara masak — langkah-langkah detail",
                    "Tips + CTA — trik dapur + ajak diskusi",
                ],
                tags_hint="bahan, porsi, waktu masak, tingkat kesulitan",
            ),
            "recommendation": ContentType(
                label="Rekomendasi Makanan",
                instruction="Rekomendasi tempat makan atau makanan yang wajib dicoba",
                slide_structure=[
                    "Hook — kenapa rekomendasi ini worth it",
                    "Detail — rasa, harga, suasana",
                    "Plus-Minus — kelebihan & kekurangan",
                    "Kesimpulan + CTA — rating + ajak diskusi",
                ],
                tags_hint="tempat, harga, rating, rekomendasi",
            ),
        },
    ),
    "fashion": NicheProfile(
        niche_name="fashion & outfit",
        expert_role="fashion stylist & content creator",
        education_label="edukasi fashion",
        pexels_query_suffix="fashion",
        pexels_image_desc="fashion, outfit, pakaian",
        photo_description="foto outfit/fashion",
        tags_hint="bahan, ukuran, warna, padu padan",
        has_scientific_name=False,
        cta_template="Follow {handle}\nuntuk inspirasi fashion\nsetiap minggu!",
        bg_theme="minimal",
        content_types={
            **DEFAULT_CONTENT_TYPES,
            "outfit": ContentType(
                label="Inspirasi Outfit",
                instruction="Inspirasi padu padan outfit, kasih tau detail dan variasi",
                slide_structure=[
                    "Hook — kenapa outfit ini menarik",
                    "Detail — potongan, warna, aksesoris",
                    "Variasi — outfit alternatif lain",
                    "Tips + CTA — tips styling + ajak sharing",
                ],
                tags_hint="bahan, warna, padu padan, tips fashion",
            ),
        },
    ),
    "tech": NicheProfile(
        niche_name="teknologi & gadget",
        expert_role="tech reviewer & content creator",
        education_label="edukasi teknologi",
        pexels_query_suffix="technology",
        pexels_image_desc="teknologi, gadget, elektronik",
        photo_description="foto gadget/teknologi",
        tags_hint="spesifikasi, harga, fitur unggulan, kekurangan",
        has_scientific_name=False,
        cta_template="Follow {handle}\nuntuk review teknologi\nsetiap minggu!",
        bg_theme="minimal",
        content_types={
            **DEFAULT_CONTENT_TYPES,
            "comparison": ContentType(
                label="Perbandingan Produk",
                instruction="Bandingkan 2 produk atau lebih dengan tabel plus-minus",
                slide_structure=[
                    "Hook — masalah apa yang dipecahin",
                    "Produk A — kelebihan & kekurangan",
                    "Produk B — kelebihan & kekurangan",
                    "Verdict + CTA — mana yang terbaik? + ajak diskusi",
                ],
                tags_hint="spesifikasi, harga, plus minus, perbandingan",
            ),
        },
    ),
}

current_niche: NicheProfile = _NICHE_REGISTRY["aquascape"]
current_content_type: ContentType = current_niche.content_types["edu"]


def set_niche(name: str):
    global current_niche, current_content_type
    if name in _NICHE_REGISTRY:
        current_niche = _NICHE_REGISTRY[name]
        current_content_type = list(current_niche.content_types.values())[0]
        print(f"  🎯 Niche: {current_niche.niche_name}")
    else:
        print(f"  ⚠️  Niche '{name}' ngga dikenal. Pilihan: {', '.join(_NICHE_REGISTRY)}")


def set_content_type(type_name: str):
    global current_content_type
    if type_name in current_niche.content_types:
        current_content_type = current_niche.content_types[type_name]
        print(f"  📋 Tipe konten: {current_content_type.label}")
    else:
        tersedia = ", ".join(current_niche.content_types)
        print(f"  ⚠️  Tipe '{type_name}' ngga ada di niche ini. Tersedia: {tersedia}")
        return False
    return True
