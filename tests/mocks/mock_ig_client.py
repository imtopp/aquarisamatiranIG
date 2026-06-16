"""Stateless mock for InstagramClient — no network calls, returns dicts."""

from dataclasses import dataclass


@dataclass
class MockInstagramClient:
    access_token: str = "mock_token"
    ig_user_id: str = "mock_123"
    api_version: str = "v22.0"
    base_url: str = "https://graph.mock.instagram.com"

    def post_photo(self, url: str, caption: str = "") -> dict:
        return {"id": "mock_photo_001", "permalink": "https://ig.mock/p/mock_photo_001"}

    def post_reel(self, url: str, caption: str = "") -> dict:
        return {"id": "mock_reel_001", "permalink": "https://ig.mock/p/mock_reel_001"}

    def post_carousel(self, urls: list[str], caption: str = "") -> dict:
        return {"id": "mock_carousel_001", "permalink": "https://ig.mock/p/mock_carousel_001"}

    def get_media_by_id(self, media_id: str) -> dict:
        return {"id": media_id, "permalink": f"https://ig.mock/p/{media_id}"}
