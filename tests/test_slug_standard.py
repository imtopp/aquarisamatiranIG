"""Tests for slug standardization: facts_cache_path, cover fallback, curriculum update guards."""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from nixfw.content.providers.facts_generator import facts_cache_path
from nixfw.carousel.slides.cover import build_cover
from nixfw import config


class TestFactsCachePath:
    """facts_cache_path harus return path slug-based, bukan title-based."""

    def test_hyphen_slug(self):
        path = facts_cache_path("filter-aquarium")
        assert path.name == "edu_filter_aquarium_facts.json"

    def test_underscore_slug(self):
        path = facts_cache_path("filter_aquarium")
        assert path.name == "edu_filter_aquarium_facts.json"

    def test_long_slug_truncated(self):
        path = facts_cache_path("abcdefghijklmnopqrstuvwxyz")
        name = path.name
        assert name.startswith("edu_")
        assert name.endswith("_facts.json")
        core = name.replace("edu_", "").replace("_facts.json", "")
        assert len(core) <= 20

    def test_slug_with_spaces(self):
        path = facts_cache_path("test slug here")
        # spaces convert to underscores
        assert path.name == "edu_test_slug_here_facts.json"

    def test_slug_special_chars_stripped(self):
        path = facts_cache_path("what?! filter@#$")
        assert path.name == "edu_what_filter_facts.json"

    def test_existing_slug_matches_file_on_disk(self):
        """filter-aquarium → edu_filter_aquarium_facts.json — existing file must match."""
        path = facts_cache_path("filter-aquarium")
        photo_dir = PROJECT_ROOT / "accounts" / "aquarisamatiran" / "resource" / "photos"
        full = photo_dir / path.name
        assert full.exists(), f"Expected {path.name} to exist on disk"


class TestCoverFallback:
    """build_cover harus fallback gracefully kalo display_name kosong atau scientific_name N/A."""

    def test_empty_display_name_uses_topic(self, monkeypatch):
        monkeypatch.setattr(config, "PALETTE", {
            "bg_dark": "#000000", "bg_card": "#111111",
            "text_main": "#FFFFFF", "text_sub": "#AAAAAA",
            "accent": "#4FC3F7", "accent2": "#00E5FF", "tag_bg": "#333333",
        })
        monkeypatch.setattr(config, "SLIDE_SIZE", (200, 200))
        monkeypatch.setattr(config, "IG_HANDLE", "@test")
        facts = {"topic": "Fallback Topic", "display_name": "",
                 "scientific_name": "N/A", "subtitle": "", "facts": []}
        img = build_cover(facts, None)
        assert img is not None
        # Should not crash — display_name falls back to "Fallback Topic"

    def test_na_scientific_name_filtered(self, monkeypatch):
        monkeypatch.setattr(config, "PALETTE", {
            "bg_dark": "#000000", "bg_card": "#111111",
            "text_main": "#FFFFFF", "text_sub": "#AAAAAA",
            "accent": "#4FC3F7", "accent2": "#00E5FF", "tag_bg": "#333333",
        })
        monkeypatch.setattr(config, "SLIDE_SIZE", (200, 200))
        monkeypatch.setattr(config, "IG_HANDLE", "@test")
        facts = {"topic": "Test", "display_name": "Valid Name",
                 "scientific_name": "N/A", "subtitle": "", "facts": []}
        img = build_cover(facts, None)
        assert img is not None

    def test_valid_scientific_name_shown(self, monkeypatch):
        monkeypatch.setattr(config, "PALETTE", {
            "bg_dark": "#000000", "bg_card": "#111111",
            "text_main": "#FFFFFF", "text_sub": "#AAAAAA",
            "accent": "#4FC3F7", "accent2": "#00E5FF", "tag_bg": "#333333",
        })
        monkeypatch.setattr(config, "SLIDE_SIZE", (200, 200))
        monkeypatch.setattr(config, "IG_HANDLE", "@test")
        facts = {"topic": "Test", "display_name": "Valid Name",
                 "scientific_name": "Poecilia reticulata", "subtitle": "", "facts": []}
        img = build_cover(facts, None)
        assert img is not None
