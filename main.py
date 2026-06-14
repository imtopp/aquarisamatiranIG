"""Aquarisamatiran — Instagram Manager CLI"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import config
from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _notify_telegram(msg: str):
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        pass

load_dotenv()

from ig_client import InstagramClient, parse_schedule
from edit_media import replace_audio, compress_video, upload_file, copy_to_published, VIDEO_DIR, MUSIC_DIR, PHOTO_DIR, OUTPUT_DIR, PUBLISHED_DIR, MAX_UPLOAD_MB
from curriculum_manager import cmd_curriculum

import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont
import PIL.ImageFilter
from google import genai


def _extract_frames(video_path, output_dir, n_frames=4):
    from moviepy import VideoFileClip
    import imageio_ffmpeg
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    with VideoFileClip(str(video_path)) as clip:
        duration = clip.duration

    if duration <= 0:
        return []

    frames = []
    for i in range(1, n_frames + 1):
        ts = (duration / (n_frames + 1)) * i
        out = output_dir / f"frame_{i:02d}.jpg"
        subprocess.run(
            [ffmpeg, "-ss", str(ts), "-i", str(video_path),
             "-vframes", "1", "-q:v", "2", str(out), "-y"],
            capture_output=True, timeout=30,
        )
        if out.exists():
            frames.append(out)
    return frames


def pp(data):
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_profile(client, args=None):
    if args is None:
        args = []
    pp(client.get_profile())


def cmd_media(client, args):
    media = client.get_media(limit=int(args[0]) if args else 25)
    pp(media)


def cmd_post_photo(client, args):
    schedule_ts = None
    schedule_mode = None
    schedule_time_str = None
    slug = None
    filtered = []
    i = 0
    while i < len(args):
        if args[i] == "--schedule" and i + 2 < len(args) and args[i + 1] in ("ig", "cron"):
            schedule_mode = args[i + 1]
            schedule_time_str = args[i + 2]
            schedule_ts = parse_schedule(schedule_time_str)
            i += 3
        elif args[i] == "--schedule" and i + 1 < len(args):
            schedule_mode = "ig"
            schedule_time_str = args[i + 1]
            schedule_ts = parse_schedule(schedule_time_str)
            i += 2
        elif args[i] == "--slug" and i + 1 < len(args):
            slug = args[i + 1]
            i += 2
        else:
            filtered.append(args[i])
            i += 1

    if len(filtered) < 1:
        print("Gunakan: python main.py post-photo <image_url> [caption] [--schedule ig|cron \"Mon 19:00\"]")
        return

    url = filtered[0]
    caption = " ".join(filtered[1:]) if len(filtered) > 1 else ""

    if schedule_mode == "cron":
        from datetime import datetime
        dt = datetime.fromtimestamp(schedule_ts)
        _add_schedule_entry(slug or "photo", "photo", url, caption, dt.strftime("%Y-%m-%d %H:%M"))
        print(f"\n📅 Foto masuk antrian schedule.json: {dt.strftime('%Y-%m-%d %H:%M')}")
        return

    result = client.post_photo(url, caption, scheduled_publish_time=schedule_ts)
    if result.get("scheduled"):
        from datetime import datetime
        dt = datetime.fromtimestamp(result["scheduled_publish_time"])
        print(f"📅 Foto terjadwal: {dt.strftime('%A, %d %b %Y jam %H:%M')} | ID: {result.get('id')}")
    else:
        print(f"✅ Foto berhasil di-publish! ID: {result.get('id')}")


def _find_curriculum_key_by_slug(slug: str) -> str | None:
    """Cari #XX dari curriculum_content.json berdasarkan slug."""
    cpath = Path("curriculum_content.json")
    if not cpath.exists():
        return None
    try:
        cc = json.loads(cpath.read_text(encoding="utf-8"))
    except Exception:
        return None
    for sid, st in cc.get("topics", {}).items():
        for num, topic in st.items():
            if topic.get("slug") == slug or topic.get("slug", "").replace("-", "_") == slug:
                return f"#{num}"
    return None


