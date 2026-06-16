# NIX — Product Requirements Document

> **NIX**: Multi-niche, multi-account Instagram automation CLI + bot.
> Buat, generate, schedule, dan post konten IG dengan bantuan AI — untuk niche apapun, akun sebanyak apapun.

---

## 1. Vision & Philosophy

### 1.1 Product Vision

NIX adalah platform otomatisasi Instagram yang memungkinkan user **memelihara satu atau banyak akun IG** dengan konten terstruktur. Bukan sekadar scheduler — NIX mengelola siklus hidup konten secara utuh:

```
Rencana → Generate → Review → Jadwalkan/Tayangkan → Catat → Evaluasi
```

### 1.2 Target User

- Social media manager dengan multiple IG account
- Hobbyist/content creator yang punya >1 akun tematik
- Brand yang konsisten posting konten edukasi/inspirasi

### 1.3 Design Principles

1. **Cache-first, API-second**: Semua hasil generate AI di-cache. Generate ulang gambar cukup, tanpa panggil AI lagi.
2. **Resumable**: Kalau proses berhenti di tengah (gagal generate gambar), cukup lanjutkan dari step gagal — tanpa generate ulang konten dari AI.
3. **Single Source of Truth**: Satu file master yang jadi acuan semua data konten. File lain (schedule, bio, report) adalah derived/turunan.
4. **General by design**: Konsep niche, palette, prompt style — semuanya configurable per-account. Bukan hardcode.
5. **Bot-first, Dashboard-later**: Touchpoint utama adalah Telegram bot. Dashboard web menyusul setelah workflow matang.

---

## 2. Core Concepts

### 2.1 Content Taxonomy

```
Niche (domain, misal: aquascape, food, travel)
│
├─ Curriculum (seri konten berkesinambungan)
│   └─ Category (grouping besar — dulu "season")
│       └─ Subcategory (sub-grouping — dulu "level")
│           └─ Topic (materi individual)
│
└─ Adhoc Topic (konten independent, di luar curriculum)
```

**Definisi:**

| Istilah | Makna | Contoh |
|---------|-------|--------|
| **Niche** | Domain konten | `aquascape`, `food`, `travel` |
| **Curriculum** | Satu seri konten yang saling berkorelasi dan berurutan | "Perjalanan dari Nol Sampai Pro" |
| **Category** | Grouping besar dalam curriculum — dulu "season" | "Perjalanan dari Nol" |
| **Subcategory** | Sub-grouping dalam category — dulu "level" | "Pemula Absolut", "Mulai Pede" |
| **Topic** | Materi konten individual, wajib dalam subcategory | "#01 Filter Air" |
| **Adhoc Topic** | Konten lepas tanpa curriculum | "Tips Harian Aquascape" |

**Aturan:**
- Satu niche bisa punya banyak curriculum
- Satu curriculum bisa punya banyak category
- Satu category bisa punya banyak subcategory
- **Topic wajib punya subcategory** (dulu "level")
- Adhoc topic tidak terikat curriculum manapun

### 2.2 Content State Machine

Setiap topic melewati state ini:

```
PLANNED ──▶ GENERATED ──▶ REVIEWED ──▶ SCHEDULED ──▶ LIVE
                   │                      │
                   └──▶ FAILED ──▶ RETRY──┘
```

| State | Makna | Tampil di Bio? |
|-------|-------|:---:|
| `planned` | Rencana, belum digenerate | ✅ upcoming section |
| `generated` | Slide + caption sudah jadi, belum direview | ❌ internal |
| `reviewed` | Konten sudah di-approve | ❌ internal |
| `scheduled` | Terjadwal di antrian posting | ✅ upcoming section |
| `live` | Sudah terbit di IG | ✅ archive section |
| `failed` | Gagal posting (IG error, timeout, dll) | ❌ internal |
| `retry` | Akan dicoba ulang posting | ❌ internal |

### 2.3 Adhoc Topic

