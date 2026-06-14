"""Telegram bot untuk Aquarisamatiran — personality AGENTS.md + Gemini API"""
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
from telegram import Update, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest

sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GEMINI_API_KEYS = [
    os.environ.get("GEMINI_API_KEY", ""),
    *[v for k, v in sorted(os.environ.items()) if k.startswith("GEMINI_API_KEY_") and v],
]
ALLOWED_USERNAMES = os.environ.get("BOT_ALLOWED_USERNAMES", "").split(",")
PROJECT_DIR = Path(__file__).resolve().parent.parent
AGENTS_MD = PROJECT_DIR / "AGENTS.md"
DB_PATH = PROJECT_DIR / "bot" / "chat_history.db"
SCHEDULE_PATH = PROJECT_DIR / "schedule.json"
CURRICULUM_PATH = PROJECT_DIR / "curriculum_content.json"
FORBIDDEN_WORDS = ["lu", "gue", "lo", "elu", "gw"]

GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash"]

_pending_posts: dict[int, dict] = {}
GITHUB_PAT = os.environ.get("GITHUB_PAT", "")
GH_REPO = "imtopp/aquarisamatiranIG"
GH_API = "https://api.github.com"

system_prompt = ""
if AGENTS_MD.exists():
    system_prompt = AGENTS_MD.read_text(encoding="utf-8")
    system_prompt += "\n\nKamu adalah aku yang asli — personality, suara, gaya bicara, semuanya sama persis."

# Inject terminology from curriculum_content.json (v4: nested per-season)
if CURRICULUM_PATH.exists():
    try:
        cur_data = json.loads(CURRICULUM_PATH.read_text(encoding="utf-8"))
        topics = cur_data.get("topics", {})
        seasons = cur_data.get("seasons", {})
        if topics:
            term_lines = ["", "## Curriculum Terminology (live from curriculum_content.json)", ""]
            for sid in sorted(seasons, key=int):
                s = seasons[sid]
                st = topics.get(str(sid), {})
                levels = s.get("level_labels", {})
                for lv in sorted(levels, key=int):
                    label = levels[lv]
                    lv_topics = sorted(
                        [(k, st[k]) for k in st if st[k].get("level") == int(lv)],
                        key=lambda x: int(x[0]),
                    )
                    if not lv_topics:
                        continue
                    term_lines.append(f"Season {sid} Level {lv} ({label}):")
                    for k, v in lv_topics:
                        status = v.get("status", "planned")
                        keywords = v.get("keywords", [])
                        kw_str = ", ".join(keywords) if keywords else "(no keywords)"
                        status_tag = " ✅" if status == "live" else (" 📅" if status == "scheduled" else "")
                        term_lines.append(f"  S{sid}#{k} {v['title']}{status_tag}: {kw_str}")
            system_prompt += "\n" + "\n".join(term_lines)
    except Exception:
        pass  # best-effort

HTTPX_CLIENT = httpx.AsyncClient(timeout=300)


def _today_context() -> str:
    return f"Hari ini: {datetime.datetime.now().strftime('%A, %d %B %Y %H:%M WIB')}"


async def _call_gemini(messages: list[dict]) -> str:
    """Call Gemini REST API with fallback keys + fallback models, retry on timeout."""
    if messages and messages[-1].get("role") == "user":
        today = _today_context()
        messages[-1]["parts"][0]["text"] = f"{today}\n\n{system_prompt}\n\n{messages[-1]['parts'][0]['text']}"
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
    "/reset — hapus riwayat obrolan\n"
    "/run `<cmd>` — jalanin perintah (terbatas)\n"
    "/generate `<topik>` `[jml_fakta]` — trigger generate carousel SD via GH Actions\n"
    "/status — cek progress generate terakhir\n"
    "/post `[#XX]` `[hari jam]` — preview & jadwalin carousel terbaru\n"
    "/confirm — lanjutin posting setelah preview\n"
    "/editcaption `<instruksi>` — ganti caption\n"
    "/regenerate — generate ulang slide\n"
    "/cancel — batalin posting\n"
    "/myid — liat chat ID kamu\n\n"
    "**🚀 Cara pake:**\n"
    "1. `/generate Siklus Air 8` — bikin carousel (10-30 menit di GH Actions)\n"
    "2. `/status` — cek udah selesai belum\n"
    "3. `/post #03` — preview slide + caption\n"
    "4. `/confirm` — upload & jadwal otomatis"
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
    try:
        return json.loads(CURRICULUM_PATH.read_text(encoding="utf-8")).get("topics", {})
    except Exception:
        return {}


