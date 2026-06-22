---
name: nix-arch-analysis
description: Trace end-to-end data flow of NIX Telegram bot commands, file modifications, API calls, and git/GH Actions triggers. Use when analyzing how a command flows through the system, debugging data propagation, or planning architecture changes.
---

# NIX Architecture Analysis Skill

Use this skill to trace how any Telegram command, cron trigger, or CLI operation flows through NIX — from user input through handlers, file writes, API calls, git sync, and deployment.

## Legend

```
📱 Telegram → 💻 VPS Bot → 📁 File lokal → 🔄 Auto-push ke GitHub
📱 Telegram → 🌐 GitHub API → 🤖 GH Actions → 📁 Repo
⏰ cron-job.org → 🌐 GitHub API → 🤖 GH Actions → 📁 Repo → 🚀 Deploy VPS
```

## 1. Critical Files Map

| File | Role |
|---|---|
| `nixfw/bot/bot.py` | Telegram bot — all command handlers, Gemini calls, git sync |
| `nixfw/cli/commands.py` | CLI commands (post-carousel, stage, etc.) called via subprocess |
| `nixfw/curriculum/manager.py` | Curriculum CRUD (categories, subcategories, topics), curriculum sync |
| `nixfw/config.py` | Paths, palette, API constants, niche registry |
| `nixfw/ig_client.py` | Instagram Graph API wrapper (post carousel/photo/reel) |
| `nixfw/runner.py` | Post from schedule.json (called by scheduler) |
| `nixfw/bio/generator.py` | Bio page (Jinja2 template render + upload to pages repo) |
| `nixfw/slot_manager.py` | Slot jadwal loader/syncer + cron-job.org sync |
| `nixfw/editor.py` | Video editor + file upload (Catbox) |
| `accounts/aquarisamatiran/source_of_truth.json` | Master konten (curriculum + topics) |
| `accounts/aquarisamatiran/schedule.json` | Master jadwal & status posting |
| `accounts/aquarisamatiran/bio/index.html` | Landing page (auto-updated) |
| `nixfw/slots.json` | Definisi slot global |
| `.github/workflows/scheduler.yml` | Cron-triggered posting via GH Actions |
| `.github/workflows/deploy.yml` | VPS deploy on push |
| `.github/workflows/generate.yml` | Slide generation via Stable Diffusion on GH runners |

## 2. API Registry

| API | Called From | Trigger |
|---|---|---|
| **Gemini REST API** | `_call_gemini()` in bot.py | caption generation, fact generation, chat |
| **GitHub REST API** | `_dispatch_workflow()`, `status_cmd()`, `cancel_wf_callback()` in bot.py | dispatch generate/clean workflows, check status, cancel |
| **Instagram Graph API** | `InstagramClient.post_carousel()` in ig_client.py | posting carousel/photo/reel (via CLI subprocess) |
| **cron-job.org** | `SlotManager.sync_cronjob()` in slot_manager.py | slot add/remove sync |
| **Catbox** | `upload_file()` in commands.py | slide image upload (fallback: GitHub raw URL) |
| **Pexels** | `_search_pexels_image()` in commands.py | image search |

## 3. Git Sync Map (`_git_sync_after` call sites)

Every mutation command in bot.py triggers `_git_sync_after(commit_msg)` which runs: `git add -A → git commit → git push origin main` with 3× retry + `pull --strategy-option=ours`.

| Command | Commit Message |
|---|---|
| `/topic cat add` | `auto: add category` |
| `/topic cat sub add` | `auto: add subcategory` |
| `/topic cat rename` | `auto: rename cat {id}` |
| `/topic cat remove` | `auto: remove cat {id}` |
| `/topic cat sub rename` | `auto: rename subcat {id}.{sid}` |
| `/topic cat sub remove` | `auto: remove subcat {id}.{sid}` |
| `/topic add` | `auto: add topic` |
| `/topic edit` | `auto: edit {ref}` |
| `/topic delete` | `auto: delete {ref}` |
| `/topic move` | `auto: move {ref}` |
| `/post confirm` | `auto: post {slug}` or `auto: schedule {slug}` |
| `/post caption` | `auto: caption {slug}` |
| `/schedule delete` | `auto: unschedule {ref}` |
| `/schedule slot add` | `auto: slot add {sid}` |
| `/schedule slot remove` | `auto: slot remove {sid}` |
| fact:confirm callback | `auto: facts {slug}` |

