# -*- coding: utf-8 -*-
"""Curriculum manager — single source of truth untuk struktur kurikulum multi-category, multi-subcategory, multi-topic.

Topics are nested per-category in source_of_truth.json v5+:
  topics: { "1": { "01": {...}, "02": {...} }, "2": { "01": {...} } }

Usage:
    python main.py curriculum add category --title "..." --subtitle "..."
    python main.py curriculum add subcategory --category 1 --number 5 --label "..."
    python main.py curriculum add topic --category 1 --subcategory 1 --title "..." [--slug ...] [--keywords ...]
    python main.py curriculum edit category --category 1 --title "..."
    python main.py curriculum edit subcategory --category 1 --subcategory 2 --label "..."
    python main.py curriculum edit topic --category 1 --num 04 --title "..." [--status live|scheduled|planned]
    python main.py curriculum delete topic --category 1 --num 04
    python main.py curriculum list [--category 1]
    python main.py curriculum sync
"""

import json
import re
import sys
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

from nixfw import config
from nixfw.account import AccountContext, get_account
from nixfw.bio.generator import update_bio

WIB = timezone(timedelta(hours=7))


def _resolve_account(account=None):
    if isinstance(account, AccountContext):
        return account
    return get_account(account)


# ──── helpers ────


def load(account=None):
    ctx = _resolve_account(account)
    data = json.loads(ctx.source_of_truth.read_text(encoding="utf-8"))
    _migrate_v4_to_v5(data, account=ctx)
    changed = _backfill_uuids(data)
    if changed:
        save(data, account=ctx)
    return data


def _migrate_v4_to_v5(data, account=None):
    """Auto-migrate v4 (seasons/level_labels/level) → v5 (categories/subcategories/subcategory)."""
    if data.get("version", 5) >= 5:
        return
    seasons = data.pop("seasons", {})
    categories = {}
    for sid, s in seasons.items():
        level_labels = s.pop("level_labels", {})
        subcats = {}
        for lv, label in level_labels.items():
            subcats[lv] = {"title": label}
        categories[sid] = {
            "title": s.get("title", f"Category {sid}"),
            "subtitle": s.get("subtitle", ""),
            "subcategories": subcats,
        }
    # Convert topic level (int) → subcategory (string)
    for cid, st in data.get("topics", {}).items():
        for num, topic in st.items():
            lv = topic.pop("level", None)
            if lv is not None:
                topic["subcategory"] = str(lv)
    data["categories"] = categories
    data["version"] = 5
    save(data, account=account)


def _safe_print(msg):
    """Print with ASCII-safe encoding fallback for cp1252 environments."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def save(data, account=None):
    ctx = _resolve_account(account)
    ctx.source_of_truth.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _safe_print(f"  [OK] source_of_truth.json saved (v{data.get('version', '?')})")


def _get_category_topics(data, category):
    """Return the topics dict for a given category (creates if missing)."""
    data.setdefault("topics", {})
    data["topics"].setdefault(str(category), {})
    return data["topics"][str(category)]


def _next_topic_num(data, category):
    """Next available topic number within a category."""
    st = _get_category_topics(data, category)
    existing = [int(k) for k in st]
    return f"{max(existing) + 1:02d}" if existing else "01"


def _subcat_seq_map(data):
    """Build {(cid, sc): {num_key: seq}} — sequence number per subcategory."""
    mapping = {}
    for cid in sorted(data.get("topics", {}), key=int):
        st = data["topics"][cid]
        sc_groups = {}
        for num_key in st:
            sc = st[num_key].get("subcategory", "1")
            sc_groups.setdefault(sc, []).append(int(num_key))
        for sc, nums in sc_groups.items():
            nums.sort()
            for seq, num in enumerate(nums, 1):
                mapping.setdefault((cid, sc), {})[str(num).zfill(2)] = seq
    return mapping


def _format_src_ref(cid, sc, seq):
    """Format source_ref as C{cid}.{sc}#{seq:02d}."""
    return f"C{cid}.{sc}#{seq:02d}"


def format_ref(data, cid, num_key):
    """Public helper: format a topic reference using its subcategory and sequence.
    For adhoc topics, cid=\"adhoc\", num_key=slug."""
    if cid == "adhoc":
        return f"adhoc:{num_key}"
    sc = data.get("topics", {}).get(cid, {}).get(num_key, {}).get("subcategory", "1")
    seq_map = _subcat_seq_map(data)
    seq = seq_map.get((cid, sc), {}).get(num_key.zfill(2))
    if seq is None:
        return f"C{cid}#{num_key}"
    return _format_src_ref(cid, sc, seq)


def build_ref_map(data):
    """Build {src_ref: (cid, num_key)} mapping for input resolution (both old & new format)."""
    mapping = {}
    for cid in sorted(data.get("topics", {}), key=int):
        st = data["topics"][cid]
        for num_key in st:
            sc = st[num_key].get("subcategory", "1")
            old_ref = f"C{cid}#{num_key}"
            mapping[old_ref] = (cid, num_key)
            seq_map = _subcat_seq_map(data)
            seq = seq_map.get((cid, sc), {}).get(num_key.zfill(2))
            if seq is not None:
                new_ref = _format_src_ref(cid, sc, seq)
                mapping[new_ref] = (cid, num_key)
    return mapping


