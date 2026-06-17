"""Edit video — ganti audio, kompres, upload, dll"""

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import requests
from moviepy import AudioFileClip

from nixfw import config

RESOURCE_DIR = config.RESOURCE_DIR
VIDEO_DIR = config.RESOURCE_DIR / "videos"
MUSIC_DIR = config.RESOURCE_DIR / "music"
PHOTO_DIR = config.PHOTO_DIR
PUBLISHED_DIR = config.RESOURCE_DIR / "published"
OUTPUT_DIR = config.RESOURCE_DIR / "output"

for d in [VIDEO_DIR, MUSIC_DIR, PHOTO_DIR, PUBLISHED_DIR, OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_MB = 200


def _has_nvidia_gpu() -> bool:
    try:
        subprocess.run(["nvidia-smi"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


_VIDEO_CODEC = "h264_nvenc" if _has_nvidia_gpu() else "libx264"
_NVENC_PARAMS = [
    "-preset", "p7", "-rc", "vbr_hq", "-cq", "23", "-b:v", "30M", "-maxrate", "30M",
]
_HAS_GPU = _has_nvidia_gpu()


def _ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _get_frame_count(video_path: Path) -> int:
    """Hitung total frame pake ffmpeg (parse dari stderr)."""
    ffmpeg = _ffmpeg_exe()
    r = subprocess.run(
        [ffmpeg, "-i", str(video_path), "-f", "null", "-"],
        capture_output=True, text=True, timeout=120,
    )
    for line in r.stderr.split("\n"):
        line = line.strip()
        if line.startswith("frame="):
            try:
                parts = line.split()
                return int(parts[0].split("=")[1])
            except (ValueError, IndexError):
                continue
    return 0


def _run_ffmpeg(cmd: list[str], total_frames: int, label: str = "Render"):
    """Jalankan ffmpeg, parse progress, tampilkan bar."""
    start = time.time()
    last_print = 0

    proc = subprocess.Popen(
        cmd + ["-progress", "pipe:1", "-y"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1,
    )

    for line in proc.stdout:
        line = line.strip()
        if line.startswith("frame="):
            try:
                frame = int(line.split("=", 1)[1].strip())
            except ValueError:
                continue

            now = time.time()
            elapsed = now - start
            fps = frame / elapsed if elapsed > 0 else 0

            if total_frames > 0:
                pct = min(frame / total_frames * 100, 100)
            else:
                pct = 0

            eta = (total_frames - frame) / fps if fps > 0 else 0

            if frame - last_print >= max(1, total_frames // 20) or (total_frames > 0 and frame >= total_frames):
                eta_str = f"{eta:.0f}s" if eta < 120 else f"{eta/60:.1f}m"
                print(f"  {label}: {pct:3.0f}% | frame {frame}/{total_frames} | {fps:.0f} fps | ETA {eta_str}")
                last_print = frame

    proc.wait()
    elapsed = time.time() - start
    elapsed_str = f"{elapsed:.0f}s" if elapsed < 120 else f"{elapsed/60:.1f}m"
    print(f"  ✅ Selesai dalam {elapsed_str}")


def replace_audio(
    video_path: str | Path,
    audio_path: str | Path,
    output_path: str | Path | None = None,
    video_volume: float = 0.0,
    music_volume: float = 1.0,
) -> Path:
    """Ganti audio video dengan musik. video_volume 0.0 = hapus suara asli."""
    vid = Path(video_path)
    aud = Path(audio_path)

    if output_path is None:
        output_path = OUTPUT_DIR / f"{vid.stem}_edited.mp4"

    total = _get_frame_count(vid)
    ffmpeg = _ffmpeg_exe()

    # prepare audio — loop/trim pake moviepy
    audio_clip = AudioFileClip(str(aud))
    video_dur = None
    r = subprocess.run(
        [ffmpeg, "-i", str(vid), "-f", "null", "-"],
        capture_output=True, text=True, timeout=30,
    )
    for line in r.stderr.split("\n"):
        if "Duration" in line:
            parts = line.strip().split(",")[0].split("Duration: ")[-1]
            h, m, s = parts.split(":")
            video_dur = int(h) * 3600 + int(m) * 60 + float(s)
            break

    if video_dur and audio_clip.duration < video_dur:
        audio_clip = audio_clip.loop(duration=video_dur)
    elif video_dur and audio_clip.duration > video_dur:
        audio_clip = audio_clip.subclipped(0, video_dur)

    audio_clip = audio_clip.with_volume_scaled(music_volume)
    temp_audio = OUTPUT_DIR / f"_audio_{aud.stem}.aac"
    audio_clip.write_audiofile(str(temp_audio), codec="aac", logger=None)
    audio_clip.close()

    cmd = [ffmpeg, "-i", str(vid), "-i", str(temp_audio)]
    if video_volume <= 0:
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    cmd += [
        "-c:v", _VIDEO_CODEC,
        *_NVENC_PARAMS,
        "-c:a", "aac",
        "-shortest",
        str(output_path),
    ]

    print(f"🎬  Frame: {total}")
    _run_ffmpeg(cmd, total, "Edit audio")

    temp_audio.unlink(missing_ok=True)
    for f in Path(".").glob("*TEMP_MPY*"):
        f.unlink(missing_ok=True)
    return Path(output_path)


def compress_video(
    video_path: str | Path,
    output_path: str | Path | None = None,
    quality: str = "high",
) -> Path:
    """Kompres video (keep original audio). quality: 'high' atau 'medium'."""
    vid = Path(video_path)

    if output_path is None:
        stem = vid.stem
        suffix = "_compressed.mp4" if quality == "high" else "_compressed_medium.mp4"
        output_path = OUTPUT_DIR / f"{stem}{suffix}"

    total = _get_frame_count(vid)
    ffmpeg = _ffmpeg_exe()

    params = list(_NVENC_PARAMS)
    if quality == "medium":
        params = ["-preset", "p7", "-rc", "vbr_hq", "-cq", "28", "-b:v", "15M", "-maxrate", "15M"]

    cmd = [
        ffmpeg, "-i", str(vid),
        "-c:v", _VIDEO_CODEC, *params,
        "-c:a", "aac",
        str(output_path),
    ]

    print(f"🎬  Frame: {total}  |  Kualitas: {quality}")
    _run_ffmpeg(cmd, total, "Kompres")
    return Path(output_path)


def upload_file(file_path: str | Path) -> str:
    """Upload file ke Catbox.moe, return public URL."""
    path = Path(file_path)
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"  📦 Ukuran: {size_mb:.0f}MB  |  Upload ke Catbox...")

    with open(path, "rb") as f:
        r = requests.post(
            "https://catbox.moe/user/api.php",
            data={"reqtype": "fileupload"},
            files={"fileToUpload": f},
            timeout=600,
        )
    r.raise_for_status()
    return r.text.strip()


def copy_to_published(file_path: Path, label: str = "") -> Path:
    """Simpan file ke folder published sebagai referensi."""
    stem = file_path.stem
    suffix = file_path.suffix
    label_part = f"_{label}" if label else ""
    dest = PUBLISHED_DIR / f"{stem}{label_part}{suffix}"
    shutil.copy2(file_path, dest)
    return dest
