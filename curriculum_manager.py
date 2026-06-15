"""Curriculum manager — single source of truth untuk struktur kurikulum multi-season, multi-level, multi-topic.

Topics are nested per-season in curriculum_content.json v4+:
  topics: { "1": { "01": {...}, "02": {...} }, "2": { "01": {...} } }

Usage:
    python main.py curriculum add season --title "..." --subtitle "..."
    python main.py curriculum add level --season 1 --number 5 --label "..."
    python main.py curriculum add topic --season 1 --level 1 --title "..." [--slug ...] [--keywords ...]
    python main.py curriculum edit season --season 1 --title "..."
    python main.py curriculum edit level --season 1 --level 2 --label "..."
    python main.py curriculum edit topic --season 1 --num 04 --title "..." [--status live|scheduled|planned]
    python main.py curriculum delete topic --season 1 --num 04
    python main.py curriculum list [--season 1]
    python main.py curriculum sync
"""

import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
SRC = BASE / "curriculum_content.json"
CUR_MD = BASE / "curriculum.md"
BIO_HTML = BASE / "bio" / "index.html"
SCHEDULE_JSON = BASE / "schedule.json"
AGENTS_MD = BASE / "AGENTS.md"


# ──── helpers ────

def load():
    return json.loads(SRC.read_text(encoding="utf-8"))


def save(data):
    SRC.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  ✅ curriculum_content.json saved (v{data.get('version', '?')})")


def _get_season_topics(data, season):
    """Return the topics dict for a given season (creates if missing)."""
    data.setdefault("topics", {})
    data["topics"].setdefault(str(season), {})
    return data["topics"][str(season)]


def _next_topic_num(data, season):
    """Next available topic number within a season."""
    st = _get_season_topics(data, season)
    existing = [int(k) for k in st]
    return f"{max(existing) + 1:02d}" if existing else "01"


def _renumber_topics(data):
    """Renumber topics sequentially within each season."""
    for sid, st in data.get("topics", {}).items():
        sorted_ = sorted(
            [(int(k), k, v) for k, v in st.items()],
            key=lambda x: x[0],
        )
        for idx, (old_num, old_key, topic) in enumerate(sorted_, 1):
            new_key = f"{idx:02d}"
            if old_key != new_key:
                st[new_key] = st.pop(old_key)
    return data


def _all_topics(data):
    """Yield (season_id, topic_num_str, topic_dict) across all seasons."""
    for sid in sorted(data.get("topics", {}), key=int):
        for k in sorted(data["topics"][sid], key=int):
            yield str(sid), k, data["topics"][sid][k]


def _level_topics(data, sid, lv):
    """Yield (topic_num_str, topic_dict) for a specific season+level."""
    st = data.get("topics", {}).get(str(sid), {})
    for k in sorted(st, key=int):
        v = st[k]
        if v.get("level") == int(lv):
            yield k, v


# ──── season crud ────

def cmd_add_season(args):
    data = load()
    title = _get_arg(args, "--title")
    subtitle = _get_arg(args, "--subtitle", "")
    if not title:
        print("❌ --title wajib diisi")
        return

    existing_ids = [int(k) for k in data.get("seasons", {})]
    new_id = str(max(existing_ids) + 1) if existing_ids else "1"

    seasons = data.setdefault("seasons", {})
    seasons[new_id] = {
        "title": title,
        "subtitle": subtitle,
        "level_labels": {"1": "New Level 1"},
    }
    save(data)
    print(f"  ✅ Season {new_id}: {title} added")


def cmd_edit_season(args):
    data = load()
    season_id = _get_arg(args, "--season")
    if not season_id or season_id not in data.get("seasons", {}):
        print(f"❌ --season {season_id} tidak ditemukan")
        return
    season = data["seasons"][season_id]
    title = _get_arg(args, "--title")
    subtitle = _get_arg(args, "--subtitle")
    if title:
        season["title"] = title
    if subtitle is not None:
        season["subtitle"] = subtitle
    save(data)
    print(f"  ✅  Season {season_id} updated")


