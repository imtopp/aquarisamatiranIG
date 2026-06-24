# NIX Architecture Report — generated 2026-06-22 21:43

Scanned: `nixfw/bot/bot.py`, `nixfw/cli/commands.py`, `.github/workflows/`, `accounts/`


# Accounts


| Name | Handle | Niche | SOT | Schedule | Bio |
| --- | --- | --- | --- | --- | --- |
| aquarisamatiran | @aquarisamatiran | aquascape | ✅ | ✅ | ✅ |


# Command Reference


| Handler | File | Line | Type |
| --- | --- | --- | --- |
| help_cmd | bot.py | 261 | bot |
| topics_cmd | bot.py | 427 | bot |
| catlist_cmd | bot.py | 462 | bot |
| slides_cmd | bot.py | 483 | bot |
| generate_cmd | bot.py | 559 | bot |
| status_cmd | bot.py | 882 | bot |
| post_cmd | bot.py | 925 | bot |
| peekcaption_cmd | bot.py | 1112 | bot |
| showtopic_cmd | bot.py | 1131 | bot |
| editcaption_cmd | bot.py | 1158 | bot |
| regenerate_cmd | bot.py | 1267 | bot |
| confirm_cmd | bot.py | 1419 | bot |
| cancel_cmd | bot.py | 1458 | bot |
| clean_cmd | bot.py | 1464 | bot |
| myid_cmd | bot.py | 1562 | bot |
| addcategory_cmd | bot.py | 1590 | bot |
| addsubcategory_cmd | bot.py | 1602 | bot |
| addtopic_cmd | bot.py | 1616 | bot |
| edittopic_cmd | bot.py | 1630 | bot |
| deletetopic_cmd | bot.py | 1658 | bot |
| movetopic_cmd | bot.py | 1670 | bot |
| schedule_cmd | bot.py | 1684 | bot |
| delete_schedule_cmd | bot.py | 1693 | bot |
| setslot_cmd | bot.py | 1736 | bot |
| run_cmd | bot.py | 1988 | bot |
| sync_cmd | bot.py | 2020 | bot |
| topic_cmd | bot.py | 2196 | bot |
| slot_pick_callback | bot.py | 1320 | callback |
| wizard_callback | bot.py | 1769 | callback |
| fact_callback | bot.py | 1823 | callback |
| cancel_wf_callback | bot.py | 1880 | callback |


### CLI Functions (commands.py)
| Function | Line |
| --- | --- |
| cmd_media | 84 |
| cmd_post_photo | 89 |
| cmd_post_carousel | 225 |
| cmd_post_reel | 522 |
| cmd_comments | 575 |
| cmd_reply | 582 |
| cmd_insights | 590 |
| cmd_search_hashtag | 597 |
| cmd_prepare_reel | 604 |
| cmd_stage_reel | 680 |
| cmd_stage_photo | 759 |
| cmd_generate_caption | 836 |
| cmd_generate_carousel_sd | 1145 |
| cmd_compress_slides | 1357 |
| cmd_sync_slots | 1370 |
| cmd_refresh_token | 1382 |
| cmd_generate_carousel | 1386 |
| cmd_delete_post | 1679 |
| cmd_clean | 1728 |


## Git Sync Map


Every mutation command in bot.py triggers `_git_sync_after(commit_msg)`:

| Line | Commit Message |
| --- | --- |
| 1243 | auto: caption {slug} |
| 1451 | auto: {prefix} {slug} |
| 1599 | auto: add category |
| 1613 | auto: add subcategory |
| 1627 | auto: add topic |
| 1655 | auto: edit {topic_ref} |
| 1667 | auto: delete {topic_ref} |
| 1681 | auto: move {topic_ref} |
| 1733 | auto: unschedule {topic_ref} |
| 1755 | auto: slot remove {args[1]} |
| 1819 | auto: slot add {sid} |
| 1863 | auto: facts {pending['slug']} |
| 2245 | auto: rename cat {rest[0]} |
| 2253 | auto: remove cat {rest[0]} |
| 2275 | auto: rename subcat {rest[0]}.{rest[1]} |
| 2282 | auto: remove subcat {rest[0]}.{rest[1]} |


## API Registry


External API calls found across the codebase:


**dispatch** (7 calls):

- Line 602: `await _dispatch_workflow(topic, num_facts, False, update)`
- Line 604: `await _dispatch_workflow(topic, num_facts, False, update)`
- Line 1252: `async def _dispatch_workflow(topic: str, num_facts: str, force: bool, update: Update):`
- Line 1312: `await _dispatch_workflow(topic_input, "8", True, update)`
- Line 1317: `await _dispatch_workflow(topic_input, "8", force, update)`
- Line 2347: `await _dispatch_workflow(slug, count, True, update)`
- Line 2355: `await _dispatch_workflow(slug, count, False, update)`

**httpx** (2 calls):

- Line 158: `HTTPX_CLIENT = httpx.AsyncClient(timeout=300)`
- Line 894: `async with httpx.AsyncClient(timeout=15) as client:`

**requests** (7 calls):

