"""NIX Architecture Analyzer — scans codebase and generates up-to-date architecture doc.

Usage:
    python nix-arch-analysis/analyzer.py
    python nix-arch-analysis/analyzer.py --output docs/architecture.md

Scans bot.py, commands.py, workflows, and account data to produce a living doc.
"""

import re
import json
import subprocess
import textwrap
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent.parent
BOT_PY = BASE / "nixfw" / "bot" / "bot.py"
COMMANDS_PY = BASE / "nixfw" / "cli" / "commands.py"
WORKFLOWS_DIR = BASE / ".github" / "workflows"
ACCOUNTS_DIR = BASE / "accounts"
SLOTS_JSON = BASE / "nixfw" / "slots.json"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def findall(text: str, pattern: str) -> list[str]:
    return re.findall(pattern, text, re.MULTILINE)


def section(title: str, level: int = 2) -> str:
    return f"\n{'#' * level} {title}\n\n"


def table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_No data._\n"
    cols = len(headers)
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    hdr = "| " + " | ".join(headers) + " |"
    lines = [hdr, sep]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines) + "\n"


def scan_commands() -> tuple[list[dict], list[dict]]:
    """Scan command handlers from bot.py and CLI functions from commands.py."""
    bot_source = read(BOT_PY)
    cmd_source = read(COMMANDS_PY)

    # --- Bot command handlers ---
    handlers = []
    cmd_pat = re.compile(r"async def (\w+_cmd)\(update: Update, context: ContextTypes\.DEFAULT_TYPE\)")
    for m in cmd_pat.finditer(bot_source):
        name = m.group(1)
        line_no = bot_source[:m.start()].count("\n") + 1
        handlers.append({"name": name, "line": line_no, "type": "bot"})

    # --- Callback handlers ---
    callback_pat = re.compile(r"async def (\w+_callback)\(update: Update, context: ContextTypes\.DEFAULT_TYPE\)")
    for m in callback_pat.finditer(bot_source):
        name = m.group(1)
        line_no = bot_source[:m.start()].count("\n") + 1
        handlers.append({"name": name, "line": line_no, "type": "callback"})

    # --- CLI functions (public, non-underscore) ---
    cli_funcs = []
    func_pat = re.compile(r"^def (cmd_\w+)\(_?client, args\):", re.MULTILINE)
    for m in func_pat.finditer(cmd_source):
        name = m.group(1)
        line_no = cmd_source[:m.start()].count("\n") + 1
        cli_funcs.append({"name": name, "line": line_no})

    return handlers, cli_funcs


def scan_git_sync(source: str) -> list[dict]:
    """Find all _git_sync_after calls with commit messages."""
    calls = []
    pat = re.compile(r'_git_sync_after\(f?"([^"]+)"\)')
    for m in pat.finditer(source):
        msg = m.group(1)
        line_no = source[:m.start()].count("\n") + 1
        calls.append({"line": line_no, "message": msg})
    return calls


def scan_api_calls(source: str) -> list[dict]:
    """Find all httpx, requests, subprocess, and dispatch calls."""
    calls = []
    pats = [
        (r'httpx\.\w+\(', "httpx"),
        (r'requests\.\w+\(', "requests"),
        (r'subprocess\.run\(', "subprocess"),
        (r'_dispatch_workflow\(', "dispatch"),
        (r'requests\.utils\.quote\(', "requests"),
    ]
    for pat, lib in pats:
        for m in re.finditer(pat, source):
            line_no = source[:m.start()].count("\n") + 1
            line_text = source.split("\n")[line_no - 1].strip()
            calls.append({"line": line_no, "library": lib, "code": line_text[:120]})
    return calls


def scan_file_writes(source: str) -> list[dict]:
    """Find all file write operations."""
    writes = []
    pats = [
        r'write_text\(',
        r'\.dump\(',
        r'write_json\(',
        r'json\.dump\(',
    ]
    for pat in pats:
        for m in re.finditer(pat, source):
            line_no = source[:m.start()].count("\n") + 1
            writes.append({"line": line_no, "pattern": pat})
    return writes