def cmd_delete_season(args):
    data = load()
    season_id = _get_arg(args, "--season")
    if not season_id or season_id not in data.get("seasons", {}):
        print(f"❌ --season {season_id} tidak ditemukan")
        return

    st = data.get("topics", {}).pop(str(season_id), {})
    del data["seasons"][season_id]
    save(data)
    print(f"  ✅  Season {season_id} deleted ({len(st)} topics removed)")


# ──── level crud ────

def cmd_add_level(args):
    data = load()
    season_id = _get_arg(args, "--season", "1")
    if season_id not in data.get("seasons", {}):
        print(f"❌ Season {season_id} tidak ditemukan")
        return
    level_num = _get_arg(args, "--number")
    label = _get_arg(args, "--label", "")

    if not level_num:
        existing = data["seasons"][season_id].get("level_labels", {})
        max_lv = max(int(k) for k in existing) if existing else 0
        level_num = str(max_lv + 1)

    data["seasons"][season_id].setdefault("level_labels", {})
    data["seasons"][season_id]["level_labels"][str(int(level_num))] = label or f"Level {int(level_num)}"
    save(data)
    print(f"  ✅ Level {level_num} added to Season {season_id}")


def cmd_edit_level(args):
    data = load()
    season_id = _get_arg(args, "--season", "1")
    level_num = _get_arg(args, "--level")
    label = _get_arg(args, "--label")

    if not level_num or season_id not in data.get("seasons", {}):
        print("❌ --level dan --season valid wajib diisi")
        return
    levels = data["seasons"][season_id].get("level_labels", {})
    if level_num not in levels:
        print(f"❌ Level {level_num} tidak ditemukan di Season {season_id}")
        return
    if label:
        levels[level_num] = label
        save(data)
        print(f"  ✅  Level {level_num} in Season {season_id} updated")


# ──── topic crud ────

def cmd_add_topic(args):
    data = load()
    season_id = _get_arg(args, "--season")
    if not season_id:
        print("❌ --season wajib diisi")
        return
    level = _get_arg(args, "--level", "1")
    title = _get_arg(args, "--title")
    if not title:
        print("❌ --title wajib diisi")
        return

    new_key = _next_topic_num(data, season_id)
    slug = _get_arg(args, "--slug") or title.lower().replace(" ", "-").replace(":", "").replace("?", "")[:30]
    keywords_raw = _get_arg(args, "--keywords", "")
    keywords = [k.strip() for k in keywords_raw.split(",") if k.strip()]

    topic = {
        "slug": slug,
        "title": title,
        "level": int(level),
        "status": "planned",
        "keywords": keywords,
    }
    display = _get_arg(args, "--display")
    if display:
        topic["display_name"] = display
    subtitle = _get_arg(args, "--subtitle")
    if subtitle:
        topic["subtitle"] = subtitle

    _get_season_topics(data, season_id)[new_key] = topic
    save(data)
    print(f"  ✅ S{season_id}#{new_key}: {title} (L{level}) added")


def cmd_edit_topic(args):
    data = load()
    season_id = _get_arg(args, "--season")
    num = _get_arg(args, "--num")
    if not season_id or not num:
        print("❌ --season dan --num wajib diisi")
        return
    st = _get_season_topics(data, season_id)
    if num not in st:
        print(f"❌ S{season_id}#{num} tidak ditemukan")
        return

    topic = st[num]
    for field in ("title", "slug", "status", "display_name", "subtitle"):
        val = _get_arg(args, f"--{field}")
        if val is not None:
            topic[field] = val
    st_val = _get_arg(args, "--scheduled-time") or _get_arg(args, "--scheduled_time")
    if st_val is not None:
        topic["scheduled_time"] = st_val
    level_raw = _get_arg(args, "--level")
    if level_raw:
        topic["level"] = int(level_raw)
    keywords_raw = _get_arg(args, "--keywords")
    if keywords_raw is not None:
        topic["keywords"] = [k.strip() for k in keywords_raw.split(",") if k.strip()]

    save(data)
    print(f"  ✅  S{season_id}#{num} updated")


