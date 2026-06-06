# Workflow: Post Foto

Foto langsung dari `resource/photos/` → upload + caption → posting.

## Flow

```
┌──────────────────────┐
│  resource/photos/   │
│  (foto siap upload) │
└─────────┬────────────┘
          ▼
┌──────────────────────────────┐
│ stage-photo <nama_file>      │
│ • upload ke Catbox → URL     │
│ • Gemini → 3 opsi caption    │
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│ post-photo <url> [caption]   │
│ • posting ke Instagram       │
└──────────────────────────────┘
```

## Stage

Upload foto + generate caption.

```bash
python main.py stage-photo <nama_file_foto>
```

- Foto dari `resource/photos/`
- Upload ke Catbox → URL
- Gemini analisis langsung dari gambar → 3 opsi caption + hashtag
- Output: URL + 3 caption siap pilih

## Post

Publish foto ke Instagram.

```bash
python main.py post-photo <url> [caption]
```

- `url`: URL foto dari Catbox (hasil stage-photo)
- `caption`: teks caption (opsional)

## Contoh

```bash
# Upload + caption
python main.py stage-photo tank_setup.jpg
# → URL + 3 caption

# Posting
python main.py post-photo https://files.catbox.moe/xxx.jpg "caption pilihan"
```
