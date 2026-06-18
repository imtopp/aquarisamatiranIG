# Rename "curriculum" → <TBD>

**Goal:** Ganti istilah "curriculum" yang terlalu edukasi dengan istilah netral yang cocok
untuk multi-niche content management system.

**Target istilah:** `___` (TBD — candidates: `catalog`, `series`, `content`, `library`, `blueprint`)

---

## Step-by-step Execution

### Phase 1: Folder & Imports

```yaml
1. Rename directory:
   nixfw/curriculum/ → nixfw/<term>/

2. Update imports:
   - nixfw/cli/commands.py:37
     from nixfw.curriculum.manager import cmd_curriculum
     → from nixfw.<term>.manager import cmd_<term>

   - tests/test_phase2_compat.py:21,47,53,57,62,68,105,125,149,172,192
     from nixfw.curriculum.manager import _all_topics  / import ... as cm
     → from nixfw.<term>.manager import ...

   - tests/test_pure_writers.py:89,114
     import nixfw.curriculum.manager as cm
     → import nixfw.<term>.manager as cm
```

### Phase 2: CLI Command

```yaml
File: nixfw/cli/commands.py
  - Line 1536: print("  curriculum  — kelola kurikulum ...")
  - Line 1546: "curriculum" in no_ig_cmds set
  - Line 1568: "curriculum": cmd_curriculum,

File: nixfw/curriculum/<term>/manager.py
  - Line 581: def cmd_curriculum(client, args) → def cmd_<term>
  - Line 8-16: docstring usage examples
  - Line 618,631,644: help text
  - Line 655: cmd_curriculum(None, ...)

File: README.md:29
  - "python main.py curriculum" → "python main.py <term>"
```

### Phase 3: Fungsi & Variabel Internal

```yaml
File: nixfw/cli/commands.py
  - Line 135: def _find_curriculum_key_by_slug → def _find_<term>_key_by_slug
  - Line 1365: def _update_curriculum_content → def _update_<term>_content
  - Variable: curriculum_key → <term>_key

File: nixfw/runner.py
  - Line 28: def _update_curriculum_after_post → def _update_<term>_after_post

File: nixfw/bot/bot.py
  - Line 20: CONTENT_PATH as CURRICULUM_PATH → CONTENT_PATH as CONTENT_PATH (remove alias)
  - Line 233: def _load_curriculum → def _load_<term>
  - Line 247: def _match_curriculum_topic → def _match_<term>_topic
  - Line 265: def _format_curriculum_context → def _format_<term>_context
  - Variables: curriculum_topics, curriculum_inject, cur_order → <term>_topics, <term>_inject, <term>_order

File: nixfw/<term>/manager.py
  - Line 28: CUR_MD → <TERM>_MD
  - Line 343: def _sync_curriculum_md → def _sync_<term>_md
```

### Phase 4: Config & JSON Fields

```yaml
File: accounts/aquarisamatiran/config.json:6
  - "curriculum_version": 4 → "<term>_version": 4

File: nixfw/templates/account/config.json:6
  - "curriculum_version": 4 → "<term>_version": 4
```

### Phase 5: Legacy Field "curriculum" in schedule.json

Keep backward-compat fallback `entry.get("curriculum")` but add TODO to migrate.

Files with fallback:
  - nixfw/bot/bot.py:214
  - nixfw/runner.py:31
  - nixfw/bio/generator.py:31
  - nixfw/<term>/manager.py:414,416,419,461
  - tests/test_pure_critical.py:19,102,103
  - tests/test_pure_readers.py:117,118

**Strategy:** Keep fallback, add comment `# LEGACY: migrate to source_ref`.
```

### Phase 6: Bot User-Facing Strings

```yaml
File: nixfw/bot/bot.py
  - Line 61: "## Curriculum Terminology" → "## <Term> Terminology"
  - Line 276: "KONTEN KURIKULUM" → "KONTEN <TERM>"
  - Line 309: "📚 Kurikulum Aquarisamatiran" → "📚 <Term> Aquarisamatiran"
  - Line 391: "📚 Curriculum:" → "📚 <Term>:"
