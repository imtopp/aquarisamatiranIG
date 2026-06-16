# NixFW — Multi-niche Instagram Automation

Flexible CLI + Telegram bot + GitHub Actions scheduler for managing multi-account Instagram content pipelines.

## Quick Start

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py
```

## Structure

- **`nixfw/`** — framework package (all logic)
- **`accounts/`** — per-account data (config, content, schedule, resources)
- **`main.py`** — thin CLI entry point

## Documentation

- `PRD.md` — product requirements & architecture
- `AGENTS.md` — detailed workflow docs
- `docs/` — usage guides

## Entry Points

| Command | Description |
|---------|-------------|
| `python main.py curriculum` | Manage curriculum & topics |
| `python -m nixfw` | Same, from framework package |
| `python -m nixfw.bot.bot` | Start Telegram bot |
