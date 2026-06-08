# Workflow: Carousel Slides

2 langkah untuk generate + posting carousel infografis ke Instagram.

## Flow

```
                     ┌──────────────────────────────────┐
                     │  python main.py generate-carousel│
                     │  "Nama Topik"                    │
                     └──────────────┬───────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │  Step 1: Gemini               │
                    │  → facts JSON (cache di       │
                    │    resource/photos/*_facts.json)│
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │  Step 2: Cari gambar          │
                    │  → Wikimedia API (prioritas)  │
                    │  → iNaturalist API (fallback) │
                    │  → --force-image (opsional)   │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │  Step 3: Generate slide PNG   │
                    │  • Slide 1: Cover + ilustrasi │
                    │  • Slide 2-N: Fakta (masing2) │
                    │  • Slide N: CTA follow        │
                    │  → resource/photos/*_slide_NN.png│
                    └───────────────┬───────────────┘
                                    │
                                    ▼
                    ┌──────────────────────────────┐
                    │  python main.py post-carousel│
                    │  "caption"                    │
                    │  → auto-detect slide terbaru │
                    │  → upload slide ke Catbox     │
                    │  → carousel container → IG   │
                    └──────────────────────────────┘
```

## Step 1 — Generate Carousel

Generate facts dari Gemini + cari gambar otomatis dari Wikipedia/iNaturalist.

```bash
python main.py generate-carousel <topik> [--num-facts N] [--facts file.json] [--force-image foto.jpg]
```

| Argumen | Wajib? | Fungsi |
|---------|--------|--------|
| `topik` | ✅ | Nama topik (contoh: Pseudomugil Luminatus, Resep Nasi Goreng) |
| `--num-facts N` | ❌ | Jumlah fakta (default: 4) |
| `--facts file.json` | ❌ | Skip Gemini, pake facts JSON existing |
| `--force-image foto.jpg` | ❌ | Skip Wikimedia, pake foto lokal |

### Alur detail:

1. **Gemini API** → generate facts (scientific name, subtitle, 4 fakta, tags, CTA)
2. **Cache** → simpan ke `resource/photos/{slug}_facts.json`
3. **Cari gambar** → Wikimedia API → fallback iNaturalist → Pexels
4. **Cartoon effect** → download → crop 1:1 → smooth filter + saturasi naik → 400x400
5. **Generate slide** → Pillow overlay gradient + teks infografis

### Opsi hemat Gemini quota:

```bash
# Pake facts + foto lokal (0 Gemini call)
python main.py generate-carousel "Anubias" --facts facts_anubias.json --force-image anubias.jpg
```

Output: `resource/photos/{slug}_slide_01.png` sampai `_slide_NN.png`

## Step 2 — Post Carousel

Upload slide ke Catbox + publish ke Instagram.

```bash
python main.py post-carousel "caption"
```

- **Auto-detect** slide terbaru dari `resource/photos/*_slide_??.png`
- Upload slide ke Catbox
- Container 2-step: create item containers → CAROUSEL container → publish
- Nggak perlu ketik filename manual!

## Struktur Output

```
resource/photos/
├── {slug}_facts.json            ← cache facts Gemini
├── {slug}_slide_01.png          ← Cover (ilustrasi + judul + tagline)
├── {slug}_slide_02.png          ← Fakta 1 (nomor + judul + deskripsi + tags)
├── {slug}_slide_NN.png          ← CTA (Like/Save/Share + follow)
```

## Design System

- **Ukuran**: 1080×1080px (Instagram square carousel)
- **Format**: PNG
- **Background**: Gradient sesuai tema niche
- **Font**: Nunito (ExtraBold untuk judul, Regular untuk body)
  - Download otomatis dari Google Fonts saat pertama jalan
  - Fallback: Segoe UI (Windows)

### Palet Warna

| Token | Warna | Penggunaan |
|-------|-------|-----------|
| `bg_dark` | `#0D1B2A` | Background utama |
| `bg_card` | `#1B2E45` | Gradient bawah |
| `accent` | `#00C9A7` | Teal, dekorasi |
| `accent2` | `#FFD166` | Kuning, judul, nomor fakta |
| `text_main` | `#F0F4F8` | Teks utama |
| `text_sub` | `#8BAFC7` | Teks sekunder |
| `tag_bg` | `#0A3D62` | Background tag pills |

### Layout per Slide

**Slide 1 — Cover**
- Handle `@aquarisamatiran` di pojok kiri atas (accent)
- Ilustrasi objek 400x400 (cartoon effect) di tengah
- Subtitle (text_sub) di bawah gambar
- Nama display besar (accent2, bold) di bawah subtitle
- Teaser "N Fakta Menarik" di bawah

**Slide 2-N — Fakta**
- Nomor fakta besar (accent2) di kiri atas
- Ilustrasi objek 300x300 di kanan tengah
- Judul fakta (bold) + separator + deskripsi di kiri
- Tag pills (info teknis) di bawah

**Slide N — CTA**
- Ilustrasi objek 280x280 di tengah atas
- "Suka konten ini?" + Like / Save / Share
- `@aquarisamatiran` besar (accent, bold)
- CTA text dari facts JSON

## Contoh Lengkap

### Dari awal (Gemini + Wikipedia)

```bash
python main.py generate-carousel "Nannostomus mortenthaleri"
# → Generate facts + cari gambar → slide PNG

python main.py post-carousel "Ikan pencil merah ini bikin aku..."
```

### Pake data existing (hemat quota)

```bash
python main.py generate-carousel "Pseudomugil Luminatus" \
  --facts edu_pseudomugil_lum_facts.json \
  --force-image IMG_20260314_183345.jpg
# → Skip Gemini + Wikipedia → slide PNG

python main.py post-carousel "Caption sesuai keinginan"
```

### Pake niche lain

```bash
python main.py generate-carousel "Resep Nasi Goreng" --niche food

python main.py post-carousel "Nasi goreng favoritku..."
```
