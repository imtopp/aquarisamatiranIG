"""Tests for account.py — multi-account context + registry."""

import json
from pathlib import Path

import pytest

from nixfw.account import (
    AccountContext,
    load_account,
    load_registry,
    get_account,
    set_active_account,
    list_accounts,
    add_account,
    enable_account,
    disable_account,
    remove_account,
)


class TestAccountContext:
    def test_properties(self, tmp_path):
        base = tmp_path / "accounts" / "testacc"
        base.mkdir(parents=True)
        (base / "source_of_truth.json").write_text("{}", encoding="utf-8")
        (base / "schedule.json").write_text("[]", encoding="utf-8")
        (base / "bio").mkdir()
        (base / "bio" / "index.html").write_text("ok", encoding="utf-8")
        (base / "resource").mkdir()
        (base / "resource" / "photos").mkdir()
        (base / "resource" / ".scheduler_output").mkdir()
        ctx = AccountContext(name="testacc", base=base, enabled=True)

        assert ctx.source_of_truth == base / "source_of_truth.json"
        assert ctx.schedule_json == base / "schedule.json"
        assert ctx.bio_html == base / "bio" / "index.html"
        assert ctx.resource_dir == base / "resource"
        assert ctx.photo_dir == base / "resource" / "photos"
        assert ctx.scheduler_output_dir == base / "resource" / ".scheduler_output"
        assert ctx.name == "testacc"

    def test_resource_dir_from_config(self, tmp_path):
        base = tmp_path / "accounts" / "customres"
        base.mkdir(parents=True)
        cfg = {"resource_dir": "my_assets"}
        ctx = AccountContext(name="customres", base=base, config_data=cfg)
        assert ctx.resource_dir == base / "my_assets"

    def test_logo_dir(self, tmp_path):
        base = tmp_path / "accounts" / "logoacc"
        ctx = AccountContext(name="logoacc", base=base)
        assert ctx.logo_dir == base / "resource" / "logo"