def resolve_ref(ref: str, data) -> tuple | None:
    """Resolve a user-provided ref to (category, num_key) or (\"adhoc\", slug) or None.
    Handles: C1#01, C1.1#01, #01, adhoc:{slug}, raw slug."""
    # Adhoc format: "adhoc:{slug}"
    m = re.match(r'adhoc:(.+)', ref)
    if m:
        slug = m.group(1)
        for t in data.get("adhoc_topics", []):
            if t.get("slug") == slug:
                return ("adhoc", slug)
        return None

    # Curriculum mapping
    mapping = build_ref_map(data)
    normalized = ref.replace("S", "C")  # S1#01 → C1#01
    if normalized in mapping:
        return mapping[normalized]

    # Try partial match: #01 only
    m = re.search(r"#(\d+)", ref)
    if m:
        num = m.group(1).zfill(2)
        for (cid, nk) in mapping.values():
            if nk == num:
                return (cid, nk)
    return None


def _backfill_uuids(data) -> bool:
    """Backfill UUIDs for topics that lack one. Returns True if any were added."""
    import uuid
    changed = False
    for cid in sorted(data.get("topics", {}), key=int):
        for k in sorted(data["topics"][cid], key=int):
            v = data["topics"][cid][k]
            if "id" not in v or not v["id"]:
                v["id"] = str(uuid.uuid4())
                changed = True
    return changed


def _all_topics(data):
    """Yield (category_id, topic_num_str, topic_dict) across all categories."""
    _backfill_uuids(data)
    for cid in sorted(data.get("topics", {}), key=int):
        for k in sorted(data["topics"][cid], key=int):
            yield str(cid), k, data["topics"][cid][k]


def _subcategory_topics(data, cid, sc):
    """Yield (topic_num_str, topic_dict) for a specific category+subcategory."""
    st = data.get("topics", {}).get(str(cid), {})
    for k in sorted(st, key=int):
        v = st[k]
        if v.get("subcategory") == str(sc):
            yield k, v


# ──── category crud ────


def cmd_add_category(args):
    data = load()
    title = _get_arg(args, "--title")
    subtitle = _get_arg(args, "--subtitle", "")
    if not title:
        print("❌ --title wajib diisi")
        return

    categories = data.setdefault("categories", {})
    existing_ids = [int(k) for k in categories]
    new_id = str(max(existing_ids) + 1) if existing_ids else "1"

    categories[new_id] = {
        "title": title,
        "subtitle": subtitle,
        "subcategories": {"1": {"title": "New Subcategory 1"}},
    }
    save(data)
    print(f"  ✅ Category {new_id}: {title} added")


def cmd_edit_category(args):
    data = load()
    cat_id = _get_arg(args, "--category")
    if not cat_id or cat_id not in data.get("categories", {}):
        print(f"❌ --category {cat_id} tidak ditemukan")
        return
    category = data["categories"][cat_id]
    title = _get_arg(args, "--title")
    subtitle = _get_arg(args, "--subtitle")
    if title:
        category["title"] = title
    if subtitle is not None:
        category["subtitle"] = subtitle
    save(data)
    print(f"  ✅ Category {cat_id} updated")


def cmd_delete_category(args):
    data = load()
    cat_id = _get_arg(args, "--category")
    if not cat_id or cat_id not in data.get("categories", {}):
        print(f"❌ --category {cat_id} tidak ditemukan")
        return

    st = data.get("topics", {}).pop(str(cat_id), {})
    del data["categories"][cat_id]
    save(data)
    print(f"  ✅ Category {cat_id} deleted ({len(st)} topics removed)")


# ──── subcategory crud ────


def cmd_add_subcategory(args):
    data = load()
    cat_id = _get_arg(args, "--category", "1")
    if cat_id not in data.get("categories", {}):
        print(f"❌ Category {cat_id} tidak ditemukan")
        return
    sc_num = _get_arg(args, "--number")
    label = _get_arg(args, "--label", "")

    if not sc_num:
        existing = data["categories"][cat_id].get("subcategories", {})
        max_sc = max(int(k) for k in existing) if existing else 0
        sc_num = str(max_sc + 1)

    data["categories"][cat_id].setdefault("subcategories", {})
    data["categories"][cat_id]["subcategories"][str(int(sc_num))] = {
        "title": label or f"Subcategory {int(sc_num)}"
    }
    save(data)
    print(f"  ✅ Subcategory {sc_num} added to Category {cat_id}")


def cmd_edit_subcategory(args):
    data = load()
    cat_id = _get_arg(args, "--category", "1")
    sc_num = _get_arg(args, "--subcategory")
    label = _get_arg(args, "--label")

    if not sc_num or cat_id not in data.get("categories", {}):
        print("❌ --subcategory dan --category valid wajib diisi")
        return
    subcats = data["categories"][cat_id].get("subcategories", {})
    if sc_num not in subcats:
        print(f"❌ Subcategory {sc_num} tidak ditemukan di Category {cat_id}")
        return
    if label:
        subcats[sc_num]["title"] = label
        save(data)
        print(f"  ✅ Subcategory {sc_num} in Category {cat_id} updated")


# ──── topic crud ────


def cmd_add_topic(args):
    data = load()
    cat_id = _get_arg(args, "--category")
    if not cat_id:
        print("❌ --category wajib diisi")
        return
    sc = _get_arg(args, "--subcategory", "1")
    title = _get_arg(args, "--title")
    if not title:
        print("❌ --title wajib diisi")
        return

    new_key = _next_topic_num(data, cat_id)
    slug = _get_arg(args, "--slug") or title.lower().replace(" ", "-").replace(":", "").replace("?", "")[:30]
    keywords_raw = _get_arg(args, "--keywords", "")
    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
    import uuid
    topic = {
        "id": str(uuid.uuid4()),
        "slug": slug,
        "title": title,
        "subcategory": str(sc),
        "status": "planned",
        "keywords": keywords,
    }
    display = _get_arg(args, "--display")
    if display:
        topic["display_name"] = display
    subtitle = _get_arg(args, "--subtitle")
    if subtitle:
        topic["subtitle"] = subtitle

    _get_category_topics(data, cat_id)[new_key] = topic
    save(data)
    ref = format_ref(data, cat_id, new_key)
    print(f"  ✅ {ref}: {title} added")