Topic yang tidak termasuk curriculum manapun. Berguna untuk:
- Konten musiman (lebaran, tahun baru)
- Promo / kolaborasi
- Konten spontan "behind the scene"

Adhoc topic tetap melalui pipeline generate → review → schedule/post yang sama, tapi tidak punya nomor urut curriculum.

---

## 3. Data Model & Source of Truth

### 3.1 Data Ownership & Cross-Reference

Ada **2 file master** dengan tanggung jawab berbeda, bukan 1 file tunggal:

```
source_of_truth.json  ← MASTER konten (curriculum, slides, facts, caption)
schedule.json          ← MASTER eksekusi (jadwal, status posting, result_id)

bio/index.html         ← DERIVED dari source_of_truth + schedule.json (data live)
curriculum.md          ← DERIVED dokumentasi
resource/photos/       ← CACHE slide images + facts JSON
```

**Pembagian tanggung jawab:**

| Aspek | Ditulis oleh | Dimana |
|-------|-------------|--------|
| Curriculum structure | User / CRUD | `source_of_truth.json` |
| Slides + facts + caption | Generate command | `source_of_truth.json` |
| Status `planned` → `generated` → `reviewed` | Generate / Review | `source_of_truth.json` |
| Jadwal posting | Post / Confirm | `schedule.json` (+ `source_of_truth.json` menyimpan `scheduled_time` sebagai referensi) |
| Status `scheduled` | Confirm | `source_of_truth.json` |
| `done`, `result_id`, `permalink` | Runner | `schedule.json` |
| Status `live`, `result_id`, `permalink` | Runner | `source_of_truth.json` |

**Hubungan schedule.json ↔ source_of_truth.json:**

Setiap entry di `schedule.json` punya field `source_ref` yang berisi **path ke topic/content di source_of_truth**.

- **Curriculum topic (bagian dari curriculum):**
  ```json
  { "source_ref": "aquarisamatiran:perjalanan-dari-nol:1:2:01" }
  ```
  Format: `{account}:{curriculum_id}:{category}:{subcategory}:{topic}`
  Referensi lengkap ke topic dalam curriculum.

- **Adhoc topic (independent, bukan bagian curriculum):**
  ```json
  { "source_ref": "aquarisamatiran:adhoc:tip-harian-001" }
  ```
  Format: `{account}:adhoc:{adhoc_id}`
  Tidak punya category/subcategory karena konten independent.

- **Non-curriculum entry (reel/foto bebas tanpa referensi):**
  ```json
  { "source_ref": null }
  ```
  Field `source_ref` bisa dihilangkan sama sekali untuk entry tanpa referensi.

Ini memungkinkan:
- schedule.json cukup nyimpen referensi, gak perlu duplikasi konten
- source_of_truth bisa di-rebuild kapan aja tanpa kehilangan relasi ke schedule
- Bio page di-generate dari source_of_truth (data konten) + schedule.json (data posting)

### 3.2 Proposed JSON Structure

Berdasarkan taxonomy: Curriculum → Category → Subcategory → Topic.

Subcategory **diletakkan di dalam category** masing-masing, bukan flat list global. Ini mencegah conflict ID antar category dan memperjelas hierarki.