class TestLoadAccount:
    def test_load_existing(self, tmp_path, monkeypatch):
        from nixfw import config
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        base = tmp_path / "accounts" / "myacc"
        base.mkdir(parents=True)
        cfg = {"niche": "food", "enabled": True, "handle": "@myacc"}
        (base / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

        ctx = load_account("myacc")
        assert ctx is not None
        assert ctx.name == "myacc"
        assert ctx.niche == "food"
        assert ctx.config_data.get("handle") == "@myacc"

    def test_load_missing(self, tmp_path, monkeypatch):
        from nixfw import config
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        ctx = load_account("nonexistent")
        assert ctx is None

    def test_load_disabled(self, tmp_path, monkeypatch):
        from nixfw import config
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        base = tmp_path / "accounts" / "disabledacc"
        base.mkdir(parents=True)
        (base / "config.json").write_text(
            json.dumps({"enabled": False, "niche": "tech"}), encoding="utf-8"
        )
        ctx = load_account("disabledacc")
        assert ctx is not None
        assert ctx.enabled is False


class TestLoadRegistry:
    def test_load_registry(self, tmp_path, monkeypatch):
        from nixfw import config
        from nixfw.account import _registry
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        _registry.clear()

        for name in ["acc1", "acc2"]:
            base = tmp_path / "accounts" / name
            base.mkdir(parents=True)
            (base / "config.json").write_text(
                json.dumps({"enabled": True}), encoding="utf-8"
            )

        load_registry()
        assert "acc1" in _registry
        assert "acc2" in _registry

    def test_load_registry_skips_disabled(self, tmp_path, monkeypatch):
        from nixfw import config
        from nixfw.account import _registry
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        _registry.clear()

        base = tmp_path / "accounts" / "disabled"
        base.mkdir(parents=True)
        (base / "config.json").write_text(
            json.dumps({"enabled": False}), encoding="utf-8"
        )
        base2 = tmp_path / "accounts" / "enabled"
        base2.mkdir(parents=True)
        (base2 / "config.json").write_text(
            json.dumps({"enabled": True}), encoding="utf-8"
        )

        load_registry()
        assert "disabled" not in _registry
        assert "enabled" in _registry

    def test_load_registry_empty_dir(self, tmp_path, monkeypatch):
        from nixfw import config
        from nixfw.account import _registry
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        _registry.clear()

        load_registry()
        assert len(_registry) == 0


class TestGetAccount:
    def test_get_account_by_name(self, tmp_path, monkeypatch):
        from nixfw import config
        from nixfw.account import _registry
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        _registry.clear()

        base = tmp_path / "accounts" / "myacc"
        base.mkdir(parents=True)
        (base / "config.json").write_text(
            json.dumps({"enabled": True}), encoding="utf-8"
        )
        load_registry()

        ctx = get_account("myacc")
        assert ctx.name == "myacc"

    def test_get_account_returns_active(self, tmp_path, monkeypatch):
        from nixfw import config
        from nixfw.account import _registry, _active
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        _registry.clear()
        globals_before = set(globals().keys())

        base1 = tmp_path / "accounts" / "primary"
        base1.mkdir(parents=True)
        (base1 / "config.json").write_text(
            json.dumps({"enabled": True}), encoding="utf-8"
        )
        base2 = tmp_path / "accounts" / "secondary"
        base2.mkdir(parents=True)
        (base2 / "config.json").write_text(
            json.dumps({"enabled": True}), encoding="utf-8"
        )
        load_registry()

        set_active_account("primary")
        ctx = get_account()
        assert ctx.name == "primary"

    def test_get_account_none_fallback(self, tmp_path, monkeypatch):
        from nixfw import config
        from nixfw.account import _registry, _active
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        _registry.clear()
        # Ensure _active is None
        import nixfw.account as acct_mod
        acct_mod._active = None

        base = tmp_path / "accounts" / "first"
        base.mkdir(parents=True)
        (base / "config.json").write_text(
            json.dumps({"enabled": True}), encoding="utf-8"
        )
        load_registry()

        ctx = get_account()
        assert ctx is not None

    def test_get_account_accountcontext_passthrough(self):
        ctx = AccountContext(name="direct", base=Path("/tmp"))
        result = get_account(ctx)
        assert result is ctx

    def test_get_account_not_found(self, tmp_path, monkeypatch):
        from nixfw import config
        from nixfw.account import _registry
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        _registry.clear()

        with pytest.raises(ValueError, match="not found"):
            get_account("nope")

    def test_get_account_loads_on_demand(self, tmp_path, monkeypatch):
        from nixfw import config
        from nixfw.account import _registry
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        _registry.clear()

        base = tmp_path / "accounts" / "lazy"
        base.mkdir(parents=True)
        (base / "config.json").write_text(
            json.dumps({"enabled": True}), encoding="utf-8"
        )

        ctx = get_account("lazy")
        assert ctx.name == "lazy"
        assert "lazy" in _registry


class TestAccountCRUD:
    def _setup_template(self, tmp_path):
        tpl = tmp_path / "nixfw" / "templates" / "account"
        tpl.mkdir(parents=True)
        (tpl / "config.json").write_text(
            json.dumps({"enabled": True, "niche": ""}), encoding="utf-8"
        )

    def test_add_account(self, tmp_path, monkeypatch):
        from nixfw import config
        from nixfw.account import _registry
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        _registry.clear()
        self._setup_template(tmp_path)

        ctx = add_account("newacc", "aquascape")
        assert ctx is not None
        assert ctx.name == "newacc"
        assert (tmp_path / "accounts" / "newacc").exists()
        assert (tmp_path / "accounts" / "newacc" / "source_of_truth.json").exists()
        assert (tmp_path / "accounts" / "newacc" / "bio" / "index.html").exists()

    def test_add_account_with_from(self, tmp_path, monkeypatch):
        from nixfw import config
        from nixfw.account import _registry
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        _registry.clear()
        self._setup_template(tmp_path)

        add_account("template", "aquascape")
        ctx = add_account("copycat", "food", from_account="template")
        assert ctx.name == "copycat"
        assert ctx.niche == "food"

    def test_add_account_duplicate(self, tmp_path, monkeypatch):
        from nixfw import config
        from nixfw.account import _registry
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        _registry.clear()
        self._setup_template(tmp_path)

        add_account("dup", "aquascape")
        with pytest.raises(FileExistsError):
            add_account("dup", "aquascape")

    def test_enable_disable_account(self, tmp_path, monkeypatch):
        from nixfw import config
        from nixfw.account import _registry
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        _registry.clear()
        self._setup_template(tmp_path)

        add_account("togglable", "aquascape")
        disable_account("togglable")
        accs = list_accounts()
        entry = [a for a in accs if a["name"] == "togglable"][0]
        assert entry["enabled"] is False

        enable_account("togglable")
        accs = list_accounts()
        entry = [a for a in accs if a["name"] == "togglable"][0]
        assert entry["enabled"] is True

    def test_disable_not_found(self, tmp_path, monkeypatch):
        from nixfw import config
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        with pytest.raises(FileNotFoundError):
            disable_account("nope")

    def test_list_accounts(self, tmp_path, monkeypatch):
        from nixfw import config
        from nixfw.account import _registry
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        _registry.clear()
        self._setup_template(tmp_path)

        add_account("alpha", "aquascape")
        add_account("beta", "food")
        accs = list_accounts()
        names = {a["name"] for a in accs}
        assert "alpha" in names
        assert "beta" in names

    def test_remove_account(self, tmp_path, monkeypatch):
        from nixfw import config
        from nixfw.account import _registry
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        _registry.clear()
        self._setup_template(tmp_path)

        add_account("goner", "aquascape")
        assert (tmp_path / "accounts" / "goner").exists()

        # force=True to skip prompt
        remove_account("goner", force=True)
        assert not (tmp_path / "accounts" / "goner").exists()
        assert "goner" not in _registry