def cmd_edit_topic(args):
    data = load()
    cat_id = _get_arg(args, "--category")
    num = _get_arg(args, "--num")
    if not cat_id or not num:
        print("❌ --category dan --num wajib diisi")
        return
    st = _get_category_topics(data, cat_id)
    if num not in st:
        ref = format_ref(data, cat_id, num)
        print(f"❌ {ref} tidak ditemukan")
        return

    topic = st[num]
    for field in ("title", "slug", "status", "display_name", "subtitle"):
        val = _get_arg(args, f"--{field}")
        if val is not None:
            topic[field] = val
    st_val = _get_arg(args, "--scheduled-time") or _get_arg(args, "--scheduled_time")
    if st_val is not None:
        topic["scheduled_time"] = st_val
    sc_raw = _get_arg(args, "--subcategory")
    if sc_raw:
        topic["subcategory"] = str(sc_raw)
    keywords_raw = _get_arg(args, "--keywords")
    if keywords_raw is not None:
        topic["keywords"] = [k.strip() for k in keywords_raw.split(",") if k.strip()]

    save(data)
    ref = format_ref(data, cat_id, num)
    print(f"  ✅ {ref} updated")


def cmd_delete_topic(args):
    data = load()
    cat_id = _get_arg(args, "--category")
    num = _get_arg(args, "--num")
    if not cat_id or not num:
        print("❌ --category dan --num wajib diisi")
        return
    st = _get_category_topics(data, cat_id)
    if num not in st:
        ref = format_ref(data, cat_id, num)
        print(f"❌ {ref} tidak ditemukan")
        return

    del st[num]
    save(data)
    ref = format_ref(data, cat_id, num)
    print(f"  ✅ {ref} deleted")


def cmd_list(args):
    data = load()
    cat_filter = _get_arg(args, "--category")

    categories = data.get("categories", {})

    for cid in sorted(categories, key=int):
        if cat_filter and cid != cat_filter:
            continue
        c = categories[cid]
        subcats = c.get("subcategories", {})
        st = data.get("topics", {}).get(str(cid), {})
        print(f"\n{'='*50}")
        print(f"  Category {cid}: {c['title']}")
        print(f"  {c.get('subtitle','')}")
        print(f"{'='*50}")

        for sc in sorted(subcats, key=int):
            label = subcats[sc]["title"]
            print(f"\n  ──── Subcategory {sc}: {label} ────")
            sc_topics = [(k, st[k]) for k in sorted(st, key=int) if st[k].get("subcategory") == str(sc)]
            if not sc_topics:
                print("    (empty)")
            for k, v in sc_topics:
                status_icon = {"live": "✅", "scheduled": "📅", "planned": "⬜"}.get(v.get("status", ""), "⬜")
                ref = format_ref(data, str(cid), k)
                print(f"    {status_icon} {ref:14s} {v['title']:30s} [{v.get('status','planned')}]")

    # ── Adhoc section ──
    adhoc = data.get("adhoc_topics", [])
    if adhoc:
        print(f"\n{'='*50}")
        print("  📌 Adhoc Topics")
        print(f"{'='*50}")
        icons = {"live": "✅", "scheduled": "📅", "planned": "⬜", "generated": "🟡", "failed": "❌"}
        for t in adhoc:
            icon = icons.get(t.get("status", ""), "⬜")
            slug = t.get("slug", "?")
            title = t.get("title", slug)
            ref = format_ref(data, "adhoc", slug)
            print(f"    {icon} {ref:14s} {title:30s} [{t.get('status','planned')}]")


# ──── sync ────


def cmd_sync(args):
    ctx = get_account()
    data = load(account=ctx)
    _sync_curriculum_md(data, account=ctx)
    _sync_schedule_json(data, account=ctx)
    update_bio(account=ctx.name)
    print("\n  ✅ All files synced!")


def _sync_curriculum_md(data, account=None):
    ctx = _resolve_account(account)
    categories = data.get("categories", {})

    lines = ["# 📚 Kurikulum Aquarisamatiran\n"]
    lines.append("Belajar aquarium dari nol sampai advanced — step by step, pake bahasa awam.\n")
    lines.append("---\n")

    for cid in sorted(categories, key=int):
        c = categories[cid]
        st = data.get("topics", {}).get(str(cid), {})
        lines.append(f"\n## 🌱 Category {cid}: {c['title']}\n")
        if c.get("subtitle"):
            lines.append(f"> {c['subtitle']}\n")

        subcats = c.get("subcategories", {})
        for sc in sorted(subcats, key=int):
            label = subcats[sc]["title"].split("—")[0].strip() if "—" in subcats[sc]["title"] else subcats[sc]["title"]
            lines.append(f"\n### Subcategory {sc}: {label}\n")
            lines.append("| # | Topik | Status |\n")
            lines.append("|---|-------|--------|\n")

            seq_map = _subcat_seq_map(data)
            for k in sorted(st, key=int):
                v = st[k]
                if v.get("subcategory") != str(sc):
                    continue
                title = v.get("title", "?")
                status = v.get("status", "planned")
                icon = {"live": "✅", "scheduled": "📅", "planned": "⬜"}.get(status, "⬜")
                tgl = v.get("scheduled_time", "")
                tgl_str = f" ({tgl})" if tgl else ""
                seq = seq_map.get((str(cid), str(sc)), {}).get(k)
                num = f"{seq:02d}" if seq else k
                lines.append(f"| {num} | {title}{tgl_str} | {icon} |\n")

    ctx.curriculum_md.write_text("".join(lines), encoding="utf-8")
    print("  ✅ curriculum.md regenerated")


