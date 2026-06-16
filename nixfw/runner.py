"""NixFW Runner — post from schedule.json."""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nixfw.ig_client import InstagramClient
from nixfw.bio.generator import update_bio

WIB = timezone(timedelta(hours=7))

# Module-level paths (overridable for testing)
CONTENT_PATH = Path(__file__).resolve().parent.parent / "accounts" / "aquarisamatiran" / "source_of_truth.json"
SCHED_PATH = Path(__file__).resolve().parent.parent / "accounts" / "aquarisamatiran" / "schedule.json"


def _find_topic_by_num(cc, num):
    for st in cc.get("topics", {}).values():
        if num in st:
            return st[num]
    return None


def _update_curriculum_after_post(post, content_path=None):
    if content_path is None:
        content_path = CONTENT_PATH
    curriculum = post.get("source_ref") or post.get("curriculum", "")
    if not curriculum or not content_path.exists():
        return
    try:
        cc = json.loads(content_path.read_text(encoding="utf-8"))
        m = re.search(r"#(\d+)", curriculum)
        num = m.group(1) if m else curriculum.lstrip("#")
        topic = _find_topic_by_num(cc, num)
        if topic:
            topic["status"] = "live"
            if post.get("result_id"):
                topic["result_id"] = post["result_id"]
            if post.get("permalink"):
                topic["permalink"] = post["permalink"]
            content_path.write_text(json.dumps(cc, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"   📝 source_of_truth.json diupdate untuk #{num}")
    except Exception:
        pass


def run(account: str = "aquarisamatiran"):
    base = Path(__file__).resolve().parent.parent / "accounts" / account
    content_path = base / "source_of_truth.json"
    sched_path = base / "schedule.json"

    def load_schedule():
        if not sched_path.exists():
            return []
        return json.loads(sched_path.read_text(encoding="utf-8"))

    def save_schedule(data):
        sched_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    now = datetime.now(WIB)
    now_str = now.strftime("%Y-%m-%d %H:%M")
    print(f"🕐 Runner jalan [{account}]: {now_str} WIB")

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

    client = InstagramClient()

    for post in schedule:
        if post.get("result_id") and not post.get("permalink"):
            print(f"   🔄 Backfill permalink buat {post.get('result_id')}...")
            try:
                info = client.get_media_by_id(post["result_id"])
                post["permalink"] = info.get("permalink", "")
                if post["permalink"]:
                    print(f"      ✅ {post['permalink']}")
            except Exception as e:
                print(f"      ⚠️  Gagal: {e}")
    save_schedule(schedule)

    if not target:
        print("✅ Semua postingan udah selesai")
        update_bio(account=account)
        return

    for post in target:
        ptype = post.get("type", "?")
        ptime = post.get("time", "?")
        print(f"\n📤 {ptype} — {ptime}")

        if ptype == "carousel" and not post.get("urls"):
            print(f"   ⏭️  url kosong — skip"); continue
        if ptype != "carousel" and not post.get("url"):
            print(f"   ⏭️  url kosong — skip"); continue

        caption = post.get("caption", "")
        try:
            if post.get("time") and not force_time:
                dt = datetime.strptime(post["time"], "%Y-%m-%d %H:%M")
                dt_wib = dt.replace(tzinfo=WIB)
                if dt_wib > now:
                    print(f"   ⏳ Belum waktunya — cron nanti yg handle"); continue

            if ptype == "photo":
                result = client.post_photo(post["url"], caption)
            elif ptype == "reel":
                result = client.post_reel(post["url"], caption)
            elif ptype == "carousel":
                result = client.post_carousel(post["urls"], caption)
            else:
                print(f"   ⚠️  Tipe '{ptype}' ngga dikenal"); continue

            post["done"] = True
            post["result_id"] = result.get("id", "")
            try:
                media_info = client.get_media_by_id(post["result_id"])
                post["permalink"] = media_info.get("permalink", "")
            except Exception:
                post["permalink"] = ""
            save_schedule(schedule)
            print(f"   ✅ ID: {result.get('id')}")
            if post.get("permalink"):
                print(f"   🔗 {post['permalink']}")
            print(f"   📝 schedule.json diupdate")
            _update_curriculum_after_post(post, content_path=content_path)
            update_bio(account=account)

        except Exception as e:
            print(f"   ❌ Gagal: {e}")

    update_bio(account=account)


if __name__ == "__main__":
    run()
