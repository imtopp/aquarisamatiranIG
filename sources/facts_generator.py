import json
import re
import time
from pathlib import Path

from google import genai

import config


def _build_json_schema(niche: config.NicheProfile, ct: config.ContentType, num_facts: int) -> str:
    """Bangun schema JSON sesuai ContentType (scientific_name optional)."""
    schema_parts = [
        '{',
        '  "topic": "...",',
        '  "display_name": "...",',
        '  "subtitle": "<tagline menarik max 5 kata>",',
    ]
    if ct.has_scientific_name or (not ct.has_scientific_name and niche.has_scientific_name and ct == niche.content_types.get("edu", ct)):
        schema_parts.append('  "scientific_name": "...",')
    if ct.json_schema_extra:
        schema_parts.append(f'  {ct.json_schema_extra},')
    schema_parts.append('  "facts": [')
    schema_parts.append('    {')
    schema_parts.append('      "number": "01",')
    schema_parts.append('      "title": "<judul + 1 emoji>",')
    schema_parts.append('      "description": "<2-3 kalimat informatif dan engaging>",')
    schema_parts.append('      "tags": ["<tag1>", "<tag2>", "<tag3>"]')
    schema_parts.append('    }')
    schema_parts.append(f'    // ... total {num_facts} fakta')
    schema_parts.append('  ],')
    schema_parts.append(f'  "cta_text": "{niche.cta_template.format(handle=niche.handle, topic=niche.education_label)}"')
    schema_parts.append('}')
    return '\n'.join(schema_parts)


def generate_facts(topic: str, num_facts: int = 4) -> dict:
    if not config.GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY ngga ditemukan di .env")

    niche = config.current_niche
    ct = config.current_content_type

    slug = re.sub(r'[^\w\-]', '', topic.lower().replace(" ", "_").replace("-", "_"))
    cache_path = config.PHOTO_DIR / f"edu_{slug[:20]}_facts.json"

    if cache_path.exists():
        print(f"📦 Facts cache ditemukan: {cache_path.name}")
        ans = input("   Pakai ulang? (y/n): ").strip().lower()
        if ans == "y":
            return json.loads(cache_path.read_text(encoding="utf-8"))
        print("   Regenerate...")

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    schema = _build_json_schema(niche, ct, num_facts)

    extra = f"\n{ct.prompt_extra}" if ct.prompt_extra else ""
    tags = ct.tags_hint or niche.tags_hint
    inst = ct.instruction.format(topic=topic) if "{topic}" in ct.instruction else f"{ct.instruction} tentang {topic}"

    prompt = (
        f"Kamu adalah {niche.expert_role} yang menulis konten {niche.education_label} Instagram "
        f"dalam Bahasa Indonesia untuk akun {niche.handle}. "
        "Tulis konten yang akurat, menarik, dan mudah dipahami pemula. "
        "Selalu respond hanya dengan JSON valid, tanpa markdown backtick, tanpa teks lain.\n\n"
        f"{inst}\n\n"
        "Hasilkan JSON dengan format PERSIS ini:\n"
        f"{schema}\n\n"
        "Pastikan:\n"
        f"- {ct.label}: informatif dan engaging\n"
        f"- Tags berisi info singkat tapi bermakna ({tags})\n"
        "- Bahasa Indonesia yang natural dan engaging\n"
        "- Subtitle unik dan memorable"
        f"{extra}"
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

            data.setdefault("scientific_name", topic if ct.has_scientific_name or niche.has_scientific_name else "")
            data.setdefault("subtitle", "")
            data.setdefault("cta_text",
                            niche.cta_template.format(handle=niche.handle, topic=niche.education_label))

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