def _sync_schedule_json(data, account=None):
    """Ensure schedule.json matches source_of_truth.json — handles renumbering, time updates, cross-category."""
    ctx = _resolve_account(account)
    if not ctx.schedule_json.exists():
        print("  ⚠️  schedule.json not found — skip")
        return

    schedule = json.loads(ctx.schedule_json.read_text(encoding="utf-8"))

    # Build identity maps from existing schedule entries
    uuid_map = {}
    result_id_map = {}
    permalink_map = {}
    for i, entry in enumerate(schedule):
        tu = entry.get("topic_uuid", "")
        if tu:
            uuid_map[tu] = i
        rid = entry.get("result_id", "")
        if rid:
            result_id_map[rid] = i
        pl = entry.get("permalink", "")
        if pl and pl.strip():
            permalink_map[pl.strip().rstrip("/")] = i

    seq_map = _subcat_seq_map(data)

    # ── Adhoc topics ──
    adhoc_map = {}  # slug → entry index
    for i, e in enumerate(schedule):
        if e.get("source_ref", "").startswith("adhoc:"):
            adhoc_map[e["source_ref"]] = i
    for t in data.get("adhoc_topics", []):
        slug = t.get("slug", "")
        if not slug:
            continue
        ref = f"adhoc:{slug}"
        if ref in adhoc_map:
            idx = adhoc_map[ref]
            schedule[idx].setdefault("topic_uuid", slug)
            if t.get("status") == "live":
                schedule[idx]["done"] = True
            elif t.get("status") == "scheduled" and not schedule[idx].get("result_id"):
                schedule[idx]["done"] = False
            if t.get("permalink"):
                schedule[idx]["permalink"] = t["permalink"]
            if t.get("result_id"):
                schedule[idx]["result_id"] = t["result_id"]
            if t.get("scheduled_time"):
                schedule[idx]["time"] = t["scheduled_time"]
        elif t.get("status") in ("live", "scheduled"):
            entry = {
                "source_ref": ref,
                "time": t.get("scheduled_time", ""),
                "type": "carousel",
                "done": t.get("status") == "live",
                "topic_uuid": slug,
            }
            if t.get("permalink"):
                entry["permalink"] = t["permalink"]
            if t.get("result_id"):
                entry["result_id"] = t["result_id"]
            if t.get("caption"):
                entry["caption"] = t["caption"]
            schedule.append(entry)
            print(f"  📋 schedule.json: added adhoc:{slug}")

    # Iterate all topics across all categories
    for cid, num, v in _all_topics(data):
        sc = v.get("subcategory", "1")
        seq = seq_map.get((cid, sc), {}).get(num)
        if seq is None:
            continue
        target_label = _format_src_ref(cid, sc, seq)
        tuuid = v.get("id", "")
        rid = v.get("result_id", "")
        pl = v.get("permalink", "").strip().rstrip("/")

        idx = None
        if tuuid and tuuid in uuid_map:
            idx = uuid_map[tuuid]
        elif rid and rid in result_id_map:
            idx = result_id_map[rid]
        elif pl and pl in permalink_map:
            idx = permalink_map[pl]

        entry = None
        old_label = None
        if idx is not None:
            entry = schedule[idx]
            old_label = entry.get("source_ref") or entry.get("curriculum", "")
        else:
            existing = [e for e in schedule if re.search(r"#(\d+)", e.get("source_ref") or e.get("curriculum", "")) and re.search(r"#(\d+)", e.get("source_ref") or e.get("curriculum", "")).group(1) == num]
            if existing:
                entry = existing[0]
                old_label = entry.get("source_ref") or entry.get("curriculum", "")

        if entry is not None:
            entry["source_ref"] = target_label
            entry["category"] = int(cid)
            entry["topic_uuid"] = tuuid
            if v.get("scheduled_time"):
                entry["time"] = v["scheduled_time"]
            elif v.get("status") == "live" and not entry.get("time"):
                entry["time"] = v.get("posted_at", "")
            if v.get("status") == "live":
                entry["done"] = True
            elif v.get("status") == "scheduled":
                if not entry.get("result_id"):
                    entry["done"] = False
            if v.get("permalink"):
                entry["permalink"] = v["permalink"]
            if v.get("result_id"):
                entry["result_id"] = v["result_id"]
            if old_label and old_label != target_label:
                print(f"  🔄 schedule.json: {old_label} → {target_label}")
        elif v.get("status") in ("live", "scheduled"):
            entry = {
                "source_ref": target_label,
                "category": int(cid),
                "time": v.get("scheduled_time", "") or v.get("posted_at", ""),
                "type": "carousel",
                "done": v.get("status") == "live",
                "topic_uuid": tuuid,
            }
            if v.get("permalink"):
                entry["permalink"] = v["permalink"]
            if v.get("result_id"):
                entry["result_id"] = v["result_id"]
            slides = v.get("slides", [])
            if slides:
                entry["urls"] = []
            entry["caption"] = v.get("caption", "")
            schedule.append(entry)
            print(f"  📋 schedule.json: added {target_label}")

    # Build set of valid UUIDs + curriculum+category combos + adhoc slugs
    valid_uuids = set()
    valid_keys = set()
    valid_adhoc = set()
    for cid, num, v in _all_topics(data):
        valid_uuids.add(v.get("id", ""))
        sc = v.get("subcategory", "1")
        seq = seq_map.get((cid, sc), {}).get(num)
        valid_keys.add((num, int(cid)))  # dict key (for legacy format matching)
        if seq is not None:
            valid_keys.add((f"{seq:02d}", int(cid)))  # seq (for new format matching)
    for t in data.get("adhoc_topics", []):
        s = t.get("slug", "")
        if s:
            valid_adhoc.add(s)

    def keep(entry):
        tu = entry.get("topic_uuid", "")
        if tu and tu in valid_uuids:
            return True
        c = entry.get("source_ref") or entry.get("curriculum", "")
        s = entry.get("category") or entry.get("season")
        if not c:
            return True
        # Check adhoc entries
        if c.startswith("adhoc:"):
            slug = c[6:]
            return slug in valid_adhoc
        m = re.search(r"#(\d+)", c)
        n = m.group(1) if m else c.lstrip("#")
        if s and (n, int(s)) in valid_keys:
            return True
        if (n, None) in valid_keys:
            return True
        return False

    schedule = [e for e in schedule if keep(e)]

    ctx.schedule_json.write_text(json.dumps(schedule, indent=2, ensure_ascii=False), encoding="utf-8")
    _safe_print("  [OK] schedule.json synced")