- Line 28: `requests.post(`
- Line 1032: `r = requests.get(url, headers=headers, timeout=15)`
- Line 1054: `r = requests.get(url, headers=headers, timeout=15)`
- Line 1069: `img_resp = requests.get(img_url, timeout=20)`
- Line 1533: `resp = requests.get(img_url, timeout=20)`
- Line 1030: `url = f"https://api.pexels.com/v1/search?query={requests.utils.quote(query)}&per_page={per_page}&orientation=square"`
- Line 1051: `url = f"https://api.pexels.com/v1/search?query={requests.utils.quote(query)}&per_page=5&orientation=square"`

**subprocess** (11 calls):

- Line 85: `r = await loop.run_in_executor(None, lambda: subprocess.run(`
- Line 91: `r = await loop.run_in_executor(None, lambda: subprocess.run(`
- Line 97: `r = await loop.run_in_executor(None, lambda: subprocess.run(`
- Line 103: `r = await loop.run_in_executor(None, lambda: subprocess.run(`
- Line 109: `await loop.run_in_executor(None, lambda: subprocess.run(`
- Line 957: `subprocess.run(`
- Line 1444: `result = subprocess.run(proc_args, capture_output=True, text=True, timeout=300, cwd=str(PROJECT_ROOT))`
- Line 2000: `result = subprocess.run(`
- Line 2027: `r = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=timeout)`
- Line 2091: `subprocess.run(`
  _... and 1 more_

## File Write Operations



**bot.py** (5 writes):

- Line 279: writes to `CURRICULUM_PATH`
- Line 765: writes to `CURRICULUM_PATH`
- Line 1729: writes to `SCHEDULE_PATH`
- Line 1861: writes to `?`
- Line 2099: writes to `?`

**commands.py** (7 writes):

- Line 221: writes to `?`
- Line 469: writes to `_UPLOAD_MAP`
- Line 481: writes to `_URLS_CACHE`
- Line 1650: writes to `?`
- Line 1802: writes to `?`
- Line 1831: writes to `?`
- Line 1845: writes to `?`

## GitHub Actions Workflows


| File | Name | Triggers |
| --- | --- | --- |
| clean.yml | Clean slides | workflow_dispatch (with inputs) |
| deploy.yml | Deploy to VPS | push [main]; workflow_dispatch |
| generate.yml | Generate Carousel (SD) | workflow_dispatch (with inputs) |
| pages.yml | Deploy Bio Page | push [main] (paths: 'bio/**'; '.github/workflows/pages.yml'); workflow_dispatch |
| scheduler.yml | Scheduler — triggered by cron-job.org | workflow_dispatch |
| sync-slots.yml | Sync Slots to cron-job.org | push [main] (paths: "nixfw/slots.json"); workflow_dispatch |


## NixFW Source Files


| File | Size |
| --- | --- |
| __init__.py | 0 B |
| __main__.py | 210 B |
| bio\__init__.py | 0 B |
| bio\generator.py | 5506 B |
| bio\templates\__init__.py | 0 B |
| bot\__init__.py | 0 B |
| bot\bot.py | 101246 B |
| bot\handlers\__init__.py | 0 B |
| carousel\__init__.py | 0 B |
| carousel\composer.py | 9725 B |
| carousel\slides\__init__.py | 0 B |
| carousel\slides\cover.py | 2869 B |
| carousel\slides\cta.py | 3832 B |
| carousel\slides\fact.py | 2767 B |
| cli\__init__.py | 0 B |
| cli\commands.py | 74672 B |
| cli\dispatch.py | 139 B |
| cli\refresh_token.py | 3390 B |
| config.py | 10170 B |
| content\__init__.py | 0 B |
| content\providers\__init__.py | 0 B |
| content\providers\facts_generator.py | 6234 B |
| content\providers\image_utils.py | 1173 B |
| content\providers\inaturalist.py | 692 B |
| content\providers\wikimedia.py | 592 B |
| curriculum\__init__.py | 0 B |
| curriculum\manager.py | 30184 B |
| dashboard\__init__.py | 0 B |
| editor.py | 6987 B |
| ig_client.py | 12603 B |
| runner.py | 6124 B |
| slot_manager.py | 9146 B |


# Flow Templates


Auto-generated patterns based on handler + API + git sync cross-reference:

### Curriculum CRUD
```
📱 /topic (add|edit|delete|move) <ref>
  → telegram handler  # writes source_of_truth.json
  → asyncio.create_task(_git_sync_after())  # git add → commit → push
```

### Generate + Post
```
📱 /generate <ref>
  → Gemini API (facts generation)
  → preview → confirm callback
    → writes edu_{slug}.json
    → _dispatch_workflow()  # GH Actions generate.yml
    → _git_sync_after()
📱 /post <ref> → /post confirm [--now]
  → subprocess: python main.py post-carousel
    → IG Graph API (if --now)
    → Catbox upload / GitHub raw URL fallback
    → writes schedule.json, source_of_truth.json, bio/index.html
    → _git_sync_after()
```


---

_Generated by `nix-arch-analysis/analyzer.py` at 2026-06-22T21:43:30.530655_