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
    print(f"🕐 Runner jalan: {now_str} WIB")

    schedule = load_schedule()
    if not schedule:
        print("📭 schedule.json kosong — ngga ada jadwal")
        return

    force_time = os.environ.get("FORCE_SCHEDULE_TIME")
    if force_time:
        print(f"⚡ Force jadwal: {force_time}")
        target = [p for p in schedule if p.get("time") == force_time and not p.get("done")]
    else:
        target = [p for p in schedule if not p.get("done")]

    if not target:
        print("✅ Semua postingan udah selesai")
        return

    client = InstagramClient()

    for post in target:
        ptype = post.get("type", "?")
        ptime = post.get("time", "?")
        print(f"\n📤 {ptype} — {ptime}")

        # Skip kalo kontennya kosong
        if ptype == "carousel" and not post.get("urls"):
            print(f"   ⏭️  url kosong — skip")
            continue
        if ptype != "carousel" and not post.get("url"):
            print(f"   ⏭️  url kosong — skip")
            continue

        caption = post.get("caption", "")
        try:
            if post.get("time") and not force_time:
                dt = datetime.strptime(post["time"], "%Y-%m-%d %H:%M")
                dt_wib = dt.replace(tzinfo=WIB)
                if dt_wib > now:
                    print(f"   ⏳ Belum waktunya — cron nanti yg handle")
                    continue
                else:
                    print(f"   ⏰ Udah lewat → publish sekarang")

            if ptype == "photo":
                result = client.post_photo(post["url"], caption)
            elif ptype == "reel":
                result = client.post_reel(post["url"], caption)
            elif ptype == "carousel":
                result = client.post_carousel(post["urls"], caption)
            else:
                print(f"   ⚠️  Tipe '{ptype}' ngga dikenal")
                continue

            post["done"] = True
            post["result_id"] = result.get("id", "")
            save_schedule(schedule)
            print(f"   ✅ ID: {result.get('id')}")
            print(f"   📝 schedule.json diupdate")

        except Exception as e:
            print(f"   ❌ Gagal: {e}")


if __name__ == "__main__":
    main()