# ──── scheduler output processing ────


def write_output_file(source_ref: str, result_id: str = "", permalink: str = "",
                       caption: str = "", urls: list = None,
                       action: str = "publish", schedule_time: str = "",
                       account=None) -> Path | None:
    """Write a .scheduler_output/{safe_ref}_{uuid}.json file.
    Shared by runner.py, commands.py, and bot.py.
    action: 'publish' — post result (result_id, permalink)
            'schedule' — schedule entry (time)
    Returns the output file Path, or None on error."""
    ctx = _resolve_account(account)
    output_dir = ctx.scheduler_output_dir
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None
    safe_name = source_ref.replace("#", "_").replace(".", "_")
    uid = uuid.uuid4().hex[:8]
    output = {
        "source_ref": source_ref,
        "action": action,
        "caption": caption,
        "urls": urls or [],
        "timestamp": datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB"),
    }
    if action == "publish":
        output["result_id"] = result_id
        output["permalink"] = permalink
    elif action == "schedule":
        output["time"] = schedule_time
    out_path = output_dir / f"{safe_name}_{uid}.json"
    try:
        out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"   📝 .scheduler_output/{safe_name}_{uid}.json ditulis")
        return out_path
    except Exception as e:
        print(f"   ❌ Gagal nulis output file: {e}")
        return None


def process_scheduler_results(account: str | AccountContext | None = None) -> int:
    """Process .scheduler_output/*.json files from any source (GH Actions, bot, CLI).
    Reads each file, updates schedule.json + source_of_truth.json,
    then deletes the output file. Idempotent — safe to call multiple times.

    Action types:
      'publish' (default) — mark topic as live, schedule entry as done
      'schedule' — mark topic as scheduled, create schedule entry with done=false

    Returns number of processed files."""
    ctx = _resolve_account(account)
    output_dir = ctx.scheduler_output_dir
    if not output_dir.is_dir():
        return 0

    files = sorted(output_dir.glob("*.json"))
    if not files:
        return 0

    data = load(account=ctx)

    schedule = []
    if ctx.schedule_json.exists():
        schedule = json.loads(ctx.schedule_json.read_text(encoding="utf-8"))

    processed = 0
    for f in files:
        try:
            result = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print(f"  ⚠️  skip corrupt output file: {f.name}")
            f.unlink(missing_ok=True)
            continue

        source_ref = result.get("source_ref", "")
        action = result.get("action", "publish")
        result_id = result.get("result_id", "")
        permalink = result.get("permalink", "")
        caption = result.get("caption", "")
        urls = result.get("urls", [])
        schedule_time = result.get("time", "")

        if not source_ref:
            f.unlink(missing_ok=True)
            continue

        # Resolve ref to category + num_key (or "adhoc" + slug)
        resolved = resolve_ref(source_ref, data)
        if not resolved:
            print(f"  ⚠️  scheduler output {f.name}: {source_ref} gak dikenal, skip")
            f.unlink(missing_ok=True)
            continue
        cid, num_key = resolved
        is_adhoc = cid == "adhoc"

        # 1. Update source_of_truth.json
        topic = None
        if is_adhoc:
            adhoc_list = data.setdefault("adhoc_topics", [])
            for t in adhoc_list:
                if t.get("slug") == num_key:
                    topic = t
                    break
        else:
            topic = data.get("topics", {}).get(cid, {}).get(num_key)

        if topic:
            if action == "publish":
                topic["status"] = "live"
                if result_id:
                    topic["result_id"] = result_id
                if permalink:
                    topic["permalink"] = permalink
                if caption:
                    topic["caption"] = caption
                print(f"  ✅ source_of_truth: {source_ref} → live")
            elif action == "schedule":
                topic["status"] = "scheduled"
                if caption:
                    topic["caption"] = caption
                if schedule_time:
                    topic["scheduled_time"] = schedule_time
                print(f"  ✅ source_of_truth: {source_ref} → scheduled")

        # 2. Update schedule.json
        entry = None
        for e in schedule:
            if e.get("source_ref") == source_ref:
                entry = e
                break
        if not entry and topic:
            entry = {
                "source_ref": source_ref,
                "time": schedule_time or topic.get("scheduled_time", ""),
                "type": "carousel",
                "done": action == "publish",
                "topic_uuid": num_key if is_adhoc else topic.get("id", ""),
            }
            if not is_adhoc:
                entry["category"] = int(cid)
            schedule.append(entry)
            if action == "schedule":
                print(f"  ✅ schedule.json: {source_ref} → scheduled")
            else:
                print(f"  ✅ schedule.json: {source_ref} → new entry")
        if entry:
            if action == "publish":
                entry["done"] = True
                if result_id:
                    entry["result_id"] = result_id
                if permalink:
                    entry["permalink"] = permalink
                if caption:
                    entry["caption"] = caption
                if urls:
                    entry["urls"] = urls
                print(f"  ✅ schedule.json: {source_ref} → done")
            elif action == "schedule" and not entry.get("done"):
                entry["time"] = schedule_time or entry.get("time", "")
                if caption:
                    entry["caption"] = caption
                if urls:
                    entry["urls"] = urls
                entry["done"] = False
                print(f"  ✅ schedule.json: {source_ref} → scheduled")

        # 3. Delete output file
        f.unlink(missing_ok=True)
        processed += 1

    if processed:
        save(data, account=ctx)
        ctx.schedule_json.write_text(json.dumps(schedule, indent=2, ensure_ascii=False), encoding="utf-8")
        update_bio(account=ctx.name)
        print(f"  ✅ Bio page updated after {processed} scheduler result(s)")

    return processed


