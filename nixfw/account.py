"""Account management — multi-account context + registry."""
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from nixfw import config


_registry: dict[str, "AccountContext"] = {}
_active: Optional["AccountContext"] = None


@dataclass
class AccountContext:
    name: str
    base: Path
    enabled: bool = True
    niche: Optional[str] = None
    config_data: dict = field(default_factory=dict)

    @property
    def source_of_truth(self) -> Path:
        return self.base / "source_of_truth.json"

    @property
    def schedule_json(self) -> Path:
        return self.base / "schedule.json"

    @property
    def curriculum_md(self) -> Path:
        return self.base / "curriculum.md"

    @property
    def bio_html(self) -> Path:
        return self.base / "bio" / "index.html"

    @property
    def resource_dir(self) -> Path:
        rd = self.config_data.get("resource_dir", "resource")
        return self.base / rd

    @property
    def photo_dir(self) -> Path:
        return self.resource_dir / "photos"

    @property
    def scheduler_output_dir(self) -> Path:
        return self.resource_dir / ".scheduler_output"

    @property
    def uploaded_json(self) -> Path:
        return self.resource_dir / ".uploaded.json"

    @property
    def logo_dir(self) -> Path:
        return self.resource_dir / "logo"

    @property
    def output_dir(self) -> Path:
        return self.resource_dir / "output"

    @property
    def published_dir(self) -> Path:
        return self.resource_dir / "published"


def load_account(name: str) -> Optional[AccountContext]:
    """Load a single account from disk by name."""
    base = config.PROJECT_ROOT / "accounts" / name
    cfg_path = base / "config.json"
    if not cfg_path.exists():
        return None
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    enabled = cfg.pop("enabled", True)
    return AccountContext(
        name=name,
        base=base,
        enabled=enabled,
        niche=cfg.get("niche"),
        config_data=cfg,
    )


def load_registry():
    """Scan accounts/ directory and populate _registry."""
    _registry.clear()
    accounts_dir = config.PROJECT_ROOT / "accounts"
    if not accounts_dir.is_dir():
        return
    for d in sorted(accounts_dir.iterdir()):
        if not d.is_dir():
            continue
        ctx = load_account(d.name)
        if ctx and ctx.enabled:
            _registry[ctx.name] = ctx


def get_account(account: Optional[str | AccountContext] = None) -> AccountContext:
    """Resolve account reference to AccountContext.

    - None -> _active or first enabled or fallback from ACCOUNT_NAME
    - str -> lookup in _registry (load on demand if missing)
    - AccountContext -> return as-is
    """
    if isinstance(account, AccountContext):
        return account
    if isinstance(account, str):
        if account not in _registry:
            ctx = load_account(account)
            if ctx and ctx.enabled:
                _registry[account] = ctx
        if account in _registry:
            return _registry[account]
        raise ValueError(f"Account '{account}' not found or disabled")
    if _active is not None:
        return _active
    if _registry:
        first = next(iter(_registry.values()))
        return first
    load_registry()
    if _registry:
        first = next(iter(_registry.values()))
        return first
    if config.ACCOUNT_NAME:
        ctx = load_account(config.ACCOUNT_NAME)
        if ctx:
            _registry[ctx.name] = ctx
            return ctx
    raise RuntimeError("No accounts found. Run 'account init' first.")


def set_active_account(name: str):
    """Set the active account for CLI commands."""
    ctx = get_account(name)
    globals()["_active"] = ctx


def list_accounts() -> list[dict]:
    """Return list of all account summaries (enabled + disabled)."""
    accounts_dir = config.PROJECT_ROOT / "accounts"
    result = []
    if not accounts_dir.is_dir():
        return result
    for d in sorted(accounts_dir.iterdir()):
        if not d.is_dir():
            continue
        cfg_path = d / "config.json"
        if not cfg_path.exists():
            continue
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
        result.append({
            "name": d.name,
            "niche": cfg.get("niche", "?"),
            "enabled": cfg.get("enabled", True),
            "handle": cfg.get("handle", ""),
        })
    return result


def add_account(name: str, niche: str, from_account: Optional[str] = None) -> AccountContext:
    """Create a new account directory from template."""
    tpl_dir = config.PROJECT_ROOT / "nixfw" / "templates" / "account"
    dest = config.PROJECT_ROOT / "accounts" / name
    if dest.exists():
        raise FileExistsError(f"Account '{name}' already exists at {dest}")

    shutil.copytree(tpl_dir, dest)

    cfg_path = dest / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

    if from_account:
        src_cfg = config.PROJECT_ROOT / "accounts" / from_account / "config.json"
        if src_cfg.exists():
            src_data = json.loads(src_cfg.read_text(encoding="utf-8"))
            src_data["handle"] = f"@{name}"
            src_data["name"] = name
            src_data["niche"] = niche
            src_data["enabled"] = True
            cfg_path.write_text(json.dumps(src_data, indent=2, ensure_ascii=False), encoding="utf-8")
            cfg = src_data
    else:
        niche_profile = config._NICHE_REGISTRY.get(niche)
        if niche_profile:
            cfg["handle"] = f"@{name}"
            cfg["name"] = name
            cfg["niche"] = niche
            cfg["tagline"] = f"Konten {niche_profile.niche_name}"
            cfg["tone"] = "santai, edukatif, engaging"
            cfg["mission"] = f"Menyajikan konten {niche_profile.niche_name} yang menarik"
            cfg["enabled"] = True
            cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

    sot = {
        "version": 5,
        "categories": {},
        "topics": {},
        "adhoc_topics": [],
    }
    (dest / "source_of_truth.json").write_text(
        json.dumps(sot, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    (dest / "schedule.json").write_text("[]", encoding="utf-8")

    (dest / "bio").mkdir(parents=True, exist_ok=True)
    (dest / "bio" / "index.html").write_text(
        f"<!DOCTYPE html><html><head><title>{name}</title></head>"
        f"<body><h1>{name}</h1><p>Coming soon</p></body></html>",
        encoding="utf-8",
    )

    ctx = load_account(name)
    if ctx:
        _registry[name] = ctx
    return ctx


def enable_account(name: str):
    """Enable a disabled account."""
    cfg_path = config.PROJECT_ROOT / "accounts" / name / "config.json"
    if not cfg_path.exists():
        raise FileNotFoundError(f"Account '{name}' not found")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["enabled"] = True
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    ctx = load_account(name)
    if ctx:
        _registry[name] = ctx


def disable_account(name: str):
    """Disable an account (keep data on disk)."""
    cfg_path = config.PROJECT_ROOT / "accounts" / name / "config.json"
    if not cfg_path.exists():
        raise FileNotFoundError(f"Account '{name}' not found")
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["enabled"] = False
    cfg_path.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    _registry.pop(name, None)


def remove_account(name: str, force: bool = False):
    """Permanently delete an account directory."""
    dest = config.PROJECT_ROOT / "accounts" / name
    if not dest.exists():
        raise FileNotFoundError(f"Account '{name}' not found")
    if not force:
        confirm = input(f"Delete account '{name}' and all its data? (y/N): ")
        if confirm.lower() != "y":
            print("Cancelled.")
            return
    shutil.rmtree(dest)
    _registry.pop(name, None)
    print(f"  Account '{name}' deleted.")
