# Workflow: Post Video Reel

3 skills modular untuk handle video dari awal sampe posting ke Instagram.

## Flow

```
                    ┌─────────────────────┐
                    │  resource/videos/   │
                    │  (video mentah)     │
                    └─────────┬───────────┘
                              │
               ┌──────────────┴──────────────┐
               │  audio perlu diganti?       │
               └──────┬──────────────┬───────┘
                     Ya              Tidak
                      │                │
          ┌───────────▼────┐  ┌───────▼──────────┐
          │ Skill 1        │  │                  │
          │ prepare-reel   │  │  Langsung ke     │
          │ (ganti audio)  │  │  Skill 2         │
          └───────────┬────┘  └───────┬──────────┘
                      │                │
                      └──────┬─────────┘
                             ▼
               ┌──────────────────────────────┐
               │ Skill 2                      │
               │ stage-reel                   │
               │ • upload ke Catbox → URL     │
               │ • Gemini → 3 opsi caption    │
               └──────────┬───────────────────┘
                          ▼
               ┌──────────────────────────────┐
               │ Skill 3                      │
               │ post-reel <url> <caption>    │
               │ • posting ke Instagram       │
               │ • simpan ke published/       │
               └──────────────────────────────┘
```

## Skill 1 — Edit Audio (opsional)

Ganti audio video kalo musik bawaan ngga cocok.

```bash
python main.py prepare-reel <nama_video> <nama_music>
```

- Video dari `resource/videos/`, music dari `resource/music/`
- Hasil edit: `resource/output/<nama_video>_edited.mp4`
- Output: 100% musik, 0% suara asli
- Selanjutnya: `stage-reel` pake file hasil edit

## Skill 2 — Stage (Upload + Caption)

Upload video ke Catbox, generate caption pake Gemini.

```bash
python main.py stage-reel <nama_file_video>
```

- Cari file di `resource/videos/` atau `resource/output/`
- **Otomatis deteksi ukuran**: kalo >200MB → kompres dulu (keep original audio)
- Simpen mapping URL → file lokal di `resource/.uploaded.json`
- Upload ke Catbox → dapet public URL
- Extract 4 frame → Gemini (`gemini-3.5-flash`) → 3 opsi caption + hashtag
- Output: URL + 3 caption siap pilih

## Skill 3 — Post

Publish reel ke Instagram.

```bash
python main.py post-reel <url> [caption]
```

- `url`: URL video dari Catbox (hasil stage-reel)
- `caption`: teks caption (opsional)
- Container 2-step: create → wait FINISHED → publish
- Sukses → simpan referensi ke `resource/published/` dengan format `{YYYYMMDD}_{media_id}_{stem}.mp4`

## Utility

Buat yg cuma butuh caption aja (udah upload manual):

```bash
python main.py generate-caption <nama_file_video>
```



## Contoh Lengkap

### Audio perlu diganti

```bash
python main.py prepare-reel vid_koi.mp4 bossa_nova.mp3
# → resource/output/vid_koi_edited.mp4

python main.py stage-reel vid_koi_edited.mp4
# → URL + 3 caption

python main.py post-reel https://files.catbox.moe/xxx.mp4 "caption pilihan"
```

### Audio udah oke

```bash
python main.py stage-reel vid_langsung.mp4
# → URL + 3 caption

python main.py post-reel https://files.catbox.moe/xxx.mp4 "caption pilihan"
```
