"""Bio page generator — renders bio/index.html from source_of_truth + schedule + Jinja2 template."""
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from jinja2 import Environment, FileSystemLoader

from nixfw.account import AccountContext, get_account



WIB = timezone(timedelta(hours=7))
MONTHS_ID = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mei", 6: "Jun",
             7: "Jul", 8: "Agu", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Des"}


def parse_time(time_str):
    try:
        return datetime.strptime(time_str, "%Y-%m-%d %H:%M").replace(tzinfo=WIB)
    except (ValueError, TypeError):
        return None


def fmt_date(dt):
    return f"{dt.day} {MONTHS_ID[dt.month]} {dt.strftime('%H:%M')}"


def _ref_to_card_key(source_ref, truth):
    """Resolve source_ref (C1.2#01 or C1#07) to integer dict_key for status lookup."""
    if truth:
        from nixfw.curriculum.manager import resolve_ref
        resolved = resolve_ref(source_ref, truth)
        if resolved:
            return int(resolved[1])  # (cid, num_key) → int(num_key)
    m = re.search(r'#(\d+)', source_ref)
    if m:
        return int(m.group(1))
    return None


def build_card_statuses(schedule, truth=None):
    statuses = {}
    for entry in schedule:
        source_ref = entry.get("source_ref") or entry.get("curriculum")
        if not source_ref:
            continue
        card_key = _ref_to_card_key(source_ref, truth)
        if card_key is None:
            continue
        permalink = entry.get("permalink", "")
        if entry.get("done"):
            statuses[card_key] = {"tag_class": "tag-live", "tag_text": "✅ Live", "permalink": permalink}
        else:
            dt = parse_time(entry.get("time"))
            if dt and dt > datetime.now(WIB):
                statuses[card_key] = {"tag_class": "tag-soon", "tag_text": f"📅 {fmt_date(dt)}", "permalink": permalink}
            else:
                if dt:
                    statuses[card_key] = {"tag_class": "tag-live", "tag_text": "✅ Live", "permalink": permalink}
                else:
                    statuses[card_key] = {"tag_class": "tag-empty", "tag_text": "🔜", "permalink": permalink}
    return statuses


def _merge_permalinks(statuses, topics):
    """Fallback: if a topic has permalink in source_of_truth but not in schedule, merge it."""
    for cat_topics in topics.values():
        for num_str, topic in cat_topics.items():
            num = int(num_str)
            topic_pl = topic.get("permalink", "")
            if topic_pl and num in statuses and not statuses[num].get("permalink"):
                statuses[num]["permalink"] = topic_pl


def update_bio(schedule=None, account: str | AccountContext | None = None):
    """Update bio page for a given account using Jinja2 template."""
    ctx = account if isinstance(account, AccountContext) else get_account(account)
    truth_path = ctx.source_of_truth
    sched_path = ctx.schedule_json
    config_path = ctx.base / "config.json"
    bio_path = ctx.bio_html

    if not truth_path.exists():
        print(f"  📭 source_of_truth.json not found for {ctx.name}")
        return False

    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    categories = truth.get("categories", {})
    topics = truth.get("topics", {})

    if not categories or not topics:
        print(f"  📭 No categories or topics in source_of_truth for {ctx.name}")
        return False

    if schedule is None:
        if not sched_path.exists():
            print(f"  📭 schedule.json not found for {ctx.name} — all topics shown as planned")
            schedule = []
        else:
            schedule = json.loads(sched_path.read_text(encoding="utf-8"))

    statuses = build_card_statuses(schedule, truth)
    _merge_permalinks(statuses, topics)

    from nixfw.curriculum.manager import _subcat_seq_map
    seq_map = _subcat_seq_map(truth)

    config = {}
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))

    palette = config.get("palette", {
        "bg_dark": "#0A1628",
        "bg_card": "#1A2A4A",
        "text_main": "#F0F4FF",
        "text_sub": "#A0B4D0",
        "accent": "#4FC3F7",
        "accent2": "#00E5FF",
        "tag_bg": "#2A3A5A",
    })

    handle = config.get("ig_handle", f"@{ctx.name}")
    handle_clean = handle.lstrip("@")

    template_dir = Path(__file__).resolve().parent / "templates"
    env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
    tmpl = env.get_template("bio.html.j2")

    html = tmpl.render(
        title=f"{handle_clean.title()} — Belajar Aquarium Dari Nol",
        account_name=handle_clean.title(),
        account_handle=handle,
        handle=handle_clean,
        emoji="🐟",
        tagline=config.get("bio_tagline", "Belajar aquarium dari nol, bareng-bareng! 🌱"),
        palette=palette,
        categories=categories,
        topics=topics,
        statuses=statuses,
        seq_map=seq_map,
        cta_text="Jalanin kurikulum ini bareng aku di Instagram! 🐟",
        footer_text=f"dibuat dengan 🐟 oleh {handle_clean.title()} — 2026",
    )

    bio_path.parent.mkdir(parents=True, exist_ok=True)
    bio_path.write_text(html, encoding="utf-8")
    print(f"  ✅ bio/index.html regenerated ({len(statuses)} card statuses mapped)")
    return True


if __name__ == "__main__":
    import sys
    account_arg = sys.argv[1] if len(sys.argv) > 1 else None
    update_bio(account=account_arg)