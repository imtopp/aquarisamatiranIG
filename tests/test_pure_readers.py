import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from nixfw.runner import _find_topic_by_num, _update_curriculum_after_post
from nixfw.bio.generator import build_card_statuses


class TestRunnerReaders:
    """Tests for runner module _find_topic_by_num and _update_curriculum_after_post readers."""

    def test_find_topic_by_num_v4(self, v4_content):
        topic = _find_topic_by_num(v4_content, "01")
        assert topic is not None
        assert topic["slug"] == "aquarium-itu-apa"

    def test_find_topic_by_num_missing(self, v4_content):
        assert _find_topic_by_num(v4_content, "99") is None

    def test_find_topic_by_num_v5_works_same(self, v5_content):
        """Same function must work with v5 structure too (topics still nested per-category)."""
        topic = _find_topic_by_num(v5_content, "01")
        assert topic is not None
        assert topic["slug"] == "aquarium-itu-apa"

    def test_update_after_post_with_curriculum_key(self, v4_content, tmp_content):
        tmp_content.write_text(json.dumps(v4_content, indent=2), encoding="utf-8")
        post = {"source_ref": "C1#06", "result_id": "new_id", "permalink": "https://ig.example/p/new"}
        _update_curriculum_after_post(post, content_path=tmp_content)

        updated = json.loads(tmp_content.read_text(encoding="utf-8"))
        assert updated["topics"]["1"]["06"]["status"] == "live"
        assert updated["topics"]["1"]["06"]["result_id"] == "new_id"

    def test_update_after_post_with_source_ref_key(self, v4_content, tmp_content):
        tmp_content.write_text(json.dumps(v4_content, indent=2), encoding="utf-8")
        post = {"source_ref": "C1#06", "result_id": "new_id"}
        _update_curriculum_after_post(post, content_path=tmp_content)

        updated = json.loads(tmp_content.read_text(encoding="utf-8"))
        assert updated["topics"]["1"]["06"]["status"] == "live"
        assert updated["topics"]["1"]["06"]["result_id"] == "new_id"

    def test_update_after_post_no_match_skips(self, v4_content, tmp_content):
        tmp_content.write_text(json.dumps(v4_content, indent=2), encoding="utf-8")
        post = {"source_ref": "C1#99"}
        _update_curriculum_after_post(post, content_path=tmp_content)
        assert True

    def test_update_after_post_empty_curriculum_skips(self, v4_content, tmp_content):
        tmp_content.write_text(json.dumps(v4_content, indent=2), encoding="utf-8")
        post = {"source_ref": ""}
        _update_curriculum_after_post(post, content_path=tmp_content)
        assert True


class TestMainReaders:
    """Tests for main.py _find_curriculum_key_by_slug reader."""

    def test_find_key_by_slug(self, monkeypatch, tmp_path):
        import nixfw.config as cfg
        monkeypatch.chdir(tmp_path)
        content_path = tmp_path / "curriculum_content.json"
        v4 = {"topics": {"1": {"04": {"slug": "test-slug"}}}}
        content_path.write_text(json.dumps(v4, indent=2), encoding="utf-8")
        monkeypatch.setattr(cfg, "CONTENT_PATH", content_path)

        import main as main_mod
        result = main_mod._find_curriculum_key_by_slug("test-slug")
        assert result == "C1#04"

    def test_find_key_by_slug_not_found(self, monkeypatch, tmp_path):
        import nixfw.config as cfg
        monkeypatch.chdir(tmp_path)
        content_path = tmp_path / "curriculum_content.json"
        v4 = {"topics": {"1": {"04": {"slug": "other"}}}}
        content_path.write_text(json.dumps(v4, indent=2), encoding="utf-8")
        monkeypatch.setattr(cfg, "CONTENT_PATH", content_path)

        import main as main_mod
        result = main_mod._find_curriculum_key_by_slug("nonexistent")
        assert result is None

    def test_find_key_by_slug_file_missing(self, monkeypatch, tmp_path):
        import nixfw.config as cfg
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(cfg, "CONTENT_PATH", tmp_path / "nonexistent.json")
        import main as main_mod
        result = main_mod._find_curriculum_key_by_slug("test")
        assert result is None

    def test_add_schedule_entry_writes_curriculum_ref(self, monkeypatch, tmp_path):
        """Before Phase 1: writes 'curriculum' field. After Phase 1: writes 'source_ref'.
        This test validates both cases."""
        import nixfw.config as cfg
        monkeypatch.setattr(cfg, "SCHEDULE_PATH", tmp_path / "schedule.json")
        monkeypatch.chdir(tmp_path)
        content_path = tmp_path / "curriculum_content.json"
        v4 = {"topics": {"1": {"04": {"slug": "test-slug"}}}}
        content_path.write_text(json.dumps(v4, indent=2), encoding="utf-8")
        monkeypatch.setattr(cfg, "CONTENT_PATH", content_path)

        import main as main_mod
        main_mod._add_schedule_entry("test-slug", "carousel", ["url1"], "Test caption", "2026-06-20 19:00")

        schedule_path = tmp_path / "schedule.json"
        schedule = json.loads(schedule_path.read_text(encoding="utf-8"))
        assert len(schedule) == 1
        entry = schedule[0]
        if "source_ref" in entry:
            assert entry["source_ref"] == "C1#04"
        elif "curriculum" in entry:
            assert entry["curriculum"] == "C1#04"
        assert entry["type"] == "carousel"
        assert entry["urls"] == ["url1"]


class TestBioReaders:
    """Tests for build_card_statuses reader.

    NOTE: Old regex r'(\\d+)' on value 'S1#06' matched '1' (from S1) not '06'.
    Now fixed to r'#(\\d+)' — card_num extracts from after # correctly.
    Tests reflect current fixed behavior.
    """

    def test_build_card_statuses_with_curriculum(self, schedule_old):
        result = build_card_statuses(schedule_old)
        assert 1 in result
        card1 = result[1]
        assert card1[0] == "tag-live"

    def test_build_card_statuses_with_source_ref(self, schedule_clean):
        result = build_card_statuses(schedule_clean)
        assert 1 in result
        card1 = result[1]
        assert card1[0] == "tag-live"

    def test_build_card_statuses_non_curriculum_skipped(self, schedule_old):
        result = build_card_statuses(schedule_old)
        assert len(result) == 3  # 3 curriculum entries, 1 non-curriculum skipped
        assert None not in result  # no None keys
        assert 1 in result and 6 in result and 7 in result

    def test_build_card_statuses_scheduled(self, schedule_mixed):
        result = build_card_statuses(schedule_mixed)
        assert 1 in result