```json
{
  "version": 5,
  "accounts": {
    "aquarisamatiran": {
      "niche": "aquascape",
      "curriculums": [
        {
          "id": "perjalanan-dari-nol",
          "title": "Perjalanan dari Nol Sampai Pro",
          "description": "Belajar aquarium step by step",
          "categories": {
            "1": {
              "title": "Perjalanan dari Nol",
              "description": "Season 1 — dari zero ke advanced",
              "subcategories": {
                "1": { "title": "Pemula Absolut" },
                "2": { "title": "Mulai Pede" }
              }
            },
            "2": {
              "title": "Eksperimen Lanjutan",
              "description": "Season 2 — mulai eksperimen",
              "subcategories": {
                "1": { "title": "Naik Kelas" }
              }
            }
          },
          "topics": {
            "01": {
              "title": "Aquarium itu Apa?",
              "display_name": "Ekosistem Akuarium",
              "slug": "aquarium-itu-apa",
              "category": "1",
              "subcategory": "1",
              "level": 1,
              "status": "live",
              "result_id": "17882725962597921",
              "permalink": "https://www.instagram.com/p/...",
              "scheduled_time": null,
              "slides": [
                { "type": "cover", "title": "Ekosistem Akuarium", "subtitle": "Dunia Air di Rumahmu" },
                { "type": "fact", "number": 1, "title": "Apa Itu Aquarium? 💧", "description": "...", "tags": [...] },
                { "type": "cta" }
              ],
              "caption": "Pernah penasaran...",
              "facts_cache": "edu_aquarium_itu_apa_facts.json"
            }
          }
        }
      ],
      "adhoc_topics": [
        {
          "id": "tip-harian-001",
          "title": "5 Tips Air Tetap Jernih",
          "slug": "tips-air-jernih",
          "status": "planned",
          "slides": [],
          "caption": ""
        }
      ]
    }
  }
}
```

**Key points:**
- Subcategory **nested di dalam category**, bukan flat list — jadi ID subcategory unik per-category
- Topic punya `category` + `subcategory` (keduanya wajib untuk curriculum topic)
- Category dan subcategory title hanya ditulis **satu kali** sebagai source of truth — tidak ada duplikasi yang bisa typo
- `slides` array menyimpan struktur slide tanpa duplikasi konten penuh
- `facts_cache` merujuk ke file JSON terpisah (biar source_of_truth tetap ringan)
- `accounts` key memungkinkan multiple akun dalam 1 file (atau dipisah per file — lihat 4.2)

**Menjaga konsistensi nama category/subcategory:**
- Nama hanya ditulis **1x** di definisi `categories` → semua topic yang referensi ke ID itu otomatis pake nama yang sama
- CRUD category/subcategory via bot / CLI dengan autocomplete — mengurangi risiko typo
- Kalau ada rename, cukup edit 1 baris di definisi category/subcategory — semua topic yang referensi ikut berubah otomatis

### 3.3 Schedule Entry & Relation

schedule.json adalah **master eksekusi** — antrian yang dibaca runner.

Setiap entry punya referensi **cross ke source_of_truth** via field `source_ref`:

```json
{
  "source_ref": "aquarisamatiran:perjalanan-dari-nol:1:2:01",
  "time": "2026-06-15 19:00",
  "type": "carousel",
  "done": false,
  "urls": ["https://files.catbox.moe/..."],
  "result_id": null,
  "permalink": null,
  "failed_attempts": 0,
  "last_error": null
}
```

**Field `source_ref` memiliki 3 bentuk tergantung jenis konten:**

| Jenis | Format `source_ref` | Contoh |
|-------|---------------------|--------|
| **Curriculum topic** | `{account}:{curriculum_id}:{category}:{subcategory}:{topic}` | `aquarisamatiran:perjalanan-dari-nol:1:2:01` |
| **Adhoc topic** | `{account}:adhoc:{adhoc_id}` | `aquarisamatiran:adhoc:tip-harian-001` |
| **Non-curriculum** (reel/foto bebas) | `null` atau field dihilangkan | `"source_ref": null` |

**Siklus update:**
1. 🖊️ **Confirm/schedule** → tulis entry ke schedule.json + source_of_truth `status: scheduled`, `scheduled_time: ...`
2. 🏃 **Runner posting** → update `done`, `result_id`, `permalink` di schedule.json
3. 📝 **Runner selesai** → cocokkan via `source_ref`, update `status: live`, `result_id`, `permalink` di source_of_truth
   - Curriculum topic → parse source_ref, temukan topic di source_of_truth
   - Adhoc topic → parse adhoc_id, temukan di adhoc_topics[]
   - Non-curriculum → tidak update source_of_truth (source_ref null)
4. 🌿 **Bio page** → re-generate dari source_of_truth (live + planned + scheduled)