`_git_sync_after` is NOT called by: read-only commands (list/show/status/help/start), `/generate` (fact confirmation triggers it, not initial generate), free-form chat, cancel workflow.

### Sync-only commands

| Command | How it syncs |
|---|---|
| `/sync` | Manual `git add → commit → push → push pages → restart bot` (not via `_git_sync_after`) |
| `/post clean` | Delegates to GH Actions `clean.yml` which commits directly |
| Scheduler (cron) | GH Actions `scheduler.yml` commits directly |

## 4. Flow Templates

### Template 1: Curriculum CRUD (cat/sub/topic add/edit/delete/move)

```
📱 /topic add C1 1 "Judul"
  → telegram_{action}_{entity}()   # nulis source_of_truth.json
  → _git_sync_after()              # git add → commit → push origin main
  ✅ VPS → GitHub langsung
```

### Template 2: Generate content

```
📱 /generate C1.2#09
  → generate_facts() via Gemini    # API call (VPS)
  → Tampil preview + tombol confirm
  → User klik ✅ confirm
    → Simpan edu_{slug}.json       # cache facts
    → _git_sync_after()            # push cache ke GitHub
    → _dispatch_workflow()         # POST ke GH API → trigger generate.yml
      → GH Actions: generate-carousel-sd
        - Generate slide gambar pake Stable Diffusion
        - Simpan di resource/photos/{slug}_sd_*.jpg
        - Push ke repo
  ✅ Facts: VPS → GitHub
  ✅ Gambar: GH Actions → Repo langsung
```

### Template 3: Post topic

```
📱 /post C1.2#09
  → Cari slide terbaru di resource/photos/
  → git pull --rebase               # sync data terbaru
  → Cek status (gak boleh live/scheduled)
  → Kalo tanpa waktu:
      SLOT_MANAGER.next_occurrences() → pilih slot via inline keyboard
  → Kirim preview slide (media group)
  → Generate caption via Gemini
  → Simpan caption ke source_of_truth.json
  → Simpan pending state di memory

📱 /post confirm [--now]
  → subprocess: python main.py post-carousel --slug {slug} ...
    - Upload slide ke Catbox (atau fallback GitHub raw URL)
    - Simpan .uploaded.json + .urls_cache.json
    - Mode --now:
        Instagram Graph API → post carousel → result_id + permalink
        source_of_truth.json status="live"
        schedule.json entry done=True
        update_bio() → bio/index.html
    - Mode scheduled:
        schedule.json entry dengan time
        source_of_truth.json status="scheduled"
  → _git_sync_after()
  ✅ VPS → GitHub (semua file)
```

### Template 4: Schedule slot management

```
📱 /schedule slot add
  → Wizard interaktif (hari + jam)
  → SLOT_MANAGER.add_slot()         # nulis nixfw/slots.json
  → SLOT_MANAGER.sync_cronjob()     # PATCH ke cron-job.org API
  → _git_sync_after()
  ✅ VPS → GitHub + cron-job.org
```

### Template 5: Full sync

```
📱 /sync
  → Manual steps (bukan _git_sync_after):
    1. git add + commit "pre-sync save"
    2. git fetch + merge origin/main --strategy-option=ours
    3. pip install -q -r requirements.txt
    4. python main.py curriculum sync
       → _sync_curriculum_md()      # nulis curriculum.md
       → _sync_schedule_json()      # baca+tulis schedule.json
       → update_bio()               # nulis bio/index.html
    5. git add bio + commit "sync bio"
    6. git push origin main
    7. Push ke pages repo
    8. sudo systemctl restart nix-bot
  ✅ VPS → GitHub → Pages repo
```

### Template 6: cron-job.org → Scheduler

```
⏰ cron-job.org (setiap jam posting)
  → POST ke GitHub API: workflows/scheduler.yml/dispatches
    → GH Actions scheduler.yml:
      1. Baca schedule.json
      2. Cari entry non-done dengan time ≤ now
      3. Post ke Instagram
      4. schedule.json entry → done=True
      5. source_of_truth.json → status="live"
      6. update_bio() → bio/index.html
      7. git commit + push
      8. Trigger deploy.yml
  ✅ GH Actions → Repo → Deploy VPS
```

