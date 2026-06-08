"""Update bio/index.html status cards based on schedule.json + curriculum.md progress."""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

WIB = timezone(timedelta(hours=7))
SCHEDULE_PATH = Path("schedule.json")
BIO_PATH = Path("bio/index.html")
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
        curr = entry.get("curriculum")
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


def update_bio(schedule=None):
    if schedule is None:
        schedule = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))

    statuses = build_card_statuses(schedule)
    if not statuses:
        print("  📭 Ngga ada curriculum entry — skip update bio")
        return False

    html = BIO_PATH.read_text(encoding="utf-8")
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

        # Update href kalo ada permalink
        if permalink:
            href_pattern = r'(<a class="card-link" href=")[^"]+(".*?<div class="num">' + str(card_num) + r')'
            html, href_count = re.subn(href_pattern, r'\1' + permalink + r'\2', html, count=1, flags=re.DOTALL)
            if href_count:
                print(f"  🔗 Card #{card_num} → {permalink}")

    BIO_PATH.write_text(html, encoding="utf-8")
    print(f"  ✅ bio/index.html diupdate ({len(statuses)} card)")
    return True


if __name__ == "__main__":
    schedule = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
    update_bio(schedule)