**Aturan konsistensi:**
- Entry schedule dengan `source_ref` tidak null WAJIB punya referensi valid di source_of_truth
- `source_ref` tidak boleh diubah manual — hanya sync yang boleh rebuild
- `result_id` dan `permalink` harus identik di kedua file (validasi via consistency check)
- Entry non-curriculum (`source_ref: null`) tetap diproses runner, tapi tidak terikat ke source_of_truth

---

## 4. Multi-Account Configuration

### 4.1 Per-Account Config Items

```
├─ IG Credentials
│   ├─ access_token
│   ├─ user_id
│   └─ username
├─ AI Keys
│   ├─ gemini_api_keys[] (multiple, fallback)
│   └─ pexels_api_key
├─ Branding
│   ├─ handle (@aquarisamatiran)
│   ├─ palette (bg_dark, bg_card, text_main, text_sub, accent, accent2, tag_bg)
│   ├─ slide_size (1080x1080)
│   ├─ logo_path
│   └─ cta_template
├─ Content Style
│   ├─ niche_name (aquascape / food / travel)
│   ├─ sd_prompt_prefix (aquascape theme)
│   ├─ pexels_query_suffix
│   ├─ content_types (edu, story, humor, tips, dll)
│   └─ caption_style (santai / formal / playful)
├─ Bio Page
│   ├─ pages_repo
│   └─ pages_pat
└─ Schedule Slots (reuse dari slots.json)
```

### 4.2 Storage Design

**Rekomendasi: Opsi A — File-based directory**

```
accounts/
├── aquarisamatiran/
│   ├── config.json              (branding, style, niche — NON-secret)
│   ├── source_of_truth.json     (master konten)
│   └── schedule.json            (master eksekusi)
├── another-account/
│   ├── config.json
│   ├── source_of_truth.json
│   └── schedule.json
└── template/
    └── config.json               (template untuk account baru)
```

**Alasan:**
1. **Portable** — cukup copy folder `accounts/` ke VPS baru, semua data + config kebawa
2. **Backup mudah** — tinggal taruh folder accounts di git (kecuali config yang contains token)
3. **Isolasi** — error di satu account gak nganggu account lain
4. **Sederhana** — gak perlu dependency database

**Secrets tetep di `.env` atau env vars:**
```
NIX_ACCOUNTS_AQUARISAMATIRAN_IG_TOKEN=IGAA...
NIX_ACCOUNTS_AQUARISAMATIRAN_GEMINI_KEY=AIza...
NIX_ACCOUNTS_AQUARISAMATIRAN_PEXELS_KEY=...
```

**Format config.json:**
```json
{
  "ig_handle": "@aquarisamatiran",
  "ig_username": "aquarisamatiran",
  "niche": "aquascape",
  "palette": {
    "bg_dark": "#0A1628",
    "bg_card": "#1A2A4A",
    "text_main": "#F0F4FF",
    "text_sub": "#A0B4D0",
    "accent": "#4FC3F7",
    "accent2": "#00E5FF",
    "tag_bg": "#2A3A5A"
  },
  "slide_size": [1080, 1080],
  "logo_path": "resource/logo/logo-cta-square.png",
  "cta_template": "Follow @{handle}\nuntuk edukasi {topic}\nsetiap minggu!",
  "sd_prompt_prefix": "aquascape aquarium, underwater planted tank",
  "pexels_query_suffix": "aquarium fish",
  "content_types": ["edu", "story", "humor", "tips", "review"],
  "caption_style": "santai",
  "bio_pages_repo": "imtopp/aquarisamatiran-pages",
  "schedule_slots": "default"
}
```

---

## 5. Content Pipeline

### 5.1 Pipeline Flow

