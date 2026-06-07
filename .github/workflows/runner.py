"""Runner untuk GitHub Actions — jadwalin post IG dari schedule.json."""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

# Tambah root project ke path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from ig_client import InstagramClient

WIB = timezone(timedelta(hours=7))
SCHEDULE_PATH = Path("schedule.json")


def wib_now():
    return datetime.now(WIB).strftime("%Y-%m-%d %H:%M")


def load_schedule():
    if not SCHEDULE_PATH.exists():
        return []
    return json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))


def save_schedule(data):
    SCHEDULE_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    now = datetime.now(WIB)
    now_str = now.strftime("%Y-%m-%d %H:%M")
    print(f"🕐 Scheduler jalan: {now_str} WIB")

    schedule = load_schedule()
    if not schedule:
        print("📭 schedule.json kosong — ngga ada jadwal")
        return

    # Cek force_time dari workflow_dispatch
    force_time = os.environ.get("FORCE_SCHEDULE_TIME")
    if force_time:
        print(f"⚡ Force jadwal: {force_time}")
        due = [p for p in schedule if p.get("time") == force_time and not p.get("done")]
    else:
        due = [p for p in schedule if not p.get("done") and p.get("time") and p["time"] <= now_str]

    if not due:
        print(f"✅ Ngga ada postingan due di {now_str}")
        return

    client = InstagramClient()

    for post in due:
        print(f"📤 Posting: {post.get('type', '?')} — {post.get('time')}")
        try:
            ptype = post.get("type")
            caption = post.get("caption", "")
            if ptype == "photo":
                url = post["url"]
                result = client.post_photo(url, caption)
                print(f"   ✅ ID: {result.get('id')}")
            elif ptype == "reel":
                url = post["url"]
                result = client.post_reel(url, caption)
                print(f"   ✅ ID: {result.get('id')}")
            elif ptype == "carousel":
                urls = post["urls"]
                result = client.post_carousel(urls, caption)
                print(f"   ✅ ID: {result.get('id')}")
            else:
                print(f"   ⚠️  Tipe '{ptype}' ngga dikenal")
                continue

            post["done"] = True
            post["result_id"] = result.get("id", "")
            save_schedule(schedule)
            print(f"   📝 schedule.json diupdate")

        except Exception as e:
            print(f"   ❌ Gagal: {e}")


if __name__ == "__main__":
    main()