# ──── Telegram-callable helpers ────


def telegram_add_category(title: str, subtitle: str = "") -> str:
    """Add a category. Returns result message."""
    if not title:
        return "❌ --title wajib diisi"
    data = load()
    categories = data.setdefault("categories", {})
    existing_ids = [int(k) for k in categories]
    new_id = str(max(existing_ids) + 1) if existing_ids else "1"
    categories[new_id] = {
        "title": title,
        "subtitle": subtitle,
        "subcategories": {"1": {"title": "New Subcategory 1"}},
    }
    save(data)
    return f"✅ Category {new_id}: {title} ditambahkan"


def telegram_add_subcategory(cat_id: str, number: str, label: str) -> str:
    """Add a subcategory to a category. Returns result message."""
    data = load()
    if cat_id not in data.get("categories", {}):
        return f"❌ Category {cat_id} tidak ditemukan"
    data["categories"][cat_id].setdefault("subcategories", {})
    data["categories"][cat_id]["subcategories"][str(int(number))] = {"title": label}
    save(data)
    return f"✅ Subcategory {number} ditambahkan ke Category {cat_id}"


def telegram_add_topic(cat_id: str, subcat: str, title: str, slug: str | None = None, keywords: list | None = None) -> str:
    """Add a topic. Returns topic_ref string on success, error on failure."""
    if not cat_id:
        return "❌ --category wajib diisi"
    if not title:
        return "❌ --title wajib diisi"
    import uuid
    data = load()
    new_key = _next_topic_num(data, cat_id)
    slug = slug or title.lower().replace(" ", "-").replace(":", "").replace("?", "")[:30]
    topic = {
        "id": str(uuid.uuid4()),
        "slug": slug,
        "title": title,
        "subcategory": str(subcat),
        "status": "planned",
        "keywords": keywords or [],
    }
    _get_category_topics(data, cat_id)[new_key] = topic
    save(data)
    ref = format_ref(data, cat_id, new_key)
    return f"✅ {ref}: {title} ditambahkan ke Category {cat_id}"


def telegram_edit_topic(topic_ref: str, **fields) -> str:
    """Edit topic fields. Supported: title, slug, status, subcategory, display_name, subtitle, keywords, scheduled_time."""
    if not re.match(r'[CS]\d+(?:\.\d+)?#\d+', topic_ref):
        return f"❌ Format topic_ref salah: {topic_ref}"
    data = load()
    resolved = resolve_ref(topic_ref, data)
    if not resolved:
        return f"❌ {topic_ref} tidak ditemukan"
    cat_id, num = resolved
    st = _get_category_topics(data, cat_id)
    if num not in st:
        return f"❌ {topic_ref} tidak ditemukan"
    topic = st[num]
    for field in ("title", "slug", "status", "display_name", "subtitle", "scheduled_time"):
        if field in fields and fields[field] is not None:
            topic[field] = fields[field]
    if "subcategory" in fields and fields["subcategory"] is not None:
        topic["subcategory"] = str(fields["subcategory"])
    if "keywords" in fields and fields["keywords"] is not None:
        topic["keywords"] = fields["keywords"]
    save(data)
    return f"✅ {topic_ref} diupdate"


def telegram_delete_topic(topic_ref: str) -> str:
    """Delete a topic and renumber. Returns result message."""
    if not re.match(r'[CS]\d+(?:\.\d+)?#\d+', topic_ref):
        return f"❌ Format topic_ref salah: {topic_ref}"
    data = load()
    resolved = resolve_ref(topic_ref, data)
    if not resolved:
        return f"❌ {topic_ref} tidak ditemukan"
    cat_id, num = resolved
    st = _get_category_topics(data, cat_id)
    if num not in st:
        return f"❌ {topic_ref} tidak ditemukan"
    title = st[num].get("title", "")
    del st[num]
    save(data)
    return f"✅ {topic_ref} ({title}) dihapus"