```
┌──────────────────────────────────────────────────────────┐
│  PHASE 1: GENERATE                                        │
│                                                          │
│  [Step 1] AI → Facts JSON                                │
│    Input: topic + num_facts                              │
│    Process: Gemini → structured JSON                     │
│    Output: edu_{slug}_facts.json (cached)                │
│    ⚠️  Skip if cache exists (manual override: --force)   │
│                                                          │
│  [Step 2] AI → Caption                                   │
│    Input: facts JSON + topic + style instruction         │
│    Process: Gemini from facts data                       │
│    Output: caption text (cached / pending)               │
│    ⚠️  Skip if caption already generated & approved      │
│                                                          │
│  [Step 3] Generate Slide Images                          │
│    Input: facts JSON                                     │
│    Process: SD / Pexels / Wikimedia → background + text  │
│    Output: slide PNG files                               │
│    ⚠️  Resumable: jika gagal di slide ke-5,              │
│        cukup ulang dari slide ke-5                       │
│                                                          │
│  [Auto] Update source_of_truth                           │
│    → status: "generated"                                 │
│    → slides array with display_name, subtitle, facts     │
│    → caption text                                        │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  PHASE 2: REVIEW                                          │
│                                                          │
│  [Step 4] Preview                                        │
│    → Lihat slide + caption                               │
│    → Approve / Reject / Edit                             │
│                                                          │
│  [Step 4a] If reject slides (gambar kurang bagus):       │
│    → Regenerate slide images (skip AI, pake cache facts) │
│    → atau edit caption                                   │
│                                                          │
│  [Step 4b] If reject facts (konten kurang akurat):       │
│    → Hapus cache facts JSON                              │
│    → Regenerate facts dari AI (force)                    │
│    → Auto regenerate slide images + caption ulang        │
│                                                          │
│  [Step 5] Approve                                        │
│    → status: "reviewed"                                  │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  PHASE 3: PUBLISH                                         │
│                                                          │
│  [Step 6] Upload + Schedule / Post Now                   │
│    → Upload slides ke Catbox                              │
│    → Schedule: tulis ke schedule.json (+ cron-job.org)   │
│    → Post Now: langsung ke IG API                        │
│    → status: "scheduled" atau "live"                     │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  PHASE 4: RECORD                                          │
│                                                          │
│  [Step 7] Runner selesai posting                         │
│    → schedule.json: done=true, result_id, permalink      │
│    → source_of_truth: status="live", result_id, permalink│
│    → update_bio(): regenerate bio page                   │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### 5.2 State Transitions Detail

| Event | From | To | Action |
|-------|------|----|--------|
| Topic dibuat | — | `planned` | Entry di source_of_truth |
| Generate selesai | `planned` | `generated` | Simpan slides + caption |
| User approve review | `generated` | `reviewed` | — |
| User jadwalkan | `reviewed` | `scheduled` | Tulis ke schedule.json |
| User post now | `reviewed` | `live` | Post ke IG langsung, dapat result_id |
| Runner sukses post | `scheduled` | `live` | Update result_id, permalink |
| Post gagal | `scheduled` | `failed` | Catat error, increment retry |
| User minta retry | `failed` | `scheduled` | Reset failed_attempts |

### 5.3 Error Recovery Rules

| Error | Recovery | Notifikasi |
|-------|----------|------------|
| Gemini API 429/503 | Fallback key → fallback model → exponential backoff | Bot + CLI |
| SD generate timeout | Skip slide, retry 1x, notif partial failure | Bot + CLI |
| Catbox upload fail | Retry 3x dengan delay 5s, skip slide | Bot |
| IG API post fail | Retry 1x, set failed state | Bot |
| Partial failure (misal 1/8 slide gagal) | Hanya regenerate slide yang gagal | Bot |

**Notifikasi dikirim ke semua touchpoint yang tersedia.** Saat ini via Telegram bot (prioritas utama). Ke depannya bisa via dashboard notification, email, atau webhook.

---

## 6. Scheduling System

### 6.1 Architecture

```
slot_config/slots.json         ← configurable slot definitions
       │
cron-job.org API               ← sync slot definitions otomatis
       │
cron-job.org triggers          ← HTTP call ke GitHub API
       │
