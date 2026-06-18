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

sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GEMINI_API_KEYS = [
    os.environ.get("GEMINI_API_KEY", ""),
    *[v for k, v in sorted(os.environ.items()) if k.startswith("GEMINI_API_KEY_") and v],
]
ALLOWED_USERNAMES = os.environ.get("BOT_ALLOWED_USERNAMES", "").split(",")
FORBIDDEN_WORDS = ["lu", "gue", "lo", "elu", "gw"]

GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash"]

_pending_posts: dict[int, dict] = {}
GITHUB_PAT = os.environ.get("GITHUB_PAT", "")
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
                        term_lines.append(f"  C{cid}#{k} {v['title']}{status_tag}: {kw_str}")
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
            for attempt in range(2):
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
                    break  # server sibuk, guna model lain aja, gak perlu retry
                if resp.status_code in (429, 403):
                    break  # quota abis / forbidden, guna key berikutnya
    raise RuntimeError(f"Semua model & key Gemini kehabisan: {last_err[:100]}")


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
    "/help — nampilin ini\n"
    "/topics — daftar topik kurikulum (`#XX`)\n"
    "/slides — daftar slide yang siap post (curriculum + adhoc)\n"
    "/reset — hapus riwayat obrolan\n"
    "/run `<cmd>` — jalanin perintah (terbatas)\n"
    "/generate `C1#07` `[jml_fakta]` — trigger generate carousel SD\n"
    "/status — cek progress generate terakhir\n"
    "/post `[C1#07 atau slug]` `[hari jam]` — post carousel (auto-detect kalo tanpa arg)\n"
    "/confirm — lanjutin posting setelah preview\n"
    "/editcaption `<instruksi>` — ganti caption\n"
    "/regenerate — generate ulang slide\n"
    "/cancel — batalin posting\n"
    "/myid — liat chat ID kamu\n"
    "/setslot — atur jadwal slot (`add` wizard, `remove`, `sync`)\n"
    "/schedule — liat jadwal postingan\n"
    "/clean `<slug atau C1#XX>` — hapus slide yang gak jadi dipost\n\n"
    "**🧙 Wizard Interaktif:**\n"
    "Ketik `/setslot add` — bot tanya nama, pilih hari via tombol, jam → auto-sync cron-job.org!\n\n"
    "**🚀 Cara pake Curriculum:**\n"
    "1. `/topics` — liat daftar `C1#07` yang tersedia\n"
    "2. `/generate C1#07` — bikin carousel (10-30 menit di GH Actions)\n"
    "3. `/status` — cek udah selesai belum\n"
    "4. `/post C1#07` — preview slide + caption\n"
    "5. `/confirm` — upload & jadwal otomatis\n\n"
    "**🚀 Cara pake Adhoc:**\n"
    "1. `/slides` — liat slide yang siap post\n"
    "2. `/post <slug>` — preview + caption\n"
    "3. `/confirm` — upload & jadwal"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


def _read_schedule() -> str:
    """Read schedule.json and return a formatted summary."""
    try:
        data = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return ""
    now = datetime.date.today()
    done, upcoming = [], []
    for entry in data:
        t = entry.get("time", "")
        try:
            d = datetime.datetime.strptime(t[:10], "%Y-%m-%d").date()
        except (ValueError, IndexError):
            continue
        topic = entry.get("curriculum") or entry.get("type", "post")
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
    """Load and flatten curriculum topics to {C1#01: {...}} format."""
    try:
        data = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
        topics = data.get("topics", {})
        flat = {}
        for sid in sorted(topics, key=int):
            for tnum in sorted(topics[sid], key=int):
                flat[f"C{sid}#{tnum}"] = topics[sid][tnum]
        return flat
    except Exception:
        return {}