def _add_schedule_entry(slug: str, ptype: str, urls_or_url: str | list[str],
                         caption: str, time_str: str):
    """Tambah entry ke schedule.json."""
    import json
    spath = Path("schedule.json")
    schedule = json.loads(spath.read_text(encoding="utf-8")) if spath.exists() else []
    curriculum_key = _find_curriculum_key_by_slug(slug)
    entry = {
        "curriculum": curriculum_key,
        "time": time_str,
        "type": ptype,
        "caption": caption,
        "done": False,
        "season": 1,
    }
    if ptype == "carousel":
        entry["urls"] = list(urls_or_url) if isinstance(urls_or_url, list) else [urls_or_url]
    else:
        entry["url"] = str(urls_or_url)
    schedule.append(entry)
    spath.write_text(json.dumps(schedule, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"   📝 schedule.json: {curriculum_key or slug} ({ptype}) dijadwalkan {time_str}")


def cmd_post_carousel(client, args):
    schedule_ts = None
    slug_filter = None
    upload_only = False
    schedule_mode = None  # None = langsung, "ig" = IG schedule, "cron" = schedule.json
    schedule_time_str = None
    filtered = []
    i = 0
    while i < len(args):
        if args[i] == "--schedule" and i + 2 < len(args) and args[i + 1] in ("ig", "cron"):
            schedule_mode = args[i + 1]
            schedule_time_str = args[i + 2]
            schedule_ts = parse_schedule(schedule_time_str)
            i += 3
        elif args[i] == "--schedule" and i + 1 < len(args):
            schedule_mode = "ig"
            schedule_time_str = args[i + 1]
            schedule_ts = parse_schedule(schedule_time_str)
            i += 2
        elif args[i] == "--upload-only":
            upload_only = True
            i += 1
        elif args[i] == "--slug" and i + 1 < len(args):
            slug_filter = args[i + 1]
            i += 2
        else:
            filtered.append(args[i])
            i += 1

    caption = " ".join(filtered) if filtered else ""

    # Auto-detect slide terbaru
    slides = sorted(PHOTO_DIR.glob("*_slide_??.png")) + sorted(PHOTO_DIR.glob("edu_*_??.jpg")) + sorted(PHOTO_DIR.glob("*_sd_*.png"))
    if not slides:
        print("❌ Ngga ada slide carousel di resource/photos/")
        print()
        print("Generate dulu ya: python main.py generate-carousel <topik>")
        return

    # Kelompokin berdasarkan prefix
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

    if slug_filter:
        if slug_filter not in groups:
            tersedia = ", ".join(sorted(groups))
            print(f"❌ Slug '{slug_filter}' ngga ditemukan. Tersedia: {tersedia}")
            return
        latest_prefix = slug_filter
    else:
        latest_prefix = max(groups, key=lambda k: max(groups[k], key=lambda f: f.stat().st_mtime).stat().st_mtime)

    latest = sorted(groups[latest_prefix])
    print(f"📋 Detected {len(latest)} slide: {', '.join(f.name for f in latest)}")

    if not caption:
        print("💬 Caption belum dikasih. Mau pake caption apa?")
        print("  python main.py post-carousel \"caption di sini\"")
        print("  python main.py post-carousel --slug <nama_slug> \"caption\"")
        return

    print(f"📤 Upload {len(latest)} slide ke Catbox...")
    urls = []
    from PIL import Image
    import io
    for p in latest:
        print(f"  Upload {p.name}...")
        upload_path = p
        # Auto-compress PNG >500KB ke JPEG biar IG gak timeout
        if p.suffix.lower() == ".png" and p.stat().st_size > 500 * 1024:
            jpg_path = p.with_suffix(".jpg")
            if not jpg_path.exists():
                Image.open(p).convert("RGB").save(jpg_path, "JPEG", quality=82, optimize=True)
            upload_path = jpg_path
            print(f"   🗜️  Kompres ke JPEG ({upload_path.stat().st_size // 1024} KB)")
        url = upload_file(upload_path)
        _save_map(url, str(upload_path))
        urls.append(url)
        print(f"   ✅ {url}")

    if upload_only:
        print()
        print(f"📌 Upload-only mode — ngga dipublish ke IG")
        print(f"   URLs siap: {urls[0]} ... ({len(urls)} file)")
        _update_curriculum_content(latest_prefix, facts=None)
        return

    if schedule_mode == "cron":
        from datetime import datetime
        dt = datetime.fromtimestamp(schedule_ts)
        time_str = dt.strftime("%Y-%m-%d %H:%M")
        _add_schedule_entry(latest_prefix, "carousel", urls, caption, time_str)
        _update_curriculum_content(latest_prefix, status="scheduled")
        print(f"\n📅 Carousel masuk antrian schedule.json: {time_str}")
        return

    # IG langsung
    if schedule_ts and schedule_mode == "ig":
        print(f"   ⚠️  Carousel scheduling via IG butuh whitelist — fallback ke cron mode")
        from datetime import datetime
        dt = datetime.fromtimestamp(schedule_ts)
        _add_schedule_entry(latest_prefix, "carousel", urls, caption, dt.strftime("%Y-%m-%d %H:%M"))
        _update_curriculum_content(latest_prefix, status="scheduled")
        print(f"\n📅 Carousel masuk antrian schedule.json: {dt.strftime('%Y-%m-%d %H:%M')}")
        return

    result = client.post_carousel(urls, caption, scheduled_publish_time=None)
    media_id = result.get("id")
    print(f"✅ Carousel berhasil di-publish! ID: {media_id}")

    # Simpan ke published/
    for p in latest:
        _save_to_published(p, media_id, group_slug=latest_prefix)

    # Update curriculum_content.json
    _update_curriculum_content(latest_prefix, result_id=media_id, status="live")


_UPLOAD_MAP = Path("resource") / ".uploaded.json"


def _map_file() -> dict:
    if _UPLOAD_MAP.exists():
        return json.loads(_UPLOAD_MAP.read_text())
    return {}


def _save_map(url: str, local_path: str):
    data = _map_file()
    data[url] = str(local_path)
    _UPLOAD_MAP.write_text(json.dumps(data, indent=2))


def cmd_post_reel(client, args):
    schedule_ts = None
    schedule_mode = None
    schedule_time_str = None
    slug = None
    filtered = []
    i = 0
    while i < len(args):
        if args[i] == "--schedule" and i + 2 < len(args) and args[i + 1] in ("ig", "cron"):
            schedule_mode = args[i + 1]
            schedule_time_str = args[i + 2]
            schedule_ts = parse_schedule(schedule_time_str)
            i += 3
        elif args[i] == "--schedule" and i + 1 < len(args):
            schedule_mode = "ig"
            schedule_time_str = args[i + 1]
            schedule_ts = parse_schedule(schedule_time_str)
            i += 2
        elif args[i] == "--slug" and i + 1 < len(args):
            slug = args[i + 1]
            i += 2
        else:
            filtered.append(args[i])
            i += 1

    if len(filtered) < 1:
        print("Gunakan: python main.py post-reel <video_url> [caption] [--schedule ig|cron \"Mon 19:00\"]")
        return
    url = filtered[0]
    caption = " ".join(filtered[1:]) if len(filtered) > 1 else ""

    if schedule_mode == "cron":
        from datetime import datetime
        dt = datetime.fromtimestamp(schedule_ts)
        _add_schedule_entry(slug or "reel", "reel", url, caption, dt.strftime("%Y-%m-%d %H:%M"))
        print(f"\n📅 Reel masuk antrian schedule.json: {dt.strftime('%Y-%m-%d %H:%M')}")
        return

    result = client.post_reel(url, caption, scheduled_publish_time=schedule_ts)
    if result.get("scheduled"):
        from datetime import datetime
        dt = datetime.fromtimestamp(result["scheduled_publish_time"])
        print(f"📅 Reel terjadwal: {dt.strftime('%A, %d %b %Y jam %H:%M')} | ID: {result.get('id')}")
    else:
        print(f"✅ Reel berhasil di-publish! ID: {result.get('id')}")
    if result.get("id"):
        local = Path(_map_file().get(url, ""))
        if local.exists():
            _save_to_published(local, result["id"])
        else:
            print("⚠️  File lokal ngga ketemu — publish ok, tapi referensi ngga disimpan")


def cmd_comments(client, args):
    if not args:
        print("Gunakan: python main.py comments <media_id>")
        return
    pp(client.get_comments(args[0]))


def cmd_reply(client, args):
    if len(args) < 2:
        print("Gunakan: python main.py reply <comment_id> <pesan>")
        return
    result = client.reply_comment(args[0], " ".join(args[1:]))
    print(f"✅ Balasan terkirim! ID: {result.get('id')}")


def cmd_insights(client, args):
    if not args:
        pp(client.get_account_insights())
    else:
        pp(client.get_media_insights(args[0]))


def cmd_search_hashtag(client, args):
    if not args:
        print("Gunakan: python main.py search-hashtag <tag>")
        return
    pp(client.search_hashtag(args[0].lstrip("#")))


def cmd_prepare_reel(_client, args):
    if len(args) < 2:
        print("Gunakan: python main.py prepare-reel <nama_video> <nama_music>")
        print()
        print("  Video di resource/videos/, music di resource/music/")
        print("  Hasil di resource/output/, referensi di resource/published/")
        _list_files("video", VIDEO_DIR)
        _list_files("music", MUSIC_DIR)
        return
    video_name = args[0]
    music_name = args[1]
    video_path = VIDEO_DIR / video_name
    music_path = MUSIC_DIR / music_name
    if not video_path.exists():
        print(f"❌ Video '{video_name}' ngga ditemukan di resource/videos/")
        return
    if not music_path.exists():
        print(f"❌ Music '{music_name}' ngga ditemukan di resource/music/")
        return
    print("🎬 Lagi edit video...")
    output = replace_audio(video_path, music_path, video_volume=0.0, music_volume=1.0)
    print(f"✅ Hasil edit: {output}")
    print()
    print("🎯 Lanjut ke step berikutnya:")
    print(f"   python main.py stage-reel {output.name}   # upload + caption")


def _find_video(name):
    for base_dir in [VIDEO_DIR, OUTPUT_DIR]:
        p = base_dir / name
        if p.exists():
            return p
    return None


def _generate_captions(video_path):
    print("🎞️  Extract frames...")
    with tempfile.TemporaryDirectory() as tmpdir:
        frames = _extract_frames(video_path, Path(tmpdir))
        if not frames:
            print("❌ Gagal extract frames dari video")
            return None
        imgs = [PIL.Image.open(p).copy() for p in frames]

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ GEMINI_API_KEY ngga ditemukan di .env")
        return None

    print("🤖 Generate caption pake Gemini...")
    niche = config.current_niche
    client = genai.Client(api_key=api_key)
    prompt = (
        f"Kamu adalah social media manager Instagram {niche.handle} ({niche.niche_name}). "
        "Berdasarkan cuplikan video berikut, buat 3 opsi caption IG yang menarik, casual, "
        "pake Bahasa Indonesia + emoji + hashtag relevan. "
        "Catatan penting:\n"
        f"- Misi akun: {niche.mission_blurb}\n"
        "- Tiap caption harus mendorong diskusi di kolom komentar — ajak ngobrol, "
        "kasi pertanyaan, bikin orang mau reply.\n"
        "- Tujuan: bangun komunitas setia & follower growth organik.\n"
        "Format:\n\n"
        "--- Opsi 1 ---\n[caption]\n--- Hashtag ---\n[hashtags]\n\n"
        "--- Opsi 2 ---\n[caption]\n--- Hashtag ---\n[hashtags]\n\n"
        "--- Opsi 3 ---\n[caption]\n--- Hashtag ---\n[hashtags]"
    )

    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash", contents=[prompt, *imgs]
        )
        return response.text
    except Exception as e:
        return f"❌ Gagal: {e}"