GH Actions scheduler.yml       ← workflow_dispatch → runner.py
       │
runner.py                      ← baca schedule.json, posting ke IG
       │
selesai → update schedule.json + source_of_truth + bio
```

### 6.2 Slot Definitions

```json
{
  "slots": [
    {"id": "weekday-19", "days": [0,1,2,3], "time": "19:00"},
    {"id": "fri-15", "days": [4], "time": "15:00"},
    {"id": "weekend-09", "days": [5,6], "time": "09:00"},
    {"id": "lunch-12", "days": [0,1,2,3,4], "time": "12:00"}
  ]
}
```

**Custom one-time slot:** Untuk post di tanggal & jam spesifik (bukan recurring), user bisa langsung set `time` di schedule.json tanpa perlu slot config. Contoh:
```
python main.py post-carousel --schedule cron "2026-06-25 14:30" "..."
```

Ini akan menulis entry ke schedule.json dengan waktu spesifik. Runner akan nge-post di jam itu dan entry langsung **ilang/hilang** dari antrian setelah diproses (karena `done=true`). Tidak perlu daftarin slot khusus.

**Aturan:**
- Recurring slot → definisi di `slots.json`, trigger cron-job.org otomatis
- One-time slot → langsung tulis ke `schedule.json` tanpa daftarin slot
- Runner nge-post semua entry yang `done=false` dan `time <= now`, terlepas dari slot mana asalnya

### 6.3 Runner

**Lokasi eksekusi:** Hanya GH Actions (`.github/workflows/scheduler.yml`)
**Trigger:** cron-job.org → workflow_dispatch

**VPS tidak menjalankan runner.** VPS hanya untuk:
- Telegram bot (systemd service)
- CLI akses manual

### 6.4 Post Now

Post langsung (tanpa jadwal) bisa dari:
- CLI: `python main.py post-carousel ...` (tanpa `--schedule`)
- Bot: `/postnow` atau `/confirm` tanpa jadwal

---

## 7. Touchpoints

### 7.1 Telegram Bot

**Infrastructure:** Berjalan di VPS sebagai systemd service (`nix-bot`)

**Command Tree:**

```
/start, /help              — Panduan bot
/topics [filter]           — List topic (by status, category, curriculum)
/schedule                  — Antrian posting (pending + done)

=== CONTENT ===
/create <curriculum>       — Buat topic baru dalam curriculum
/generate <topic>          — Generate konten (facts + slides + caption)
  └── progress: real-time via Telegram updates

=== REVIEW ===
/review                    — Preview konten pending review
/approve                   — Setujui konten → ready to publish
/editcaption <instruction> — Edit caption via AI
/regenerate                — Ulang generate gambar (skip AI facts)

=== PUBLISH ===
/post <topic> [jadwal]     — Preview + caption → siap schedule atau post now
/confirm                   — Eksekusi schedule / post now
/cancel                    — Batalin pending post

=== MANAGEMENT ===
/setslot                   — Kelola slot jadwal (add/remove/sync cron-job)
/curriculum                — CRUD curriculum (add/edit/delete category/subcategory/topic)
/status                    — Cek status GH Actions runner
/myid                      — Info chat ID
```

### 7.2 CLI

```
python main.py <command> [options]

Commands:
  curriculum                  — CRUD + sync source of truth
  generate-carousel-sd <topic>  — Generate carousel dgn SD (GH Actions)
  generate-carousel <topic>     — Generate carousel dgn Pexels (local)
  post-carousel               — Upload + jadwalkan/tayangkan carousel
  post-photo <url>            — Post foto ke IG
  post-reel <url>             — Post reel ke IG
  stage-reel <video>          — Upload video ke Catbox
  stage-photo <photo>         — Upload foto ke Catbox
  sync-slots                  — Sync slot config ke cron-job.org
  compress-slides             — Kompres slide PNG ke JPG