def cmd_delete_topic(args):
    data = load()
    season_id = _get_arg(args, "--season")
    num = _get_arg(args, "--num")
    if not season_id or not num:
        print("❌ --season dan --num wajib diisi")
        return
    st = _get_season_topics(data, season_id)
    if num not in st:
        print(f"❌ S{season_id}#{num} tidak ditemukan")
        return

    del st[num]
    data = _renumber_topics(data)
    save(data)
    print(f"  ✅  S{season_id}#{num} deleted (topics renumbered)")


def cmd_list(args):
    data = load()
    season_filter = _get_arg(args, "--season")

    seasons = data.get("seasons", {})

    for sid in sorted(seasons, key=int):
        if season_filter and sid != season_filter:
            continue
        s = seasons[sid]
        levels = s.get("level_labels", {})
        st = data.get("topics", {}).get(str(sid), {})
        print(f"\n{'='*50}")
        print(f"  Season {sid}: {s['title']}")
        print(f"  {s.get('subtitle','')}")
        print(f"{'='*50}")

        for lv in sorted(levels, key=int):
            label = levels[lv]
            print(f"\n  ──── Level {lv}: {label} ────")
            lv_topics = [(k, st[k]) for k in sorted(st, key=int) if st[k].get("level") == int(lv)]
            if not lv_topics:
                print("    (empty)")
            for k, v in lv_topics:
                status_icon = {"live": "✅", "scheduled": "📅", "planned": "⬜"}.get(v.get("status", ""), "⬜")
                print(f"    {status_icon} #{k} {v['title']:30s} [{v.get('status','planned')}]")


# ──── sync ────

def cmd_sync(args):
    data = load()
    _sync_curriculum_md(data)
    _sync_agents_md(data)
    _sync_schedule_json(data)
    _sync_bio_html(data)
    print("\n  ✅ All files synced!")


def _sync_curriculum_md(data):
    seasons = data.get("seasons", {})

    lines = ["# 📚 Kurikulum Aquarisamatiran\n"]
    lines.append("Belajar aquarium dari nol sampai advanced — step by step, pake bahasa awam.\n")
    lines.append("---\n")

    for sid in sorted(seasons, key=int):
        s = seasons[sid]
        st = data.get("topics", {}).get(str(sid), {})
        lines.append(f"\n## 🌱 Season {sid}: {s['title']}\n")
        if s.get("subtitle"):
            lines.append(f"> {s['subtitle']}\n")

        levels = s.get("level_labels", {})
        for lv in sorted(levels, key=int):
            label = levels[lv].split("—")[0].strip() if "—" in levels[lv] else levels[lv]
            lines.append(f"\n### Level {lv}: {label}\n")
            lines.append("| # | Topik | Status |\n")
            lines.append("|---|-------|--------|\n")

            for k in sorted(st, key=int):
                v = st[k]
                if v.get("level") != int(lv):
                    continue
                title = v.get("title", "?")
                status = v.get("status", "planned")
                icon = {"live": "✅", "scheduled": "📅", "planned": "⬜"}.get(status, "⬜")
                tgl = v.get("scheduled_time", "")
                tgl_str = f" ({tgl})" if tgl else ""
                lines.append(f"| {k} | {title}{tgl_str} | {icon} |\n")

    CUR_MD.write_text("".join(lines), encoding="utf-8")
    print("  ✅ curriculum.md regenerated")


def _sync_agents_md(data):
    """No-op — terminology now served from curriculum_content.json by bot.py directly."""
    pass


