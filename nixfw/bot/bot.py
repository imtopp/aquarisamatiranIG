"""Telegram bot untuk Aquarisamatiran — personality AGENTS.md + Gemini API"""
import asyncio
import datetime
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

from nixfw.config import (
    AGENTS_MD,
    CONTENT_PATH as CURRICULUM_PATH,
    DB_PATH,
    PHOTO_DIR,
    PROJECT_ROOT,
    SCHEDULE_PATH,
)
from nixfw.slot_manager import SlotManager, DAYS_ID
from nixfw.content.providers.facts_generator import facts_cache_path, generate_facts
from nixfw.curriculum.manager import (
    telegram_add_category,
    telegram_add_subcategory,
    telegram_add_topic,
    telegram_edit_topic,
    telegram_delete_topic,
    telegram_move_topic,
    format_ref,
)


def _seq_to_key(data, cid, sc, seq):
    """Reverse-lookup dict key from sequence number within subcategory."""
    st = data.get("topics", {}).get(cid, {})
    items = [(int(k), k) for k, v in st.items() if v.get("subcategory", "1") == sc]
    items.sort()
    idx = int(seq) - 1
    if 0 <= idx < len(items):
        return items[idx][1]
    return None

sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GEMINI_API_KEYS = [
    os.environ.get("GEMINI_API_KEY", ""),
    *[v for k, v in sorted(os.environ.items()) if k.startswith("GEMINI_API_KEY_") and v],
]
ALLOWED_USERNAMES = os.environ.get("BOT_ALLOWED_USERNAMES", "").split(",")
FORBIDDEN_WORDS = ["lu", "gue", "lo", "elu", "gw"]

GEMINI_MODELS = ["gemini-2.5-flash"]

_pending_posts: dict[int, dict] = {}
GH_PAT = os.environ.get("GH_PAT", "")
GH_REPO = "imtopp/aquarisamatiranIG"
GH_API = "https://api.github.com"

SLOT_MANAGER = SlotManager()

system_prompt = ""
if AGENTS_MD.exists():
    system_prompt = AGENTS_MD.read_text(encoding="utf-8")
    system_prompt += "\n\nKamu adalah aku yang asli — personality, suara, gaya bicara, semuanya sama persis."

# Inject terminology from source_of_truth.json (v5: categories → subcategories)
if CURRICULUM_PATH.exists():
    try:
        cur_data = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
        topics = cur_data.get("topics", {})
        categories = cur_data.get("categories", {})
        if topics:
            term_lines = ["", "## Curriculum Terminology (live from source_of_truth.json)", ""]
            for cid in sorted(categories, key=int):
                c = categories[cid]
                st = topics.get(str(cid), {})
                subcats = c.get("subcategories", {})
                for sc_key in sorted(subcats, key=int):
                    sc = subcats[sc_key]
                    label = sc.get("title", f"Level {sc_key}")
                    sc_topics = sorted(
                        [(k, st[k]) for k in st if st[k].get("subcategory") == sc_key],
                        key=lambda x: int(x[0]),
                    )
                    if not sc_topics:
                        continue
                    term_lines.append(f"Season {cid} — {label}:")
                    for k, v in sc_topics:
                        status = v.get("status", "planned")
                        keywords = v.get("keywords", [])
                        kw_str = ", ".join(keywords) if keywords else "(no keywords)"
                        status_tag = " ✅" if status == "live" else (" 📅" if status == "scheduled" else "")
                        term_lines.append(f"  {format_ref(cc_raw, cid, k)} {v['title']}{status_tag}: {kw_str}")
            system_prompt += "\n" + "\n".join(term_lines)
    except Exception:
        pass  # best-effort

HTTPX_CLIENT = httpx.AsyncClient(timeout=300)


def _today_context() -> str:
    return f"Hari ini: {datetime.datetime.now().strftime('%A, %d %B %Y %H:%M WIB')}"


async def _call_gemini(messages: list[dict], system: str | None = None) -> str:
    """Call Gemini REST API with fallback keys + fallback models, retry on timeout."""
    sp = system if system is not None else system_prompt
    if messages and messages[-1].get("role") == "user":
        today = _today_context()
        messages[-1]["parts"][0]["text"] = f"{today}\n\n{sp}\n\n{messages[-1]['parts'][0]['text']}"
    body = {"contents": messages}
    keys = [k for k in GEMINI_API_KEYS if k]
    last_err = ""
    for key in keys:
        for model in GEMINI_MODELS:
            for attempt in range(3):
                url = f"https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={key}"
                try:
                    resp = await HTTPX_CLIENT.post(url, json=body)
                except (httpx.TimeoutException, httpx.ReadTimeout) as e:
                    last_err = str(e)
                    continue
                if resp.status_code == 200:
                    data = resp.json()
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                err_data = resp.json().get("error", {})
                err_msg = err_data.get("message", str(resp.status_code))
                last_err = err_msg
                if resp.status_code == 503:
                    await asyncio.sleep(3 * (attempt + 1))
                    continue
                if resp.status_code in (429, 403):
                    break
    if "high demand" in last_err.lower() or "currently experiencing" in last_err.lower():
        raise RuntimeError(f"Gemini lagi sibuk (high demand). Coba lagi dalam beberapa menit~")
    raise RuntimeError(f"Semua model & key Gemini error: {last_err[:100]}")


