"""Bio page generator — renders bio/index.html from schedule data + Jinja2 template."""
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

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


def build_card_statuses(schedule):
    statuses = {}
    for entry in schedule:
        curr = entry.get("source_ref") or entry.get("curriculum")
        if not curr:
            continue
        m = re.search(r'(\d+)', curr)
        if not m:
            continue
        card_num = int(m.group(1))
        permalink = entry.get("permalink", "")
        if entry.get("done"):
            statuses[card_num] = ("tag-live", "✅ Live", permalink)
        else:
            dt = parse_time(entry.get("time"))
            if dt and dt > datetime.now(WIB):
                statuses[card_num] = ("tag-soon", f"📅 {fmt_date(dt)}", permalink)
            else:
                statuses[card_num] = ("tag-live", "✅ Live", permalink) if dt else ("tag-empty", "🔜", permalink)
    return statuses


def update_bio(schedule=None, account: str = "aquarisamatiran"):
    """Update bio page for a given account."""
    base = Path(__file__).resolve().parent.parent.parent / "accounts" / account
    sched_path = base / "schedule.json"
    bio_path = base / "bio" / "index.html"

    if schedule is None:
        if not sched_path.exists():
            print(f"  📭 schedule.json not found for {account}")
            return False
        schedule = json.loads(sched_path.read_text(encoding="utf-8"))

    statuses = build_card_statuses(schedule)
    if not statuses:
        print("  📭 Ngga ada curriculum entry — skip update bio")
        return False

    if not bio_path.exists():
        print(f"  ⚠️  bio/index.html not found for {account} — skip")
        return False

    html = bio_path.read_text(encoding="utf-8")
    for card_num, (tag_cls, tag_text, permalink) in statuses.items():
        pattern = (
            r'(<div class="card[^"]*">\s*<div class="num">'
            + str(card_num)
            + r'</div>.*?<span class="tag )\S+(">).*?(</span>)'
        )
        repl = r'\1' + tag_cls + r'\2' + tag_text + r'\3'
        new_html, count = re.subn(pattern, repl, html, count=1, flags=re.DOTALL)
        if count:
            print(f"  🃏 Card #{card_num} → {tag_text}")
        else:
            print(f"  ⚠️  Card #{card_num} ngga ketemu di HTML")
        html = new_html

        if permalink:
            num_tag = f'<div class="num">{card_num}</div>'
            num_pos = html.find(num_tag)
            if num_pos >= 0:
                a_start = html.rfind('<a class="card-link" href="', 0, num_pos)
                if a_start >= 0:
                    href_start = a_start + len('<a class="card-link" href="')
                    href_end = html.find('"', href_start)
                    old_href = html[href_start:href_end]
                    html = html[:href_start] + permalink + html[href_end:]
                    print(f"  🔗 Card #{card_num}: {old_href[:50]} → {permalink}")

    bio_path.write_text(html, encoding="utf-8")
    print(f"  ✅ bio/index.html diupdate ({len(statuses)} card)")
    return True


if __name__ == "__main__":
    schedule = json.loads(Path("schedule.json").read_text(encoding="utf-8"))
    update_bio(schedule)