### Template 7: Clean topic

```
📱 /post clean C1.2#09
  → Validasi topic gak "live"
  → _dispatch_workflow()            # trigger clean.yml
    → GH Actions clean.yml:
      - Hapus file {slug}_sd_* dari resource/photos/
      - Hapus edu_{slug}* cache
      - Hapus entry dari schedule.json
      - Reset topic ke "planned" di source_of_truth.json
      - Hapus .uploaded.json
      - Commit + push ke repo
      - Trigger deploy.yml
  ✅ GH Actions → Repo → Deploy VPS
```

### Template 8: Edit caption

```
📱 /post caption C1.2#09 "ubah gaya lebih santai"
  → Load caption existing + facts cache
  → Gemini rewrite caption
  → Simpan ke source_of_truth.json
  → _git_sync_after()
  ✅ VPS → GitHub langsung
```

## 5. Complete Command Reference

| Command | Handler | Files Written | APIs | Git Sync | Auto-push |
|---|---|---|---|---|---|
| `/start` | `start()` | — | — | — | ❌ |
| `/help` | `help_cmd()` | — | — | — | ❌ |
| `/reset` | `reset()` | `chat_history.db` (delete) | — | — | ❌ |
| `/run <cmd>` | `run_cmd()` | depends on cmd | — | — | ❌ |
| `/status` | `status_cmd()` | — | GitHub REST | — | ❌ |
| `/myid` | `myid_cmd()` | — | — | — | ❌ |
| `/sync` | `sync_cmd()` | `source_of_truth.json`, `schedule.json`, `bio/index.html`, `.restart_flag` | GitHub REST | manual git | ✅ (push+deploy) |
| `/topic add` | `addtopic_cmd()` | `source_of_truth.json` | — | `_git_sync_after` | ✅ |
| `/topic edit` | `edittopic_cmd()` | `source_of_truth.json` | — | `_git_sync_after` | ✅ |
| `/topic delete` | `deletetopic_cmd()` | `source_of_truth.json` | — | `_git_sync_after` | ✅ |
| `/topic move` | `movetopic_cmd()` | `source_of_truth.json` | — | `_git_sync_after` | ✅ |
| `/topic cat add` | `addcategory_cmd()` | `source_of_truth.json` | — | `_git_sync_after` | ✅ |
| `/topic cat list` | `catlist_cmd()` | — | — | — | ❌ |
| `/topic cat rename` | `telegram_rename_category()` | `source_of_truth.json` | — | `_git_sync_after` | ✅ |
| `/topic cat remove` | `telegram_remove_category()` | `source_of_truth.json` | — | `_git_sync_after` | ✅ |
| `/topic cat sub add` | `addsubcategory_cmd()` | `source_of_truth.json` | — | `_git_sync_after` | ✅ |
| `/topic cat sub rename` | `telegram_rename_subcategory()` | `source_of_truth.json` | — | `_git_sync_after` | ✅ |
| `/topic cat sub remove` | `telegram_remove_subcategory()` | `source_of_truth.json` | — | `_git_sync_after` | ✅ |
| `/topic list` | `topics_cmd()` | — | — | — | ❌ |
| `/topic show` | `showtopic_cmd()` | — | — | — | ❌ |
| `/topic slides` | `slides_cmd()` | — | — | — | ❌ |
| `/generate <ref>` | `generate_cmd()` | deletes `edu_{slug}.json` cache | Gemini | ❌ (confirmation does) | ❌ |
| `/generate --force` | `regenerate_cmd()` | deletes `edu_{slug}.json` cache | Gemini | ❌ | ❌ |
| `fact:confirm` | `fact_callback()` | writes `edu_{slug}.json` | Gemini, GitHub REST | `_git_sync_after` | ✅ |
| `fact:retry` | `fact_callback()` | deletes `edu_{slug}.json` | Gemini | ❌ | ❌ |
| `/post <ref>` | `post_cmd()` | `source_of_truth.json` (caption) | Gemini, SlotManager | `git pull --rebase` | ❌ (confirm does) |
| `/post confirm` | `confirm_cmd()` | `source_of_truth.json`, `schedule.json`, `bio/index.html`, `.uploaded.json`, `.urls_cache.json` | IG Graph API, Catbox | `_git_sync_after` | ✅ |
| `/post confirm --now` | `confirm_cmd()` | same + `bio/index.html` via `update_bio()` | IG Graph API, Catbox | `_git_sync_after` | ✅ |
| `/post cancel` | `cancel_cmd()` | — | — | — | ❌ |
| `/post caption` | `editcaption_cmd()` | `source_of_truth.json` | Gemini | `_git_sync_after` | ✅ |
| `/post caption show` | `peekcaption_cmd()` | — | — | — | ❌ |
| `/post clean` | `clean_cmd()` | delegates to GH Actions | GitHub REST | GH Actions | ✅ (via action) |
| `/schedule` | `schedule_cmd()` | — | — | — | ❌ |
| `/schedule delete` | `delete_schedule_cmd()` | `schedule.json`, `source_of_truth.json` | — | `_git_sync_after` | ✅ |
| `/schedule slot add` | wizard + `setslot_cmd()` | `nixfw/slots.json` | cron-job.org | `_git_sync_after` | ✅ |
| `/schedule slot remove` | `setslot_cmd()` | `nixfw/slots.json` | cron-job.org | `_git_sync_after` | ✅ |
| `/schedule slot sync` | `setslot_cmd()` | — | cron-job.org | — | ❌ |
| `chat message` | `chat()` | `chat_history.db` | Gemini | — | ❌ |