def telegram_move_topic(topic_ref: str, target_cat: str, target_sc: str) -> str:
    """Move a topic to another category/subcategory. Returns result message."""
    if not re.match(r'[CS]\d+(?:\.\d+)?#\d+', topic_ref):
        return f"❌ Format topic_ref salah: {topic_ref}"
    data = load()
    resolved = resolve_ref(topic_ref, data)
    if not resolved:
        return f"❌ {topic_ref} tidak ditemukan"
    src_cat, num = resolved
    if target_cat not in data.get("categories", {}):
        return f"❌ Category {target_cat} tidak ditemukan"
    src_topics = _get_category_topics(data, src_cat)
    if num not in src_topics:
        return f"❌ {topic_ref} tidak ditemukan"
    topic = src_topics.pop(num)
    topic["subcategory"] = str(target_sc)
    # Add to target
    target_topics = _get_category_topics(data, target_cat)
    new_key = _next_topic_num(data, target_cat)
    target_topics[new_key] = topic
    save(data)
    new_ref = format_ref(data, target_cat, new_key)
    return f"✅ {topic_ref} dipindah ke {new_ref}"


def telegram_rename_category(cat_id: str, new_title: str) -> str:
    """Rename a category."""
    data = load()
    if cat_id not in data.get("categories", {}):
        return f"❌ Category {cat_id} tidak ditemukan"
    data["categories"][cat_id]["title"] = new_title
    save(data)
    return f"✅ Category {cat_id} diganti judulnya → {new_title}"


def telegram_remove_category(cat_id: str) -> str:
    """Remove a category. Blocked if it still has subcategories or topics."""
    data = load()
    if cat_id not in data.get("categories", {}):
        return f"❌ Category {cat_id} tidak ditemukan"
    subcats = data["categories"][cat_id].get("subcategories", {})
    topics = data.get("topics", {}).get(str(cat_id), {})
    if subcats:
        return f"❌ Category {cat_id} masih punya {len(subcats)} subcategory. Hapus dulu subcategory-nya baru bisa remove."
    if topics:
        return f"❌ Category {cat_id} masih punya {len(topics)} topic. Pindahin atau hapus dulu topic-nya baru bisa remove."
    del data["categories"][cat_id]
    data.get("topics", {}).pop(str(cat_id), None)
    save(data)
    return f"✅ Category {cat_id} dihapus"


def telegram_rename_subcategory(cat_id: str, sub_id: str, new_label: str) -> str:
    """Rename a subcategory."""
    data = load()
    if cat_id not in data.get("categories", {}):
        return f"❌ Category {cat_id} tidak ditemukan"
    subcats = data["categories"][cat_id].get("subcategories", {})
    if sub_id not in subcats:
        return f"❌ Subcategory {sub_id} di Category {cat_id} tidak ditemukan"
    subcats[sub_id]["title"] = new_label
    save(data)
    return f"✅ Subcategory {sub_id} di Category {cat_id} diganti → {new_label}"


def telegram_remove_subcategory(cat_id: str, sub_id: str) -> str:
    """Remove a subcategory. Blocked if it still has topics."""
    data = load()
    if cat_id not in data.get("categories", {}):
        return f"❌ Category {cat_id} tidak ditemukan"
    subcats = data["categories"][cat_id].get("subcategories", {})
    if sub_id not in subcats:
        return f"❌ Subcategory {sub_id} di Category {cat_id} tidak ditemukan"
    topics = data.get("topics", {}).get(str(cat_id), {})
    sub_topics = [k for k, v in topics.items() if v.get("subcategory") == sub_id]
    if sub_topics:
        return f"❌ Subcategory {sub_id} masih punya {len(sub_topics)} topic. Pindahin atau hapus dulu baru bisa remove."
    del subcats[sub_id]
    save(data)
    return f"✅ Subcategory {sub_id} di Category {cat_id} dihapus"


# ──── adhoc topic CRUD ────


def telegram_add_adhoc(title: str, slug: str | None = None, keywords: list | None = None) -> str:
    """Add an adhoc topic (independent, no category/subcategory)."""
    if not title:
        return "❌ --title wajib diisi"
    data = load()
    adhoc = data.setdefault("adhoc_topics", [])
    slug = slug or title.lower().replace(" ", "-").replace(":", "").replace("?", "")[:30]
    # Check slug uniqueness
    if any(t.get("slug") == slug for t in adhoc):
        return f"❌ Slug `{slug}` udah dipake"
    topic = {
        "slug": slug,
        "title": title,
        "status": "planned",
        "keywords": keywords or [],
    }
    adhoc.append(topic)
    save(data)
    return f"✅ Adhoc `{slug}`: {title} ditambahkan"


def telegram_delete_adhoc(adhoc_slug: str) -> str:
    """Delete an adhoc topic by slug."""
    if not adhoc_slug:
        return "❌ Slug adhoc wajib diisi"
    data = load()
    adhoc = data.get("adhoc_topics", [])
    for i, t in enumerate(adhoc):
        if t.get("slug") == adhoc_slug:
            title = t.get("title", adhoc_slug)
            del adhoc[i]
            save(data)
            return f"✅ Adhoc `{adhoc_slug}` ({title}) dihapus"
    return f"❌ Adhoc `{adhoc_slug}` gak ditemukan"