def _sync_schedule_json(data):
    """Ensure schedule.json matches curriculum_content.json — handles renumbering, time updates, cross-season."""
    if not SCHEDULE_JSON.exists():
        print("  ⚠️  schedule.json not found — skip")
        return

    schedule = json.loads(SCHEDULE_JSON.read_text(encoding="utf-8"))

    # Build identity maps from existing schedule entries
    result_id_map = {}
    permalink_map = {}
    for i, entry in enumerate(schedule):
        rid = entry.get("result_id", "")
        if rid:
            result_id_map[rid] = i
        pl = entry.get("permalink", "")
        if pl and pl.strip():
            permalink_map[pl.strip().rstrip("/")] = i

    # Iterate all topics across all seasons
    for sid, num, v in _all_topics(data):
        target_label = f"S{sid}#{num}"
        rid = v.get("result_id", "")
        pl = v.get("permalink", "").strip().rstrip("/")

        idx = None
        if rid and rid in result_id_map:
            idx = result_id_map[rid]
        elif pl and pl in permalink_map:
            idx = permalink_map[pl]

        entry = None
        old_label = None
        if idx is not None:
            entry = schedule[idx]
            old_label = entry.get("curriculum", "")
        else:
            existing = [e for e in schedule if re.search(r"#(\d+)", e.get("curriculum", "")) and re.search(r"#(\d+)", e.get("curriculum", "")).group(1) == num]
            if existing:
                entry = existing[0]
                old_label = entry.get("curriculum", "")

        if entry is not None:
            entry["curriculum"] = target_label
            entry["season"] = int(sid)
            if v.get("scheduled_time"):
                entry["time"] = v["scheduled_time"]
            if v.get("status") == "live":
                entry["done"] = True
            elif v.get("status") == "scheduled":
                entry["done"] = False
            if v.get("permalink"):
                entry["permalink"] = v["permalink"]
            if v.get("result_id"):
                entry["result_id"] = v["result_id"]
            if old_label and old_label != target_label:
                print(f"  🔄 schedule.json: {old_label} → S{sid}#{num}")
        elif v.get("status") in ("live", "scheduled"):
            entry = {
                "curriculum": target_label,
                "season": int(sid),
                "time": v.get("scheduled_time", ""),
                "type": "carousel",
                "done": v.get("status") == "live",
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
            print(f"  📋 schedule.json: added S{sid}#{num}")

    # Build set of valid curriculum+season combos
    valid_keys = set()
    for sid, num, _ in _all_topics(data):
        valid_keys.add((num, int(sid)))

    def keep(entry):
        c = entry.get("curriculum", "")
        s = entry.get("season")
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


def _sync_bio_html(data):
    """Regenerate bio/index.html card structure from JSON."""
    if not BIO_HTML.exists():
        print("  ⚠️  bio/index.html not found — skip")
        return

    seasons = data.get("seasons", {})

    season_blocks = []
    for sid in sorted(seasons, key=int):
        s = seasons[sid]
        levels = s.get("level_labels", {})
        st = data.get("topics", {}).get(str(sid), {})
        season_html = [f'  <div class="season" data-season="{sid}">']
        season_html.append('  <div class="season-header">')
        season_html.append(f'    <h2>🌱 Season {sid}: {s["title"]}</h2>')
        if s.get("subtitle"):
            season_html.append(f'    <p>{s["subtitle"]}</p>')
        season_html.append("  </div>")

        for lv in sorted(levels, key=int):
            label = levels[lv]
            season_html.append("")
            season_html.append('  <div class="section">')
            lv_icon = {1: "🌱", 2: "🌿", 3: "🌳", 4: "💎"}.get(int(lv), "🌱")
            season_html.append(f'    <h2>{lv_icon} Level {lv} — {label.split("—")[0].strip()}</h2>')
            season_html.append(f'    <p class="level-intro">{label}</p>')

            for k in sorted(st, key=int):
                v = st[k]
                if v.get("level") != int(lv):
                    continue
                title = v.get("title", "?")
                desc = v.get("subtitle", "") or v.get("display_name", "") or v.get("scientific_name", "")
                status = v.get("status", "planned")
                permalink = v.get("permalink", "")

                if status == "live":
                    tag_cls = "tag-live"
                    tag_text = "✅ Live"
                elif status == "scheduled":
                    tag_cls = "tag-soon"
                    st_text = v.get("scheduled_time", "")
                    tag_text = f"📅 {st_text}" if st_text else "📅 Soon"
                else:
                    tag_cls = "tag-empty"
                    tag_text = "🔜"

                href = permalink if permalink else "https://instagram.com/aquarisamatiran"
                level_class = f"l{lv}"
                season_html.append(
                    f'    <a class="card-link" href="{href}" target="_blank" rel="noopener">'
                    f'<div class="card {level_class}"><div class="num">{int(k)}</div>'
                    f'<div class="body"><div class="title">{title}</div>'
                    f'<div class="desc">{desc}</div>'
                    f'<div class="status"><span class="tag {tag_cls}">{tag_text}</span></div>'
                    f"</div></div></a>"
                )

            season_html.append("  </div>")

        season_html.append("  </div>")
        season_blocks.append("\n".join(season_html))

    old_html = BIO_HTML.read_text(encoding="utf-8")
    cta_start = old_html.find('<div class="cta">')
    if cta_start < 0:
        print("  ⚠️  CTA section not found in bio/index.html — manual update needed")
        return

    header_end = old_html.find('</div>\n\n  <div class="season"')
    if header_end == -1:
        header_end = old_html.find('</div>\n\n\n\n  <div class="season"')
    # Also try finding any </div> followed by a season opening
    if header_end == -1:
        import re
        m = re.search(r'</div>\n{2,10}  <div class="season"', old_html)
        if m:
            header_end = m.start()
    if header_end == -1:
        header_end = old_html.find('</div>\n\n  <div class="section"')

    if header_end >= 0 and cta_start > header_end:
        cut = header_end + 8
        new_html = old_html[:cut] + "\n\n".join(season_blocks) + "\n\n" + old_html[cta_start:]
        BIO_HTML.write_text(new_html, encoding="utf-8")
        print("  ✅ bio/index.html regenerated")
    else:
        print("  ⚠️  Could not find card section in bio/index.html — manual update needed")


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
        print("  add season     --title T [--subtitle S]")
        print("  add level      [--season S] --number N --label L")
        print("  add topic      --season S --level L --title T [--slug SL] [--keywords K] [--display D] [--subtitle S]")
        print("  edit season    --season S [--title T] [--subtitle S]")
        print("  edit level     --season S --level N --label L")
        print("  edit topic     --season S --num N [--title T] [--status live|scheduled|planned] [--level L] [--slug SL] [--keywords K] [--scheduled-time T]")
        print("  delete season  --season S")
        print("  delete topic   --season S --num N")
        print("  list           [--season S]")
        print("  sync")
        print()
        print("Catatan: --season WAJIB untuk semua operasi topic. Nomor topic per-season (reset tiap season).")
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
        print("Tentukan: python main.py curriculum add season|level|topic")
        return
    sub = args[0]
    subargs = args[1:]
    {
        "season": cmd_add_season,
        "level": cmd_add_level,
        "topic": cmd_add_topic,
    }.get(sub, lambda _: print(f"❌ add {sub} tidak dikenal"))(subargs)


def _cmd_edit(args):
    if not args:
        print("Tentukan: python main.py curriculum edit season|level|topic")
        return
    sub = args[0]
    subargs = args[1:]
    {
        "season": cmd_edit_season,
        "level": cmd_edit_level,
        "topic": cmd_edit_topic,
    }.get(sub, lambda _: print(f"❌ edit {sub} tidak dikenal"))(subargs)


def _cmd_delete(args):
    if not args:
        print("Tentukan: python main.py curriculum delete season|topic")
        return
    sub = args[0]
    subargs = args[1:]
    {
        "season": cmd_delete_season,
        "topic": cmd_delete_topic,
    }.get(sub, lambda _: print(f"❌ delete {sub} tidak dikenal"))(subargs)


if __name__ == "__main__":
    cmd_curriculum(sys.argv[1:] if len(sys.argv) > 1 else [])
