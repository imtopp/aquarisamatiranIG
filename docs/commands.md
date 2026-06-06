# Commands Reference

## Reel Workflow (3 skills — detail di `docs/workflow-reel.md`)

```
prepare-reel <video> <music>   — [Skill 1] edit video + ganti audio (GPU encode)
stage-reel <video>             — [Skill 2] upload Catbox + Gemini caption (3 opsi)
post-reel <url> [caption]      — [Skill 3] posting ke IG + copy ke published/ + cleanup output/
```

## Photo Workflow (2 langkah — detail di `docs/workflow-photo.md`)

```
stage-photo <foto>             — upload Catbox + Gemini analisis foto → 3 caption opsi
post-photo <url> [caption]     — posting foto ke IG
```

## Edu Carousel Workflow (2 langkah)

```
generate-edu <topik>           — Gemini facts + Wikimedia/iNaturalist image → 4-6 slide .png
post-edu [caption]             — auto-detect slide terbaru → Catbox → carousel IG
```

Opsi tambahan `generate-edu`:
```
  --facts file.json       pake facts existing (skip Gemini)
  --num-facts N           jumlah fakta (default: 4)
  --force-image foto.jpg  pake foto lokal daripada Wikimedia
```

## Utility

```
delete-post <media_id>         — hapus post dari IG + referensi di published/
generate-caption <video>       — (opsional) caption aja tanpa upload
file-map                       — tampilkan isi .uploaded.json (URL ↔ file lokal)
```

`media_id` bisa dilihat dari nama file di `resource/published/` (format: `{YYYYMMDD}_{media_id}_{stem}.mp4`).
