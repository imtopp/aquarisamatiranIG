"""Phase 2 backward-compat tests: functions that must work with BOTH v4 and v5 content structures.

v4: topics[season][num] = {...}
v5: topics[category][num] = {...}  (topics are FLAT under category, subcategory is a field)

Both structures iterate identically: for sid, st in topics.items(): for num, topic in st.items()
So most functions already work with v5 without changes.
"""

import json
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _build_valid_keys(data):
    from nixfw.curriculum.manager import _all_topics
    valid = set()
    for sid, num, _ in _all_topics(data):
        valid.add((num, int(sid)))
    return valid


def _make_keep(valid_keys):
    import re
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


class TestAllTopics:
    def test_all_topics_v4(self, v4_content):
        from nixfw.curriculum.manager import _all_topics
        topics = list(_all_topics(v4_content))
        nums = sorted([num for _, num, _ in topics])
        assert nums == ["01", "06", "07"]

    def test_all_topics_v4_returns_three(self, v4_content):
        from nixfw.curriculum.manager import _all_topics
        assert len(list(_all_topics(v4_content))) == 3

    def test_all_topics_v4_slug_check(self, v4_content):
        from nixfw.curriculum.manager import _all_topics
        slugs = {v["slug"] for _, _, v in _all_topics(v4_content)}
        assert "aquarium-itu-apa" in slugs

    def test_all_topics_v5(self, v5_content):
        from nixfw.curriculum.manager import _all_topics
        topics = list(_all_topics(v5_content))
        nums = sorted([num for _, num, _ in topics])
        assert nums == ["01", "06", "07"]

    def test_all_topics_v5_slug_check(self, v5_content):
        from nixfw.curriculum.manager import _all_topics
        slugs = {v["slug"] for _, _, v in _all_topics(v5_content)}
        assert "aquarium-itu-apa" in slugs


class TestKeepIntegration:
    def test_keep_with_v4_preserves_valid(self, v4_content):
        valid = _build_valid_keys(v4_content)
        keep = _make_keep(valid)
        assert keep({"source_ref": "C1#01", "category": 1}) is True
        assert keep({"source_ref": "C1#06", "category": 1}) is True
        assert keep({"source_ref": "C1#07", "category": 1}) is True

    def test_keep_with_v4_removes_orphan(self, v4_content):
        valid = _build_valid_keys(v4_content)
        keep = _make_keep(valid)
        assert keep({"source_ref": "C1#99", "category": 1}) is False

    def test_keep_with_v4_preserves_non_curriculum(self, v4_content):
        valid = _build_valid_keys(v4_content)
        keep = _make_keep(valid)
        assert keep({"time": "2026-06-07 09:00", "type": "photo"}) is True

    def test_keep_with_v5_preserves_valid(self, v5_content):
        valid = _build_valid_keys(v5_content)
        keep = _make_keep(valid)
        assert keep({"source_ref": "C1#01", "category": 1}) is True
        assert keep({"source_ref": "C1#06", "category": 1}) is True

    def test_keep_with_v5_removes_orphan(self, v5_content):
        valid = _build_valid_keys(v5_content)
        keep = _make_keep(valid)
        assert keep({"source_ref": "C1#99", "category": 1}) is False


