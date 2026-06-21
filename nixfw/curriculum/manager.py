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
from pathlib import Path

from nixfw import config
from nixfw.bio.generator import update_bio

ACCOUNT_BASE = config.PROJECT_ROOT / "accounts" / config.ACCOUNT_NAME
SRC = ACCOUNT_BASE / "source_of_truth.json"
CUR_MD = ACCOUNT_BASE / "curriculum.md"
BIO_HTML = ACCOUNT_BASE / "bio" / "index.html"
SCHEDULE_JSON = ACCOUNT_BASE / "schedule.json"


# ──── helpers ────


def load():
    data = json.loads(SRC.read_text(encoding="utf-8"))
    _migrate_v4_to_v5(data)
    return data


def _migrate_v4_to_v5(data):
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
    save(data)


def save(data):
    SRC.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  ✅ source_of_truth.json saved (v{data.get('version', '?')})")


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
    """Public helper: format a topic reference using its subcategory and sequence."""
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
    """Resolve a user-provided ref (old C1#01 or new C1.1#01) to (cid, num_key) or None."""
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


def _all_topics(data):
    """Yield (category_id, topic_num_str, topic_dict) across all categories.
    Backfills UUID for topics that don't have one."""
    import uuid
    changed = False
    for cid in sorted(data.get("topics", {}), key=int):
        for k in sorted(data["topics"][cid], key=int):
            v = data["topics"][cid][k]
            if "id" not in v or not v["id"]:
                v["id"] = str(uuid.uuid4())
                changed = True
            yield str(cid), k, v
    if changed:
        save(data)


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


# ──── sync ────


def cmd_sync(args):
    data = load()
    _sync_curriculum_md(data)
    _sync_schedule_json(data)
    update_bio(account=config.ACCOUNT_NAME)
    print("\n  ✅ All files synced!")


def _sync_curriculum_md(data):
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

    CUR_MD.write_text("".join(lines), encoding="utf-8")
    print("  ✅ curriculum.md regenerated")


def _sync_schedule_json(data):
    """Ensure schedule.json matches source_of_truth.json — handles renumbering, time updates, cross-category."""
    if not SCHEDULE_JSON.exists():
        print("  ⚠️  schedule.json not found — skip")
        return

    schedule = json.loads(SCHEDULE_JSON.read_text(encoding="utf-8"))

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

    # Build set of valid UUIDs + curriculum+category combos
    valid_uuids = set()
    valid_keys = set()
    for cid, num, v in _all_topics(data):
        valid_uuids.add(v.get("id", ""))
        sc = v.get("subcategory", "1")
        seq = seq_map.get((cid, sc), {}).get(num)
        valid_keys.add((num, int(cid)))  # dict key (for legacy format matching)
        if seq is not None:
            valid_keys.add((f"{seq:02d}", int(cid)))  # seq (for new format matching)

    def keep(entry):
        tu = entry.get("topic_uuid", "")
        if tu and tu in valid_uuids:
            return True
        c = entry.get("source_ref") or entry.get("curriculum", "")
        s = entry.get("category") or entry.get("season")
        if not c:
            return True
        m = re.search(r"#(\d+)", c)
        n = m.group(1) if m else c.lstrip("#")
        if s and (n, int(s)) in valid_keys:
            return True
        if (n, None) in valid_keys:
            return True
        return False

    schedule = [e for e in schedule if keep(e)]

    SCHEDULE_JSON.write_text(json.dumps(schedule, indent=2, ensure_ascii=False), encoding="utf-8")
    print("  ✅ schedule.json synced")

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
    m = re.match(r'[CS](\d+)#(\d+)', topic_ref)
    if not m:
        return f"❌ Format topic_ref salah: {topic_ref}"
    cat_id, num = m.group(1), m.group(2).zfill(2)
    data = load()
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
    m = re.match(r'[CS](\d+)#(\d+)', topic_ref)
    if not m:
        return f"❌ Format topic_ref salah: {topic_ref}"
    cat_id, num = m.group(1), m.group(2).zfill(2)
    data = load()
    st = _get_category_topics(data, cat_id)
    if num not in st:
        return f"❌ {topic_ref} tidak ditemukan"
    title = st[num].get("title", "")
    del st[num]
    save(data)
    return f"✅ {topic_ref} ({title}) dihapus"


def telegram_move_topic(topic_ref: str, target_cat: str, target_sc: str) -> str:
    """Move a topic to another category/subcategory. Returns result message."""
    m = re.match(r'[CS](\d+)#(\d+)', topic_ref)
    if not m:
        return f"❌ Format topic_ref salah: {topic_ref}"
    src_cat, num = m.group(1), m.group(2).zfill(2)
    data = load()
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
        print("  list              [--category C]")
        print("  sync")
        print()
        print("Catatan: --category WAJIB untuk semua operasi topic. Nomor topic per-category (reset tiap category).")
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


def _cmd_add(args):
    if not args:
        print("Tentukan: python main.py curriculum add category|subcategory|topic")
        return
    sub = args[0]
    subargs = args[1:]
    {
        "category": cmd_add_category,
        "subcategory": cmd_add_subcategory,
        "topic": cmd_add_topic,
    }.get(sub, lambda _: print(f"❌ add {sub} tidak dikenal"))(subargs)


def _cmd_edit(args):
    if not args:
        print("Tentukan: python main.py curriculum edit category|subcategory|topic")
        return
    sub = args[0]
    subargs = args[1:]
    {
        "category": cmd_edit_category,
        "subcategory": cmd_edit_subcategory,
        "topic": cmd_edit_topic,
    }.get(sub, lambda _: print(f"❌ edit {sub} tidak dikenal"))(subargs)


def _cmd_delete(args):
    if not args:
        print("Tentukan: python main.py curriculum delete category|topic")
        return
    sub = args[0]
    subargs = args[1:]
    {
        "category": cmd_delete_category,
        "topic": cmd_delete_topic,
    }.get(sub, lambda _: print(f"❌ delete {sub} tidak dikenal"))(subargs)


if __name__ == "__main__":
    cmd_curriculum(None, sys.argv[1:] if len(sys.argv) > 1 else [])