def _match_curriculum_topic(text: str, topics: dict) -> str | None:
    """Cari topic di curriculum_content yang cocok dengan pertanyaan user."""
    text_lower = text.lower()
    for num, topic in topics.items():
        title_lower = topic.get("title", "").lower()
        slug = topic.get("slug", "")
        keywords = [k.lower().strip() for k in topic.get("keywords", [])]
        display = topic.get("display_name", "").lower()
        patterns = [f"#{num}", title_lower, slug.replace("-", " "), display]
        patterns.extend(k for k in keywords if len(k) > 3)
        for pat in patterns:
            if pat and pat in text_lower:
                return num
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


async def generate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Trigger GH Actions workflow to generate SD carousel."""
    if not GITHUB_PAT:
        await update.message.reply_text("GITHUB_PAT gak ada di .env, minta ke bebnya dulu~ 😏")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Contoh: /generate Macam-macam Filter 8")
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
                f"Cek: https://github.com/{GH_REPO}/actions/workflows/generate.yml"
            )
        else:
            await update.message.reply_text(f"❌ Gagal: HTTP {resp.status_code}")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")


def _latest_slides() -> tuple[str | None, list[Path]]:
    """Detect latest carousel slides in PHOTO_DIR, return (slug, files)."""
    slides = sorted((PROJECT_DIR / "resource/photos").glob("*_slide_??.png"))
    slides += sorted((PROJECT_DIR / "resource/photos").glob("edu_*_??.jpg"))
    slides += sorted((PROJECT_DIR / "resource/photos").glob("*_sd_*.png"))
    slides += sorted((PROJECT_DIR / "resource/photos").glob("*_sd_*.jpg"))
    if not slides:
        return None, []
    # Group by prefix
    groups = {}
    for s in slides:
        stem = s.stem
        if "_slide_" in stem:
            prefix = stem.rsplit("_slide_", 1)[0]
        elif "_sd_" in stem:
            prefix = stem.rsplit("_sd_", 1)[0]
        else:
            prefix = stem.rsplit("_", 1)[0]
        groups.setdefault(prefix, []).append(s)
    # Pick latest by mtime
    latest_prefix = max(groups, key=lambda k: max(groups[k], key=lambda f: f.stat().st_mtime).stat().st_mtime)
    return latest_prefix, sorted(groups[latest_prefix])


def _slug_to_topic(slug: str) -> str:
    """Convert slug to readable topic name for caption generation."""
    return slug.replace("_", " ").title()


async def _generate_caption(facts_json: dict | None, topic: str, curriculum_tag: str = "") -> str:
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
    if curriculum_tag:
        prompt_parts.append(f"Ini adalah bagian dari kurikulum {curriculum_tag}.")
    if facts_json and "facts" in facts_json:
        prompt_parts.append("\nFakta-fakta dalam konten ini:")
        for f in facts_json["facts"]:
            prompt_parts.append(f"- {f.get('number','')}. {f.get('title','')}: {f.get('description','')[:100]}")
    prompt_parts.append("\nGaya: santai, edukatif, engaging. Include ajakan diskusi. Maks 2000 karakter. Sertakan hashtag #Aquarisamatiran dan hashtag relevan lainnya di akhir.")
    body = {"contents": [{"role": "user", "parts": [{"text": _today_context() + "\n\n" + system_prompt + "\n\n" + "\n".join(prompt_parts)}]}]}

    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEYS[0]}"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(url, json=body)
        if resp.status_code == 200:
            return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        pass
    return f"{topic} — Yuk belajar bareng @aquarisamatiran! 🌱 #Aquarisamatiran #AquascapeIndonesia"


def _nearest_slot() -> str:
    """Return the nearest available schedule slot time string."""
    now = datetime.datetime.now()
    wday = now.weekday()  # Mon=0, Sun=6
    hour = now.hour
    weekday_slots = [(0, "19:00"), (1, "19:00"), (2, "19:00"), (3, "19:00")]
    fri_slot = (4, "15:00")
    weekend_slots = [(5, "09:00"), (6, "09:00")]
    weekday_12 = (0, "12:00"), (1, "12:00"), (2, "12:00"), (3, "12:00"), (4, "12:00")
    all_slots = weekday_slots + [fri_slot] + weekend_slots + list(weekday_12)
    for dw, tm in all_slots:
        days_ahead = dw - wday
        if days_ahead < 0 or (days_ahead == 0 and int(tm.split(":")[0]) <= hour):
            days_ahead += 7
        target = now + datetime.timedelta(days=days_ahead)
        return target.strftime("%Y-%m-%d") + " " + tm
    return (now + datetime.timedelta(days=1)).strftime("%Y-%m-%d") + " 19:00"


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
        emoji = {"completed": "✅", "in_progress": "🔄", "queued": "⏳", "failure": "❌", "success": "✅"}.get(status if status == "completed" else status, "❓")
        created = run["created_at"][:16].replace("T", " ")
        msg = (
            f"{emoji} Generate: **{topic}**\n"
            f"Status: **{status}** ({conclusion})\n"
            f"Dibuat: {created} WIB\n"
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
    curriculum_tag = ""
    schedule_time = ""
    # Parse args: /post [#07] [Kamis 19:00]
    non_flag = []
    for a in args:
        if a.startswith("#"):
            curriculum_tag = a
        elif re.match(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun|Senin|Selasa|Rabu|Kamis|Jumat|Sabtu|Minggu)", a, re.IGNORECASE) and len(args) > args.index(a) + 1:
            idx = list(args).index(a)
            schedule_time = f"{a} {args[idx+1]}"
            non_flag.append(a)
            non_flag.append(args[idx+1])
        else:
            non_flag.append(a)

    # Auto-detect latest slides
    slug, slides = _latest_slides()
    if not slug:
        await update.message.reply_text("❌ Ngga nemu slide carousel di resource/photos/")
        return

    # Determine schedule time
    if not schedule_time:
        # Map day to nearest slot
        nearest = _nearest_slot()
        days = {"Mon": "Senin", "Tue": "Selasa", "Wed": "Rabu", "Thu": "Kamis", "Fri": "Jumat", "Sat": "Sabtu", "Sun": "Minggu"}
        dt = datetime.datetime.strptime(nearest, "%Y-%m-%d %H:%M")
        day_name = days.get(dt.strftime("%a"), dt.strftime("%a"))
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
            media_group.append(InputMediaPhoto(media=s.open("rb")))
        except Exception:
            continue
    if media_group:
        try:
            await update.message.reply_media_group(media_group)
        except Exception:
            await update.message.reply_text("⚠️ Gagal kirim preview, lanjut aja~")

    # Generate caption
    facts_json = None
    facts_path = PROJECT_DIR / "resource/photos" / f"edu_{slug}_facts.json"
    if facts_path.exists():
        try:
            facts_json = json.loads(facts_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    topic_display = _slug_to_topic(slug)
    await update.message.reply_text(f"💬 Generate caption buat \"{topic_display}\"...")
    caption = await _generate_caption(facts_json, topic_display, curriculum_tag)

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
        "curriculum_tag": curriculum_tag,
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
    prompt = f"Instruksi: {instruction}\n\nCaption sebelumnya:\n{pending['caption'][:1500]}"
    messages = [{"role": "user", "parts": [{"text": prompt}]}]
    try:
        new_caption = await _call_gemini(messages)
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
    slug = pending["slug"]
    topic_display = pending["topic_display"]
    await update.message.reply_text(f"🔄 Generate ulang carousel \"{topic_display}\"...")
    _pending_posts.pop(user_id, None)
    try:
        import httpx
        body = '{"ref":"main","inputs":{"topic":"' + slug.replace("_", " ") + '","num_facts":"8"}}'
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
        result = subprocess.run(proc_args, capture_output=True, text=True, timeout=300, cwd=str(PROJECT_DIR))
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


async def myid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await update.message.reply_text(f"Chat ID kamu: `{uid}`", parse_mode="Markdown")


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.lower()

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
            cmd, shell=True, capture_output=True, text=True, timeout=30, cwd=str(PROJECT_DIR)
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
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("post", post_cmd))
    app.add_handler(CommandHandler("confirm", confirm_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("editcaption", editcaption_cmd))
    app.add_handler(CommandHandler("regenerate", regenerate_cmd))
    app.add_handler(CommandHandler("myid", myid_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    print("Bot jalan di VPS... chat aku dari Telegram~")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
