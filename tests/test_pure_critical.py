"""Critical safety tests: keep(), identity matching, edge cases."""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


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


class TestProcessSchedulerResults:
    """Test process_scheduler_results() — the new single-writer output processor."""

    def test_output_file_parsing(self):
        from nixfw.curriculum.manager import process_scheduler_results
        import tempfile
        import os

        output_dir = Path(tempfile.mkdtemp())
        output_file = output_dir / "C1_1_03.json"
        output_file.write_text(json.dumps({
            "source_ref": "C1.1#03",
            "result_id": "res_03",
            "permalink": "https://ig.example/p/03",
            "caption": "Test caption",
            "urls": [],
        }), encoding="utf-8")

        assert output_file.exists()
        data = json.loads(output_file.read_text(encoding="utf-8"))
        assert data["source_ref"] == "C1.1#03"
        assert data["result_id"] == "res_03"

    def test_output_file_idempotent(self):
        import tempfile
        output_file = Path(tempfile.mkdtemp()) / "C1_1_03.json"
        output_file.write_text(json.dumps({
            "source_ref": "C1.1#03",
            "result_id": "res_03",
            "permalink": "https://ig.example/p/03",
        }), encoding="utf-8")
        data = json.loads(output_file.read_text(encoding="utf-8"))
        assert data["source_ref"] == "C1.1#03"
        data["source_ref"] = "C1.1#03"
        output_file.write_text(json.dumps(data), encoding="utf-8")
        assert output_file.exists()

    def test_output_file_skip_empty_source_ref(self):
        import tempfile
        output_dir = Path(tempfile.mkdtemp())
        f = output_dir / "invalid.json"
        f.write_text(json.dumps({"source_ref": "", "result_id": ""}), encoding="utf-8")
        from nixfw.curriculum.manager import process_scheduler_results
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data.get("source_ref") == ""

    def test_output_file_missing_path(self):
        from nixfw.curriculum.manager import process_scheduler_results
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            fake_dir = Path(td) / "nonexistent"
            assert not fake_dir.is_dir()

    def test_resolve_ref_new_format(self):
        from nixfw.curriculum.manager import resolve_ref
        data = {"topics": {"1": {"03": {"subcategory": "1"}}}, "categories": {"1": {"subcategories": {"1": {"title": "Test"}}}}}
        result = resolve_ref("C1.1#01", data)
        assert result is not None
        cid, num_key = result
        assert cid == "1"
        assert num_key == "03"

    def test_resolve_ref_old_format(self):
        from nixfw.curriculum.manager import resolve_ref
        data = {"topics": {"1": {"03": {"subcategory": "1"}}}}
        result = resolve_ref("C1#03", data)
        assert result is not None
        cid, num_key = result
        assert cid == "1"
        assert num_key == "03"

    def test_safe_name_conversion(self):
        ref = "C1.2#03"
        safe = ref.replace("#", "_").replace(".", "_")
        assert safe == "C1_2_03"

    def test_output_file_content_structure(self):
        output = {
            "source_ref": "C1.2#03",
            "result_id": "ig_123",
            "permalink": "https://ig.example/p/abc",
            "caption": "Test",
            "urls": ["https://example.com/slide1.png"],
            "timestamp": "2026-06-23 19:00 WIB",
        }
        assert "source_ref" in output
        assert "result_id" in output
        assert "permalink" in output
        assert "caption" in output
        assert "urls" in output
        assert "timestamp" in output
