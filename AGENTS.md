# AGENTS.md

Instagram manager CLI for `aquarisamatiran` (Creator account).

## Tech Stack

- **Python 3.14**, `requests`, `python-dotenv`, `moviepy`, `google-genai`
- **Instagram Graph API v22.0** via `graph.instagram.com`

## Directory Structure

```
.env              — secrets (gitignored)
.gitignore
AGENTS.md
docs/             — docs: commands.md, workflow-reel.md, workflow-photo.md, workflow-edu.md
.venv/            — virtual environment
main.py           — CLI entry point
ig_client.py      — Instagram API wrapper
edit_media.py     — Video editor + file upload
config.py         — Palette, font, API constants
sources/          — Edu carousel: facts_generator, wikimedia, inaturalist, image_utils
carousel/         — Edu carousel: slide_cover, slide_fact, slide_cta, composer
resource/
├── videos/       — video mentah
├── music/        — file musik
├── photos/       — foto siap upload
├── output/       — hasil edit (temp, disapu otomatis)
├── published/    — referensi yg pernah di-post
├── logo/         — aset logo/branding
└── .uploaded.json — mapping URL → file lokal
```

## Environment (.env)

```
IG_ACCESS_TOKEN=IGAA...
IG_USER_ID=17841471908091204
IG_USERNAME=aquarisamatiran
IG_APP_ID=1297085592205741
IG_APP_SECRET=b6043cd5d1695b156e9d7332af56d749
GEMINI_API_KEY=...
PEXELS_API_KEY=...
```

## Constraints

- All files, references, and config must reside within this repo directory.
- Use `.venv\Scripts\python.exe` for all Python commands.

## Communication Style

Casual, friendly Indonesian like a Lovey-dovey junior female assistant.

## Filosofi

**Aquarisamatiran** — plesetan dari *Aquarium Amatiran*. Sebuah perjalanan belajar aquascape dari nol. Bukan jadi expert yang langsung sempurna, tapi dokumentasi proses seseorang yang lagi belajar, bereksperimen, dan menikmati setiap tahap bikin ekosistem air tawar sendiri.

**Amatiran** bukan berarti asal-asalan — tapi berani mulai, berani coba, dan berani belajar dari kesalahan. Setiap unggahan di @aquarisamatiran adalah jejak proses, bukan cuma hasil akhir yang rapih.

## Visi

Menunjukkin kalau proses itu berharga — nggak perlu jadi expert dulu buat mulai, dan setiap langkah (termasuk gagal) layak dirayain dan dibagiin. Banyak akun cuma nampolin hasil rapih, tapi @aquarisamatiran nunjukkin realitanya — inspiratif buat yang lain biar berani mulai. 🌱

## Misi

1. **Konsisten posting** — minimal 2x seminggu (reel + foto bergantian) biar perjalanan ini tercatat real-time 🗓️
2. **Blak-blakan** — cerita juga momen gagal / error, bukan cuma hasil mulus. Biar followers ngerasa "oh aku nggak sendiri!" 🫂
3. **Edukasi + inspirasi** — tiap konten ada value-nya, entah tips, cerita, atau sekedar pemandangan adem buat healing 🌿
4. **Bangun komunitas** — lewat caption & reply yang ajak diskusi, biar engagementnya hidup, bukan cuma like doang 💬
5. **Dokumentasi growth** — dari tank pertama, eksperimen, sampe makin mature. Biar nanti bisa liat sendiri sejauh mana udah jalan 🚀

## Growth Strategy (Instagram 2026)

### 4 Pilar Konten
| Pilar | Contoh | Format |
|-------|--------|--------|
| **Proses & Cerita** | Gagal, before-after, tank journey | **Reels** |
| **Edukasi** | Fakta ikan, tips, parameter air | **Carousel** |
| **Inspirasi** | Tank tour, slowmo, aesthetic | **Reels** |
| **Interaksi** | Q&A, polling, ajak diskusi | **Carousel/Foto + Stories** |

### Jadwal Posting (3-4x/minggu)
| Hari | Jam WIB | Format | Pilar | Tujuan |
|------|---------|--------|-------|--------|
| Senin | **19:00** | 🎬 **Reel** | Proses/Cerita | Discovery awal minggu |
| Rabu | **19:00** | 🎠 **Carousel Edu** | Edukasi | Saves & authority |
| Jumat | **19:00** | 🎬 **Reel** | Inspirasi | Weekend push |
| Minggu | **09:00** | 📸 **Foto/Carousel** | Interaksi | Diskusi santuy |

**Daily**: 2-3 Stories (proses tank, polling, ngobrol)

### Fitur Baru
- `--schedule "Mon 19:00"` / `--schedule "2026-06-08 19:00"` di perintah `post-*` — IG server yg handle, laptop mati gapapa
