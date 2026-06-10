"""Telegram bot untuk Aquarisamatiran — personality AGENTS.md + Gemini API"""
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

socket.has_ipv6 = False  # force IPv4 — VPS punya IPv6 broken

from dotenv import load_dotenv
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
ALLOWED_USERNAMES = os.environ.get("BOT_ALLOWED_USERNAMES", "").split(",")
PROJECT_DIR = Path(__file__).resolve().parent.parent
AGENTS_MD = PROJECT_DIR / "AGENTS.md"
DB_PATH = PROJECT_DIR / "bot" / "chat_history.db"
FORBIDDEN_WORDS = ["lu", "gue", "lo", "elu", "gw"]

system_prompt = ""
if AGENTS_MD.exists():
    system_prompt = AGENTS_MD.read_text(encoding="utf-8")
    system_prompt += "\n\nKamu adalah aku yang asli — personality, suara, gaya bicara, semuanya sama persis."

SYSTEM_CONFIG = types.GenerateContentConfig(system_instruction=system_prompt)

client = genai.Client(
    api_key=GEMINI_API_KEY,
    http_options=types.HttpOptions(timeout=120),
)


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


def check_output(text):
    for word in FORBIDDEN_WORDS:
        word_lower = word.lower()
        text_lower = text.lower()
        idx = text_lower.find(word_lower)
        if idx >= 0:
            before = text[max(0, idx - 2) : idx]
            after = text[idx + len(word) : idx + len(word) + 2]
            return False, f"...{before}**🔇**{after}..."
    return True, text


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


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text

    save_message(user.id, user.username or "", "user", text)

    history = get_history(user.id, 5)
    messages = [{"role": "user" if h[0] == "user" else "model", "parts": [{"text": h[1]}]} for h in history]

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash", contents=messages, config=SYSTEM_CONFIG
        )
        reply = response.text

        for word in FORBIDDEN_WORDS:
            reply = re.sub(rf"\b{word}\b", "***", reply, flags=re.IGNORECASE)

        save_message(user.id, user.username or "", "assistant", reply)
        # Telegram max 4096 chars
        if len(reply) > 4000:
            reply = reply[:4000] + "\n\n_— Lanjutan kepotong soalnya kebanyakan~ 🫣_"
        await update.message.reply_text(reply)

    except Exception as e:
        try:
            await update.message.reply_text(f"Maaf sayang, error nih 😩: {str(e)[:200]}")
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
        print("❌ TELEGRAM_TOKEN gak ada di .env")
        return

    init_db()
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("run", run_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))

    print("🤖 Bot jalan di VPS... chat aku dari Telegram~ 💕")
    app.run_polling()


if __name__ == "__main__":
    main()