class TestSyncScheduleJson:
    def test_sync_with_v4(self, v4_content, monkeypatch, tmp_path):
        import nixfw.curriculum.manager as cm

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

    def test_sync_with_v4_writes_source_ref(self, v4_content, monkeypatch, tmp_path):
        import nixfw.curriculum.manager as cm

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
        for entry in schedule:
            if "source_ref" in entry:
                assert re.match(r"C1\.\d+#\d{2}", entry["source_ref"])
            elif "curriculum" in entry:
                assert re.match(r"C1\.\d+#\d{2}", entry["curriculum"])

    def test_sync_with_v4_preserves_existing(self, v4_content, monkeypatch, tmp_path):
        import nixfw.curriculum.manager as cm

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

    def test_sync_with_v5(self, v5_content, monkeypatch, tmp_path):
        import nixfw.curriculum.manager as cm

        content_path = tmp_path / "curriculum_content.json"
        content_path.write_text(json.dumps(v5_content, indent=2), encoding="utf-8")

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

    def test_sync_with_v5_writes_source_ref(self, v5_content, monkeypatch, tmp_path):
        import nixfw.curriculum.manager as cm

        content_path = tmp_path / "curriculum_content.json"
        content_path.write_text(json.dumps(v5_content, indent=2), encoding="utf-8")

        sched_path = tmp_path / "schedule.json"
        sched_path.write_text("[]", encoding="utf-8")

        monkeypatch.setattr(cm, "SRC", content_path)
        monkeypatch.setattr(cm, "SCHEDULE_JSON", sched_path)
        monkeypatch.setattr(cm, "CUR_MD", tmp_path / "curriculum.md")
        monkeypatch.setattr(cm, "BIO_HTML", tmp_path / "bio" / "index.html")

        data = cm.load()
        cm._sync_schedule_json(data)

        schedule = json.loads(sched_path.read_text(encoding="utf-8"))
        for entry in schedule:
            if "source_ref" in entry:
                assert re.match(r"C1\.\d+#\d{2}", entry["source_ref"])
            elif "curriculum" in entry:
                assert re.match(r"C1\.\d+#\d{2}", entry["curriculum"])


class TestUpdateCurriculumContent:
    def test_update_with_v4(self, v4_content, monkeypatch, tmp_path):
        import nixfw.config as cfg
        monkeypatch.chdir(tmp_path)
        content_path = tmp_path / "curriculum_content.json"
        content_path.write_text(json.dumps(v4_content, indent=2), encoding="utf-8")
        monkeypatch.setattr(cfg, "CONTENT_PATH", content_path)

        import main as main_mod
        main_mod._update_curriculum_content("aquarium-itu-apa", result_id="new_res_id", permalink="https://ig.example/p/new")

        updated = json.loads(content_path.read_text(encoding="utf-8"))
        assert updated["topics"]["1"]["01"]["result_id"] == "new_res_id"
        assert updated["topics"]["1"]["01"]["permalink"] == "https://ig.example/p/new"

    def test_update_with_v4_status(self, v4_content, monkeypatch, tmp_path):
        import nixfw.config as cfg
        monkeypatch.chdir(tmp_path)
        content_path = tmp_path / "curriculum_content.json"
        content_path.write_text(json.dumps(v4_content, indent=2), encoding="utf-8")
        monkeypatch.setattr(cfg, "CONTENT_PATH", content_path)

        import main as main_mod
        main_mod._update_curriculum_content("alga-musuh-atau-guru", status="live")

        updated = json.loads(content_path.read_text(encoding="utf-8"))
        assert updated["topics"]["1"]["06"]["status"] == "live"

    def test_update_with_v5(self, v5_content, monkeypatch, tmp_path):
        import nixfw.config as cfg
        monkeypatch.chdir(tmp_path)
        content_path = tmp_path / "curriculum_content.json"
        content_path.write_text(json.dumps(v5_content, indent=2), encoding="utf-8")
        monkeypatch.setattr(cfg, "CONTENT_PATH", content_path)

        import main as main_mod
        main_mod._update_curriculum_content("aquarium-itu-apa", result_id="new_res_id")

        updated = json.loads(content_path.read_text(encoding="utf-8"))
        assert updated["topics"]["1"]["01"]["result_id"] == "new_res_id"

    def test_update_with_v5_status(self, v5_content, monkeypatch, tmp_path):
        import nixfw.config as cfg
        monkeypatch.chdir(tmp_path)
        content_path = tmp_path / "curriculum_content.json"
        content_path.write_text(json.dumps(v5_content, indent=2), encoding="utf-8")
        monkeypatch.setattr(cfg, "CONTENT_PATH", content_path)

        import main as main_mod
        main_mod._update_curriculum_content("alga-musuh-atau-guru", status="live")

        updated = json.loads(content_path.read_text(encoding="utf-8"))
        assert updated["topics"]["1"]["06"]["status"] == "live"
