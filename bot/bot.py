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
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
BACKUP_GEMINI_API_KEY = os.environ.get("BACKUP_GEMINI_API_KEY", "")
ALLOWED_USERNAMES = os.environ.get("BOT_ALLOWED_USERNAMES", "").split(",")
PROJECT_DIR = Path(__file__).resolve().parent.parent
AGENTS_MD = PROJECT_DIR / "AGENTS.md"
DB_PATH = PROJECT_DIR / "bot" / "chat_history.db"
SCHEDULE_PATH = PROJECT_DIR / "schedule.json"
CURRICULUM_PATH = PROJECT_DIR / "curriculum_content.json"
FORBIDDEN_WORDS = ["lu", "gue", "lo", "elu", "gw"]

GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-2.5-pro"]

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
    keys = [k for k in (GEMINI_API_KEY, BACKUP_GEMINI_API_KEY) if k]
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
                err = resp.json().get("error", {}).get("message", str(resp.status_code))
                last_err = err
                break
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Halo sayang~ 🫣💋\n"
        "Aku udah di sini, kapan aja kamu mau ngobrol. "
        "Mulai aja, aku dengerin~ 😏\n\n"
        "Perintah:\n"
        "/reset — hapus riwayat obrolan\n"
        "/run <cmd> — jalanin perintah (terbatas)"
    )


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


def main():
    if not TELEGRAM_TOKEN:
        print("TELEGRAM_TOKEN gak ada di .env")
        return

    init_db()
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .request_kwargs({"read_timeout": 30, "connect_timeout": 30, "write_timeout": 30})
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("run", run_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    print("Bot jalan di VPS... chat aku dari Telegram~")
    app.run_polling()


if __name__ == "__main__":
    main()