def scan_workflows() -> list[dict]:
    """Scan .github/workflows/*.yml for trigger info."""
    wfs = []
    if not WORKFLOWS_DIR.exists():
        return wfs
    for f in sorted(WORKFLOWS_DIR.glob("*.yml")):
        content = f.read_text(encoding="utf-8")
        name_m = re.search(r"^name:\s*(.+)$", content, re.MULTILINE)
        name = name_m.group(1) if name_m else f.stem

        triggers = []
        if "push:" in content:
            branches = re.findall(r"branches:\s*\[([^\]]+)\]", content)
            paths = re.findall(r"paths:\s*\n((?:\s+-[^\n]+\n?)+)", content)
            trigger_str = f"push"
            if branches:
                trigger_str += f" [{branches[0]}]"
            if paths:
                trigger_str += f" (paths: {'; '.join(p.strip() for p in paths[0].split('-') if p.strip())})"
            triggers.append(trigger_str)
        if "workflow_dispatch:" in content:
            inputs = re.findall(r"inputs:\s*\n((?:\s+\w+:[^\n]*\n?)+)", content)
            inp_str = "workflow_dispatch"
            if inputs:
                inp_str += " (with inputs)"
            triggers.append(inp_str)

        wfs.append({"file": f.name, "name": name, "triggers": "; ".join(triggers)})
    return wfs


def scan_accounts() -> list[dict]:
    """Scan account directories for config info."""
    accs = []
    if not ACCOUNTS_DIR.exists():
        return accs
    for d in sorted(ACCOUNTS_DIR.iterdir()):
        if d.is_dir() and (d / "config.json").exists():
            cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
            accs.append({
                "name": d.name,
                "handle": cfg.get("handle", "?"),
                "niche": cfg.get("niche", "?"),
                "has_sot": (d / "source_of_truth.json").exists(),
                "has_schedule": (d / "schedule.json").exists(),
                "has_bio": (d / "bio" / "index.html").exists(),
            })
    return accs


def scan_all_file_writes(paths: list[Path]) -> dict:
    """Cross-reference file writes across all source files."""
    all_writes = {}
    for p in paths:
        if not p.exists():
            continue
        source = read(p)
        for pat in [r'\.write_text\(', r'\.dump\(', r'\.write_json\(']:
            for m in re.finditer(pat, source):
                line_no = source[:m.start()].count("\n") + 1
                # Try to extract the file path being written
                lines = source.split("\n")
                before = "\n".join(lines[max(0, line_no - 3):line_no])
                path_match = re.search(r'([A-Z_]+(?:_PATH)?)\s*\.write_text\(', before)
                file_path = path_match.group(1) if path_match else "?"
                all_writes.setdefault(p.name, []).append({
                    "line": line_no,
                    "target": file_path,
                })
    return all_writes


def generate_report_name() -> str:
    now = datetime.now()
    return f"NIX Architecture Report — generated {now.strftime('%Y-%m-%d %H:%M')}"


