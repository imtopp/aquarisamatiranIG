"""Test functions that WRITE data fields across the codebase."""

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestScheduleWriter:
    """Tests for _add_schedule_entry in main.py."""

    def _init_ctx(self, monkeypatch, tmp_path):
        from nixfw.account import AccountContext
        from nixfw.cli import commands as cmds
        ctx = AccountContext(name="test", base=tmp_path, enabled=True, config_data={})
        monkeypatch.setattr(cmds, "get_account", lambda account=None: ctx)
        return ctx

    def test_add_schedule_entry_creates_clean_entry(self, monkeypatch, tmp_path):
        from nixfw.cli import commands as cmds
        ctx = self._init_ctx(monkeypatch, tmp_path)
        v4 = {"topics": {"1": {"04": {"slug": "test-slug"}}}}
        ctx.source_of_truth.write_text(json.dumps(v4, indent=2), encoding="utf-8")
        ctx.schedule_json.write_text("[]", encoding="utf-8")

        import main as main_mod
        main_mod._add_schedule_entry("test-slug", "carousel", ["url1"], "Cap", "2026-06-20 19:00")

        data = json.loads(ctx.schedule_json.read_text(encoding="utf-8"))
        assert len(data) == 1
        e = data[0]
        if "source_ref" in e:
            assert e["source_ref"] == "C1.1#01"
        elif "curriculum" in e:
            assert e["curriculum"] == "C1.1#01"
        assert e["time"] == "2026-06-20 19:00"
        assert e["type"] == "carousel"
        assert e["caption"] == "Cap"
        assert e["done"] is False
        assert e["category"] == 1
        assert e["urls"] == ["url1"]

    def test_add_schedule_entry_photo(self, monkeypatch, tmp_path):
        from nixfw.cli import commands as cmds
        ctx = self._init_ctx(monkeypatch, tmp_path)
        ctx.schedule_json.write_text("[]", encoding="utf-8")

        import main as main_mod
        main_mod._add_schedule_entry("no-slug", "photo", "https://url.jpg", "Cap", "2026-06-20 09:00")

        data = json.loads(ctx.schedule_json.read_text(encoding="utf-8"))
        e = data[0]
        assert e["type"] == "photo"
        assert e["url"] == "https://url.jpg"
        assert "urls" not in e

    def test_add_schedule_entry_non_curriculum(self, monkeypatch, tmp_path):
        from nixfw.cli import commands as cmds
        ctx = self._init_ctx(monkeypatch, tmp_path)
        ctx.schedule_json.write_text("[]", encoding="utf-8")

        import main as main_mod
        main_mod._add_schedule_entry("no-slug", "reel", "https://url.mp4", "Cap", "2026-06-20 15:00")

        data = json.loads(ctx.schedule_json.read_text(encoding="utf-8"))
        e = data[0]
        if "source_ref" in e:
            assert e["source_ref"] is None
        elif "curriculum" in e:
            assert e["curriculum"] is None

    def test_add_schedule_entry_appends(self, monkeypatch, tmp_path):
        from nixfw.cli import commands as cmds
        ctx = self._init_ctx(monkeypatch, tmp_path)
        ctx.schedule_json.write_text(json.dumps([{"source_ref": "C1#01", "time": "old"}]), encoding="utf-8")

        import main as main_mod
        main_mod._add_schedule_entry("no-slug", "photo", "url", "Cap", "2026-06-20 19:00")

        data = json.loads(ctx.schedule_json.read_text(encoding="utf-8"))
        assert len(data) == 2


class TestCurriculumManagerWriters:
    """Tests for curriculum_manager.py _sync_schedule_json."""

    def _sync_data(self, v_content, tmp_path):
        from nixfw.account import AccountContext
        ctx = AccountContext(name="test", base=tmp_path, enabled=True, config_data={})
        ctx.source_of_truth.write_text(json.dumps(v_content, indent=2), encoding="utf-8")
        ctx.schedule_json.write_text("[]", encoding="utf-8")
        import nixfw.curriculum.manager as cm
        data = cm.load(account=ctx)
        cm._sync_schedule_json(data, account=ctx)
        return json.loads(ctx.schedule_json.read_text(encoding="utf-8"))

    def test_sync_schedule_json_adds_curriculum_entries(self, v4_content, tmp_path):
        schedule = self._sync_data(v4_content, tmp_path)
        assert len(schedule) == 2
        for entry in schedule:
            if "source_ref" in entry:
                assert re.match(r"C1\.\d+#\d{2}", entry["source_ref"])
            elif "curriculum" in entry:
                assert re.match(r"C1\.\d+#\d{2}", entry["curriculum"])

    def test_sync_schedule_json_preserves_existing(self, v4_content, tmp_path):
        from nixfw.account import AccountContext
        ctx = AccountContext(name="test", base=tmp_path, enabled=True, config_data={})
        ctx.source_of_truth.write_text(json.dumps(v4_content, indent=2), encoding="utf-8")
        ctx.schedule_json.write_text(json.dumps([
            {"source_ref": "C1#01", "time": "2026-06-07 19:00", "type": "carousel",
             "done": True, "category": 1, "result_id": "post_01"}
        ]), encoding="utf-8")
        import nixfw.curriculum.manager as cm
        data = cm.load(account=ctx)
        cm._sync_schedule_json(data, account=ctx)
        schedule = json.loads(ctx.schedule_json.read_text(encoding="utf-8"))
        assert len(schedule) == 2