def cmd_stage_reel(_client, args):
    if not args:
        print("Gunakan: python main.py stage-reel <nama_file_video>")
        print()
        _list_files("video", VIDEO_DIR)
        _list_files("output", OUTPUT_DIR)
        return

    name = args[0]
    video_path = _find_video(name)
    if not video_path:
        print(f"❌ Video '{name}' ngga ditemukan di resource/videos/ atau resource/output/")
        return

    size_mb = video_path.stat().st_size / (1024 * 1024)

    if size_mb > MAX_UPLOAD_MB:
        print(f"📏 Ukuran file: {size_mb:.0f}MB (max Catbox {MAX_UPLOAD_MB}MB)")
        print("🗜️  Lagi kompres (keep original audio)...")
        video_path = compress_video(video_path)
        size_mb = video_path.stat().st_size / (1024 * 1024)
        print(f"✅ Hasil kompres: {video_path.name} ({size_mb:.0f}MB)")

        if size_mb > MAX_UPLOAD_MB:
            print(f"⚠️  Masih {size_mb:.0f}MB, kualitas diturunin...")
            video_path = compress_video(video_path, quality="medium")
            size_mb = video_path.stat().st_size / (1024 * 1024)

    print("📤 Upload ke Catbox...")
    url = upload_file(video_path)
    _save_map(url, str(video_path))
    print(f"✅ URL: {url}")

    captions = _generate_captions(video_path)
    if captions:
        print("\n" + "=" * 60)
        print(captions)
        print("=" * 60)

    print()
    print("📋 Copy URL & caption di atas, terus kirim pake:")
    print(f"   python main.py post-reel {url} \"<caption>\"")