```

### 7.3 Dashboard

**Status: TBD** — akan dirancang setelah seluruh workflow matang di bot.

---

## 8. Bio Page

### 8.1 Mekanisme

- Source: `source_of_truth.json` (topic `live` + `planned` + `scheduled`) + `schedule.json` (jadwal)
- Generator: `update_bio.py`
- Trigger: setiap kali runner sukses posting
- Deployment: push ke repo pages yang dikonfigurasi per-account

**Untuk multi-account:** Setiap account punya repo pages sendiri, terkonfigurasi di `config.json` tiap account:
```json
{
  "bio_pages_repo": "imtopp/aquarisamatiran-pages"
}
```

Proses `update_bio` akan:
1. Generate `bio/index.html` spesifik untuk account tersebut
2. Clone repo pages yang sesuai
3. Copy file → commit → push ke repo pages masing-masing

### 8.2 Struktur

```
aquarisamatiran-pages/
├── index.html              (bio page — hub)
├── curriculum/
│   └── <curriculum-id>/
│       └── index.html      (detail curriculum)
├── topic/
│   └── <slug>/
│       └── index.html      (detail topic + IG embed)
└── assets/
    └── style.css
```

Setiap halaman topic otomatis ter-generate pas status jadi `live`.

---

## 9. Error Handling

### 9.1 Retry Policy

| Komponen | Max Retry | Delay | Backoff | Notifikasi |
|----------|-----------|-------|---------|------------|
| Gemini API | 3 keys × 2 models | — | Langsung ganti key | Bot |
| Catbox upload | 3 | 5s | Linear | Bot |
| IG post | 2 | 30s | Exponential | Bot |
| SD generate | 1 per slide | — | — | Bot (partial) |

### 9.2 Dead Letter Queue

Jika post gagal setelah semua retry:
1. Set `status = "failed"` di source_of_truth + schedule.json
2. Catat `last_error` + `failed_attempts`
3. Notifikasi user via bot
4. User bisa `/retry <topic>` untuk reset

### 9.3 Data Consistency Check

Setiap habis `sync`, validasi otomatis:
- Semua topic `scheduled` ada di schedule.json
- Semua topic `live` punya result_id + permalink
- Tidak ada duplikasi entry di schedule.json
- Bio page mencakup semua topic `live`

---

## 10. Acceptance Criteria

### 10.1 End-to-End Flow

```
GIVEN seorang user ingin membuat konten baru
WHEN user melalui pipeline:
  1. Buat topic (curriculum atau adhoc)
  2. Generate konten (fakta + gambar + caption)
  3. Review dan approve
  4. Jadwalkan atau tayangkan langsung
THEN:
  ✅ Data konsisten di source_of_truth
  ✅ Schedule.json terisi dengan benar
  ✅ IG post berhasil terbit
  ✅ result_id + permalink tercatat
  ✅ Bio page terupdate
```

### 10.2 Error Scenarios

```
GIVEN proses generate terhenti di tengah
WHEN user retry
THEN:
  ✅ Tidak memanggil AI lagi untuk facts yang sudah di-cache
  ✅ Hanya melanjutkan dari slide yang gagal

GIVEN IG post gagal
WHEN user cek status
THEN:
  ✅ Status tercatat "failed"
  ✅ Ada trace error
  ✅ User bisa retry
