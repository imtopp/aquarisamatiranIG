# NIX Architecture Analysis Skill

**Purpose:** Analyze the current state of the NIX framework after any set of changes.  
**Not a static document** — it scans the actual codebase and produces fresh results.

## How to Use

Run the analyzer from the project root:

```
python nix-arch-analysis/analyzer.py
```

Or save to a file:

```
python nix-arch-analysis/analyzer.py -o nix-arch-analysis/REPORT.md
```

The report covers:

| Section | What it shows |
|---|---|
| **Accounts** | All account dirs with config.json + status flags |
| **Command Reference** | All `_cmd` handlers in bot.py + CLI functions in commands.py |
| **Git Sync Map** | Every `_git_sync_after(commit_msg)` call site — what auto-pushes |
| **API Registry** | All external API calls (httpx, requests, subprocess, workflow dispatch) |
| **File Write Operations** | All file write calls across source files |
| **GitHub Actions Workflows** | All workflow files + their triggers |
| **NixFW Source Files** | Complete file listing with sizes |
| **Flow Templates** | Integration patterns (CRUD, generate+post, schedule) |

## When to Call This Skill

- After adding new commands
- After changing file write paths or API calls
- Before planning architecture changes
- When debugging data propagation issues

## Architecture Principles (always true)

- `source_of_truth.json` + `schedule.json` = **master data** (never delete)
- `resource/photos/` = **cache** (safe to clean)
- `bio/index.html` = **derived** (regenerable from master data)
- VPS = touchpoint; GitHub repo = source of truth
- Every mutation → `_git_sync_after()` → auto-push
- No direct IG API from bot.py — all posting via CLI subprocess
- Catbox blocked on VPS → GitHub raw URL fallback for committed slides

## Analyzer Script

`analyzer.py` in this directory. It regex-scans the codebase for patterns — it will
automatically pick up new commands, API calls, workflows, and accounts added in the
future without modification.