def _match_curriculum_topic(text: str, topics: dict) -> str | None:
    """Cari topic di curriculum yang cocok dengan pertanyaan user."""
    text_lower = text.lower()
    for key, topic in topics.items():
        title_lower = topic.get("title", "").lower()
        slug = topic.get("slug", "")
        keywords = [k.lower().strip() for k in topic.get("keywords", [])]
        display = topic.get("display_name", "").lower()
        tnum = key.split("#")[1]
        snum = "s" + key.split("#")[0][1:]  # "s1" from "C1"
        patterns = [f"#{tnum}", key.lower(), f"{snum}#{tnum}", title_lower, slug.replace("-", " "), display]
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
            lines.append(f"  {emoji} `C{sid}#{tnum.zfill(2)}` {dn}{jadwal}")
        lines.append("")
    lines.append("Contoh: `/generate C1#07`, `/post C2#01`")
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
                    tag = f"C{sid}#{tnum}"
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
    """Trigger GH Actions workflow to generate SD carousel."""
    if not GITHUB_PAT:
        await update.message.reply_text("GITHUB_PAT gak ada di .env, minta ke bebnya dulu~ 😏")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Contoh: `/generate #07` atau `/generate #07 7`\nCek `/topics` buat liat daftar #XX.")
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
    await update.message.reply_text(f"⚙️ Trigger generate \"{topic}\" ({num_facts} fakta) di GH Actions...")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GH_API}/repos/{GH_REPO}/actions/workflows/295601892/dispatches",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {GITHUB_PAT}",
                },
                json={"ref": "main", "inputs": {"topic": topic, "num_facts": num_facts}},
            )
        if resp.status_code == 204:
            await update.message.reply_text(
                f"✅ Generate \"{topic}\" berhasil ditrigger! 🎉\n"
                f"Tunggu 10-30 menit, cek progress pake /status"
            )
        else:
            await update.message.reply_text(f"❌ Gagal: HTTP {resp.status_code}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


def _latest_slides(topic_ref: str = "") -> tuple[str | None, list[Path]]:
    """Detect carousel slides in PHOTO_DIR. 
    If topic_ref given (e.g. C1#07), filter by topic slug.
    If it doesn't match tag format, treat as direct slug (e.g. puntius_denisonii)."""
    slides_dir = PHOTO_DIR
    if topic_ref:
        m = re.match(r'[CS](\d+)#(\d+)', topic_ref)
        if m:
            cur_data = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
            topic = cur_data.get("topics", {}).get(m.group(1), {}).get(m.group(2), {})
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


async def _generate_caption(facts_json: dict | None, topic: str) -> str:
    """Generate a caption using Gemini from facts data."""
    if not GEMINI_API_KEYS[0]:
        # Fallback: build simple caption from facts
        lines = [f"{topic} — Yuk belajar! 🐟"]
        if facts_json and "facts" in facts_json:
            for f in facts_json["facts"]:
                lines.append(f"\n{f.get('number','?')}. {f.get('title','')}")
            lines.append("\nFollow @aquarisamatiran untuk belajar aquarium dari nol! 🌱")
        return "\n".join(lines)

    prompt_parts = [f"Buat caption Instagram dalam bahasa Indonesia untuk konten aquarium dengan topik: {topic}."]
    if facts_json and "facts" in facts_json:
        prompt_parts.append("\nFakta-fakta dalam konten ini:")
        for f in facts_json["facts"]:
            prompt_parts.append(f"- {f.get('number','')}. {f.get('title','')}: {f.get('description','')[:100]}")
    prompt_parts.append("\nGaya: santai, edukatif, engaging. Include ajakan diskusi. Maks 2000 karakter. Sertakan hashtag #Aquarisamatiran dan hashtag relevan lainnya di akhir.")
    caption_system = (
        "Kamu adalah asisten pembuat konten Instagram untuk akun aquascape @aquarisamatiran. "
        "Gaya bicara: santai, edukatif, engaging, akrab — pake bahasa Indonesia sehari-hari. "
        "Beri informasi bermanfaat, ajak diskusi, jangan terlalu formal, jangan pake gaya genit/flirty. "
        "Tujuan: ngajarin follower aquarium dari nol dengan cara yang asyik."
    )
    text = _today_context() + "\n\n" + "\n".join(prompt_parts)

    keys = [k for k in GEMINI_API_KEYS if k]
    for key in keys:
        for model in GEMINI_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={key}"
            body = {"contents": [{"role": "user", "parts": [{"text": text}]}]}
            if caption_system:
                body["system_instruction"] = {"parts": [{"text": caption_system}]}
            try:
                resp = await HTTPX_CLIENT.post(url, json=body)
                if resp.status_code == 200:
                    return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            except Exception:
                continue
    return f"{topic} — Yuk belajar bareng @aquarisamatiran! 🌱 #Aquarisamatiran #AquascapeIndonesia"


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check latest GH Actions generate run status."""
    if not GITHUB_PAT:
        await update.message.reply_text("GITHUB_PAT gak ada, gak bisa cek~ 😏")
        return
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{GH_API}/repos/{GH_REPO}/actions/workflows/295601892/runs?per_page=1",
                headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {GITHUB_PAT}"},
            )
        if resp.status_code != 200:
            await update.message.reply_text(f"❌ Gagal cek status: HTTP {resp.status_code}")
            return
        run = resp.json()["workflow_runs"][0]
        status = run["status"]
        conclusion = run["conclusion"] or "—"
        topic = run.get("display_title", "?")
        html_url = run["html_url"]
        emoji = {"queued": "⏳", "in_progress": "🔄", "completed": {"success": "✅", "failure": "❌", "cancelled": "🚫"}.get(conclusion, "❓")}.get(status, "❓")
        created_utc = run["created_at"][:16].replace("T", " ")
        try:
            dt = datetime.datetime.strptime(created_utc, "%Y-%m-%d %H:%M") + datetime.timedelta(hours=7)
            created_wib = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            created_wib = created_utc
        msg = (
            f"{emoji} Generate: **{topic}**\n"
            f"Status: **{status}** ({conclusion})\n"
            f"Dibuat: {created_wib} WIB\n"
            f"[Lihat di GitHub]({html_url})"
        )
        if slides := _latest_slides()[1]:
            msg += f"\n📸 Slide siap: {len(slides)} file"
        await update.message.reply_text(msg)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def post_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Upload slides + schedule carousel. Smart auto-detect + auto-caption."""
    args = context.args
    topic_ref = ""
    schedule_time = ""
    # Parse args: /post [slug/C1#07] [Kamis 19:00]
    for a in args:
        if a.startswith("#") or re.match(r"[CS]\d+#\d+", a):
            topic_ref = a
        elif re.match(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun|Senin|Selasa|Rabu|Kamis|Jumat|Sabtu|Minggu)", a, re.IGNORECASE) and len(args) > args.index(a) + 1:
            idx = list(args).index(a)
            schedule_time = f"{a} {args[idx+1]}"
        elif not topic_ref:
            topic_ref = a  # treat as direct slug

    # Auto-detect latest slides (filter by topic_ref if given)
    slug, slides = _latest_slides(topic_ref)
    if not slug:
        await update.message.reply_text("❌ Ngga nemu slide carousel di resource/photos/")
        return
    if not topic_ref:
        cc = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
        for s_num, ts in cc.get("topics", {}).items():
            for t_num, t in ts.items():
                if t.get("slug", "").replace("-", "_") == slug:
                    topic_ref = f"C{s_num}#{t_num}"
                    break
            if topic_ref:
                break
    if len(slides) > 10:
        await update.message.reply_text(f"❌ IG carousel maksimal 10 slide, ini ada {len(slides)} (cover + fakta + CTA). Generate ulang pake lebih dikit fakta ya~")
        return

    # Determine schedule time
    if not schedule_time:
        # Map day to nearest slot
        nearest = SLOT_MANAGER.nearest_slot()
        dt = datetime.datetime.strptime(nearest, "%Y-%m-%d %H:%M")
        day_name = DAYS_ID[dt.weekday()]
        time_str = dt.strftime("%H:%M")
        schedule_time = f"{day_name} {time_str}"

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

    # Generate caption
    facts_json = None
    facts_path = PHOTO_DIR / f"edu_{slug}_facts.json"
    if facts_path.exists():
        try:
            facts_json = json.loads(facts_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    topic_display = _slug_to_topic(slug)
    await update.message.reply_text(f"💬 Generate caption buat \"{topic_display}\"...")
    try:
        caption = await asyncio.wait_for(_generate_caption(facts_json, topic_display), timeout=60)
    except asyncio.TimeoutError:
        caption = f"{topic_display} — Yuk belajar bareng @aquarisamatiran! 🌱 #Aquarisamatiran #AquascapeIndonesia"
        await update.message.reply_text("⚠️ Caption generation timeout, pakai fallback~")

    # Preview + confirm
    msg = (
        f"📋 **{topic_display}** ({len(slides)} slide)\n"
        f"📅 Jadwal: {schedule_time}\n\n"
        f"📝 **Caption:**\n{caption[:1000]}\n\n"
        f"`/confirm` → upload & jadwalin\n"
        f"`/editcaption <instruksi>` → ganti caption\n"
        f"`/regenerate` → generate ulang slide\n"
        f"`/cancel` → batalin"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

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


async def editcaption_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pending = _pending_posts.get(user_id)
    if not pending:
        await update.message.reply_text("Ngga ada pending post. Coba `/post` dulu~")
        return
    instruction = " ".join(context.args) if context.args else ""
    if not instruction:
        await update.message.reply_text("Gunakan: `/editcaption <instruksi>`\nContoh: `/editcaption bikin lebih santai dan pake lebih banyak emoji`")
        return
    await update.message.reply_text(f"💬 Edit caption dengan instruksi: \"{instruction}\"...")
    caption_system = (
        "Kamu adalah asisten pembuat konten Instagram untuk akun aquascape @aquarisamatiran. "
        "Gaya bicara: santai, edukatif, engaging, akrab. Pake bahasa Indonesia sehari-hari, "
        "jangan genit/flirty. Tujuan: ngajarin follower aquarium dari nol dengan cara yang asyik."
    )
    prompt = f"Instruksi: {instruction}\n\nCaption sebelumnya:\n{pending['caption'][:1500]}"
    messages = [{"role": "user", "parts": [{"text": prompt}]}]
    try:
        new_caption = await _call_gemini(messages, system=caption_system)
        pending["caption"] = new_caption
        await update.message.reply_text(f"✅ Caption baru:\n{new_caption[:1000]}\n\nKetik `/confirm` buat lanjut, atau `/editcaption` lagi~")
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal edit caption: {e}")


async def regenerate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pending = _pending_posts.get(user_id)
    if not pending:
        await update.message.reply_text("Ngga ada pending post. Coba `/post` dulu~")
        return
    topic_display = pending["topic_display"]
    topic_ref = pending.get("topic_ref", "")
    if not topic_ref:
        slug = pending["slug"]
        try:
            cc = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
            for s_num, ts in cc.get("topics", {}).items():
                for t_num, t in ts.items():
                    if t.get("slug", "").replace("-", "_") == slug:
                        topic_ref = f"C{s_num}#{t_num}"
                        break
                if topic_ref:
                    break
        except Exception:
            pass
    topic_input = topic_ref if topic_ref else pending["slug"].replace("_", " ")
    await update.message.reply_text(f"🔄 Generate ulang carousel \"{topic_display}\" (topic: {topic_input})...")
    _pending_posts.pop(user_id, None)
    try:
        import httpx
        body = '{"ref":"main","inputs":{"topic":"' + topic_input + '","num_facts":"8"}}'
        headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {os.environ.get('GITHUB_PAT', '')}", "Content-Type": "application/json"}
        resp = await HTTPX_CLIENT.post("https://api.github.com/repos/imtopp/aquarisamatiranIG/actions/workflows/generate.yml/dispatches", content=body, headers=headers)
        if resp.status_code == 204:
            await update.message.reply_text(f"✅ Generate ulang untuk \"{topic_display}\" udah di-trigger! Cek `/status` ~30 menit~")
        else:
            await update.message.reply_text(f"❌ Gagal trigger: {resp.status_code}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def confirm_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pending = _pending_posts.pop(user_id, None)
    if not pending:
        await update.message.reply_text("Ngga ada pending post. Coba `/post` dulu~")
        return

    slug = pending["slug"]
    caption = pending["caption"]
    schedule_time = pending["schedule_time"]

    await update.message.reply_text(f"📤 Upload & jadwalin \"{slug}\"...")
    try:
        proc_args = [sys.executable, "main.py", "post-carousel", "--slug", slug, "--schedule", "cron", schedule_time, caption]
        result = subprocess.run(proc_args, capture_output=True, text=True, timeout=300, cwd=str(PROJECT_ROOT))
        out = (result.stdout or "") + (result.stderr or "")
        out = out.strip()[-3000:]
        status = "✅" if result.returncode == 0 else "❌"
        await update.message.reply_text(f"{status} Result:\n```\n{out}\n```")
    except subprocess.TimeoutExpired:
        await update.message.reply_text("⏳ Kelamaan (>5 menit), cek manual aja sayang~")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


async def cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    _pending_posts.pop(user_id, None)
    await update.message.reply_text("Oke, pending post dibatalin~ Mau `/post` lagi? 😏")


async def clean_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Hapus slide yang gak jadi dipost via GH Actions clean.yml."""
    args = context.args
    if not args:
        await update.message.reply_text(
            "Gunakan: `/clean <slug>` atau `/clean C1#XX`\n"
            "Cek `/slides` buat liat slug yang tersedia."
        )
        return

    raw = args[0]
    slug = ""
    m = re.match(r'[CS](\d+)#(\d+)', raw)
    if m:
        try:
            cc = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
            topic = cc.get("topics", {}).get(m.group(1), {}).get(m.group(2), {})
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
    files = list(slides_dir.glob(f"{slug}_sd_*"))
    files += list(slides_dir.glob(f"{slug}_slide_*"))
    files += list(slides_dir.glob(f"edu_{slug[:20]}*"))
    if not files:
        await update.message.reply_text(f"❌ Gak nemu file dengan prefix `{slug}` di resource/photos/")
        return

    if not GITHUB_PAT:
        await update.message.reply_text("GITHUB_PAT gak ada di .env, minta ke bebnya dulu~ 😏")
        return

    try:
        body = json.dumps({"ref": "main", "inputs": {"slug": slug}})
        headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {GITHUB_PAT}"}
        resp = await HTTPX_CLIENT.post(
            "https://api.github.com/repos/imtopp/aquarisamatiranIG/actions/workflows/clean.yml/dispatches",
            content=body, headers=headers,
        )
        if resp.status_code == 204:
            await update.message.reply_text(
                f"🗑️ Clean trigger buat `{slug}`! {len(files)} file bakal dihapus.\n"
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


async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sched = _read_schedule()
    if sched:
        reply = f"{sched}\n\nAda yang mau ditanyain lagi, beb? 😏"
        await update.message.reply_text(reply)
    else:
        await update.message.reply_text("❌ `schedule.json` gak bisa dibaca atau kosong.")


async def setslot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        slots_str = SLOT_MANAGER.format_list()
        await update.message.reply_text(f"📅 **Slot Jadwal Saat Ini:**\n{slots_str}\n\nGunakan:\n`/setslot add` — tambah slot interaktif\n`/setslot remove <id>`\n`/setslot sync`", parse_mode="Markdown")
        return

    cmd = args[0].lower()

    if cmd == "add":
        context.user_data["wizard"] = {"step": "id"}
        await update.message.reply_text("📝 **Id slotnya?** (huruf, angka, strip `-`, underscore `_` aja, gak boleh spasi)\nContoh: `weekend-09`, `weekday-19`, `lunch-12`", parse_mode="Markdown")
    elif cmd == "remove":
        if len(args) < 2:
            await update.message.reply_text("Pake: `/setslot remove <id>`")
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


async def _delete_webhook(app: Application) -> None:
    """Force delete webhook to clear 409 conflict on restart."""
    try:
        await app.bot.delete_webhook(drop_pending_updates=True)
        print("✅ Webhook deleted, polling clean.")
    except Exception as e:
        print(f"⚠️  Gagal delete webhook: {e}")


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
    app.add_handler(CommandHandler("generate", generate_cmd))
    app.add_handler(CommandHandler("topics", topics_cmd))
    app.add_handler(CommandHandler("slides", slides_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("post", post_cmd))
    app.add_handler(CommandHandler("confirm", confirm_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("clean", clean_cmd))
    app.add_handler(CommandHandler("editcaption", editcaption_cmd))
    app.add_handler(CommandHandler("regenerate", regenerate_cmd))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(CommandHandler("schedule", schedule_cmd))
    app.add_handler(CommandHandler("setslot", setslot_cmd))
    app.add_handler(CallbackQueryHandler(wizard_callback, pattern="^wiz:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    print("Bot jalan di VPS... chat aku dari Telegram~")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
