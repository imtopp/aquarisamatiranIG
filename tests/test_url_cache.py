"""Tests for URL cache functions in commands.py."""

from pathlib import Path

from nixfw.cli import commands as cmd


class TestUrlCache:
    def test_read_empty_cache(self, tmp_path):
        cache_file = tmp_path / ".urls_cache.json"
        cmd._URLS_CACHE = cache_file
        assert cmd._read_urls_cache() == {}

    def test_save_and_read(self, tmp_path):
        cache_file = tmp_path / ".urls_cache.json"
        cmd._URLS_CACHE = cache_file
        data = {"my-slug": {"slide1.jpg": "https://catbox.moe/abc.jpg"}}
        cmd._save_urls_cache(data)
        assert cache_file.exists()
        result = cmd._read_urls_cache()
        assert result == data

    def test_cached_upload_url_hit(self, tmp_path):
        cache_file = tmp_path / ".urls_cache.json"
        cmd._URLS_CACHE = cache_file
        data = {"my-slug": {"slide1.jpg": "https://catbox.moe/abc.jpg"}}
        cmd._save_urls_cache(data)
        url = cmd._cached_upload_url("my-slug", "slide1.jpg")
        assert url == "https://catbox.moe/abc.jpg"

    def test_cached_upload_url_miss(self, tmp_path):
        cache_file = tmp_path / ".urls_cache.json"
        cmd._URLS_CACHE = cache_file
        data = {"my-slug": {"slide1.jpg": "https://catbox.moe/abc.jpg"}}
        cmd._save_urls_cache(data)
        url = cmd._cached_upload_url("my-slug", "other.jpg")
        assert url is None

    def test_cached_upload_url_no_slug(self, tmp_path):
        cache_file = tmp_path / ".urls_cache.json"
        cmd._URLS_CACHE = cache_file
        data = {"other-slug": {"slide1.jpg": "https://catbox.moe/abc.jpg"}}
        cmd._save_urls_cache(data)
        url = cmd._cached_upload_url("my-slug", "slide1.jpg")
        assert url is None

    def test_cache_upload_url(self, tmp_path):
        cache_file = tmp_path / ".urls_cache.json"
        cmd._URLS_CACHE = cache_file
        cmd._cache_upload_url("my-slug", "slide1.jpg", "https://catbox.moe/abc.jpg")
        result = cmd._read_urls_cache()
        assert result["my-slug"]["slide1.jpg"] == "https://catbox.moe/abc.jpg"

    def test_cache_overwrite(self, tmp_path):
        cache_file = tmp_path / ".urls_cache.json"
        cmd._URLS_CACHE = cache_file
        cmd._cache_upload_url("my-slug", "slide1.jpg", "old.url")
        cmd._cache_upload_url("my-slug", "slide1.jpg", "new.url")
        result = cmd._read_urls_cache()
        assert result["my-slug"]["slide1.jpg"] == "new.url"

    def test_multiple_slugs_separate(self, tmp_path):
        cache_file = tmp_path / ".urls_cache.json"
        cmd._URLS_CACHE = cache_file
        cmd._cache_upload_url("slug-a", "1.jpg", "url.a.1")
        cmd._cache_upload_url("slug-b", "1.jpg", "url.b.1")
        result = cmd._read_urls_cache()
        assert result["slug-a"]["1.jpg"] == "url.a.1"
        assert result["slug-b"]["1.jpg"] == "url.b.1"

    def test_read_corrupted_cache(self, tmp_path):
        cache_file = tmp_path / ".urls_cache.json"
        cmd._URLS_CACHE = cache_file
        cache_file.write_text("invalid json", encoding="utf-8")
        # json.JSONDecodeError propagates — not crashing is enough
        import pytest
        with pytest.raises(Exception):
            cmd._read_urls_cache()

    def test_cache_creates_parent_dir(self, tmp_path):
        nested = tmp_path / "nested" / "dir" / ".urls_cache.json"
        cmd._URLS_CACHE = nested
        cmd._save_urls_cache({"a": {"b": "c"}})
        assert nested.exists()
        assert nested.parent.exists()