def _generate_photo_captions(photo_path: Path):
    """Generate caption dari foto pake Gemini."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ GEMINI_API_KEY ngga ditemukan di .env")
        return None

    print("🤖 Generate caption dari gambar pake Gemini...")
    niche = config.current_niche
    client = genai.Client(api_key=api_key)
    img = PIL.Image.open(photo_path)
    prompt = (
        f"Kamu adalah social media manager Instagram {niche.handle} ({niche.niche_name}). "
        f"Berdasarkan {niche.photo_description} berikut, buat 3 opsi caption IG yang menarik, casual, "
        "pake Bahasa Indonesia + emoji + hashtag relevan. "
        "Catatan penting:\n"
        f"- Misi akun: {niche.mission_blurb}\n"
        "- Tiap caption harus mendorong diskusi di kolom komentar — ajak ngobrol, "
        "kasi pertanyaan, bikin orang mau reply.\n"
        "- Tujuan: bangun komunitas setia & follower growth organik.\n"
        "Format:\n\n"
        "--- Opsi 1 ---\n[caption]\n--- Hashtag ---\n[hashtags]\n\n"
        "--- Opsi 2 ---\n[caption]\n--- Hashtag ---\n[hashtags]\n\n"
        "--- Opsi 3 ---\n[caption]\n--- Hashtag ---\n[hashtags]"
    )

    try:
        response = client.models.generate_content(
            model="gemini-3.5-flash", contents=[prompt, img]
        )
        return response.text
    except Exception as e:
        return f"❌ Gagal: {e}"


def cmd_stage_photo(_client, args):
    if not args:
        print("Gunakan: python main.py stage-photo <nama_file_foto> [--crop / --no-crop]")
        print()
        _list_files("foto", PHOTO_DIR)
        return

    crop_flag = None
    filtered = []
    for a in args:
        if a == "--crop":
            crop_flag = True
        elif a == "--no-crop":
            crop_flag = False
        else:
            filtered.append(a)

    if not filtered:
        print("Gunakan: python main.py stage-photo <nama_file_foto> [--crop / --no-crop]")
        print()
        _list_files("foto", PHOTO_DIR)
        return

    name = filtered[0]
    photo_path = PHOTO_DIR / name
    if not photo_path.exists():
        print(f"❌ Foto '{name}' ngga ditemukan di resource/photos/")
        return

    # Interactive crop step
    from PIL import Image
    img = Image.open(photo_path)
    w, h = img.size
    ratio = w / h
    TARGET_RATIO = 4 / 5  # 0.8

    if abs(ratio - TARGET_RATIO) > 0.01:
        print(f"\n📐 Foto: {w}x{h} — bukan 4:5 (rasio {ratio:.2f}, ideal 0.80)")
        if ratio > TARGET_RATIO:
            print(f"   ➡️  Foto terlalu lebar — crop samping kiri-kanan")
        else:
            print(f"   ➡️  Foto terlalu tinggi — crop atas-bawah")

        if crop_flag is None:
            print("   ──")
            print("   Mau di-crop ke 4:5? Tambahin --crop (iya) / --no-crop (biarin)")
            print("   Contoh: python main.py stage-photo \"foto.jpg\" --crop")
            return
        if crop_flag:
            if ratio > TARGET_RATIO:
                new_w = int(h * TARGET_RATIO)
                left = (w - new_w) // 2
                img = img.crop((left, 0, left + new_w, h))
            else:
                new_h = int(w / TARGET_RATIO)
                top = (h - new_h) // 2
                img = img.crop((0, top, w, top + new_h))
            img = img.resize((1080, 1350), Image.LANCZOS)
            img.save(photo_path)
            print(f"   ✅ Crop 4:5 selesai -> {photo_path.name} (1080x1350)\n")

    print("📤 Upload ke Catbox...")
    url = upload_file(photo_path)
    _save_map(url, str(photo_path))
    print(f"✅ URL: {url}")

    captions = _generate_photo_captions(photo_path)
    if captions:
        print("\n" + "=" * 60)
        print(captions)
        print("=" * 60)

    print()
    print("📋 Copy URL & caption di atas, terus kirim pake:")
    print(f"   python main.py post-photo {url} \"<caption>\"")


def cmd_generate_caption(_client, args):
    if not args:
        print("Gunakan: python main.py generate-caption <nama_file_video>")
        print()
        _list_files("video", VIDEO_DIR)
        _list_files("output", OUTPUT_DIR)
        return

    name = args[0]
    video_path = _find_video(name)
    if not video_path:
        print(f"❌ Video '{name}' ngga ditemukan")
        return

    captions = _generate_captions(video_path)
    if captions:
        print("\n" + "=" * 60)
        print(captions)
        print("=" * 60)


def _generate_slide_plan(topic: str, n_slides: int = 4):
    """Generate slide plan (titles + body text + image desc) dari Gemini."""
    import time

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ GEMINI_API_KEY ngga ditemukan di .env")
        return None

    niche = config.current_niche
    ct = config.current_content_type
    client = genai.Client(api_key=api_key)
    slide_structure = "\n".join(
        f"{i+1}. {s}" for i, s in enumerate(ct.slide_structure[:n_slides])
    )
    desc = ct.pexels_desc or niche.pexels_image_desc
    prompt = (
        f"Kamu adalah kreator {niche.education_label} {niche.handle} ({niche.niche_name}).\n"
        f"Buat {n_slides} slide {ct.label} tentang \"{topic}\" buat konten Instagram carousel "
        f"dengan gaya infografis casual.\n\n"
        f"{ct.instruction.format(topic=topic) if '{topic}' in ct.instruction else f'{ct.instruction} tentang {topic}'}.\n\n"
        f"Struktur {n_slides} slide:\n"
        f"{slide_structure}\n\n"
        f"Output JSON array aja, setiap objek punya:\n"
        f"- \"title\": judul slide (max 40 karakter, Bahasa Indonesia, casual)\n"
        f"- \"body\": teks penjelasan (max 120 karakter, 2-3 kalimat pendek)\n"
        f"- \"desc\": deskripsi visual buat prompt gambar Pexels ({desc})\n"
        f"Hanya JSON, tanpa teks lain."
    )

    for attempt in range(3):
        try:
            resp = client.models.generate_content(model="gemini-3.5-flash", contents=[prompt])
            text = resp.text.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as e:
            err = str(e)
            if "503" in err:
                print(f"   ⏳ Gemini sibuk, coba lagi ({attempt+1}/3)...")
                time.sleep(5)
            else:
                print(f"❌ Gagal generate slide plan: {e}")
                return None
    print("❌ Gagal generate slide plan setelah 3x percobaan")
    return None


def _wrap_text(text, font, max_width, draw):
    """Wrap text biar muat dalam max_width pixel."""
    words = text.split()
    lines = []
    current = ""
    for w in words:
        test = f"{current} {w}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        w_px = bbox[2] - bbox[0]
        if w_px <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = w
    if current:
        lines.append(current)
    return lines


def _make_edu_slide(bg_img, title, body, slide_num, total):
    """Overlay teks infografis di atas background image."""
    W, H = 1080, 1080

    # Crop center biar 1:1 tanpa distorsi
    w, h = bg_img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    bg_img = bg_img.crop((left, top, left + side, top + side))
    bg = bg_img.resize((W, H), PIL.Image.LANCZOS).convert("RGBA")
    draw = PIL.ImageDraw.Draw(bg, "RGBA")

    pad = 60
    usable_w = W - 2 * pad

    try:
        font_title = PIL.ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 52)
        font_body = PIL.ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 36)
        font_meta = PIL.ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 26)
    except Exception:
        font_title = PIL.ImageFont.load_default()
        font_body = PIL.ImageFont.load_default()
        font_meta = PIL.ImageFont.load_default()

    # --- TOP overlay (title) ---
    tt_bbox = draw.textbbox((0, 0), title, font=font_title)
    tt_h = tt_bbox[3] - tt_bbox[1]
    top_h = tt_h + 60
    overlay_top = PIL.Image.new("RGBA", (W, top_h), (0, 0, 0, 170))
    bg.paste(overlay_top, (0, 0), overlay_top)
    draw.text((pad, 30), title, fill="white", font=font_title)

    # --- BOTTOM overlay (body text) ---
    body_lines = _wrap_text(body, font_body, usable_w, draw)
    line_h = 48
    body_h = len(body_lines) * line_h + 110
    bottom_y = H - body_h
    overlay_bot = PIL.Image.new("RGBA", (W, body_h), (0, 0, 0, 170))
    bg.paste(overlay_bot, (0, bottom_y), overlay_bot)
    y = bottom_y + 30
    for line in body_lines:
        draw.text((pad, y), line, fill="white", font=font_body)
        y += line_h

    # watermark & slide number
    draw.text((pad, H - 50), config.IG_HANDLE, fill=(255, 255, 255, 180), font=font_meta)
    num_text = f"{slide_num}/{total}"
    n_bbox = draw.textbbox((0, 0), num_text, font=font_meta)
    n_w = n_bbox[2] - n_bbox[0]
    draw.text((W - pad - n_w, H - 50), num_text, fill=(255, 255, 255, 180), font=font_meta)

    return bg.convert("RGB")


def _make_gradient_bg(theme: str = "aquascape"):
    """Buat background gradien sesuai tema niche."""
    W, H = 1080, 1080
    bg = PIL.Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = PIL.ImageDraw.Draw(bg, "RGBA")

    if theme == "aquascape":
        for y in range(H):
            t = y / H
            r = int(10 + t * 5)
            g = int(50 + t * 60)
            b = int(100 + t * 40)
            draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

        for bx in range(0, W, 60):
            bh = 200 + int(80 * (bx / W))
            bw = 30 + int(15 * (bx / W) ** 0.5)
            draw.ellipse([bx, H - bh, bx + bw, H], fill=(5, 40, 30, 200))
            draw.ellipse([bx + 10, H - bh - 40, bx + bw + 10, H], fill=(5, 45, 35, 150))

        bubbles = [(120, 300, 15), (850, 200, 20), (400, 400, 10), (700, 550, 12),
                   (950, 600, 8), (200, 650, 18), (550, 150, 14)]
        for cx, cy, r in bubbles:
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, 25))
            draw.ellipse([cx - r + 2, cy - r + 2, cx + r - 4, cy + r - 4], fill=(255, 255, 255, 15))

        for fx, fy in [(250, 400), (700, 350), (550, 550)]:
            draw.ellipse([fx, fy, fx + 25, fy + 8], fill=(255, 200, 100, 40))
            draw.polygon([(fx + 25, fy), (fx + 35, fy + 4), (fx + 25, fy + 8)], fill=(255, 200, 100, 40))
    else:
        for y in range(H):
            t = y / H
            r = int(20 + t * 15)
            g = int(20 + t * 15)
            b = int(40 + t * 25)
            draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

    return bg


def _pexels_search_results(query: str, per_page: int = 5) -> list[tuple[str, str]]:
    """Search Pexels, return list of (image_url, alt_text)."""
    import requests
    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        return []
    headers = {"Authorization": api_key}
    url = f"https://api.pexels.com/v1/search?query={requests.utils.quote(query)}&per_page={per_page}&orientation=square"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return []
        return [(p["src"]["large"], p.get("alt", "")) for p in r.json().get("photos", [])]
    except Exception:
        return []


def _search_pexels_image(query: str):
    """Cari & download gambar dari Pexels. Return PIL Image objek."""
    import requests
    from io import BytesIO

    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        print("   ❌ PEXELS_API_KEY ngga ditemukan di .env")
        return None

    headers = {"Authorization": api_key}
    url = f"https://api.pexels.com/v1/search?query={requests.utils.quote(query)}&per_page=5&orientation=square"

    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            print(f"   ❌ Pexels error: {r.status_code}")
            return None

        photos = r.json().get("photos", [])
        if not photos:
            print("   ❌ Ngga ada hasil di Pexels")
            return None

        # Pilih foto pertama
        img_url = photos[0]["src"]["large"]
        alt_text = photos[0].get("alt", "")

        # Download image
        img_resp = requests.get(img_url, timeout=20)
        if img_resp.status_code != 200:
            return None

        img = PIL.Image.open(BytesIO(img_resp.content))
        print(f"   📷 Pexels: {alt_text[:60]}")
        return img
    except Exception as e:
        print(f"   ❌ Pexels error: {e}")
        return None


# ---------------------------------------------------------------------------
# Stable Diffusion local
# ---------------------------------------------------------------------------
_sd_pipe_instance = None


def _sd_pipe():
    global _sd_pipe_instance
    if _sd_pipe_instance is None:
        import time
        from diffusers import StableDiffusionPipeline
        import torch
        print("   🧠 Loading SD pipeline (CPU)...")
        t0 = time.time()
        _sd_pipe_instance = StableDiffusionPipeline.from_pretrained(
            "runwayml/stable-diffusion-v1-5", torch_dtype=torch.float32
        )
        print(f"   ✅ SD loaded in {time.time()-t0:.1f}s")
    return _sd_pipe_instance


def _sd_generate(prompt: str, size: tuple = (512, 512)) -> PIL.Image.Image | None:
    try:
        import time
        pipe = _sd_pipe()
        print(f"   🎨 SD generating: {prompt[:60]}...")
        t0 = time.time()
        img = pipe(prompt, num_inference_steps=20, height=size[1], width=size[0]).images[0]
        print(f"   ✅ SD done in {time.time()-t0:.1f}s")
        return img
    except Exception as e:
        print(f"   ❌ SD error: {e}")
        return None


def _darken_bg(img: PIL.Image.Image, opacity: float = 0.55) -> PIL.Image.Image:
    """Overlay semi-transparent dark gradient for text readability."""
    from carousel.composer import draw_gradient_bg
    dark = draw_gradient_bg(img.size, "#000000", "#000000")
    dark.putalpha(int(255 * opacity))
    img = img.convert("RGBA")
    img = PIL.Image.alpha_composite(img, dark)
    return img


def cmd_generate_carousel_sd(_client, args):
    """Generate carousel with SD backgrounds + Pillow text overlay."""
    import argparse
    import json
    import re
    import time
    from pathlib import Path
    from sources.facts_generator import generate_facts
    from carousel.slide_cover import build_cover
    from carousel.slide_fact import build_fact_slide
    from carousel.slide_cta import build_cta_slide

    parser = argparse.ArgumentParser(prog="generate-carousel-sd", add_help=False)
    parser.add_argument("topic", nargs="?", help="topik konten")
    parser.add_argument("--num-facts", type=int, default=4, help="jumlah fakta (default: 4)")
    parsed = parser.parse_known_args(args)[0]

    if not parsed.topic:
        print("Gunakan: python main.py generate-carousel-sd <topik> [--num-facts N]")
        print()
        print("  topik       — topik konten (contoh: Ikan Cupang)")
        print("  --num-facts — jumlah fakta (default: 4)")
        print()
        print("Contoh:")
        print("  python main.py generate-carousel-sd 'Ikan Cupang'")
        return

    topic = parsed.topic
    slug = re.sub(r'[^\w\-]', '', topic.lower().replace(" ", "_").replace("-", "_"))[:30].rstrip("_")

    # Resolve S1#07 / #07 ke nama topik asli dari curriculum
    topic_name = topic
    season_tag = ""
    try:
        cc_path = Path("curriculum_content.json")
        if cc_path.exists():
            cc = json.loads(cc_path.read_text(encoding="utf-8"))
            m = re.match(r"S(\d+)#(\d+)", topic)
            if m:
                s_num, t_num = m.group(1), m.group(2).zfill(2)
                t = cc.get("topics", {}).get(s_num, {}).get(t_num)
                if t:
                    topic_name = t.get("display_name", t.get("title", topic))
                    season_tag = f"S{s_num}#{t_num} "
                    slug = t.get("slug", slug).replace("-", "_")
            else:
                t_num = topic.lstrip("#").zfill(2)
                for s_num, ts in cc.get("topics", {}).items():
                    if t_num in ts:
                        t = ts[t_num]
                        topic_name = t.get("display_name", t.get("title", topic))
                        season_tag = f"S{s_num}#{t_num} "
                        slug = t.get("slug", slug).replace("-", "_")
                        break
    except Exception:
        pass

    # Cleanup old slides for this slug
    for f in list(PHOTO_DIR.glob(f"{slug}_sd_*")) + list(PHOTO_DIR.glob(f"{slug}_slide_*")):
        f.unlink(missing_ok=True)
        print(f"   🗑️  Hapus slide lama: {f.name}")

    print(f"📝 Generate facts untuk \"{topic_name}\"...")
    try:
        facts = generate_facts(topic_name, parsed.num_facts)
    except Exception as e:
        print(f"❌ Gagal generate facts: {e}")
        return

    n_facts = len(facts.get("facts", []))
    display = facts.get("display_name", topic_name)
    # Kalau udah resolve dari curriculum, pake display_name/topic_name dari curriculum, bukan hasil Gemini
    if season_tag:
        display = topic_name
    print(f"\n📋 {n_facts} fakta tentang {display}:")

    # Fallback: cari season_tag dari topic asli (kalau pake #XX)
    if not season_tag:
        try:
            cc_path = Path("curriculum_content.json")
            if cc_path.exists():
                cc = json.loads(cc_path.read_text(encoding="utf-8"))
                t_num = topic.lstrip("#").zfill(2)
                for s_num, ts in cc.get("topics", {}).items():
                    if t_num in ts:
                        t = ts[t_num]
                        season_tag = f"S{s_num}#{t_num} "
                        display = t.get("display_name", display)
                        break
        except Exception:
            pass

    for f in facts["facts"]:
        print(f"   {f['number']}. {f['title']}")

    os.makedirs(PHOTO_DIR, exist_ok=True)
    saved = []
    topic_tag = f"[{season_tag}{display}]"

    _notify_telegram(f"{topic_tag} Proses dimulai untuk generate carousel.")

    # Prompt builder per slide type
    def _bg_prompt(slide_type: str, fact: dict | None = None) -> str:
        base = "aquascape aquarium, underwater planted tank, aquatic plant, "
        if slide_type == "cover":
            return base + f"beautiful {topic} as main subject, vibrant colors, professional aquarium photography, soft lighting, high detail, photorealistic"
        elif slide_type == "fact":
            return base + f"{fact.get('title', topic)}, {fact.get('description', '')[:80] if fact else topic}, detailed macro shot, natural aquascape environment, tranquil underwater scene"
        else:  # cta
            return base + "peaceful aquascape with lush greenery, gentle water flow, morning light, serene underwater garden, high quality"

    total_slides = n_facts + 2  # cover + facts + cta
    slide_idx = 0

    def _notify_progress(label: str, title: str):
        nonlocal slide_idx
        slide_idx += 1
        _notify_telegram(f"{topic_tag} Proses gambar {slide_idx}/{total_slides} — \"{title}\" dimulai...")

    def _notify_done(label: str, title: str):
        _notify_telegram(f"{topic_tag} Generate gambar {slide_idx}/{total_slides} — \"{title}\" selesai!")

    # --- Cover slide ---
    print(f"\n🖼️ [1/{n_facts+2}] Cover: {display}")
    _notify_progress("cover", "Cover")
    raw = _sd_generate(_bg_prompt("cover"))
    if raw:
        bg = _darken_bg(raw.resize((1080, 1080), PIL.Image.LANCZOS))
        slide = build_cover(facts, None, bg_image=bg)
        fname = f"{slug}_sd_01_cover.png"
        slide.save(PHOTO_DIR / fname)
        saved.append(fname)
        print(f"   ✅ {fname}")
        _notify_done("cover", "Cover")
    else:
        print(f"   ⚠️  Cover gagal")

    # --- Fact slides ---
    for i, f in enumerate(facts.get("facts", [])):
        title = f.get("title", f"Fakta {f['number']}")
        print(f"\n🖼️ [{i+2}/{n_facts+2}] Fact {f['number']}: {title}")
        _notify_progress("fact", title)
        raw = _sd_generate(_bg_prompt("fact", f))
        if raw:
            bg = _darken_bg(raw.resize((1080, 1080), PIL.Image.LANCZOS))
            slide = build_fact_slide(f, None, bg_image=bg)
            fname = f"{slug}_sd_{i+2:02d}_fact_{f['number']}.png"
            slide.save(PHOTO_DIR / fname)
            saved.append(fname)
            print(f"   ✅ {fname}")
            _notify_done("fact", title)
        else:
            print(f"   ⚠️  Fact {f['number']} gagal")
        if i < n_facts - 1:
            print("   ⏳ Cooldown 5s before next SD gen...")
            time.sleep(5)

    # --- CTA slide ---
    print(f"\n🖼️ [{n_facts+2}/{n_facts+2}] CTA")
    _notify_progress("cta", "CTA")
    raw = _sd_generate(_bg_prompt("cta"))
    if raw:
        bg = _darken_bg(raw.resize((1080, 1080), PIL.Image.LANCZOS))
        slide = build_cta_slide(facts, None, bg_image=bg)
        fname = f"{slug}_sd_{n_facts+2:02d}_cta.png"
        slide.save(PHOTO_DIR / fname)
        saved.append(fname)
        _notify_done("cta", "CTA")
        print(f"   ✅ {fname}")
    else:
        print(f"   ⚠️  CTA gagal")

    _notify_telegram(f"{topic_tag} Proses generate carousel selesai! 🎉")
    _notify_telegram(f"Gunakan `/post` di Telegram buat review & posting.")

    print(f"\n{'='*40}")
    if saved:
        print(f"✅ {len(saved)} slide saved di {PHOTO_DIR}:")
        for f in saved:
            print(f"   - {f}")
        print()
        print("📋 Upload via:")
        print(f"   python main.py post-carousel --upload-only --slug {slug}")
    else:
        print("❌ Nggak ada slide yang berhasil digenerate")
    print(f"{'='*40}")


def cmd_compress_slides(_client, args):
    from pathlib import Path
    from PIL import Image
    for f in sorted(Path(PHOTO_DIR).glob("*_sd_*.png")):
        sz = f.stat().st_size
        if sz > 500 * 1024:
            jpg = f.with_suffix(".jpg")
            Image.open(f).convert("RGB").save(jpg, "JPEG", quality=82, optimize=True)
            print(f"Compressed {f.name} ({sz//1024}KB -> {jpg.stat().st_size//1024}KB)")
            f.unlink(missing_ok=True)
    print("Compression done")


def cmd_generate_carousel(_client, args):
    import argparse
    parser = argparse.ArgumentParser(prog="generate-carousel", add_help=False)
    parser.add_argument("topic", nargs="?", help="nama ikan/tanaman/topik edukasi")
    parser.add_argument("--type", default=None, help="tipe konten (edu, story, humor, dll)")
    parser.add_argument("--facts", help="pake file facts JSON yang udah ada (skip Gemini)")
    parser.add_argument("--num-facts", type=int, default=4, help="jumlah fakta (default: 4)")
    parser.add_argument("--force-image", help="paksa pake file foto lokal daripada dari Wikimedia")
    parsed, _ = parser.parse_known_args(args)

    # Set content type
    if parsed.type:
        ok = config.set_content_type(parsed.type)
        if not ok:
            return
    ct = config.current_content_type

    if not parsed.topic:
        niche = config.current_niche
        niche_list = ", ".join(config._NICHE_REGISTRY)
        type_list = ", ".join(niche.content_types)
        print("Gunakan: python main.py generate-carousel <topik> [--type TIPE] [--facts file.json] [--num-facts N] [--force-image foto.jpg] [--niche NAMA]")
        print()
        print("  topik                — topik konten (contoh: Nannostomus mortenthaleri)")
        print("  --type TIPE          — tipe konten")
        print(f"                         Tersedia: {type_list}")
        print("  --facts file.json    — pake facts existing (skip Gemini)")
        print("  --num-facts N        — jumlah fakta (default: 4)")
        print("  --force-image foto   — pake foto lokal daripada dari Wikimedia")
        print("  --niche NAMA         — pilih niche (default: aquascape)")
        print(f"                         Tersedia: {niche_list}")
        print()
        print("Contoh:")
        print("  python main.py generate-carousel Nannostomus mortenthaleri")
        print("  python main.py generate-carousel 'Resep Nasi Goreng' --niche food --type recipe")
        print("  python main.py generate-carousel 'Perjalanan tank pertamaku' --type story")
        return

    from sources.facts_generator import generate_facts
    from sources.wikimedia import get_wikimedia_image
    from sources.inaturalist import get_inaturalist_image
    from sources.image_utils import prepare_subject_image
    from carousel.slide_cover import build_cover
    from carousel.slide_fact import build_fact_slide
    from carousel.slide_cta import build_cta_slide

    topic = parsed.topic
    import re
    slug = re.sub(r'[^\w\-]', '', topic.lower().replace(" ", "_").replace("-", "_"))[:30].rstrip("_")

    # --- Facts ---
    if parsed.facts:
        facts_path = PHOTO_DIR / parsed.facts
        if not facts_path.exists():
            print(f"❌ File facts ngga ditemukan: {parsed.facts}")
            return
        import json
        facts = json.loads(facts_path.read_text(encoding="utf-8"))
        print(f"✅ Loaded facts dari {parsed.facts}")
    else:
        print(f"📝 Generate facts untuk \"{topic}\"...")
        try:
            facts = generate_facts(topic, parsed.num_facts)
        except Exception as e:
            print(f"❌ Gagal generate facts: {e}")
            return

    n_facts = len(facts.get("facts", []))
    print(f"\n📋 {n_facts} fakta tentang {facts.get('display_name', topic)}:")
    for f in facts["facts"]:
        print(f"   {f['number']}. {f['title']}")
    print()

    # --- Subject image ---
    subject_img = None

    if parsed.force_image:
        local_path = PHOTO_DIR / parsed.force_image
        if local_path.exists():
            img = PIL.Image.open(local_path).convert("RGBA")
            from sources.image_utils import apply_cartoon_effect
            img = apply_cartoon_effect(img)
            side = min(img.size)
            l = (img.width - side) // 2
            t = (img.height - side) // 2
            subject_img = img.crop((l, t, l + side, t + side)).resize((400, 400), PIL.Image.LANCZOS)
            print(f"   📷 Pake foto lokal: {parsed.force_image}")
    else:
        scientific = facts.get("scientific_name", topic)
        username = facts.get("topic", topic)
        print("🔍 Cari gambar...")
        # 1. Wikimedia
        url = get_wikimedia_image(scientific)
        if url:
            subject_img = prepare_subject_image(url)
        # 2. iNaturalist
        if url is None:
            print("   ⏩ Wikimedia kosong, coba iNaturalist...")
            url = get_inaturalist_image(scientific)
            if url:
                subject_img = prepare_subject_image(url)
        # 3. Pexels (buat topik konseptual)
        if subject_img is None:
            print("   ⏩ iNaturalist kosong, coba Pexels...")
            pexels_img = _search_pexels_image(f"{topic}")
            if pexels_img:
                from sources.image_utils import apply_cartoon_effect
                pexels_img = apply_cartoon_effect(pexels_img).convert("RGBA")
                side = min(pexels_img.size)
                l = (pexels_img.width - side) // 2
                t = (pexels_img.height - side) // 2
                canvas = PIL.Image.new("RGBA", (400, 400), (0, 0, 0, 0))
                cropped = pexels_img.crop((l, t, l + side, t + side)).resize((400, 400), PIL.Image.LANCZOS)
                canvas.paste(cropped, (0, 0), cropped)
                subject_img = canvas
        if subject_img is None:
            print("   ⚠️  Ngga dapet gambar dari Wikimedia / iNaturalist / Pexels")

    if subject_img:
        print(f"   ✅ Ukuran: {subject_img.width}x{subject_img.height}px\n")

    # --- Per-slide images from Pexels (no duplicates) ---
    _pexels_used_urls = set()

    def _get_pexels_subject(query: str, size: int) -> PIL.Image.Image | None:
        """Search Pexels with dedup — skip URLs already used."""
        nonlocal _pexels_used_urls
        from sources.image_utils import apply_cartoon_effect
        import requests
        from io import BytesIO
        import re as _re
        clean = _re.sub(r'[^\w\s]', '', query).strip()
        suffix = config.current_niche.pexels_query_suffix
        search_queries = [f"{clean} {suffix}", clean] if suffix else [clean]
        for sq in search_queries:
            if not sq:
                continue
            for img_url, alt in _pexels_search_results(sq, 8):
                if img_url in _pexels_used_urls:
                    continue
                _pexels_used_urls.add(img_url)
                print(f"   📷 {alt[:60]}")
                resp = requests.get(img_url, timeout=20)
                if resp.status_code != 200:
                    continue
                pexels_img = PIL.Image.open(BytesIO(resp.content))
                pexels_img = apply_cartoon_effect(pexels_img).convert("RGBA")
                side = min(pexels_img.size)
                l = (pexels_img.width - side) // 2
                t = (pexels_img.height - side) // 2
                canvas = PIL.Image.new("RGBA", (size, size), (0, 0, 0, 0))
                cropped = pexels_img.crop((l, t, l + side, t + side)).resize((size, size), PIL.Image.LANCZOS)
                canvas.paste(cropped, (0, 0), cropped)
                return canvas
        return None

    # --- Generate slides ---
    saved = []
    slide_fns_imgs = []

    # Cover — general topic image
    cover_img = subject_img or _get_pexels_subject(topic, 400)
    slide_fns_imgs.append((build_cover, (facts, cover_img)))

    # Per fact — search Pexels based on fact title
    for fact in facts["facts"]:
        query = fact["title"]
        fact_img = _get_pexels_subject(query, 300) or subject_img
        slide_fns_imgs.append((build_fact_slide, (fact, fact_img)))

    # CTA — logo aja
    slide_fns_imgs.append((build_cta_slide, (facts, None)))

    for i, (fn, args_tuple) in enumerate(slide_fns_imgs, 1):
        print(f"🎨 Slide {i}/{len(slide_fns_imgs)}...")
        try:
            img = fn(*args_tuple)
            filename = f"{slug}_slide_{i:02d}.png"
            img.save(str(PHOTO_DIR / filename))
            saved.append(filename)
            sz = PHOTO_DIR.joinpath(filename).stat().st_size // 1024
            print(f"   ✅ {filename} ({sz}KB)")
        except Exception as e:
            print(f"   ❌ Gagal: {e}")

    if saved:
        _update_curriculum_content(slug, facts)
        print(f"\n📸 {len(saved)} slide siap di resource/photos/:")
        for f in saved:
            print(f"   - {f}")
        print()
        print("📋 Upload & posting carousel pake:")
        print(f"   python main.py post-carousel \"<caption>\"")
        print()
        print("   ⚡ Auto-detect slide terbaru, nggak perlu intervensi manual!")
    else:
        print("\n❌ Nggak ada slide yang berhasil digenerate")


def _update_curriculum_content(slug: str, facts: dict | None = None,
                                result_id: str | None = None, permalink: str | None = None,
                                status: str | None = None):
    """Update curriculum_content.json with generated facts or post result (v4 nested)."""
    import json
    cpath = Path("curriculum_content.json")
    if not cpath.exists():
        return
    try:
        cc = json.loads(cpath.read_text(encoding="utf-8"))
    except Exception:
        return
    all_topics = cc.get("topics", {})

    matched_sid = None
    matched_num = None
    for sid, st in all_topics.items():
        for num, topic in st.items():
            if topic.get("slug") == slug:
                matched_sid, matched_num = sid, num
                break
        if matched_sid:
            break
    if not matched_sid:
        for sid, st in all_topics.items():
            for num, topic in st.items():
                if topic.get("slug", "").replace("-", "_") == slug:
                    matched_sid, matched_num = sid, num
                    break
            if matched_sid:
                break
    if not matched_sid:
        return

    topic = all_topics[matched_sid][matched_num]
    if facts:
        topic["display_name"] = facts.get("display_name", topic.get("display_name", ""))
        topic["subtitle"] = facts.get("subtitle", "")
        topic["scientific_name"] = facts.get("scientific_name", "")
        slides = [{"type": "cover", "title": facts.get("display_name", ""),
                   "subtitle": facts.get("subtitle", "")}]
        for f in facts.get("facts", []):
            slides.append({
                "type": "fact",
                "number": int(f.get("number", 0)),
                "title": f.get("title", ""),
                "description": f.get("description", ""),
                "tags": f.get("tags", [])
            })
        topic["slides"] = slides
    if result_id:
        topic["result_id"] = result_id
    if permalink:
        topic["permalink"] = permalink
    if status:
        topic["status"] = status
    cpath.write_text(json.dumps(cc, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"📝 curriculum_content.json diupdate untuk #{matched_num}")


def _save_to_published(file_paths, media_id: str, group_slug: str | None = None):
    """Simpan file ke published/, sapu file temp di output/.

    - file_paths: Path atau list of Path
    - group_slug: optional slug untuk carousel (dipakai sebagai stem)
    """
    from datetime import date
    today = date.today().strftime("%Y%m%d")

    if isinstance(file_paths, (list, tuple)):
        for i, fp in enumerate(file_paths):
            stem = group_slug or Path(fp).stem
            suffix = Path(fp).suffix
            dest = PUBLISHED_DIR / f"{today}_{media_id}_{stem}{suffix}"
            shutil.copy2(fp, dest)
            print(f"📁 Referensi tersimpan: {dest}")
    else:
        stem = Path(file_paths).stem
        dest = PUBLISHED_DIR / f"{today}_{media_id}_{stem}{Path(file_paths).suffix}"
        shutil.copy2(file_paths, dest)
        print(f"📁 Referensi tersimpan: {dest}")

    _cleanup_output()


def cmd_delete_post(client, args):
    if not args:
        print("Gunakan: python main.py delete-post <media_id>")
        print()
        print("  Cari media_id di folder resource/published/ dari nama file:")
        for f in sorted(PUBLISHED_DIR.glob("*.mp4")):
            print(f"    {f.stem}")
        return
    mid = args[0]
    result = client.delete_media(mid)
    print(f"✅ Post {mid} berhasil dihapus!")

    # hapus juga referensi di published/ kalo ada
    for f in PUBLISHED_DIR.glob(f"*{mid}*"):
        f.unlink()
        print(f"🗑️  Referensi dihapus: {f.name}")


def cmd_file_map(_client, _args=None):
    data = _map_file()
    if not data:
        print("📭 .uploaded.json kosong atau belum ada")
        return
    print("📍 File mapping (URL → file lokal):")
    for url, path in data.items():
        exists = "✅" if Path(path).exists() else "❌"
        print(f"  {exists} {url}")
        print(f"       {path}")


def _cleanup_output():
    """Sapu SEMUA file temp di output/ (udah di-copy ke published/)."""
    cleaned = 0
    for f in list(OUTPUT_DIR.iterdir()):
        if f.is_file() and f.suffix in (".mp4", ".aac"):
            f.unlink()
            cleaned += 1
    if cleaned:
        print(f"🧹 {cleaned} file temp dibersihin dari output/")


def _list_files(label, directory):
    files = list(directory.glob("*"))
    if files:
        print(f"  {label} yang tersedia:")
        for f in files:
            print(f"    - {f.name}")


def main():
    # Parse --niche dulu sebelum dispatch (biar ga masuk ke args perintah)
    if "--niche" in sys.argv:
        idx = sys.argv.index("--niche")
        if idx + 1 < len(sys.argv):
            niche_name = sys.argv.pop(idx + 1)
            sys.argv.pop(idx)
            config.set_niche(niche_name)

    if len(sys.argv) < 2:
        niche_list = ", ".join(config._NICHE_REGISTRY)
        print(__doc__)
        print()
        print("Perintah:")
        print("  profile                    — lihat profil IG")
        print("  media [limit]             — lihat postingan terbaru")
        print('  post-photo <url> [caption]  — posting foto')
        print('                  --schedule ig|cron "Mon 19:00"')
        print("  post-carousel [caption]    — posting carousel slides")
        print("                  --slug SLUG pilih slide tertentu")
        print("                  --upload-only upload Catbox aja, gak posting")
        print('                  --schedule cron "Mon 19:00" masuk antrian')
        print('  prepare-reel <vid> <music> — [Skill 1] edit video + ganti audio')
        print('  stage-reel <video>         — [Skill 2] upload Catbox + generate caption')
        print('  post-reel <url> [caption]  — [Skill 3] posting reel ke IG')
        print('                  --schedule ig|cron "Mon 19:00"')
        print('  stage-photo <foto>         — [Foto] upload Catbox + generate caption')
        print('  generate-caption <video>   — (opsional) caption aja tanpa upload')
        print("  generate-carousel <topik>  — generate carousel slides (facts Gemini + gambar)")

        print("  generate-carousel-sd <topik>— generate carousel via Stable Diffusion lokal (background + teks)")
        print("  comments <media_id>        — lihat komen")
        print('  reply <comment_id> <msg>   — balas komen')
        print("  insights [media_id]        — lihat insights")
        print("  search-hashtag <tag>       — cari hashtag")
        print("  delete-post <media_id>     — hapus post dari IG + referensi published/")
        print("  file-map                   — tampilkan mapping URL → file lokal")
        print("  curriculum                 — kelola kurikulum (add/edit/delete season, level, topic, sync)")
        print()
        print("Opsi global:")
        print(f"  --niche NAMA               pilih niche. Tersedia: {niche_list}")
        return

    cmd = sys.argv[1]
    args = sys.argv[2:]

    no_ig_cmds = {"generate-carousel-sd", "compress-slides", "curriculum", "generate-caption"}
    client = InstagramClient() if cmd not in no_ig_cmds else None

    cmds = {
        "profile": cmd_profile,
        "media": cmd_media,
        "post-photo": cmd_post_photo,
        "post-carousel": cmd_post_carousel,
        "post-reel": cmd_post_reel,
        "comments": cmd_comments,
        "reply": cmd_reply,
        "insights": cmd_insights,
        "search-hashtag": cmd_search_hashtag,
        "prepare-reel": cmd_prepare_reel,
        "stage-reel": cmd_stage_reel,
        "stage-photo": cmd_stage_photo,
        "generate-caption": cmd_generate_caption,
        "generate-carousel": cmd_generate_carousel,
        "generate-carousel-sd": cmd_generate_carousel_sd,
        "compress-slides": cmd_compress_slides,
        "delete-post": cmd_delete_post,
        "file-map": cmd_file_map,
        "curriculum": cmd_curriculum,
    }

    fn = cmds.get(cmd)
    if not fn:
        print(f"Perintah tidak dikenal: {cmd}")
        sys.exit(1)

    fn(client, args)


if __name__ == "__main__":
    main()