```

### Phase 7: Test Files

```yaml
Function renames in tests:
  - _update_curriculum_after_post → _update_<term>_after_post
  - _update_curriculum_content → _update_<term>_content
  - _find_curriculum_key_by_slug → _find_<term>_key_by_slug
  - cmd_curriculum → cmd_<term>

Class names:
  - TestUpdateCurriculumAfterPost → TestUpdate<Term>AfterPost
  - class TestUpdateCurriculumContent → TestUpdate<Term>Content

Test function names (~15 functions):
  - test_update_after_post_with_curriculum_key → test_update_after_post_with_<term>_key
  - test_update_after_post_empty_curriculum_skips → test_update_after_post_empty_<term>_skips
  - test_add_schedule_entry_writes_curriculum_ref → test_add_schedule_entry_writes_<term>_ref
  - test_build_card_statuses_with_curriculum → test_build_card_statuses_with_<term>
  - test_build_card_statuses_non_curriculum_skipped → test_build_card_statuses_non_<term>_skipped
  - etc.

Fixture paths (nice to have, not critical):
  - tmp_path / "curriculum_content.json" → tmp_path / "<term>_content.json"
```

### Phase 8: Documentation

```yaml
File: AGENTS.md
  - Line 46-47: nixfw/curriculum/ directory entry
  - Line 67: "Master konten (curriculum + topics)"
  - Line 83: CLI command example
  - Line 120: "## Terminology per Curriculum Topic"
  - Line 149: "## Published Posts × Curriculum"
  - Line 151,160: Table headers
  - Line 285: "## Curriculum Manager (v4 — nested per-season)"
  - Line 296: CLI command

File: PRD.md (~40+ references)
  - Directory tree references
  - Terminology definitions
  - JSON schema field "curriculums"
  - CLI command specs
  - Glossary entries
```

### Phase 9: Generated File Names

```yaml
- accounts/<name>/curriculum.md → accounts/<name>/<term>.md
- (CUR_MD constant update in manager.py)
```

### Phase 10: Clean Up

```yaml
- Remove old nixfw/curriculum/ directory after confirming new one works
- Run full test suite
```

---

## Files Affected (Complete List)

| # | File | Priority |
|---|------|----------|
| 1 | `nixfw/curriculum/manager.py` | MUST (rename file) |
| 2 | `nixfw/cli/commands.py` | MUST |
| 3 | `nixfw/runner.py` | MUST |
| 4 | `nixfw/bot/bot.py` | MUST |
| 5 | `nixfw/bio/generator.py` | MUST (legacy fallback) |
| 6 | `nixfw/config.py` | SHOULD (if CURRICULUM_PATH alias) |
| 7 | `main.py` | MUST (imports) |
| 8 | `accounts/aquarisamatiran/config.json` | MUST |
| 9 | `nixfw/templates/account/config.json` | MUST |
| 10 | `tests/test_pure_readers.py` | MUST |
| 11 | `tests/test_pure_writers.py` | MUST |
| 12 | `tests/test_pure_critical.py` | MUST |
| 13 | `tests/test_phase2_compat.py` | MUST |
| 14 | `tests/test_pure_migration.py` | NICE |
| 15 | `tests/conftest.py` | NICE |
| 16 | `AGENTS.md` | MUST |
| 17 | `PRD.md` | MUST |
| 18 | `README.md` | MUST |

---

## Notes

- Production `source_of_truth.json` has NO `"curriculum"` field — sudah migrasi ke `source_ref`
- `schedule.json` also NO `"curriculum"` field — only in legacy fallback code
- `accounts/<name>/curriculum.md` is a **generated file** (auto-regenerated by `curriculum sync`)
