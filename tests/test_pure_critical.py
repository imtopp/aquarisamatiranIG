"""Critical safety tests: keep(), identity matching, edge cases."""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from nixfw.runner import _update_curriculum_after_post


class TestKeepFunction:
    """Tests isolated version of keep() — critical safety net."""

    def _make_keep(self, valid_keys: set):
        def keep(entry):
            c = entry.get("source_ref") or entry.get("curriculum", "")
            s = entry.get("category") or entry.get("season")
            if not c:
                return True
            m = re.search(r"#(\d+)", c)
            n = m.group(1) if m else c.lstrip("#")
            if s and (n, int(s)) in valid_keys:
                return True
            if (n, None) in valid_keys:
                return True
            return False
        return keep

    def test_keep_curriculum_entry_valid(self):
        keep = self._make_keep({("04", 1)})
        assert keep({"source_ref": "C1#04", "category": 1}) is True

    def test_keep_curriculum_entry_invalid(self):
        keep = self._make_keep({("04", 1)})
        assert keep({"source_ref": "C1#99", "category": 1}) is False

    def test_keep_non_curriculum_entry(self):
        keep = self._make_keep(set())
        assert keep({"time": "2026-06-07", "done": True}) is True

    def test_keep_entry_missing_category(self):
        keep = self._make_keep({("04", 1)})
        entry = {"source_ref": "C1#04"}
        result = keep(entry)
        assert result is False

    def test_keep_with_source_ref(self):
        keep = self._make_keep({("04", 1)})
        entry = {"source_ref": "C1#04", "category": 1}
        result = keep(entry)
        assert result is True

    def test_keep_regex_handles_C_format(self):
        keep = self._make_keep({("04", 1)})
        assert keep({"source_ref": "C1#04", "category": 1}) is True

    def test_keep_regex_handles_hash_only(self):
        keep = self._make_keep({("04", 1)})
        assert keep({"source_ref": "#04", "category": 1}) is True


class TestIdentityMatching:
    def test_match_by_result_id(self):
        schedule = [
            {"source_ref": "C1#01", "result_id": "id_01"},
            {"source_ref": "C1#04", "result_id": "id_04"},
        ]
        result_id_map = {}
        for i, e in enumerate(schedule):
            rid = e.get("result_id", "")
            if rid:
                result_id_map[rid] = i
        assert result_id_map["id_01"] == 0
        assert result_id_map["id_04"] == 1

    def test_match_by_permalink(self):
        schedule = [
            {"source_ref": "C1#01", "permalink": "https://ig.example/p/01"},
            {"source_ref": "C1#04", "permalink": "https://ig.example/p/04"},
        ]
        permalink_map = {}
        for i, e in enumerate(schedule):
            pl = e.get("permalink", "")
            if pl and pl.strip():
                permalink_map[pl.strip().rstrip("/")] = i
        assert permalink_map["https://ig.example/p/01"] == 0

    def test_fallback_number_match(self):
        schedule = [{"source_ref": "C1#01"}, {"source_ref": "C1#04"}]
        num = "04"
        existing = [e for e in schedule if re.search(r"#(\d+)", e.get("source_ref", ""))
                    and re.search(r"#(\d+)", e.get("source_ref", "")).group(1) == num]
        assert len(existing) == 1
        assert existing[0]["source_ref"] == "C1#04"

    def test_fallback_number_no_match(self):
        schedule = [{"source_ref": "C1#01"}]
        num = "99"
        existing = [e for e in schedule if re.search(r"#(\d+)", e.get("curriculum", ""))
                    and re.search(r"#(\d+)", e.get("curriculum", "")).group(1) == num]
        assert len(existing) == 0


class TestUpdateCurriculumAfterPost:
    def test_updates_all_fields(self, v4_content, tmp_content):
        tmp_content.write_text(json.dumps(v4_content, indent=2), encoding="utf-8")
        post = {"source_ref": "C1#06", "result_id": "res_06", "permalink": "https://ig.example/p/06"}
        _update_curriculum_after_post(post, content_path=tmp_content)

        updated = json.loads(tmp_content.read_text(encoding="utf-8"))
        topic = updated["topics"]["1"]["06"]
        assert topic["status"] == "live"
        assert topic["result_id"] == "res_06"
        assert topic["permalink"] == "https://ig.example/p/06"

    def test_does_not_overwrite_missing_permalink(self, v4_content, tmp_content):
        tmp_content.write_text(json.dumps(v4_content, indent=2), encoding="utf-8")
        post = {"source_ref": "C1#06", "result_id": "res_06"}
        _update_curriculum_after_post(post, content_path=tmp_content)

        updated = json.loads(tmp_content.read_text(encoding="utf-8"))
        topic = updated["topics"]["1"]["06"]
        assert topic["status"] == "live"
        assert "permalink" not in topic or topic.get("permalink", "") == ""
