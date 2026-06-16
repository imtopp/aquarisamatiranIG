"""Test functions that WRITE data fields across the codebase."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class TestScheduleWriter:
    """Tests for _add_schedule_entry in main.py."""

    def test_add_schedule_entry_creates_clean_entry(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        content_path = tmp_path / "curriculum_content.json"
        v4 = {"topics": {"1": {"04": {"slug": "test-slug"}}}}
        content_path.write_text(json.dumps(v4, indent=2), encoding="utf-8")

        import main as main_mod
        main_mod._add_schedule_entry("test-slug", "carousel", ["url1"], "Cap", "2026-06-20 19:00")

        schedule_path = tmp_path / "schedule.json"
        data = json.loads(schedule_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        e = data[0]
        if "source_ref" in e:
            assert e["source_ref"] == "C1#04"
        elif "curriculum" in e:
            assert e["curriculum"] == "C1#04"
        assert e["time"] == "2026-06-20 19:00"
        assert e["type"] == "carousel"
        assert e["caption"] == "Cap"
        assert e["done"] is False
        assert e["category"] == 1
        assert e["urls"] == ["url1"]

    def test_add_schedule_entry_photo(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)

        import main as main_mod
        main_mod._add_schedule_entry("no-slug", "photo", "https://url.jpg", "Cap", "2026-06-20 09:00")

        schedule_path = tmp_path / "schedule.json"
        data = json.loads(schedule_path.read_text(encoding="utf-8"))
        e = data[0]
        assert e["type"] == "photo"
        assert e["url"] == "https://url.jpg"
        assert "urls" not in e

    def test_add_schedule_entry_non_curriculum(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)

        import main as main_mod
        main_mod._add_schedule_entry("no-slug", "reel", "https://url.mp4", "Cap", "2026-06-20 15:00")

        schedule_path = tmp_path / "schedule.json"
        data = json.loads(schedule_path.read_text(encoding="utf-8"))
        e = data[0]
        if "source_ref" in e:
            assert e["source_ref"] is None
        elif "curriculum" in e:
            assert e["curriculum"] is None

    def test_add_schedule_entry_appends(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        schedule_path = tmp_path / "schedule.json"
        schedule_path.write_text(json.dumps([{"source_ref": "C1#01", "time": "old"}]), encoding="utf-8")

        import main as main_mod
        main_mod._add_schedule_entry("no-slug", "photo", "url", "Cap", "2026-06-20 19:00")

        data = json.loads(schedule_path.read_text(encoding="utf-8"))
        assert len(data) == 2


class TestCurriculumManagerWriters:
    """Tests for curriculum_manager.py _sync_schedule_json."""

    def test_sync_schedule_json_adds_curriculum_entries(self, v4_content, monkeypatch, tmp_path):
        import curriculum_manager as cm

        content_path = tmp_path / "curriculum_content.json"
        content_path.write_text(json.dumps(v4_content, indent=2), encoding="utf-8")

        sched_path = tmp_path / "schedule.json"
        sched_path.write_text("[]", encoding="utf-8")

        monkeypatch.setattr(cm, "SRC", content_path)
        monkeypatch.setattr(cm, "SCHEDULE_JSON", sched_path)
        monkeypatch.setattr(cm, "CUR_MD", tmp_path / "curriculum.md")
        monkeypatch.setattr(cm, "BIO_HTML", tmp_path / "bio" / "index.html")

        data = cm.load()
        cm._sync_schedule_json(data)

        schedule = json.loads(sched_path.read_text(encoding="utf-8"))
        assert len(schedule) == 2
        for entry in schedule:
            if "source_ref" in entry:
                assert entry["source_ref"].startswith("C1#")
            elif "curriculum" in entry:
                assert entry["curriculum"].startswith("C1#")

    def test_sync_schedule_json_preserves_existing(self, v4_content, monkeypatch, tmp_path):
        import curriculum_manager as cm

        content_path = tmp_path / "curriculum_content.json"
        content_path.write_text(json.dumps(v4_content, indent=2), encoding="utf-8")

        sched_path = tmp_path / "schedule.json"
        sched_path.write_text(json.dumps([
            {"source_ref": "C1#01", "time": "2026-06-07 19:00", "type": "carousel",
             "done": True, "category": 1, "result_id": "post_01"}
        ]), encoding="utf-8")

        monkeypatch.setattr(cm, "SRC", content_path)
        monkeypatch.setattr(cm, "SCHEDULE_JSON", sched_path)
        monkeypatch.setattr(cm, "CUR_MD", tmp_path / "curriculum.md")
        monkeypatch.setattr(cm, "BIO_HTML", tmp_path / "bio" / "index.html")

        data = cm.load()
        cm._sync_schedule_json(data)

        schedule = json.loads(sched_path.read_text(encoding="utf-8"))
        assert len(schedule) == 2