def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS history (
            user_id INTEGER,
            username TEXT,
            role TEXT,
            content TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def get_history(user_id, limit=20):
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(
        "SELECT role, content FROM history WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return list(reversed(rows))


def save_message(user_id, username, role, content):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "INSERT INTO history (user_id, username, role, content) VALUES (?, ?, ?, ?)",
        (user_id, username, role, content),
    )
    conn.commit()
    conn.close()


ALLOWED_CMDS = ["python", "git", "ls", "cat", "cd", "pwd", "echo", "cp", "mv", "rm"]


HELP_TEXT = (
    "Halo sayang~ 🫣💋\n"
    "Aku di sini, kapan aja kamu mau ngobrol. "
    "Mulai aja, aku dengerin~ 😏\n\n"
    "**📋 Perintah:**\n"
    "📁 `/topic` — CRUD kurikulum (`add|show|edit|delete|move|cat|slides`)\n"
    "📁 `/post` — alur posting (`confirm|cancel|caption|clean`) atau langsung `[ref]`\n"
    "📁 `/generate` — generate slide (`[ref]`, `--cache`, `--force`)\n"
    "📁 `/schedule` — manajemen jadwal (`delete|slot`)\n\n"
    "🔧 `/help`, `/status`, `/reset`, `/run`, `/myid`, `/sync`\n\n"
    "Cek `/topic help`, `/post help`, `/generate help`, `/schedule help` buat detail subcommand~\n\n"
    "**🚀 Cara pake:**\n"
    "1. `/topic` — cari tau `C1.1#01` yang tersedia\n"
    "2. `/generate C1.1#07` — bikin slide (10-30 menit)\n"
    "3. `/status` — cek udah selesai belum\n"
    "4. `/post C1.1#07` — preview + caption\n"
    "5. `/post confirm` — upload & jadwal"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


def _reset_topic_status(topic_ref: str, new_status: str = "generated"):
    """Set status topik di source_of_truth.json."""
    m = re.match(r"[CS](\d+)(?:\.(\d+))?#(\d+)", topic_ref)
    if not m:
        return
    try:
        cc = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
        sid, sc, seq = m.group(1), m.group(2) or "1", m.group(3).zfill(2)
        num_key = _seq_to_key(cc, sid, sc, seq) if m.group(2) else seq
        if not num_key:
            return
        t = cc.get("topics", {}).get(sid, {}).get(num_key)
        if t:
            t["status"] = new_status
            CURRICULUM_PATH.write_text(json.dumps(cc, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _read_schedule() -> str:
    """Read schedule.json and return a formatted summary."""
    try:
        data = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return ""
    now = datetime.date.today()
    cc = {}
    try:
    cc_raw = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
    for cid, ts in cc_raw.get("topics", {}).items():
        for t_num, t in ts.items():
            cc[format_ref(cc_raw, cid, t_num)] = t.get("title", "")
    except Exception:
        pass
    done, upcoming = [], []
    for entry in data:
        t = entry.get("time", "")
        try:
            d = datetime.datetime.strptime(t[:10], "%Y-%m-%d").date()
        except (ValueError, IndexError):
            continue
        ref = entry.get("source_ref") or entry.get("curriculum") or ""
        title = cc.get(ref, "") if ref else ""
        if title:
            topic = f"{ref} — {title}"
        elif ref:
            topic = ref
        else:
            cap = entry.get("caption", "")
            snippet = cap[:60].replace("\n", " ") + "…" if len(cap) > 60 else cap.replace("\n", " ")
            topic = f"{entry.get('type', 'post')}: \"{snippet}\"" if snippet else entry.get('type', 'post')
        if entry.get("done"):
            done.append(f"{topic}: {d.strftime('%d %b')} ✅")
        elif d < now:
            done.append(f"{topic}: {d.strftime('%d %b')} (skip)")
        else:
            days = (d - now).days
            label = "HARI INI 🟡" if days == 0 else f"{days} hari lagi"
            upcoming.append(f"{topic}: {d.strftime('%d %b')} {entry['time'][11:16]} WIB — {label}")
    lines = ["**📋 Schedule Posting:**"]
    if upcoming:
        lines.append("\n**Belum posting:**")
        lines.extend(f"• {u}" for u in upcoming)
    if done:
        lines.append("\n**Udah dipublish:**")
        lines.extend(f"• {d}" for d in done)
    return "\n".join(lines)


def _load_curriculum() -> dict:
    """Load and flatten curriculum topics to {C1.1#01: {...}} format."""
    try:
        data = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
        topics = data.get("topics", {})
        flat = {}
        for sid in sorted(topics, key=int):
            for tnum in sorted(topics[sid], key=int):
                flat[format_ref(data, sid, tnum)] = topics[sid][tnum]
        return flat
    except Exception:
        return {}


def _topic_title_from_ref(topic_ref):
    """Extract topic title from curriculum given a ref (old C1#01 or new C1.1#01 format)."""
    m = re.match(r'[CS](\d+)(?:\.(\d+))?#(\d+)', topic_ref)
    if not m:
        return None
    try:
        cc = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
        sid, sc, seq = m.group(1), m.group(2) or "1", m.group(3).zfill(2)
        num_key = _seq_to_key(cc, sid, sc, seq) if m.group(2) else seq
        if num_key:
            return cc.get("topics", {}).get(sid, {}).get(num_key, {}).get("title")
    except Exception:
        pass
    return None


def _match_curriculum_topic(text: str, topics: dict) -> str | None:
    """Cari topic di curriculum yang cocok dengan pertanyaan user."""
    text_lower = text.lower()
    for key, topic in topics.items():
        title_lower = topic.get("title", "").lower()
        slug = topic.get("slug", "")
        keywords = [k.lower().strip() for k in topic.get("keywords", [])]
        display = topic.get("display_name", "").lower()
        tnum = key.split("#")[1]
        prefix = key.split("#")[0]
        patterns = [f"#{tnum}", key.lower(), prefix.lower(), title_lower, slug.replace("-", " "), display]
        patterns.extend(k for k in keywords if len(k) > 3)
        for pat in patterns:
            if pat and pat in text_lower:
                return key
    return None


def _format_curriculum_context(num: str, topic: dict) -> str:
    """Bentuk context string dari data curriculum untuk di-inject ke prompt Gemini."""
    status_map = {"live": "✅ Sudah dipublish", "scheduled": "📅 Terjadwal", "planned": "🔜 Belum dibuat"}
    status = topic.get("status", "planned")
    status_line = status_map.get(status, status)
    extra = ""
    if topic.get("scheduled_time"):
        extra = f" — pada {topic['scheduled_time']} WIB"
    elif topic.get("permalink"):
        extra = f" — link: {topic['permalink']}"

    lines = [f"--- KONTEN KURIKULUM #{num}: {topic.get('title', '')} ---"]
    lines.append(f"Status: {status_line}{extra}")
    if topic.get("display_name"):
        lines.append(f"Judul konten: {topic['display_name']}")
    if topic.get("subtitle"):
        lines.append(f"Subtitle: {topic['subtitle']}")
    if topic.get("caption"):
        lines.append(f"Caption posting:\n{topic['caption']}")
    if topic.get("keywords"):
        lines.append(f"Istilah kunci: {', '.join(topic['keywords'])}")
    if topic.get("permalink") and status == "live":
        lines.append(f"Link post: {topic['permalink']}")
    slides = topic.get("slides", [])
    if slides:
        lines.append("\nIsi slide carousel:")
        for s in slides:
            if s.get("type") == "cover":
                lines.append(f"- [Cover] {s.get('title')}: {s.get('subtitle')}")
            elif s.get("type") == "fact":
                lines.append(f"- Fakta {s['number']}: {s['title']} — {s['description']}")
    lines.append("---")
    return "\n".join(lines)


async def topics_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all curriculum topics with their C#XX codes."""
    try:
        cc = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
    except Exception:
        await update.message.reply_text("❌ Gagal baca source_of_truth.json")
        return
    topics = cc.get("topics", {})
    categories = cc.get("categories", {})
    lines = ["**📚 Kurikulum Aquarisamatiran**\n"]
    for sid in sorted(topics, key=int):
        sname = categories.get(sid, {}).get("title", f"Category {sid}")
        lines.append(f"**{sname}**")
        for tnum in sorted(topics[sid], key=int):
            t = topics[sid][tnum]
            st = t.get("status", "planned")
            emoji = {"live": "✅", "scheduled": "📅", "planned": "🔜"}.get(st, "❓")
            dn = t.get("display_name", t.get("title", "?"))
            jadwal = ""
            if st == "scheduled" and t.get("scheduled_time"):
                jadwal = f" — {t['scheduled_time']} WIB"
            ref = format_ref(cc, sid, tnum.zfill(2))
            lines.append(f"  {emoji} `{ref}` {dn}{jadwal}")
        lines.append("")
    lines.append("Contoh: `/generate {ref}`, `/post {ref}` — ganti {ref} pake kode di atas")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def slides_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List available slide groups in resource/photos/, split curriculum vs adhoc."""
    slides_dir = PHOTO_DIR
    if not slides_dir.is_dir():
        await update.message.reply_text("❌ Folder resource/photos/ gak ada.")
        return

    # Build slug → C{sid}#{tnum} mapping, ordered by curriculum
    slug_to_tag = {}
    cur_order = []  # (slug, tag) in curriculum order
    try:
        cc = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
        for sid in sorted(cc.get("topics", {}), key=int):
            for tnum in sorted(cc["topics"][sid], key=int):
                t = cc["topics"][sid][tnum]
                slug = (t.get("slug", "") or "").replace("-", "_")
                if slug:
                    tag = format_ref(cc, sid, tnum)
                    slug_to_tag[slug] = tag
                    cur_order.append((slug, tag))
    except Exception:
        pass

    # Scan photo dir
    groups = {}
    for f in slides_dir.glob("*"):
        if not f.is_file():
            continue
        stem = f.stem
        if "_sd_" in stem:
            prefix = stem.rsplit("_sd_", 1)[0]
        elif "_slide_" in stem:
            prefix = stem.rsplit("_slide_", 1)[0]
        else:
            continue
        groups.setdefault(prefix, []).append(f.name)

    if not groups:
        await update.message.reply_text("📂 Gak ada slide di resource/photos/.")
        return

    def _prefix_mtime(p):
        return max((Path(slides_dir / f).stat().st_mtime for f in groups[p]), default=0)

    cur_lines = []
    adhoc_groups = dict(groups)
    for slug, tag in cur_order:
        if slug not in groups:
            continue
        del adhoc_groups[slug]
        count = len(groups[slug])
        mtime = _prefix_mtime(slug)
        time_str = datetime.datetime.fromtimestamp(mtime).strftime("%d/%m %H:%M")
        cur_lines.append(f"  `{tag}` `{slug}` — {count} file ({time_str})")

    adhoc_lines = []
    for prefix in sorted(adhoc_groups, key=_prefix_mtime, reverse=True):
        count = len(adhoc_groups[prefix])
        mtime = _prefix_mtime(prefix)
        time_str = datetime.datetime.fromtimestamp(mtime).strftime("%d/%m %H:%M")
        adhoc_lines.append(f"  `{prefix}` — {count} file ({time_str})")

    lines = ["**📸 Slide siap post:**\n"]
    if cur_lines:
        lines.append("**📚 Curriculum:**")
        lines.extend(cur_lines)
        lines.append("")
    if adhoc_lines:
        lines.append("**🎨 Adhoc:**")
        lines.extend(adhoc_lines)
        lines.append("")
    lines.append(f"**Total: {sum(len(v) for v in groups.values())} file**")
    lines.append("Gunakan: `/post <slug>` atau `/post C1#XX`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def generate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate carousel with fact confirmation or fallback to direct dispatch."""
    if not GH_PAT:
        await update.message.reply_text("GH_PAT gak ada di .env, minta ke bebnya dulu~ 😏")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Contoh: `/generate #07` atau `/generate #07 7`\nCek `/topic` buat liat daftar #XX.")
        return
    num_facts = "8"
    topic_parts = []
    for a in args:
        if a.isdigit() and len(topic_parts) >= 1 and not topic_parts[-1].isdigit():
            num_facts = a
        else:
            topic_parts.append(a)
    topic = " ".join(topic_parts)
    if not topic:
        await update.message.reply_text("Topiknya mana sayang? 😏")
        return

    display_name, slug, topic_ref = _resolve_topic(topic)
    if display_name and slug:
        await update.message.reply_text(f"📋 Bikin fakta untuk \"{display_name}\" ({num_facts} fakta)...")
        try:
            facts_path = facts_cache_path(slug)
            if facts_path.exists():
                facts_path.unlink()
            facts = await asyncio.to_thread(generate_facts, display_name, int(num_facts), slug=slug)
            preview = _format_facts_preview(facts)
            await update.message.reply_text(
                f"📋 **Fakta untuk \"{display_name}\":**\n\n{preview}\n\nSetuju sama faktanya?",
                reply_markup=_fact_keyboard()
            )
            context.user_data["pending_facts"] = {
                "topic_display": display_name,
                "slug": slug,
                "num_facts": int(num_facts),
                "facts_data": facts,
                "topic_ref": topic_ref or topic,
            }
        except Exception as e:
            await update.message.reply_text(f"❌ Gagal generate fakta di VPS: {e}\nFallback ke GH Actions...")
            await _dispatch_workflow(topic, num_facts, False, update)
    else:
        await _dispatch_workflow(topic, num_facts, False, update)


def _latest_slides(topic_ref: str = "") -> tuple[str | None, list[Path]]:
    """Detect carousel slides in PHOTO_DIR. 
    If topic_ref given (e.g. C1.1#07 or C1#07), filter by topic slug.
    If it doesn't match tag format, treat as direct slug (e.g. puntius_denisonii)."""
    slides_dir = PHOTO_DIR
    if topic_ref:
        m = re.match(r'[CS](\d+)(?:\.(\d+))?#(\d+)', topic_ref)
        if m:
            cur_data = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
            s_num, sc, t_num = m.group(1), m.group(2) or "1", m.group(3).zfill(2)
            # If ref used per-subcategory seq (C1.1#03), resolve seq→dict_key
            if m.group(2):
                num_key = _seq_to_key(cur_data, s_num, sc, t_num)
            else:
                num_key = t_num
            topic = cur_data.get("topics", {}).get(s_num, {}).get(num_key, {}) if num_key else {}
            slug = (topic.get("slug", "") or "").replace("-", "_")
            if not slug:
                return None, []
        else:
            slug = topic_ref.replace("-", "_")
        sd = sorted(slides_dir.glob(f"{slug}_sd_*.png"))
        sd += sorted(slides_dir.glob(f"{slug}_sd_*.jpg"))
        if sd:
            return slug, sd
        legacy = sorted(slides_dir.glob(f"{slug}_slide_*.png"))
        legacy += sorted(slides_dir.glob(f"{slug}_slide_*.jpg"))
        if legacy:
            return slug, legacy
        return None, []

    slides = sorted(slides_dir.glob("*_slide_??.png"))
    slides += sorted(slides_dir.glob("edu_*_??.jpg"))
    slides += sorted(f for f in slides_dir.glob("*_sd_*.png") if not f.stem.endswith("_sd_bg"))
    slides += sorted(f for f in slides_dir.glob("*_sd_*.jpg") if not f.stem.endswith("_sd_bg"))
    if not slides:
        return None, []
    groups = {}
    for s in slides:
        stem = s.stem
        if "_slide_" in stem:
            prefix = stem.rsplit("_slide_", 1)[0]
        elif "_sd_" in stem:
            prefix = stem.rsplit("_sd_", 1)[0]
        else:
            prefix = stem.rsplit("_", 1)[0]
        if not prefix:
            continue
        groups.setdefault(prefix, []).append(s)
    if not groups:
        return None, []
    latest_prefix = max(groups, key=lambda k: max(groups[k], key=lambda f: f.stat().st_mtime).stat().st_mtime)
    return latest_prefix, sorted(groups[latest_prefix])


def _slug_to_topic(slug: str) -> str:
    """Convert slug to readable topic name for caption generation."""
    return slug.replace("_", " ").title()


def _resolve_topic(input_str: str) -> tuple[str | None, str | None, str | None]:
    """Resolve topic input to (display_name, slug, topic_ref).
    Returns (None, None, None) if unresolvable."""
    try:
        cc = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None, None, None
    topics = cc.get("topics", {})

    # New format: C{cat}.{subcat}#{seq}
    m = re.match(r'[CS](\d+)\.(\d+)#(\d+)', input_str)
    if m:
        sid, sc, seq = m.group(1), m.group(2), m.group(3).zfill(2)
        num_key = _seq_to_key(cc, sid, sc, seq)
        if num_key:
            t = topics.get(sid, {}).get(num_key, {})
            if t:
                slug = (t.get("slug", "") or "").replace("-", "_")
                ref = format_ref(cc, sid, num_key)
                return t.get("title") or t.get("display_name", input_str), slug or None, ref

    # Legacy format: C{cat}#{num}
    m = re.match(r'[CS](\d+)#(\d+)', input_str)
    if m:
        sid, tnum = m.group(1), m.group(2).zfill(2)
        t = topics.get(sid, {}).get(tnum, {})
        if t:
            slug = (t.get("slug", "") or "").replace("-", "_")
            ref = format_ref(cc, sid, tnum)
            return t.get("title") or t.get("display_name", input_str), slug or None, ref

    m = re.match(r'#(\d+)', input_str)
    if m:
        tnum = m.group(1).zfill(2)
        for sid in sorted(topics, key=int):
            t = topics[sid].get(tnum, {})
            if t:
                slug = (t.get("slug", "") or "").replace("-", "_")
                ref = format_ref(cc, sid, tnum)
                return t.get("title") or t.get("display_name", input_str), slug or None, ref

    input_lower = input_str.lower().replace(" ", "_")
    for sid in sorted(topics, key=int):
        for tnum in sorted(topics[sid], key=int):
            t = topics[sid][tnum]
            slug = (t.get("slug", "") or "")
            candidates = [t.get("title", "").lower(), t.get("display_name", "").lower(), slug.lower(), slug.replace("_", " ").lower()]
            if input_lower in candidates:
                ref = format_ref(cc, sid, tnum)
                return t.get("title") or t.get("display_name", input_str), slug.replace("-", "_") or None, ref

    return None, None, None


def _format_facts_preview(facts: dict) -> str:
    """Format facts dict into readable preview text."""
    lines = []
    for f in facts.get("facts", []):
        num = f.get("number", "?")
        title = f.get("title", "")
        desc = (f.get("description", "") or "")[:200]
        lines.append(f"**{num}. {title}**")
        if desc:
            lines.append(f"   {desc}")
        lines.append("")
    return "\n".join(lines)


def _fact_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("✅ Setuju, bikin slide", callback_data="fact:confirm")],
        [InlineKeyboardButton("🔄 Bikin Ulang", callback_data="fact:retry")],
        [InlineKeyboardButton("❌ Batal", callback_data="fact:cancel")],
    ]
    return InlineKeyboardMarkup(keyboard)


def _get_caption_from_curriculum(slug: str) -> str | None:
    """Cari caption existing di source_of_truth.json berdasarkan slug."""
    try:
        cc = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
        for s_num, ts in cc.get("topics", {}).items():
            for t_num, t in ts.items():
                if t.get("slug", "").replace("-", "_") == slug:
                    return t.get("caption") or None
    except Exception:
        pass
    return None


def _save_caption_to_curriculum(slug: str, caption: str):
    """Simpan caption ke source_of_truth.json."""
    try:
        cc = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
        for s_num, ts in cc.get("topics", {}).items():
            for t_num, t in ts.items():
                if t.get("slug", "").replace("-", "_") == slug:
                    t["caption"] = caption
                    CURRICULUM_PATH.write_text(json.dumps(cc, indent=2, ensure_ascii=False), encoding="utf-8")
                    return
    except Exception:
        pass


def _build_caption_from_facts(topic: str, facts_json: dict | None = None, handle: str = "@aquarisamatiran") -> str:
    """Build a caption locally from facts data (Gemini fallback)."""
    lines = [f"{topic} — Yuk belajar! 🐟"]
    if facts_json and "facts" in facts_json:
        for f in facts_json["facts"]:
            title = f.get("title", "")
            desc = f.get("description", "")[:120]
            if title and desc:
                lines.append(f"\n{title}")
                lines.append(desc)
            elif title:
                lines.append(f"\n{title}")
        lines.append(f"\nFollow {handle} untuk belajar aquarium dari nol! 🌱")
    return "\n".join(lines)


async def _generate_caption(facts_json: dict | None, topic: str) -> str:
    """Generate a caption using Gemini from facts data."""
    keys = [k for k in GEMINI_API_KEYS if k]

    # Load account config for dynamic persona
    config = {}
    try:
        config_path = PROJECT_ROOT / "accounts" / "aquarisamatiran" / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        pass

    niche = config.get("niche", "aquascape")
    handle = config.get("handle", "@aquarisamatiran")
    name = config.get("name", "Aquarisamatiran")
    tone = config.get("tone", "santai, edukatif, engaging, akrab — pake bahasa Indonesia sehari-hari")
    mission = config.get("mission", "ngajarin follower aquarium dari nol dengan cara yang asyik")

    if not keys:
        return _build_caption_from_facts(topic, facts_json, handle)

    system_text = (
        f"Kamu adalah alat pembuat caption Instagram untuk akun {handle}.\n"
        "Output HANYA caption — tanpa intro, tanpa penjelasan, tanpa markdown.\n"
        "Hashtag adalah BAGIAN dari caption, jangan dipisah.\n"
        f"Gaya bicara: {tone}.\n"
        "Beri informasi bermanfaat, ajak diskusi.\n"
        f"Tujuan: {mission}."
    )

    prompt_parts = [
        f"Buat caption Instagram dalam bahasa Indonesia untuk konten {niche} dengan topik: {topic}. Langsung mulai dengan teks caption — jangan pake kata pembuka."
    ]
    if facts_json and "facts" in facts_json:
        prompt_parts.append("\nFakta-fakta dalam konten ini:")
        for f in facts_json["facts"]:
            prompt_parts.append(f"- {f.get('number','')}. {f.get('title','')}: {f.get('description','')[:100]}")
    prompt_parts.append(
        f"\nInclude ajakan diskusi dan hashtag #{name} di akhir. "
        f"Maksimal 2200 karakter total. "
        f"Hashtag termasuk dalam hitungan karakter."
    )

    text = _today_context() + "\n\n" + system_text + "\n\n" + "\n".join(prompt_parts)

    for key in keys:
        for model in GEMINI_MODELS:
            for attempt in range(2):
                url = f"https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={key}"
                body = {"contents": [{"role": "user", "parts": [{"text": text}]}]}
                try:
                    resp = await HTTPX_CLIENT.post(url, json=body)
                except (httpx.TimeoutException, httpx.ReadTimeout) as e:
                    print(f"   ⚠️  Gemini {model} timeout: {e}")
                    continue
                if resp.status_code == 200:
                    caption = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                    if len(caption) > 2200:
                        truncated = caption[:2199]
                        last_period = truncated.rfind(".")
                        last_newline = truncated.rfind("\n")
                        cut = max(last_period, last_newline) + 1
                        if cut < 1100:
                            cut = 2199
                        caption = caption[:cut]
                    return caption
                print(f"   ⚠️  Gemini {model} (key?): HTTP {resp.status_code}")
                if resp.status_code in (429, 403):
                    break
    caption = _build_caption_from_facts(topic, facts_json, handle)
    if len(caption) > 2200:
        caption = caption[:2199]
    return caption


def _format_run(run: dict) -> str:
    """Format a GH Actions run into a status line."""
    status = run["status"]
    conclusion = run.get("conclusion") or "—"
    topic = run.get("display_title", "?")
    emoji = {"queued": "⏳", "in_progress": "🔄", "completed": {"success": "✅", "failure": "❌", "cancelled": "🚫"}.get(conclusion, "❓")}.get(status, "❓")
    created_utc = run["created_at"][:16].replace("T", " ")
    try:
        dt = datetime.datetime.strptime(created_utc, "%Y-%m-%d %H:%M") + datetime.timedelta(hours=7)
        created_wib = dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        created_wib = created_utc
    return (
        f"{emoji} **{topic}**\n"
        f"   Status: **{status}** ({conclusion})\n"
        f"   Dibuat: {created_wib} WIB\n"
        f"   [Lihat di GitHub]({run['html_url']})"
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check latest GH Actions runs (generate + clean) + running workflows with cancel."""
    if not GH_PAT:
        await update.message.reply_text("GH_PAT gak ada, gak bisa cek~ 😏")
        return
    workflow_ids = {
        "Generate": "295601892",
        "Clean": "297980876",
    }
    lines = ["📊 **Status Workflows**"]
    cancel_buttons = []
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            for label, wf_id in workflow_ids.items():
                resp = await client.get(
                    f"{GH_API}/repos/{GH_REPO}/actions/workflows/{wf_id}/runs?per_page=1",
                    headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {GH_PAT}"},
                )
                if resp.status_code == 200:
                    runs = resp.json().get("workflow_runs", [])
                    if runs:
                        run = runs[0]
                        lines.append(f"\n{label}:")
                        lines.append(_format_run(run))
                        if run["status"] in ("in_progress", "queued"):
                            cancel_buttons.append(
                                InlineKeyboardButton(f"❌ Cancel {label}", callback_data=f"cancel:wf:{run['id']}")
                            )
                    else:
                        lines.append(f"\n{label}: — (belum pernah jalan)")
                else:
                    lines.append(f"\n{label}: ❌ HTTP {resp.status_code}")

        reply = "\n".join(lines)
        if cancel_buttons:
            rows = [cancel_buttons[i:i+2] for i in range(0, len(cancel_buttons), 2)]
            await update.message.reply_text(reply, reply_markup=InlineKeyboardMarkup(rows), disable_web_page_preview=True)
        else:
            await update.message.reply_text(reply, disable_web_page_preview=True)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def post_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Upload slides + schedule carousel. Smart auto-detect + auto-caption."""
    args = context.args
    topic_ref = ""
    schedule_time = ""
    # Parse args: /post [slug/C1#07/C1.1#01] [Kamis 19:00]
    for a in args:
        if a.startswith("#") or re.match(r"[CS]\d+(?:\.\d+)?#\d+", a):
            topic_ref = a
        elif re.match(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun|Senin|Selasa|Rabu|Kamis|Jumat|Sabtu|Minggu)", a, re.IGNORECASE) and len(args) > args.index(a) + 1:
            idx = list(args).index(a)
            schedule_time = f"{a} {args[idx+1]}"
        elif not topic_ref:
            topic_ref = a  # treat as direct slug

    # Auto-detect latest slides (filter by topic_ref if given)
    slug, slides = _latest_slides(topic_ref)
    if not slug:
        if topic_ref:
            display_name, _, _ = _resolve_topic(topic_ref)
            if display_name:
                await update.message.reply_text(
                    f"❌ Gak nemu slide buat {topic_ref}\n"
                    f"Coba `/generate {topic_ref}` dulu buat bikin slide-nya~"
                )
            else:
                await update.message.reply_text(f"❌ Gak kenal `{topic_ref}` dan gak ada slide dengan nama itu")
        else:
            await update.message.reply_text("❌ Gak ada slide carousel di resource/photos/")
        return

    # Sync source_of_truth dari repo sebelum baca data
    subprocess.run(
        ["git", "pull", "--rebase", "origin", "main"],
        cwd=PROJECT_ROOT, capture_output=True, timeout=30,
    )

    if not topic_ref:
        cc = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
        for s_num, ts in cc.get("topics", {}).items():
            for t_num, t in ts.items():
                if t.get("slug", "").replace("-", "_") == slug:
                    topic_ref = format_ref(cc, s_num, t_num)
                    break
            if topic_ref:
                break
    # Cek kalo udah live atau scheduled
    if topic_ref:
        cc = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
        m = re.match(r"[CS](\d+)(?:\.(\d+))?#(\d+)", topic_ref)
        if m:
            s_num, t_num = m.group(1), m.group(3).zfill(2)
            t = cc.get("topics", {}).get(s_num, {}).get(t_num, {})
            st = t.get("status")
            if st == "live":
                await update.message.reply_text(f"❌ `{topic_ref}` udah live, gak bisa dipost lagi~")
                return
            if st == "scheduled":
                await update.message.reply_text(f"❌ `{topic_ref}` udah terjadwal, gak perlu dipost ulang~")
                return

    if len(slides) > 10:
        await update.message.reply_text(f"❌ IG carousel maksimal 10 slide, ini ada {len(slides)} (cover + fakta + CTA). Generate ulang pake lebih dikit fakta ya~")
        return

    # Determine schedule time — skip slot yang udah diambil
    if not schedule_time:
        occupied = set()
        try:
            existing = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
            for e in existing:
                if e.get("done") is False and e.get("time"):
                    occupied.add(e["time"])
        except Exception:
            pass
        occurrences = SLOT_MANAGER.next_occurrences(14, occupied=occupied)
        if not occurrences:
            await update.message.reply_text("❌ Semua slot penuh, coba lain waktu~")
            return
        keyboard = []
        row = []
        for i, o in enumerate(occurrences):
            row.append(InlineKeyboardButton(o["label"], callback_data=f"slot:{o['iso']}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        display_name = _slug_to_topic(slug)
        title_from_ref = _topic_title_from_ref(topic_ref or "")
        if title_from_ref:
            display_name = title_from_ref
        user_id = update.effective_user.id
        _pending_posts[user_id] = {
            "slug": slug,
            "slides": slides,
            "topic_ref": topic_ref,
            "status": "awaiting_slot",
        }
        await update.message.reply_text(
            f"🔍 \"{display_name}\" ({len(slides)} slide)\n\n📅 **Pilih jadwal:**",
            reply_markup=reply_markup,
        )
        return

    await update.message.reply_text(f"🔍 Detected: \"{slug}\" ({len(slides)} slide)\n📅 Jadwal: {schedule_time}")

    # Kirim preview slides
    await update.message.reply_text(f"📸 Kirim preview slide...")
    media_group = []
    for s in sorted(slides):
        if len(media_group) >= 10:
            break
        try:
            with open(s, "rb") as f:
                media_group.append(InputMediaPhoto(media=f.read()))
        except Exception:
            continue
    if media_group:
        try:
            await asyncio.wait_for(update.message.reply_media_group(media_group), timeout=30)
        except asyncio.TimeoutError:
            await update.message.reply_text("⚠️ Preview upload timeout, lanjut aja~")
        except Exception:
            await update.message.reply_text("⚠️ Gagal kirim preview, lanjut aja~")

    # Generate caption — cek dulu apakah udah ada di source_of_truth
    topic_display = _slug_to_topic(slug)
    title_from_ref = _topic_title_from_ref(topic_ref or "")
    if title_from_ref:
        topic_display = title_from_ref
    facts_json = None
    existing_caption = _get_caption_from_curriculum(slug)
    if existing_caption:
        await update.message.reply_text(f"💡 Caption udah ada, pake yang lama~")
        caption = existing_caption
    else:
        facts_path = facts_cache_path(slug)
        if facts_path.exists():
            try:
                facts_json = json.loads(facts_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        await update.message.reply_text(f"💬 Generate caption buat \"{topic_display}\"...")
        try:
            caption = await asyncio.wait_for(_generate_caption(facts_json, topic_display), timeout=60)
        except asyncio.TimeoutError:
            _cfg = {}
            try:
                _cfg = json.loads((PROJECT_ROOT / "accounts" / "aquarisamatiran" / "config.json").read_text(encoding="utf-8"))
            except Exception:
                pass
            _name = _cfg.get("name", "Aquarisamatiran")
            _handle = _cfg.get("handle", "@aquarisamatiran")
            caption = f"{topic_display} — Yuk belajar bareng {_handle}! 🌱 #{_name} #AquascapeIndonesia"
            await update.message.reply_text("⚠️ Caption generation timeout, pakai fallback~")
        _save_caption_to_curriculum(slug, caption)

    # Preview + confirm
    msg = (
        f"📋 **{topic_display}** ({len(slides)} slide)\n"
        f"📅 Jadwal: {schedule_time}\n\n"
        f"📝 **Caption (full):**\n{caption[:4000]}\n\n"
        f"`/post confirm` → upload & jadwal\n"
        f"`/post confirm --now` → publish langsung sekarang\n"
        f"`/post caption <instruksi>` → ganti caption\n"
        f"`/generate --force` → generate ulang slide\n"
        f"`/post cancel` → batalin"
    )
    await update.message.reply_text(msg)

    # Save pending
    user_id = update.effective_user.id
    _pending_posts[user_id] = {
        "slug": slug,
        "caption": caption,
        "schedule_time": schedule_time,
        "topic_display": topic_display,
        "facts_json": facts_json,
        "topic_ref": topic_ref,
    }


async def peekcaption_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Lihat caption topik tanpa trigger post flow."""
    args = context.args
    if not args:
        await update.message.reply_text("Contoh: `/post caption show C1.1#07`")
        return
    topic_input = " ".join(args)
    display_name, slug, topic_ref = _resolve_topic(topic_input)
    if not topic_ref:
        await update.message.reply_text(f"❌ `{topic_input}` gak dikenal sebagai topik")
        return
    label = topic_ref
    caption = _get_caption_from_curriculum(slug)
    if caption:
        await update.message.reply_text(f"📝 **Caption buat {label}:**\n\n{caption[:3500]}")
    else:
        await update.message.reply_text(f"📝 Belum ada caption buat {label}. Coba `/generate {label}` dulu~")


async def showtopic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tampilkan semua field topic dari curriculum."""
    args = context.args
    if not args:
        await update.message.reply_text("Contoh: `/topic show C1.1#07`")
        return
    topic_input = " ".join(args)
    display_name, slug, topic_ref = _resolve_topic(topic_input)
    if not topic_ref:
        await update.message.reply_text(f"❌ `{topic_input}` gak dikenal sebagai topik")
        return
    topics = _load_curriculum()
    topic = topics.get(topic_ref)
    if not topic:
        await update.message.reply_text(f"❌ {topic_ref} gak ditemukan di curriculum")
        return
    lines = [f"**📋 {topic_ref}:**"]
    for key in ("title", "slug", "status", "subcategory", "display_name", "subtitle", "scheduled_time", "permalink", "result_id", "keywords"):
        val = topic.get(key)
        if val is not None:
            val_str = ", ".join(val) if isinstance(val, list) else str(val)
            lines.append(f"  `{key}`: {val_str}")
    if topic.get("slides"):
        lines.append(f"  `slides`: {len(topic['slides'])} file(s)")
    await update.message.reply_text("\n".join(lines) or "ℹ️ Topic kosong")


async def editcaption_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if not args:
        await update.message.reply_text(
            "Gunakan:\n"
            "`/post caption <instruksi>` — edit caption pending post\n"
            "`/post caption C1#XX <instruksi>` — edit caption topik tertentu"
        )
        return

    is_pending_mode = False
    pending = None

    display_name, slug, topic_ref = _resolve_topic(args[0])

    if not topic_ref:
        user_id = update.effective_user.id
        pending = _pending_posts.get(user_id)
        if not pending:
            await update.message.reply_text(
                "Ngga ada pending post. Coba:\n"
                "`/post` dulu buat pending, atau\n"
                "`/post caption C1#XX <instruksi>` langsung ke topik"
            )
            return
        is_pending_mode = True
        slug = pending["slug"]
        topic_ref = pending.get("topic_ref", slug.replace("_", "-"))

    if is_pending_mode:
        instruction = " ".join(args)
    else:
        if len(args) < 2:
            await update.message.reply_text(f"Instruksinya mana sayang? Contoh: `/post caption {topic_ref} bikin lebih santai`")
            return
        instruction = " ".join(args[1:])

    await update.message.reply_text(f"💬 Edit caption buat {topic_ref}: \"{instruction}\"...")

    existing_caption = _get_caption_from_curriculum(slug)
    facts_path = facts_cache_path(slug)
    facts_json = None
    if facts_path.exists():
        try:
            facts_json = json.loads(facts_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    config = {}
    try:
        config_path = PROJECT_ROOT / "accounts" / "aquarisamatiran" / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        pass
    niche = config.get("niche", "aquascape")
    handle = config.get("handle", "@aquarisamatiran")
    name = config.get("name", "Aquarisamatiran")

    caption_system = (
        f"Kamu adalah alat pembuat caption Instagram untuk akun {niche} {handle}. "
        "Tugasmu: OUTPUT HANYA CAPTION — tanpa penjelasan, tanpa intro, tanpa 'tentu', tanpa markdown berlebih. "
        "Gaya: santai, edukatif, engaging, akrab, bahasa Indonesia sehari-hari. "
        "Maksimal 1800 karakter."
    )

    context_lines = [
        f"Edit caption sesuai instruksi ini: {instruction}",
        "Output: HANYA caption yang sudah diedit, TANPA teks tambahan apapun.",
    ]
    if existing_caption:
        context_lines.append(f"\nCaption lama:\n{existing_caption[:1500]}")
    elif facts_json and "facts" in facts_json:
        context_lines.append("\nFakta dalam konten:")
        for f in facts_json["facts"]:
            context_lines.append(f"- {f.get('number','')}. {f.get('title','')}: {f.get('description','')[:100]}")
    else:
        context_lines.append("\n(Tidak ada caption atau fakta sebelumnya)")

    messages = [{"role": "user", "parts": [{"text": "\n".join(context_lines)}]}]
    try:
        new_caption = await _call_gemini(messages, system=caption_system)
        _save_caption_to_curriculum(slug, new_caption)
        if is_pending_mode:
            pending["caption"] = new_caption
        await update.message.reply_text(f"✅ Caption buat {topic_ref} diupdate:\n\n{new_caption[:3500]}")
    except Exception as e:
        await update.message.reply_text(
            "⚠️ Gemini sibuk, caption gak berubah.\n\n"
            f"Tapi caption bakal dipotong otomatis pas post. "
            f"Langsung aja `/post confirm --now` kalo mau publish~"
        )


async def _dispatch_workflow(topic: str, num_facts: str, force: bool, update: Update):
    """Direct dispatch to GH Actions generate workflow (fallback)."""
    await update.message.reply_text(f"⚙️ Trigger generate \"{topic}\" ({num_facts} fakta, force={force}) di GH Actions...")
    try:
        body = json.dumps({"ref": "main", "inputs": {"topic": topic, "num_facts": num_facts, "force": str(force).lower()}})
        headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {GH_PAT}", "Content-Type": "application/json"}
        resp = await HTTPX_CLIENT.post(f"{GH_API}/repos/{GH_REPO}/actions/workflows/295601892/dispatches", content=body, headers=headers)
        if resp.status_code == 204:
            await update.message.reply_text(f"✅ Generate \"{topic}\" berhasil ditrigger! 🎉\nTunggu 10-30 menit, cek progress pake /status")
        else:
            await update.message.reply_text(f"❌ Gagal: HTTP {resp.status_code}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def regenerate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pending = _pending_posts.get(user_id)
    if not pending:
        await update.message.reply_text("Ngga ada pending post. Coba `/post` dulu~")
        return
    force = "--force" in (context.args or [])
    topic_display = pending["topic_display"]
    topic_ref = pending.get("topic_ref", "")
    slug = pending["slug"]
    if not topic_ref:
        try:
            cc = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
            for s_num, ts in cc.get("topics", {}).items():
                for t_num, t in ts.items():
                    if t.get("slug", "").replace("-", "_") == slug:
                        topic_ref = format_ref(cc, s_num, t_num)
                        break
                if topic_ref:
                    break
        except Exception:
            pass
    topic_input = topic_ref if topic_ref else slug.replace("_", " ")

    if force and topic_ref:
        await update.message.reply_text(f"📋 Bikin fakta baru untuk \"{topic_display}\"...")
        try:
            facts_path = facts_cache_path(slug)
            if facts_path.exists():
                facts_path.unlink()
            facts = await asyncio.to_thread(generate_facts, topic_display, 8, slug=slug)
            preview = _format_facts_preview(facts)
            await update.message.reply_text(
                f"📋 **Fakta baru untuk \"{topic_display}\":**\n\n{preview}\n\nSetuju sama faktanya?",
                reply_markup=_fact_keyboard()
            )
            context.user_data["pending_facts"] = {
                "topic_display": topic_display,
                "slug": slug,
                "num_facts": 8,
                "facts_data": facts,
                "topic_ref": topic_ref,
            }
        except Exception as e:
            await update.message.reply_text(f"❌ Gagal generate fakta di VPS: {e}\nFallback ke GH Actions...")
            await _dispatch_workflow(topic_input, "8", True, update)
    else:
        label = " (force — fakta baru)" if force else " (slides aja)"
        await update.message.reply_text(f"🔄 Generate ulang carousel \"{topic_display}\"{label}...")
        _pending_posts.pop(user_id, None)
        await _dispatch_workflow(topic_input, "8", force, update)


async def slot_pick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    iso_time = data.split(":", 1)[1]

    user_id = update.effective_user.id
    pending = _pending_posts.get(user_id)
    if not pending or pending.get("status") != "awaiting_slot":
        await query.edit_message_text("❌ Sesi kedaluarsa, ketik /post lagi~")
        return

    slug = pending["slug"]
    slides = pending["slides"]
    topic_ref = pending.get("topic_ref")

    dt = datetime.datetime.strptime(iso_time, "%Y-%m-%d %H:%M")
    day_name = DAYS_ID[dt.weekday()]
    time_str = dt.strftime("%H:%M")
    schedule_time = f"{day_name} {time_str}"

    await query.edit_message_text(f"📅 **{schedule_time}** — dipilih! 💬")

    # Kirim preview slides
    await context.bot.send_message(chat_id=update.effective_chat.id, text="📸 Preview slide...")
    media_group = []
    for s in sorted(slides):
        if len(media_group) >= 10:
            break
        try:
            with open(s, "rb") as f:
                media_group.append(InputMediaPhoto(media=f.read()))
        except Exception:
            continue
    if media_group:
        try:
            await asyncio.wait_for(query.message.reply_media_group(media_group), timeout=30)
        except asyncio.TimeoutError:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Preview upload timeout, lanjut aja~")
        except Exception:
            await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Gagal kirim preview, lanjut aja~")

    # Generate caption
    topic_display = _slug_to_topic(slug)
    title_from_ref = _topic_title_from_ref(topic_ref or "")
    if title_from_ref:
        topic_display = title_from_ref
    facts_json = None
    existing_caption = _get_caption_from_curriculum(slug)
    if existing_caption:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="💡 Caption udah ada, pake yang lama~")
        caption = existing_caption
    else:
        facts_path = facts_cache_path(slug)
        if facts_path.exists():
            try:
                facts_json = json.loads(facts_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"💬 Generate caption buat \"{topic_display}\"...")
        try:
            caption = await asyncio.wait_for(_generate_caption(facts_json, topic_display), timeout=60)
        except asyncio.TimeoutError:
            _cfg = {}
            try:
                _cfg = json.loads((PROJECT_ROOT / "accounts" / "aquarisamatiran" / "config.json").read_text(encoding="utf-8"))
            except Exception:
                pass
            _name = _cfg.get("name", "Aquarisamatiran")
            _handle = _cfg.get("handle", "@aquarisamatiran")
            caption = f"{topic_display} — Yuk belajar bareng {_handle}! 🌱 #{_name} #AquascapeIndonesia"
            await context.bot.send_message(chat_id=update.effective_chat.id, text="⚠️ Caption generation timeout, pakai fallback~")
        _save_caption_to_curriculum(slug, caption)

    # Preview + confirm
    msg = (
        f"📋 **{topic_display}** ({len(slides)} slide)\n"
        f"📅 Jadwal: {schedule_time}\n\n"
        f"📝 **Caption (full):**\n{caption[:4000]}\n\n"
        f"`/post confirm` → upload & jadwal\n"
        f"`/post confirm --now` → publish langsung sekarang\n"
        f"`/post caption <instruksi>` → ganti caption\n"
        f"`/generate --force` → generate ulang slide\n"
        f"`/post cancel` → batalin"
    )
    await context.bot.send_message(chat_id=update.effective_chat.id, text=msg)

    # Save full pending state
    _pending_posts[user_id] = {
        "slug": slug,
        "caption": caption,
        "schedule_time": schedule_time,
        "schedule_time_iso": iso_time,
        "topic_display": topic_display,
        "facts_json": facts_json,
        "topic_ref": topic_ref,
    }


async def confirm_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pending = _pending_posts.get(user_id)
    if not pending:
        await update.message.reply_text("Ngga ada pending post. Coba `/post` dulu~")
        return
    if pending.get("status") == "awaiting_slot":
        await update.message.reply_text("Pilih jadwal dulu dari tombol di atas, sayang~ 😏")
        return
    _pending_posts.pop(user_id)
    

    slug = pending["slug"]
    caption = pending["caption"]

    now = "--now" in (context.args or [])
    if now:
        await update.message.reply_text(f"📤 Publish langsung \"{slug}\"...")
        proc_args = [sys.executable, "main.py", "post-carousel", "--slug", slug, caption]
    else:
        schedule_time = pending.get("schedule_time_iso") or pending["schedule_time"]
        await update.message.reply_text(f"📤 Upload & jadwalin \"{slug}\"...")
        proc_args = [sys.executable, "main.py", "post-carousel", "--slug", slug, "--schedule", "cron", schedule_time, caption]

    try:
        result = subprocess.run(proc_args, capture_output=True, text=True, timeout=300, cwd=str(PROJECT_ROOT))
        out = (result.stdout or "") + (result.stderr or "")
        out = out.strip()[-3000:]
        status = "✅" if result.returncode == 0 else "❌"
        await update.message.reply_text(f"{status} Result:\n```\n{out}\n```")
    except subprocess.TimeoutExpired:
        await update.message.reply_text("⏳ Kelamaan (>5 menit). Kalo gagal, tinggal `/post` lagi — slide yang udah keupload bakal di-skip dari cache~")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}\n\nTinggal `/post {slug}` lagi — slide yang udah keupload bakal di-skip dari cache")


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    _pending_posts.pop(user_id, None)
    await update.message.reply_text("Oke, pending post dibatalin~ Mau `/post` lagi? 😏")


async def clean_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hapus slide yang gak jadi dipost via GH Actions clean.yml."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "Gunakan: `/post clean <slug>` atau `/post clean C1.1#XX`\n"
            "Cek `/topic slides` buat liat slug yang tersedia."
        )
        return

    raw = args[0]
    slug = ""
    m = re.match(r'[CS](\d+)(?:\.(\d+))?#(\d+)', raw)
    if m:
        try:
            cc = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
            sid, sc, seq = m.group(1), m.group(2) or "1", m.group(3).zfill(2)
            num_key = _seq_to_key(cc, sid, sc, seq) if m.group(2) else seq
            if not num_key:
                await update.message.reply_text("❌ Topic gak ditemukan di source_of_truth.")
                return
            topic = cc.get("topics", {}).get(sid, {}).get(num_key, {})
            if not topic:
                await update.message.reply_text("❌ Topic gak ditemukan di source_of_truth.")
                return
            if topic.get("status") == "live":
                await update.message.reply_text("❌ Topic udah live (udah dipost). Gak bisa di-clean.")
                return
            slug = (topic.get("slug", "") or "").replace("-", "_")
            if not slug:
                await update.message.reply_text("❌ Topic gak punya slug.")
                return
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {e}")
            return
    else:
        slug = raw.replace("-", "_")
        try:
            cc = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
            for sid, ts in cc.get("topics", {}).items():
                for num, t in ts.items():
                    if t.get("slug", "").replace("-", "_") == slug and t.get("status") == "live":
                        await update.message.reply_text("❌ Topic udah live. Gak bisa di-clean.")
                        return
        except Exception:
            pass

    slides_dir = PHOTO_DIR
    slide_files = list(slides_dir.glob(f"{slug}_sd_*"))
    slide_files += list(slides_dir.glob(f"{slug}_slide_*"))
    edu_files = []
    # Match both curriculum-slug and topic-name-derived cache filenames
    for pattern in [f"edu_{slug[:20]}*"]:
        edu_files.extend(slides_dir.glob(pattern))
    # Also check topic-name-derived path if we have a curriculum ref
    try:
        cc = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
        for sid, ts in cc.get("topics", {}).items():
            for num, t in ts.items():
                if t.get("slug", "").replace("-", "_") == slug:
                    title = t.get("title") or t.get("display_name")
                    if title:
                        edu_files.extend(slides_dir.glob(f"edu_{facts_cache_path(title).stem}*"))
    except Exception:
        pass
    if not slide_files and not edu_files:
        await update.message.reply_text(f"❌ Gak nemu file dengan prefix `{slug}` di resource/photos/")
        return

    if not GH_PAT:
        await update.message.reply_text("GH_PAT gak ada di .env, minta ke bebnya dulu~ 😏")
        return

    try:
        body = json.dumps({"ref": "main", "inputs": {"slug": slug}})
        headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {GH_PAT}"}
        resp = await HTTPX_CLIENT.post(
            "https://api.github.com/repos/imtopp/aquarisamatiranIG/actions/workflows/clean.yml/dispatches",
            content=body, headers=headers,
        )
        if resp.status_code == 204:
            parts = []
            if slide_files:
                parts.append(f"{len(slide_files)} slide")
            if edu_files:
                parts.append(f"{len(edu_files)} data fakta")
            total = len(slide_files) + len(edu_files)
            detail = " + ".join(parts)
            await update.message.reply_text(
                f"🗑️ Clean trigger buat `{slug}`! {total} file ({detail}) bakal dihapus.\n"
                "Proses ~2 menit, cek `/status` nanti ya~"
            )
        else:
            await update.message.reply_text(f"❌ Gagal trigger: HTTP {resp.status_code}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(f"Chat ID kamu: `{uid}`", parse_mode="Markdown")


def _day_keyboard(selected: set[int]) -> InlineKeyboardMarkup:
    keyboard = []
    row = []
    for i, d in enumerate(DAYS_ID):
        prefix = "✅ " if i in selected else "⬜ "
        row.append(InlineKeyboardButton(f"{prefix}{d}", callback_data=f"wiz:day:{i}"))
        if i in (2, 5):
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("✅ Selesai milih hari", callback_data="wiz:days_done")])
    return InlineKeyboardMarkup(keyboard)


def _confirm_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("✅ Ya, simpan", callback_data="wiz:confirm")],
        [InlineKeyboardButton("❌ Batal", callback_data="wiz:cancel")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def addcategory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tambah category baru via Telegram."""
    args = context.args or []
    if not args:
        await update.message.reply_text("Contoh: `/topic cat add Nama Category`")
        return
    title = " ".join(args)
    result = telegram_add_category(title)
    await update.message.reply_text(result)


async def addsubcategory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tambah subcategory ke category tertentu."""
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Contoh: `/topic cat sub add C2 1 Nama Subkategori`")
        return
    cat_id = args[0].lstrip("C")
    number = args[1]
    label = " ".join(args[2:]) if len(args) > 2 else ""
    result = telegram_add_subcategory(cat_id, number, label)
    await update.message.reply_text(result)


async def addtopic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tambah topic ke category/subcategory."""
    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text("Contoh: `/topic add C2 1 Judul Topik Disini`")
        return
    cat_id = args[0].lstrip("C")
    subcat = args[1]
    title = " ".join(args[2:]) if len(args) > 2 else ""
    result = telegram_add_topic(cat_id, subcat, title)
    await update.message.reply_text(result)


async def edittopic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Edit topic fields via Telegram. Format: /topic edit C1.1#07 --title Nama --status live"""
    args = context.args or []
    if len(args) < 1:
        await update.message.reply_text("Contoh: `/topic edit C1.1#07 --status live`\nField: title, slug, status, subcategory, display_name, subtitle, keywords")
        return
    topic_ref = args[0]
    if not re.match(r'[CS]\d+(?:\.\d+)?#\d+', topic_ref):
        await update.message.reply_text(f"❌ Format salah. Contoh: `/topic edit C1.1#07 --status live`")
        return
    fields = {}
    i = 1
    while i < len(args):
        if args[i].startswith("--"):
            field_name = args[i][2:]
            i += 1
            vals = []
            while i < len(args) and not args[i].startswith("--"):
                vals.append(args[i])
                i += 1
            fields[field_name] = " ".join(vals)
        else:
            i += 1
    result = telegram_edit_topic(topic_ref, **fields)
    await update.message.reply_text(result)


async def deletetopic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hapus topic via Telegram."""
    args = context.args or []
    if not args:
        await update.message.reply_text("Contoh: `/topic delete C1.1#07`")
        return
    topic_ref = args[0]
    result = telegram_delete_topic(topic_ref)
    await update.message.reply_text(result)


async def movetopic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Pindah topic ke category/subcategory lain."""
    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text("Contoh: `/topic move C1.1#07 C2 2`")
        return
    topic_ref = args[0]
    target_cat = args[1].lstrip("C")
    target_sc = args[2]
    result = telegram_move_topic(topic_ref, target_cat, target_sc)
    await update.message.reply_text(result)


async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sched = _read_schedule()
    if sched:
        reply = f"{sched}\n\nAda yang mau ditanyain lagi, beb? 😏"
        await update.message.reply_text(reply)
    else:
        await update.message.reply_text("❌ `schedule.json` gak bisa dibaca atau kosong.")


async def delete_schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hapus entry dari schedule.json."""
    args = context.args
    if not args:
        await update.message.reply_text("Contoh: `/schedule delete C1.1#07`")
        return

    topic_input = args[0]
    _, _, topic_ref = _resolve_topic(topic_input)
    if not topic_ref:
        await update.message.reply_text(f"❌ Topik `{topic_input}` gak dikenal")
        return

    try:
        schedule = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
    except Exception:
        await update.message.reply_text("❌ Gagal baca schedule.json")
        return

    found = None
    for i, entry in enumerate(schedule):
        ref = entry.get("source_ref") or entry.get("curriculum", "")
        if ref == topic_ref:
            found = i
            break

    if found is None:
        await update.message.reply_text(f"❌ Gak ada jadwal buat {topic_ref}")
        return

    entry = schedule[found]
    if entry.get("done"):
        await update.message.reply_text(f"❌ {topic_ref} udah live, gak bisa dihapus jadwalnya")
        return

    del schedule[found]
    SCHEDULE_PATH.write_text(json.dumps(schedule, indent=2, ensure_ascii=False), encoding="utf-8")
    # Reset status di curriculum biar bisa /post lagi
    _reset_topic_status(topic_ref, "generated")
    await update.message.reply_text(f"✅ Jadwal {topic_ref} dihapus dari antrian. Status di-reset ke 'generated'. Bisa `/post {topic_ref}` lagi~")


async def setslot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        slots_str = SLOT_MANAGER.format_list()
        await update.message.reply_text(f"📅 **Slot Jadwal Saat Ini:**\n{slots_str}\n\nGunakan:\n`/schedule slot add` — tambah slot interaktif\n`/schedule slot remove <id>`\n`/schedule slot sync`", parse_mode="Markdown")
        return

    cmd = args[0].lower()

    if cmd == "add":
        context.user_data["wizard"] = {"step": "id"}
        await update.message.reply_text("📝 **Id slotnya?** (huruf, angka, strip `-`, underscore `_` aja, gak boleh spasi)\nContoh: `weekend-09`, `weekday-19`, `lunch-12`", parse_mode="Markdown")
    elif cmd == "remove":
        if len(args) < 2:
            await update.message.reply_text("Pake: `/schedule slot remove <id>`")
            return
        ok = SLOT_MANAGER.remove_slot(args[1])
        if ok:
            await update.message.reply_text(f"✅ Slot `{args[1]}` dihapus")
            sync_msg = await update.message.reply_text("🔄 Auto-sync ke cron-job.org...")
            result = await SLOT_MANAGER.sync_cronjob()
            await sync_msg.edit_text(f"📋 Sync selesai:\n{result}")
        else:
            await update.message.reply_text(f"❌ Slot `{args[1]}` gak ketemu")
    elif cmd == "sync":
        await update.message.reply_text("🔄 Sync slot ke cron-job.org...")
        result = await SLOT_MANAGER.sync_cronjob()
        await update.message.reply_text(f"📋 Hasil sync:\n{result}")
    else:
        await update.message.reply_text(f"❌ Subcommand `{cmd}` gak dikenal. Pake: add, remove, sync")


async def wizard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "wiz:cancel":
        context.user_data.pop("wizard", None)
        await query.edit_message_text("❌ Wizard dibatalin.")
        return

    if data.startswith("wiz:day:"):
        wiz = context.user_data.get("wizard")
        if not wiz or wiz["step"] != "days":
            return
        day_idx = int(data.split(":")[2])
        if day_idx in wiz["selected_days"]:
            wiz["selected_days"].discard(day_idx)
        else:
            wiz["selected_days"].add(day_idx)
        await query.edit_message_reply_markup(reply_markup=_day_keyboard(wiz["selected_days"]))
        return

    if data == "wiz:days_done":
        wiz = context.user_data.get("wizard")
        if not wiz or wiz["step"] != "days":
            return
        if not wiz["selected_days"]:
            await query.edit_message_text("Pilih minimal 1 hari dulu, sayang~ 🫣")
            await query.edit_message_reply_markup(reply_markup=_day_keyboard(wiz["selected_days"]))
            return
        wiz["step"] = "time"
        wiz["days_msg"] = ", ".join(sorted(DAYS_ID[d] for d in wiz["selected_days"]))
        await query.edit_message_text(f"✅ Hari: {wiz['days_msg']}\n\n⏰ **Jam berapa?** (HH:MM format, contoh: `19:00`)", parse_mode="Markdown")
        return

    if data == "wiz:confirm":
        wiz = context.user_data.pop("wizard", None)
        if not wiz:
            return
        sid = wiz["sid"]
        days_list = sorted(wiz["selected_days"])
        time_str = wiz["time"]

        ok = SLOT_MANAGER.add_slot(sid, days_list, time_str)
        if not ok:
            await query.edit_message_text(f"❌ Slot `{sid}` udah ada.")
            return
        await query.edit_message_text(f"✅ Slot `{sid}` disimpan!\n🔄 Auto-sync ke cron-job.org...")
        result = await SLOT_MANAGER.sync_cronjob()
        await query.edit_message_text(f"✅ Slot `{sid}` disimpan!\n📋 Sync selesai:\n{result}")
        return


async def fact_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle fact confirmation (setuju / bikin ulang / batal)."""
    query = update.callback_query
    await query.answer()
    data = query.data
    pending = context.user_data.get("pending_facts")

    if not pending:
        await query.edit_message_text("❌ Sesi kadaluarsa, ketik /generate lagi~")
        return

    if data == "fact:cancel":
        context.user_data.pop("pending_facts", None)
        await query.edit_message_text("Oke, dibatalin~ 🫣")
        return

    if data == "fact:retry":
        await query.edit_message_text("🔄 Bikin ulang fakta...")
        try:
            facts_path = facts_cache_path(pending["slug"])
            if facts_path.exists():
                facts_path.unlink()
            new_facts = await asyncio.to_thread(generate_facts, pending["topic_display"], pending["num_facts"], slug=pending["slug"])
            pending["facts_data"] = new_facts
            preview = _format_facts_preview(new_facts)
            await query.edit_message_text(
                f"📋 **Fakta baru untuk \"{pending['topic_display']}\":**\n\n{preview}\n\nSetuju sama faktanya?",
                reply_markup=_fact_keyboard()
            )
        except Exception as e:
            await query.edit_message_text(f"❌ Gagal generate ulang: {e}")
        return

    if data == "fact:confirm":
        await query.edit_message_text("💾 Nyimpen fakta & trigger generate slide...")
        try:
            facts_data = pending["facts_data"]
            facts_path = facts_cache_path(pending["slug"])
            facts_path.write_text(json.dumps(facts_data, indent=2, ensure_ascii=False), encoding="utf-8")

            subprocess.run(["git", "add", str(facts_path)], cwd=PROJECT_ROOT, capture_output=True, timeout=10)
            subprocess.run(
                ["git", "commit", "-m", f"auto: facts confirmed for {pending['topic_display']}"],
                cwd=PROJECT_ROOT, capture_output=True, timeout=10,
            )
            subprocess.run(
                ["git", "pull", "--rebase", "origin", "main"],
                cwd=PROJECT_ROOT, capture_output=True, timeout=30,
            )
            push = subprocess.run(
                ["git", "push", "origin", "main"],
                cwd=PROJECT_ROOT, capture_output=True, timeout=30,
            )
            if push.returncode != 0:
                await query.edit_message_text(f"⚠️ Fakta disimpan, tapi push error: {push.stderr[:200]}\nCoba /sync nanti")
                return

            topic_ref = pending.get("topic_ref", "") or slug.replace("_", "-")
            body = json.dumps({"ref": "main", "inputs": {"topic": topic_ref, "num_facts": str(pending["num_facts"]), "force": "false"}})
            headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {GH_PAT}", "Content-Type": "application/json"}
            resp = await HTTPX_CLIENT.post(f"{GH_API}/repos/{GH_REPO}/actions/workflows/295601892/dispatches", content=body, headers=headers)
            if resp.status_code == 204:
                await query.edit_message_text(f"✅ Fakta disimpan & generate slide di-trigger! Cek /status nanti~")
            else:
                await query.edit_message_text(f"⚠️ Fakta disimpan, tapi trigger workflow gagal: HTTP {resp.status_code}")
        except Exception as e:
            await query.edit_message_text(f"❌ Error: {e}")
        finally:
            context.user_data.pop("pending_facts", None)
        return


async def cancel_wf_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel a running GH Actions workflow."""
    query = update.callback_query
    await query.answer()
    try:
        run_id = query.data.split(":", 2)[2]
        headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {GH_PAT}"}
        resp = await HTTPX_CLIENT.post(f"{GH_API}/repos/{GH_REPO}/actions/runs/{run_id}/cancel", headers=headers)
        if resp.status_code == 202:
            await query.edit_message_text(f"✅ Run #{run_id} dicancel!")
        else:
            await query.edit_message_text(f"❌ Gagal cancel: HTTP {resp.status_code}")
    except Exception as e:
        await query.edit_message_text(f"❌ Error: {e}")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.lower()

    # Wizard: handle text responses for /setslot add
    wiz = context.user_data.get("wizard")
    if wiz:
        if wiz["step"] == "id":
            if not re.match(r"^[a-zA-Z0-9_-]+$", text):
                await update.message.reply_text("❌ Id cuma boleh huruf, angka, strip, underscore. Coba lagi~")
                return
            if any(s["id"] == text for s in SLOT_MANAGER.slots):
                await update.message.reply_text(f"❌ Slot `{text}` udah ada. Pake id lain~")
                return
            wiz["sid"] = text
            wiz["step"] = "days"
            wiz["selected_days"] = set()
            await update.message.reply_text(f"📝 Nama: `{text}`\n\n🗓️ **Pilih hari:**", reply_markup=_day_keyboard(set()), parse_mode="Markdown")
            return
        if wiz["step"] == "time":
            if not re.match(r"^\d{1,2}:\d{2}$", text):
                await update.message.reply_text("❌ Format jam salah. Pake HH:MM, contoh: `19:00`")
                return
            h, m = text.split(":")
            if not (0 <= int(h) <= 23 and 0 <= int(m) <= 59):
                await update.message.reply_text("❌ Jam antara 00:00 - 23:59, coba lagi~")
                return
            wiz["time"] = text
            days_str = ", ".join(sorted(DAYS_ID[d] for d in wiz["selected_days"]))
            preview = (
                f"📋 **Konfirmasi Slot Baru:**\n"
                f"Nama: `{wiz['sid']}`\n"
                f"Hari: {days_str}\n"
                f"Jam: {text}\n\n"
                f"Udah bener?"
            )
            await update.message.reply_text(preview, reply_markup=_confirm_keyboard(), parse_mode="Markdown")
            return
        context.user_data.pop("wizard", None)

    save_message(user.id, user.username or "", "user", update.message.text)

    # Cek apakah user nanya topik kurikulum tertentu (sebelum schedule check)
    curriculum_topics = _load_curriculum()
    matched = _match_curriculum_topic(text, curriculum_topics)

    schedule_keywords = ["jadwal", "schedule", "posting", "hari ini", "besok", "nanti"]
    if any(kw in text for kw in schedule_keywords):
        sched = _read_schedule()
        if sched:
            reply = f"{sched}\n\nAda yang mau ditanyain lagi beb? 😏🫣"
            for word in FORBIDDEN_WORDS:
                reply = re.sub(rf"\b{word}\b", "***", reply, flags=re.IGNORECASE)
            if len(reply) > 4000:
                reply = reply[:4000] + "\n\n_— Lanjutan kepotong~_"
            await update.message.reply_text(reply)
            return

    curriculum_inject = ""
    if matched and matched in curriculum_topics:
        curriculum_inject = _format_curriculum_context(matched, curriculum_topics[matched])

    history = get_history(user.id, 5)
    messages = [{"role": "user" if h[0] == "user" else "model", "parts": [{"text": h[1]}]} for h in history]
    if curriculum_inject and messages and messages[0].get("role") == "user":
        messages[0]["parts"][0]["text"] = f"{curriculum_inject}\n\n{messages[0]['parts'][0]['text']}"

    try:
        reply = await _call_gemini(messages)

        for word in FORBIDDEN_WORDS:
            reply = re.sub(rf"\b{word}\b", "***", reply, flags=re.IGNORECASE)

        save_message(user.id, user.username or "", "assistant", reply)
        if len(reply) > 4000:
            reply = reply[:4000] + "\n\n_— Lanjutan kepotong soalnya kebanyakan~ 🫣_"
        await update.message.reply_text(reply)

    except Exception as e:
        err = str(e)
        if "quota" in err.lower() or "429" in err:
            msg = "Maaf sayang~ 😩 Gemini lagi kehabisan jatah hari ini. Coba lagi nanti abis 3 PM WIB ya~ quota-nya reset tiap sore~ 🫣"
        elif "503" in err or "unavailable" in err.lower():
            msg = "Maaf sayang~ 😩 Gemini lagi sibuk banget. Coba lagi ya~ 🫣"
        else:
            msg = f"Maaf sayang, error nih 😩: {err[:200]}"
        try:
            await update.message.reply_text(msg)
        except Exception:
            pass


async def run_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cmd = " ".join(context.args) if context.args else ""
    if not cmd:
        await update.message.reply_text("Contoh: /run git status")
        return

    base = cmd.split()[0] if cmd.split() else ""
    if base not in ALLOWED_CMDS:
        await update.message.reply_text(f"Perintah '{base}' gak diizinin sayang~ 😏")
        return

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=30, cwd=str(PROJECT_ROOT)
        )
        out = (result.stdout or "") + (result.stderr or "")
        out = out.strip()[-2000:]
        await update.message.reply_text(f"```\n{out}\n```" if out else "✅ Selesai")
    except subprocess.TimeoutExpired:
        await update.message.reply_text("⏳ Kelamaan, di-cut dulu~")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DELETE FROM history WHERE user_id = ?", (update.effective_user.id,))
    conn.commit()
    conn.close()
    await update.message.reply_text("Udah aku lupain obrolan kita~ Mau mulai lagi? 🫣")


async def sync_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sync VPS with remote repo — commit lokal, curriculum sync, push, pages push, restart."""
    msg = await update.message.reply_text("⏳ Sync on progress...")
    chat_id = update.effective_chat.id
    BIO_PATH = "accounts/aquarisamatiran/bio/index.html"

    def _sh(cmd, timeout=30, check=False):
        r = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=timeout)
        if check and r.returncode != 0:
            raise RuntimeError(f"cmd failed: {cmd}\n{r.stderr[:200]}")
        return r

    try:
        # 1. Commit pending local changes
        _sh(["git", "add", "-A"])
        diff = _sh(["git", "diff", "--cached", "--quiet"])
        if diff.returncode != 0:
            _sh(["git", "commit", "-m", "auto: pre-sync save"])

        # 2. Sync with remote
        _sh(["git", "fetch", "origin", "main"])
        _sh(["git", "rebase", "origin/main"], timeout=60)

        # 3. Install deps
        pip_res = _sh([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], timeout=120)
        if pip_res.returncode != 0:
            await msg.edit_text(f"⚠️ pip install error:\n{pip_res.stderr[:300]}")

        # 4. Curriculum sync — regenerates bio/index.html
        _sh([sys.executable, "main.py", "curriculum", "sync"], timeout=60)

        # 5. Commit bio changes
        _sh(["git", "add", BIO_PATH])
        bio_diff = _sh(["git", "diff", "--cached", "--quiet"])
        if bio_diff.returncode != 0:
            _sh(["git", "commit", "-m", "auto: sync bio [skip ci]"])

        # 6. Push ke repo ini (includes bio commit)
        push = _sh(["git", "push", "origin", "main"])
        if push.returncode != 0:
            await msg.edit_text(f"❌ Sync failed — push error:\n{push.stderr[:300]}")
            return

        # 7. Push bio ke pages repo (opsional)
        try:
            pages_script = (
                'set -e\n'
                'cd "$1"\n'
                'test -f .env && set -a && source .env && set +a || true\n'
                'if [ -z "$GH_PAT" ]; then\n'
                '  echo "GH_PAT not set -- skip pages push"\n'
                '  exit 0\n'
                'fi\n'
                'if [ ! -d /tmp/pages-repo ]; then\n'
                '  git clone "https://${GH_PAT}@github.com/imtopp/aquarisamatiran-pages.git" /tmp/pages-repo\n'
                'else\n'
                '  cd /tmp/pages-repo && git pull origin main && cd "$1"\n'
                'fi\n'
                'cp accounts/aquarisamatiran/bio/index.html /tmp/pages-repo/index.html\n'
                'cd /tmp/pages-repo\n'
                'git config user.name "Nix Bot"\n'
                'git config user.email "nix@aquarisamatiran.dev"\n'
                'git add index.html\n'
                'git diff --cached --quiet || git commit -m "auto: update bio from sync"\n'
                'git push origin main\n'
            )
            subprocess.run(
                ["bash", "-c", pages_script, "_", str(PROJECT_ROOT)],
                timeout=60,
            )
        except Exception as pages_err:
            print(f"  ⚠️  Pages push skipped: {pages_err}")

        # 8. Save flag for restart notification
        (PROJECT_ROOT / ".restart_flag").write_text(
            json.dumps({"chat_id": chat_id}), encoding="utf-8"
        )

        await msg.edit_text("✅ Sync done!\n🔄 Restart bot system...")

        # 9. Restart via systemctl with small delay
        subprocess.Popen(
            ["nohup", "sh", "-c", "sleep 2 && sudo systemctl restart nix-bot"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    except subprocess.TimeoutExpired:
        await msg.edit_text("❌ Sync timeout — salah satu langkah terlalu lama")
    except Exception as e:
        await msg.edit_text(f"❌ Sync error: {e}")


async def _notify_restart_done(app: Application) -> None:
    flag = PROJECT_ROOT / ".restart_flag"
    if not flag.exists():
        return
    try:
        data = json.loads(flag.read_text(encoding="utf-8"))
        await app.bot.send_message(
            chat_id=data["chat_id"],
            text="✅ Bot system is ready to serve!",
        )
    except Exception as e:
        print(f"⚠️ Gagal notif restart: {e}")
    flag.unlink(missing_ok=True)


async def _delete_webhook(app: Application) -> None:
    """Force delete webhook to clear 409 conflict on restart."""
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook deleted, polling clean.")
    except Exception as e:
        print(f"⚠️  Gagal delete webhook: {e}")
    await _notify_restart_done(app)


# ──── Group help texts ────

_TOPIC_HELP = """\
📁 `/topic <subcommand>` — CRUD kurikulum
  (tanpa args) → daftar semua topik
  `add <C#> <sub#> <judul>`           → tambah topic
  `show <ref>`                         → liat detail topic
  `edit <ref> --field val [...]`        → edit topic
  `delete <ref>`                       → hapus topic
  `move <ref> <C#> <sub#>`             → pindah topic
  `slides`                             → daftar file slide
  `cat add <nama>`                     → tambah category
  `cat rename <C#> <nama>`             → ganti nama category
  `cat remove <C#>`                    → hapus category
  `cat sub add <C#> <id> <label>`      → tambah subcategory
  `cat sub rename <C#> <id> <label>`   → ganti nama subcategory
  `cat sub remove <C#> <id>`           → hapus subcategory
  `help`                               → liat ini"""

_POST_HELP = """\
📁 `/post <subcommand>` — Alur posting
  `[ref] [hari jam]`       → siapin post (implicit kalo arg pertama bukan subcommand)
  (tanpa args)              → auto-detect slide terbaru
  `confirm`                 → upload & jadwalin
  `cancel`                  → batalin pending post
  `caption [ref] <instruksi>` → edit caption
  `caption show <ref>`      → liat caption topik
  `clean <ref>`             → hapus slide gak jadi
  `help`                    → liat ini"""

_GENERATE_HELP = """\
📁 `/generate <ref> [count]` — Generate slide
  `<ref> [count]`           → generate facts baru + slide
  `--cache <ref> [count]`   → pake facts lama, slide baru aja
  `--force <ref> [count]`   → generate facts ulang + slide
  (kalo ada pending post, <ref> gak perlu)
  `help`                    → liat ini"""

_SCHEDULE_HELP = """\
📁 `/schedule <subcommand>` — Manajemen jadwal
  (tanpa args) → liat jadwal posting
  `delete <ref>`                     → hapus dari jadwal
  `slot add`                         → tambah slot (wizard interaktif)
  `slot remove <id>`                 → hapus slot
  `slot sync`                        → sync ke cron-job.org
  `help`                             → liat ini"""

_POST_SUBCOMMANDS = {"help", "confirm", "cancel", "caption", "clean"}


# ──── Group dispatchers ────


async def topic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if not args:
        return await topics_cmd(update, context)
    sub = args[0].lower()
    rest = args[1:]
    if sub == "help":
        return await update.message.reply_text(_TOPIC_HELP)
    if sub == "slides":
        context.args = rest
        return await slides_cmd(update, context)
    if sub == "add":
        context.args = rest
        return await addtopic_cmd(update, context)
    if sub == "show":
        context.args = rest
        return await showtopic_cmd(update, context)
    if sub == "edit":
        context.args = rest
        return await edittopic_cmd(update, context)
    if sub == "delete":
        context.args = rest
        return await deletetopic_cmd(update, context)
    if sub == "move":
        context.args = rest
        return await movetopic_cmd(update, context)
    if sub == "cat":
        return await _topic_cat_cmd(update, context, rest)
    await update.message.reply_text(f"❌ Subcommand `{sub}` gak dikenal.\n\n{_TOPIC_HELP}")


async def _topic_cat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list):
    if not args:
        return await update.message.reply_text(
            "Gunakan: `/topic cat add|rename|remove|sub`\n\n" + _TOPIC_HELP
        )
    sub = args[0].lower()
    rest = args[1:]
    if sub == "add":
        context.args = rest
        return await addcategory_cmd(update, context)
    if sub == "rename":
        # /topic cat rename <C#> <nama>
        if len(rest) < 2:
            return await update.message.reply_text("Format: `/topic cat rename <C#> <nama>`")
        from nixfw.curriculum.manager import telegram_rename_category
        result = telegram_rename_category(rest[0], " ".join(rest[1:]))
        return await update.message.reply_text(result)
    if sub == "remove":
        # /topic cat remove <C#>
        if not rest:
            return await update.message.reply_text("Format: `/topic cat remove <C#>`")
        from nixfw.curriculum.manager import telegram_remove_category
        result = telegram_remove_category(rest[0])
        return await update.message.reply_text(result)
    if sub == "sub":
        return await _topic_cat_sub_cmd(update, context, rest)
    await update.message.reply_text(f"❌ Subcommand `{sub}` gak dikenal.\n\n" + _TOPIC_HELP)


async def _topic_cat_sub_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list):
    if not args:
        return await update.message.reply_text(
            "Gunakan: `/topic cat sub add|rename|remove`\n\n" + _TOPIC_HELP
        )
    sub = args[0].lower()
    rest = args[1:]
    if sub == "add":
        context.args = rest
        return await addsubcategory_cmd(update, context)
    if sub == "rename":
        if len(rest) < 3:
            return await update.message.reply_text("Format: `/topic cat sub rename <C#> <id> <label>`")
        from nixfw.curriculum.manager import telegram_rename_subcategory
        result = telegram_rename_subcategory(rest[0], rest[1], " ".join(rest[2:]))
        return await update.message.reply_text(result)
    if sub == "remove":
        if len(rest) < 2:
            return await update.message.reply_text("Format: `/topic cat sub remove <C#> <id>`")
        from nixfw.curriculum.manager import telegram_remove_subcategory
        result = telegram_remove_subcategory(rest[0], rest[1])
        return await update.message.reply_text(result)
    await update.message.reply_text(f"❌ Subcommand `{sub}` gak dikenal.\n\n" + _TOPIC_HELP)


async def post_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if not args:
        return await post_cmd(update, context)
    sub = args[0].lower()
    rest = args[1:]
    if sub == "help":
        return await update.message.reply_text(_POST_HELP)
    if sub == "confirm":
        context.args = rest
        return await confirm_cmd(update, context)
    if sub == "cancel":
        context.args = rest
        return await cancel_cmd(update, context)
    if sub == "caption":
        if rest and rest[0].lower() == "show":
            context.args = rest[1:]
            return await peekcaption_cmd(update, context)
        context.args = rest
        return await editcaption_cmd(update, context)
    if sub == "clean":
        context.args = rest
        return await clean_cmd(update, context)
    if sub in _POST_SUBCOMMANDS:
        return await update.message.reply_text(f"❌ Format salah.\n\n{_POST_HELP}")
    # Implicit create: args diperlakukan sebagai [ref, hari, jam, ...]
    context.args = args
    return await post_cmd(update, context)


async def generate_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if not args:
        return await update.message.reply_text(_GENERATE_HELP)
    force = "--force" in args
    cache = "--cache" in args
    filtered = [a for a in args if a not in ("--force", "--cache")]
    pending = _pending_posts.get(update.effective_user.id)

    def _pick_slug(filtered, pending):
        slug = None
        count = "8"
        if filtered:
            slug = filtered[0]
            if len(filtered) > 1:
                try:
                    count = filtered[1]
                except ValueError:
                    slug = " ".join(filtered)
        elif pending:
            slug = pending.get("slug") or pending.get("topic_ref")
        return slug, count

    if force:
        if pending and not filtered:
            context.args = []
            return await regenerate_cmd(update, context)
        slug, count = _pick_slug(filtered, pending)
        if not slug:
            return await update.message.reply_text(f"❌ Gak ada ref dan gak ada pending post.\n\n{_GENERATE_HELP}")
        await _dispatch_workflow(slug, count, True, update)
        return

    if cache:
        await update.message.reply_text("⏳ Generate slide (pake facts lama)...")
        slug, count = _pick_slug(filtered, pending)
        if not slug:
            return await update.message.reply_text(f"❌ Gak ada ref dan gak ada pending post.\n\n{_GENERATE_HELP}")
        await _dispatch_workflow(slug, count, False, update)
        return

    # Normal generate
    context.args = filtered
    return await generate_cmd(update, context)


async def schedule_dispatch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if not args:
        return await schedule_cmd(update, context)
    sub = args[0].lower()
    rest = args[1:]
    if sub == "help":
        return await update.message.reply_text(_SCHEDULE_HELP)
    if sub == "delete":
        context.args = rest
        return await delete_schedule_cmd(update, context)
    if sub == "slot":
        context.args = rest
        return await setslot_cmd(update, context)
    await update.message.reply_text(f"❌ Subcommand `{sub}` gak dikenal.\n\n{_SCHEDULE_HELP}")


def main():
    if not TELEGRAM_TOKEN:
        print("TELEGRAM_TOKEN gak ada di .env")
        return

    init_db()
    request = HTTPXRequest(connect_timeout=30, read_timeout=30, write_timeout=30)
    app = Application.builder().token(TELEGRAM_TOKEN).request(request).post_init(_delete_webhook).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("run", run_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("sync", sync_cmd))

    app.add_handler(CommandHandler("topic", topic_cmd))
    app.add_handler(CommandHandler("post", post_dispatch))
    app.add_handler(CommandHandler("generate", generate_dispatch))
    app.add_handler(CommandHandler("schedule", schedule_dispatch))

    app.add_handler(CallbackQueryHandler(wizard_callback, pattern="^wiz:"))
    app.add_handler(CallbackQueryHandler(fact_callback, pattern="^fact:"))
    app.add_handler(CallbackQueryHandler(cancel_wf_callback, pattern="^cancel:wf:"))
    app.add_handler(CallbackQueryHandler(slot_pick_callback, pattern="^slot:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    print("Bot jalan di VPS... chat aku dari Telegram~")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
