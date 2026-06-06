import json
import re
import time
from pathlib import Path

from google import genai

import config


def generate_facts(topic: str, num_facts: int = 4) -> dict:
    if not config.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY ngga ditemukan di .env")

    slug = topic.lower().replace(" ", "_").replace("-", "_")
    cache_path = config.PHOTO_DIR / f"edu_{slug[:20]}_facts.json"

    if cache_path.exists():
        print(f"📦 Facts cache ditemukan: {cache_path.name}")
        ans = input("   Pakai ulang? (y/n): ").strip().lower()
        if ans == "y":
            return json.loads(cache_path.read_text(encoding="utf-8"))
        print("   Regenerate...")

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    prompt = (
        "Kamu adalah ahli aquaristik yang menulis konten edukasi Instagram "
        f"dalam Bahasa Indonesia untuk akun {config.IG_HANDLE}. "
        "Tulis fakta yang akurat, menarik, dan mudah dipahami pemula. "
        "Selalu respond hanya dengan JSON valid, tanpa markdown backtick, tanpa teks lain.\n\n"
        f"Buat konten edukasi aquarium tentang: {topic}\n\n"
        "Hasilkan JSON dengan format PERSIS ini:\n"
        "{\n"
        '  "topic": "...",\n'
        '  "display_name": "...",\n'
        '  "subtitle": "<tagline menarik max 5 kata>",\n'
        '  "scientific_name": "...",\n'
        '  "facts": [\n'
        "    {\n"
        '      "number": "01",\n'
        '      "title": "<judul + 1 emoji>",\n'
        '      "description": "<2-3 kalimat informatif dan engaging>",\n'
        '      "tags": ["<tag1>", "<tag2>", "<tag3>"]\n'
        "    }\n"
        f"    // ... total {num_facts} fakta\n"
        "  ],\n"
        '  "cta_text": "Follow @aquarisamatiran\\\\nuntuk edukasi aquarium\\\\nsetiap minggu!"\n'
        "}\n\n"
        "Pastikan:\n"
        "- Fakta akurat secara ilmiah\n"
        "- Tags berisi info teknis singkat (pH, suhu, ukuran, dll)\n"
        "- Bahasa Indonesia yang natural dan engaging\n"
        "- Subtitle unik dan memorable"
    )

    for attempt in range(3):
        try:
            resp = client.models.generate_content(
                model=config.GEMINI_MODEL, contents=[prompt]
            )
            text = resp.text.strip()
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            data = json.loads(text)

            required = ["topic", "display_name", "facts"]
            for field in required:
                if field not in data:
                    raise ValueError(f"Field '{field}' ngga ada di response Gemini")
            if not isinstance(data["facts"], list) or len(data["facts"]) == 0:
                raise ValueError("Facts harus list minimal 1")

            def _strip_emoji(t):
                return re.sub(r"[\U0001F300-\U0001F9FF\u2600-\u27BF\u2700-\u27BF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\u2300-\u23FF\uFE00-\uFE0F\u200D]", "", t).strip()

            data.setdefault("scientific_name", topic)
            data.setdefault("subtitle", "")
            data.setdefault("cta_text",
                            f"Follow {config.IG_HANDLE}\nuntuk edukasi aquarium\nsetiap minggu!")
            data["cta_text"] = _strip_emoji(data["cta_text"])
            data["subtitle"] = _strip_emoji(data["subtitle"])
            for f in data.get("facts", []):
                f["title"] = _strip_emoji(f["title"])
                f["description"] = _strip_emoji(f["description"])

            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"✅ Facts tersimpan: {cache_path.name}")
            return data

        except json.JSONDecodeError:
            print(f"   ⚠️  JSON parse gagal, coba lagi ({attempt+1}/3)...")
            time.sleep(3)
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                print("   ⛔ Gemini quota abis, coba lagi nanti ya")
                raise
            if "503" in err:
                print(f"   ⏳ Gemini sibuk, coba lagi ({attempt+1}/3)...")
                time.sleep(5)
            else:
                print(f"   ❌ Gagal: {e}")
                if attempt == 2:
                    raise
                time.sleep(3)

    raise RuntimeError("Gagal generate facts setelah 3x percobaan")
