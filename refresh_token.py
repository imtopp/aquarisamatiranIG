"""Refresh FB_PAGE_TOKEN via Graph API — extend ke long-lived / non-expiring."""
import os
import re
import sys
import pathlib
import requests
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

APP_ID = os.getenv("IG_APP_ID", "")
APP_SECRET = os.getenv("IG_APP_SECRET", "")
USER_TOKEN = os.getenv("FB_ACCESS_TOKEN", "")  # short-lived user token
PAGE_ID = os.getenv("FB_PAGE_ID", "1169620009564150")
API_VER = "v22.0"


def exchange_user_token(short_token: str) -> str | None:
    """Tukar short-lived user token → long-lived (60 hari)."""
    url = f"https://graph.facebook.com/{API_VER}/oauth/access_token"
    params = {
        "grant_type": "fb_exchange_token",
        "client_id": APP_ID,
        "client_secret": APP_SECRET,
        "fb_exchange_token": short_token,
    }
    r = requests.get(url, params=params)
    if not r.ok:
        print(f"❌ Gagal exchange token: {r.text}")
        return None
    return r.json().get("access_token")


def get_page_token(long_user_token: str) -> str | None:
    """Ambil page access token (non-expiring) dari long-lived user token."""
    url = f"https://graph.facebook.com/{API_VER}/{PAGE_ID}"
    params = {
        "fields": "access_token",
        "access_token": long_user_token,
    }
    r = requests.get(url, params=params)
    if not r.ok:
        print(f"❌ Gagal ambil page token: {r.text}")
        return None
    return r.json().get("access_token")


def update_env(key: str, value: str):
    """Update .env file."""
    text = pathlib.Path(".env").read_text(encoding="utf-8")

    # Hapus baris #[ ]?key=... kalau ada
    # Trus ganti key=...
    pattern = re.compile(rf"^{re.escape(key)}=.*", re.MULTILINE)
    new_line = f"{key}={value}"
    if pattern.search(text):
        text = pattern.sub(new_line, text)
    else:
        text = text.rstrip("\n") + f"\n{new_line}\n"
    pathlib.Path(path).write_text(text, encoding="utf-8")
    print(f"  ✅ {key} updated di .env")


def main():
    print("🔄 Refresh FB_PAGE_TOKEN")
    print(f"  App ID: {APP_ID[:8]}...")
    print(f"  Page ID: {PAGE_ID}")

    if not USER_TOKEN:
        print("\n❌ FB_ACCESS_TOKEN kosong di .env")
        print()
        print("Langkah manual (1x aja):")
        print("1. Buka https://developers.facebook.com/tools/explorer/")
        print("2. Pilih app IG_APP_ID, pilih 'aquarisamatiran' Page")
        print("3. Tambah permissions: instagram_basic, pages_show_list, pages_read_engagement")
        print("4. Generate token → copy ke .env sebagai FB_ACCESS_TOKEN")
        print("5. Jalanin script ini lagi")
        return

    print("\n📤 Exchange user token → long-lived...")
    long_token = exchange_user_token(USER_TOKEN)
    if not long_token:
        return
    print("  ✅ Long-lived user token didapat")

    print("\n📤 Ambil page token (non-expiring)...")
    page_token = get_page_token(long_token)
    if not page_token:
        return
    print(f"  ✅ Page token: {page_token[:40]}...")

    update_env("FB_PAGE_TOKEN", page_token)
    print("\n🎉 FB_PAGE_TOKEN berhasil di-refresh!")
    print("📌 Jangan lupa update juga di GitHub Secrets → FB_PAGE_TOKEN")


if __name__ == "__main__":
    main()