## 6. File Modification Matrix

| File | Created by | Modified by |
|---|---|---|
| `source_of_truth.json` | curriculum init | cat/sub/topic CRUD, post caption, post confirm, clean, curriculum sync, scheduler |
| `schedule.json` | curriculum sync | post confirm (CLI), schedule delete, curriculum sync, scheduler, clean |
| `bio/index.html` | curriculum sync | post confirm (--now), curriculum sync, scheduler (cron) |
| `nixfw/slots.json` | slot manager init | slot add/remove |
| `resource/photos/*.jpg` | GH Actions generate.yml | GH Actions clean.yml |
| `resource/photos/edu_*.json` | fact confirm callback | fact retry, generate refresh, clean |
| `resource/.uploaded.json` | CLI post-carousel | CLI post-carousel, clean |
| `resource/.urls_cache.json` | CLI post-carousel | CLI post-carousel |
| `bot/chat_history.db` | bot init | chat(), reset() |

## 7. Analysis Workflow Template

When analyzing how a feature/command flows through NIX:

1. **Find the handler** — grep `async def.*_cmd(` in `bot.py` or check the command reference above
2. **Trace file writes** — every `write_text()`, `save()`, `dump()` call in the handler chain
3. **Trace API calls** — every `httpx.post/get`, `requests.post/get`, subprocess calling external
4. **Check git sync** — is `_git_sync_after()` called? Or manual git? Or GH Actions?
5. **Check deploy trigger** — does it push to main → deploy.yml auto-triggers? Or does it dispatch a workflow?
6. **Map the full path** — Input → Handler → File writes → API calls → Git sync → Deploy

## 8. Key Architecture Decisions

- **No direct IG API from bot.py** — all Instagram posting delegated to CLI via `subprocess.run(["python", "main.py", "post-carousel", ...])`
- **`_git_sync_after()` is the persistence backbone** — without it, all mutations are local-only
- **Two parallel slide generation paths**: local VPS facts (Gemini) → GH Actions SD rendering fallback
- **`/sync` is the only command that restarts the bot** — it writes `.restart_flag` then runs `sudo systemctl restart nix-bot`
- **`confirm_cmd()` has the deepest flow** — subprocesses into CLI which uploads to Catbox, calls IG API, updates 4+ files, and triggers bio regeneration
- **Catbox fallback** — blocked on VPS datacenter IP → falls back to raw GitHub URLs for committed slides
- **Debounce via `asyncio.Lock()`** — `_git_sync_after` uses `_sync_lock` to serialize concurrent pushes
