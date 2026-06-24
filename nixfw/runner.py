"""NixFW Runner — post from schedule.json.
SINGLE WRITER: outputs go to resource/.scheduler_output/{ref}.json
instead of modifying master data files directly.
VPS process_scheduler_results() reads + applies + deletes these outputs."""
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from nixfw.ig_client import InstagramClient

WIB = timezone(timedelta(hours=7))

ACCOUNT_BASE = Path(__file__).resolve().parent.parent / "accounts" / "aquarisamatiran"
CONTENT_PATH = ACCOUNT_BASE / "source_of_truth.json"
SCHED_PATH = ACCOUNT_BASE / "schedule.json"
SCHEDULER_OUTPUT_DIR = ACCOUNT_BASE / "resource" / ".scheduler_output"


def _find_topic_by_num(cc, num):
    for st in cc.get("topics", {}).values():
        if num in st:
            return st[num]
    return None


_re_ref = re.compile(r"[CS](\d+)(?:\.(\d+))?#(\d+)")


def _num_from_ref(cc, ref):
    m = _re_ref.match(ref)
    if not m:
        m2 = re.search(r"#(\d+)", ref)
        return m2.group(1) if m2 else ref.lstrip("#")
    cid, sc_part, num_str = m.group(1), m.group(2), m.group(3)
    if not sc_part:
        return num_str.zfill(2)
    st = cc.get("topics", {}).get(cid, {})
    items = [(int(k), k) for k, v in st.items() if v.get("subcategory", "1") == sc_part]
    items.sort()
    idx = int(num_str) - 1
    if 0 <= idx < len(items):
        return items[idx][1]
    return num_str.zfill(2)


def _write_output_file(source_ref: str, result_id: str, permalink: str, caption: str = "", urls: list = None):
    """Write a .scheduler_output/{safe_ref}_{uuid}.json file using the shared function."""
    from nixfw.curriculum.manager import write_output_file as _w
    _w(source_ref=source_ref, result_id=result_id, permalink=permalink,
       caption=caption, urls=urls, action="publish")


def _output_file_exists(source_ref: str) -> bool:
    """Check if an output file already exists for this ref (skip guard).
    Uses glob to match UUID-pattern filenames."""
    safe_name = source_ref.replace("#", "_").replace(".", "_")
    if not SCHEDULER_OUTPUT_DIR.is_dir():
        return False
    return len(list(SCHEDULER_OUTPUT_DIR.glob(f"{safe_name}_*.json"))) > 0


def run(account: str = "aquarisamatiran"):
    base = Path(__file__).resolve().parent.parent / "accounts" / account
    content_path = base / "source_of_truth.json"
    sched_path = base / "schedule.json"
    output_dir = base / "resource" / ".scheduler_output"
    global SCHEDULER_OUTPUT_DIR
    SCHEDULER_OUTPUT_DIR = output_dir

    def load_schedule():
        if not sched_path.exists():
            return []
        return json.loads(sched_path.read_text(encoding="utf-8"))

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

    # Backfill permalink for posts that have result_id but no permalink
    for post in schedule:
        if post.get("result_id") and not post.get("permalink"):
            ref = post.get("source_ref") or post.get("curriculum", "")
            if ref and _output_file_exists(ref):
                continue
            print(f"   🔄 Backfill permalink buat {post.get('result_id')}...")
            try:
                info = client.get_media_by_id(post["result_id"])
                permalink = info.get("permalink", "")
                if permalink:
                    post["permalink"] = permalink
                    # Write output file for VPS to pick up
                    _write_output_file(
                        source_ref=ref,
                        result_id=post["result_id"],
                        permalink=permalink,
                        caption=post.get("caption", ""),
                        urls=post.get("urls"),
                    )
            except Exception as e:
                print(f"      ⚠️  Gagal: {e}")

    if not target:
        print("✅ Semua postingan udah selesai")
        return

    for post in target:
        ptype = post.get("type", "?")
        ptime = post.get("time", "?")
        ref = post.get("source_ref") or post.get("curriculum", "")
        print(f"\n📤 {ptype} — {ptime}")

        if ptype == "carousel" and not post.get("urls"):
            print(f"   ⏭️  url kosong — skip"); continue
        if ptype != "carousel" and not post.get("url"):
            print(f"   ⏭️  url kosong — skip"); continue

        # Guard: skip if output file already exists (partial run completed post)
        if ref and _output_file_exists(ref):
            print(f"   ⏭️  output file udah ada — skip (VPS akan process)")
            continue

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

            result_id = result.get("id", "")
            permalink = ""
            try:
                media_info = client.get_media_by_id(result_id)
                permalink = media_info.get("permalink", "")
            except Exception:
                pass

            # Write .scheduler_output/{ref}.json instead of modifying master data
            _write_output_file(
                source_ref=ref,
                result_id=result_id,
                permalink=permalink,
                caption=caption,
                urls=post.get("urls"),
            )
            print(f"   ✅ ID: {result_id}")
            if permalink:
                print(f"   🔗 {permalink}")

        except Exception as e:
            print(f"   ❌ Gagal: {e}")


if __name__ == "__main__":
    run()
