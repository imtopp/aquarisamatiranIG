"""Tests for Telegram-callable curriculum CRUD helpers in manager.py."""

import json
from pathlib import Path

from nixfw.curriculum import manager as mgr


INITIAL = {
    "version": 5,
    "categories": {
        "1": {
            "title": "Category 1",
            "subtitle": "",
            "subcategories": {
                "1": {"title": "Level 1"},
                "2": {"title": "Level 2"},
            },
        }
    },
    "topics": {
        "1": {
            "01": {
                "slug": "test-topic",
                "title": "Test Topic",
                "subcategory": "1",
                "status": "planned",
                "keywords": [],
            }
        }
    },
}


def _init_src(tmp_path: Path) -> Path:
    src = tmp_path / "source_of_truth.json"
    src.write_text(json.dumps(INITIAL, indent=2), encoding="utf-8")
    return src


class TestTelegramAddCategory:
    def test_adds_new_category(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)
        result = mgr.telegram_add_category("New Cat", "sub")
        assert "Category 2" in result
        assert "New Cat" in result
        data = json.loads(src.read_text(encoding="utf-8"))
        assert data["categories"]["2"]["title"] == "New Cat"

    def test_rejects_empty_title(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        result = mgr.telegram_add_category("")
        assert "wajib" in result


class TestTelegramAddSubcategory:
    def test_adds_subcategory(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)
        result = mgr.telegram_add_subcategory("1", "3", "Level 3")
        assert "3" in result
        data = json.loads(src.read_text(encoding="utf-8"))
        assert data["categories"]["1"]["subcategories"]["3"]["title"] == "Level 3"

    def test_category_not_found(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        result = mgr.telegram_add_subcategory("99", "1", "X")
        assert "tidak ditemukan" in result


class TestTelegramAddTopic:
    def test_adds_topic(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)
        result = mgr.telegram_add_topic("1", "2", "My New Topic")
        assert "C1.2#01" in result
        data = json.loads(src.read_text(encoding="utf-8"))
        assert data["topics"]["1"]["02"]["title"] == "My New Topic"
        assert data["topics"]["1"]["02"]["subcategory"] == "2"

    def test_empty_category(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        result = mgr.telegram_add_topic("", "1", "X")
        assert "wajib" in result

    def test_empty_title(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        result = mgr.telegram_add_topic("1", "1", "")
        assert "wajib" in result

    def test_auto_slug(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)
        mgr.telegram_add_topic("1", "1", "My New Topic")
        data = json.loads(src.read_text(encoding="utf-8"))
        assert data["topics"]["1"]["02"]["slug"] == "my-new-topic"

    def test_custom_slug(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)
        mgr.telegram_add_topic("1", "1", "Another Topic", slug="custom-slug")
        data = json.loads(src.read_text(encoding="utf-8"))
        assert data["topics"]["1"]["02"]["slug"] == "custom-slug"

    def test_custom_keywords(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)
        mgr.telegram_add_topic("1", "1", "KW Topic", keywords=["kw1", "kw2"])
        data = json.loads(src.read_text(encoding="utf-8"))
        assert data["topics"]["1"]["02"]["keywords"] == ["kw1", "kw2"]


class TestTelegramEditTopic:
    def test_edit_title(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)
        result = mgr.telegram_edit_topic("C1#01", title="Updated Title")
        assert "C1#01" in result
        data = json.loads(src.read_text(encoding="utf-8"))
        assert data["topics"]["1"]["01"]["title"] == "Updated Title"

    def test_edit_status(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)
        mgr.telegram_edit_topic("C1#01", status="live")
        data = json.loads(src.read_text(encoding="utf-8"))
        assert data["topics"]["1"]["01"]["status"] == "live"

    def test_edit_subcategory(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)
        mgr.telegram_edit_topic("C1#01", subcategory="2")
        data = json.loads(src.read_text(encoding="utf-8"))
        assert data["topics"]["1"]["01"]["subcategory"] == "2"

    def test_edit_keywords(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)
        mgr.telegram_edit_topic("C1#01", keywords=["a", "b"])
        data = json.loads(src.read_text(encoding="utf-8"))
        assert data["topics"]["1"]["01"]["keywords"] == ["a", "b"]

    def test_edit_slug(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)
        mgr.telegram_edit_topic("C1#01", slug="new-slug")
        data = json.loads(src.read_text(encoding="utf-8"))
        assert data["topics"]["1"]["01"]["slug"] == "new-slug"

    def test_ref_not_found(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        result = mgr.telegram_edit_topic("C1#99", title="X")
        assert "tidak ditemukan" in result

    def test_invalid_format(self, monkeypatch, tmp_path):
        result = mgr.telegram_edit_topic("invalid", title="X")
        assert "Format" in result


class TestTelegramDeleteTopic:
    def test_delete_topic(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)
        result = mgr.telegram_delete_topic("C1#01")
        assert "dihapus" in result
        data = json.loads(src.read_text(encoding="utf-8"))
        assert "01" not in data["topics"]["1"]

    def test_ref_not_found(self, monkeypatch, tmp_path):
        src = _init_src(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        result = mgr.telegram_delete_topic("C1#99")
        assert "tidak ditemukan" in result

    def test_invalid_format(self, monkeypatch, tmp_path):
        result = mgr.telegram_delete_topic("invalid")
        assert "Format" in result


class TestTelegramMoveTopic:
    def _setup_two_cats(self, tmp_path):
        data = dict(INITIAL)
        data["categories"]["2"] = {
            "title": "Category 2",
            "subtitle": "",
            "subcategories": {"1": {"title": "Level 1"}},
        }
        # Need to have at least one topic in cat 1
        src = tmp_path / "source_of_truth.json"
        src.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return src

    def test_move_topic(self, monkeypatch, tmp_path):
        src = self._setup_two_cats(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)
        result = mgr.telegram_move_topic("C1#01", "2", "1")
        assert "dipindah" in result
        assert "C2." in result and "#01" in result
        data = json.loads(src.read_text(encoding="utf-8"))
        assert "01" not in data["topics"].get("1", {})
        assert data["topics"]["2"]["01"]["title"] == "Test Topic"
        assert data["topics"]["2"]["01"]["subcategory"] == "1"

    def test_target_cat_not_found(self, monkeypatch, tmp_path):
        src = self._setup_two_cats(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        result = mgr.telegram_move_topic("C1#01", "99", "1")
        assert "tidak ditemukan" in result

    def test_source_topic_not_found(self, monkeypatch, tmp_path):
        src = self._setup_two_cats(tmp_path)
        monkeypatch.setattr(mgr, "SRC", src)
        result = mgr.telegram_move_topic("C1#99", "2", "1")
        assert "tidak ditemukan" in result

    def test_invalid_format(self, monkeypatch, tmp_path):
        result = mgr.telegram_move_topic("invalid", "2", "1")
        assert "Format" in result


class TestTelegramHelpersStandalone:
    """Unit tests that don't need monkeypatch or tmp_path."""

    def test_edit_invalid_ref(self):
        result = mgr.telegram_edit_topic("abc")
        assert "Format" in result

    def test_delete_invalid_ref(self):
        result = mgr.telegram_delete_topic("xyz")
        assert "Format" in result

    def test_move_invalid_ref(self):
        result = mgr.telegram_move_topic("abc", "1", "1")
        assert "Format" in result

    def test_add_category_empty(self):
        result = mgr.telegram_add_category("")
        assert "wajib" in result

    def test_add_topic_no_cat(self):
        result = mgr.telegram_add_topic("", "1", "X")
        assert "wajib" in result

    def test_add_topic_no_title(self):
        result = mgr.telegram_add_topic("1", "1", "")
        assert "wajib" in result