def generate(handlers, cli_funcs, git_calls, api_calls, file_writes, workflows, accounts, all_writes):
    lines = []
    a = lambda s="": lines.append(s) if s else lines.append("")

    a(f"# {generate_report_name()}")
    a("")
    a(f"Scanned: `nixfw/bot/bot.py`, `nixfw/cli/commands.py`, `.github/workflows/`, `accounts/`")
    a("")

    # ── 1. Accounts ──
    a(section("Accounts", 1))
    if accounts:
        a(table(["Name", "Handle", "Niche", "SOT", "Schedule", "Bio"],
                [[a["name"], a["handle"], a["niche"],
                  "✅" if a["has_sot"] else "❌",
                  "✅" if a["has_schedule"] else "❌",
                  "✅" if a["has_bio"] else "❌"] for a in accounts]))
    else:
        a("_No accounts found._\n")

    # ── 2. Command Reference ──
    a(section("Command Reference", 1))
    a(table(["Handler", "File", "Line", "Type"],
            [[h["name"], "bot.py", str(h["line"]), h["type"]] for h in handlers]))
    if cli_funcs:
        a("")
        a("### CLI Functions (commands.py)")
        a(table(["Function", "Line"],
                [[f["name"], str(f["line"])] for f in cli_funcs]))

    # ── 3. Git Sync Map ──
    a(section("Git Sync Map"))
    a("Every mutation command in bot.py triggers `_git_sync_after(commit_msg)`:\n")
    if git_calls:
        a(table(["Line", "Commit Message"],
                [[str(c["line"]), c["message"]] for c in git_calls]))
    else:
        a("_No git sync calls found._\n")

    # ── 4. API Registry ──
    a(section("API Registry"))
    a("External API calls found across the codebase:\n")
    if api_calls:
        # Group by library
        libs = {}
        for c in api_calls:
            libs.setdefault(c["library"], []).append(c)
        for lib, calls in sorted(libs.items()):
            a(f"\n**{lib}** ({len(calls)} calls):")
            a("")
            for c in calls[:10]:
                a(f"- Line {c['line']}: `{c['code']}`")
            if len(calls) > 10:
                a(f"  _... and {len(calls) - 10} more_")
    else:
        a("_No API calls found._\n")

    # ── 5. File Writes ──
    a(section("File Write Operations"))
    for file_name, writes in sorted(all_writes.items()):
        a(f"\n**{file_name}** ({len(writes)} writes):")
        a("")
        for w in writes[:10]:
            a(f"- Line {w['line']}: writes to `{w['target']}`")

    # ── 6. Workflows ──
    a(section("GitHub Actions Workflows"))
    if workflows:
        a(table(["File", "Name", "Triggers"],
                [[w["file"], w["name"], w["triggers"]] for w in workflows]))
    else:
        a("_No workflows found._\n")

    # ── 7. File Map ──
    a(section("NixFW Source Files"))
    nixfw_files = sorted((BASE / "nixfw").rglob("*.py"))
    a(table(["File", "Size"],
            [[str(f.relative_to(BASE / "nixfw")), f"{f.stat().st_size} B"]
             for f in nixfw_files]))

    # ── 8. Flow Templates (auto-generated from command patterns) ──
    a(section("Flow Templates", 1))
    a("Auto-generated patterns based on handler + API + git sync cross-reference:\n")

    # Group commands by patterns
    a("### Curriculum CRUD")
    a("```")
    a(f"📱 /topic (add|edit|delete|move) <ref>")
    a(f"  → telegram handler  # writes source_of_truth.json")
    a(f"  → asyncio.create_task(_git_sync_after())  # git add → commit → push")
    a("```")
    a("")

    a("### Generate + Post")
    a("```")
    a(f"📱 /generate <ref>")
    a(f"  → Gemini API (facts generation)")
    a(f"  → preview → confirm callback")
    a(f"    → writes edu_{{slug}}.json")
    a(f"    → _dispatch_workflow()  # GH Actions generate.yml")
    a(f"    → _git_sync_after()")
    a(f"📱 /post <ref> → /post confirm [--now]")
    a(f"  → subprocess: python main.py post-carousel")
    a(f"    → IG Graph API (if --now)")
    a(f"    → Catbox upload / GitHub raw URL fallback")
    a(f"    → writes schedule.json, source_of_truth.json, bio/index.html")
    a(f"    → _git_sync_after()")
    a("```")
    a("")

    # ── Footer ──
    a("\n---")
    a(f"\n_Generated by `nix-arch-analysis/analyzer.py` at {datetime.now().isoformat()}_")

    return "\n".join(lines)


def main():
    bot_source = read(BOT_PY)
    cmd_source = read(COMMANDS_PY)

    handlers, cli_funcs = scan_commands()
    git_calls = scan_git_sync(bot_source)
    api_calls = scan_api_calls(bot_source) + scan_api_calls(cmd_source)
    file_writes = scan_file_writes(bot_source) + scan_file_writes(cmd_source)
    workflows = scan_workflows()
    accounts = scan_accounts()
    all_writes = scan_all_file_writes([BOT_PY, COMMANDS_PY])

    doc = generate(handlers, cli_funcs, git_calls, api_calls, file_writes,
                   workflows, accounts, all_writes)

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", "-o", help="Output file path")
    args = parser.parse_args()

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(doc, encoding="utf-8")
        print(f"Written to {out}")
    else:
        print(doc)


if __name__ == "__main__":
    main()