def telegram_edit_adhoc(adhoc_slug: str, **fields) -> str:
    """Edit adhoc topic fields. Supported: title, slug, status, keywords, display_name, subtitle."""
    if not adhoc_slug:
        return "❌ Slug adhoc wajib diisi"
    data = load()
    adhoc = data.get("adhoc_topics", [])
    for t in adhoc:
        if t.get("slug") == adhoc_slug:
            for field in ("title", "slug", "status", "display_name", "subtitle", "scheduled_time", "caption"):
                if field in fields and fields[field] is not None:
                    t[field] = fields[field]
            if "keywords" in fields and fields["keywords"] is not None:
                t["keywords"] = fields["keywords"]
            save(data)
            return f"✅ Adhoc `{adhoc_slug}` diupdate"
    return f"❌ Adhoc `{adhoc_slug}` gak ditemukan"


def telegram_list_adhoc() -> str:
    """List all adhoc topics with their status."""
    data = load()
    adhoc = data.get("adhoc_topics", [])
    if not adhoc:
        return "Belum ada adhoc topic."
    lines = ["📋 **Adhoc Topics:**\n"]
    icons = {"live": "✅", "scheduled": "📅", "planned": "⬜", "generated": "🟡", "failed": "❌"}
    for t in adhoc:
        icon = icons.get(t.get("status", ""), "⬜")
        slug = t.get("slug", "?")
        title = t.get("title", slug)
        sched = f" — {t.get('scheduled_time', '')}" if t.get("scheduled_time") else ""
        lines.append(f"  {icon} `{slug}` — {title}{sched}")
    return "\n".join(lines)


# ──── arg helpers ────


def _get_arg(args, name, default=None):
    for i, a in enumerate(args):
        if a == name and i + 1 < len(args):
            return args[i + 1]
    return default


# ──── dispatch ────


def cmd_curriculum(client, args):
    if not args:
        print("Subcommands: add, edit, delete, list, sync")
        print("  add category      --title T [--subtitle S]")
        print("  add subcategory   [--category C] --number N --label L")
        print("  add topic         --category C --subcategory S --title T [--slug SL] [--keywords K] [--display D] [--subtitle S]")
        print("  edit category     --category C [--title T] [--subtitle S]")
        print("  edit subcategory  --category C --subcategory N --label L")
        print("  edit topic        --category C --num N [--title T] [--status live|scheduled|planned] [--subcategory S] [--slug SL] [--keywords K] [--scheduled-time T]")
        print("  delete category   --category C")
        print("  delete topic      --category C --num N")
        print("  add adhoc         --title T [--slug SL] [--keywords K]")
        print("  delete adhoc      --slug SL")
        print("  edit adhoc        --slug SL [--title T] [--status live|scheduled|planned]")
        print("  list              [--category C]")
        print("  sync")
        print()
        print("Catatan: --category WAJIB untuk semua operasi topic. Nomor topic per-category (reset tiap category).")
        print("Adhoc topic: konten independent tanpa category/subcategory. Slug sebagai ID.")
        return

    cmd = args[0]
    subargs = args[1:]

    dispatch = {
        "add": _cmd_add,
        "edit": _cmd_edit,
        "delete": _cmd_delete,
        "list": cmd_list,
        "sync": cmd_sync,
    }

    fn = dispatch.get(cmd)
    if fn:
        fn(subargs)
    else:
        print(f"Subcommand tidak dikenal: {cmd}")


def cmd_add_adhoc(args):
    title = _get_arg(args, "--title")
    slug = _get_arg(args, "--slug")
    keywords_raw = _get_arg(args, "--keywords", "")
    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]
    if not title:
        print("❌ --title wajib diisi")
        return
    print(telegram_add_adhoc(title, slug, keywords))


def cmd_delete_adhoc(args):
    slug = _get_arg(args, "--slug")
    if not slug:
        print("❌ --slug wajib diisi")
        return
    print(telegram_delete_adhoc(slug))


def cmd_edit_adhoc(args):
    slug = _get_arg(args, "--slug")
    if not slug:
        print("❌ --slug wajib diisi")
        return
    fields = {}
    for f in ("title", "slug", "status", "display_name", "subtitle", "scheduled_time"):
        v = _get_arg(args, f"--{f}")
        if v:
            fields[f] = v
    keywords_raw = _get_arg(args, "--keywords", "")
    if keywords_raw:
        fields["keywords"] = [k.strip() for k in keywords_raw.split(",") if k.strip()]
    print(telegram_edit_adhoc(slug, **fields))


def _cmd_add(args):
    if not args:
        print("Tentukan: python main.py curriculum add category|subcategory|topic|adhoc")
        return
    sub = args[0]
    subargs = args[1:]
    {
        "category": cmd_add_category,
        "subcategory": cmd_add_subcategory,
        "topic": cmd_add_topic,
        "adhoc": cmd_add_adhoc,
    }.get(sub, lambda _: print(f"❌ add {sub} tidak dikenal"))(subargs)


def _cmd_edit(args):
    if not args:
        print("Tentukan: python main.py curriculum edit category|subcategory|topic|adhoc")
        return
    sub = args[0]
    subargs = args[1:]
    {
        "category": cmd_edit_category,
        "subcategory": cmd_edit_subcategory,
        "topic": cmd_edit_topic,
        "adhoc": cmd_edit_adhoc,
    }.get(sub, lambda _: print(f"❌ edit {sub} tidak dikenal"))(subargs)


def _cmd_delete(args):
    if not args:
        print("Tentukan: python main.py curriculum delete category|topic|adhoc")
        return
    sub = args[0]
    subargs = args[1:]
    {
        "category": cmd_delete_category,
        "topic": cmd_delete_topic,
        "adhoc": cmd_delete_adhoc,
    }.get(sub, lambda _: print(f"❌ delete {sub} tidak dikenal"))(subargs)


if __name__ == "__main__":
    cmd_curriculum(None, sys.argv[1:] if len(sys.argv) > 1 else [])