```

### 10.3 Consistency Rules

- `source_of_truth.json` adalah satu-satunya acuan
- Tidak ada field yang sama di 2 file dengan nilai berbeda
- Semua `live` topic punya IG permalink valid
- Bio page mencerminkan data `live` terkini

---

## 11. Future Scope

| Fitur | Prioritasi | Catatan |
|-------|:----------:|---------|
| **Dashboard Web** | Medium | Setelah workflow bot matang |
| **Multi-account switcher** | Medium | Tergantung desain config storage |
| **Analytics** | Low | Engagement stats, best posting time |
| **Content Calendar View** | Low | Visual kalender schedule |
| **Auto-hashtag generator** | Low | Dari topic keywords |
| **Bulk import curriculum** | Low | Dari CSV / template |
| **IG Story scheduler** | Low | Stories juga perlu di-schedule |
| **A/B testing caption** | Very Low | Multiple caption variants |

---

## 12. Glossary

| Istilah | Definisi |
|---------|----------|
| **Niche** | Domain/industri konten (aquascape, food, travel) |
| **Curriculum** | Seri konten berkesinambungan dalam satu niche |
| **Category** | Grouping besar dalam curriculum — dulu "season" |
| **Subcategory** | Sub-grouping dalam category — dulu "level" |
| **Topic** | Materi konten individual, wajib dalam subcategory |
| **Adhoc** | Konten independent di luar curriculum |
| **Source of Truth** | File master yang jadi acuan semua data |
| **Derived** | File yang di-generate dari source of truth |
| **Runner** | Proses yang nge-post konten ke IG sesuai jadwal |
| **Slot** | Definisi jadwal posting (hari + jam) |
| **State Machine** | Siklus hidup konten: planned → generated → reviewed → scheduled → live (plus failed/retry) |

---

## 13. Codebase Architecture

### 13.1 Final Directory Layout

```
.env                  — secrets (gitignored)
.gitignore
AGENTS.md
PRD.md
README.md
requirements.txt
docs/                 — panduan pengguna
tests/                — test suite
main.py               — entry point CLI (thin, ~5 baris)
nixfw/                — 📦 framework package (semua logic)
└── ...
accounts/             — 👤 per-account data
└── <name>/
    ├── config.json           — branding, niche, style
    ├── source_of_truth.json  — master konten
    ├── schedule.json         — master jadwal
    ├── bio/index.html        — landing page (auto-generated)
    └── resource/             — videos, photos, music, output, published, logo
```

Tidak ada file bisnis/logic di root — semua di `nixfw/`.  
Tidak ada data konten di root — semua di `accounts/<name>/`.  
Root cuma: entry point, konfigurasi global, dan dokumentasi.

### 13.2 nixfw/ Package Structure

```
nixfw/
├── __init__.py
├── __main__.py           — `python -m nixfw`
├── config.py             — paths, palette, API constants, niche registry
├── ig_client.py          — Instagram Graph API wrapper
├── editor.py             — video editor + file upload
├── runner.py             — posting dari schedule.json
├── slot_manager.py       — jadwal loader/syncer
├── cli/
│   └── dispatch.py       — CLI command dispatch
├── curriculum/
│   └── manager.py        — CRUD curriculum
├── carousel/
│   ├── composer.py       — komposisi slide
│   └── slides/           — cover, fact, cta
├── content/
│   ├── generator.py      — generate konten via AI
│   └── providers/        — facts_generator, wikimedia, inaturalist, image_utils
├── bio/
│   ├── generator.py      — update bio page
│   └── templates/        — Jinja2 templates
├── bot/
│   ├── bot.py            — Telegram bot
│   └── handlers/         — handler perintah
├── dashboard/            — (future)
└── templates/
    └── account/          — scaffolding buat `account init`
```

### 13.3 Entry Points

| Cara | Perintah | Keterangan |
|------|----------|------------|
| CLI | `python main.py <command>` | Thin wrapper → `nixfw.cli.dispatch` |
| CLI | `python -m nixfw <command>` | Langsung ke framework |
| Runner | `.github/workflows/runner.py` | Thin wrapper → `nixfw.runner.run()` |
| Bio | `.github/workflows/update_bio.py` | Thin wrapper → `nixfw.bio.generator.update_bio()` |
| Bot | systemd service | `python -m nixfw.bot.bot` |

### 13.4 Account Discovery

Framework otomatis menemukan data akun berdasarkan argumen `--account` atau
default account yang dikonfigurasi:

```
accounts/<name>/config.json
accounts/<name>/source_of_truth.json
accounts/<name>/schedule.json
accounts/<name>/bio/index.html
accounts/<name>/resource/
```

Akun baru: copy `nixfw/templates/account/`, isi `config.json`, jalankan
`curriculum sync`.

---
