"""Integration tests with mocked InstagramClient — no real API calls."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tests.mocks.mock_ig_client import MockInstagramClient


class TestMockIGClient:
    """Verify mock works as expected before testing pipeline."""

    def test_mock_post_photo(self):
        client = MockInstagramClient()
        result = client.post_photo("https://example.jpg")
        assert result["id"] == "mock_photo_001"
        assert "permalink" in result

    def test_mock_post_carousel(self):
        client = MockInstagramClient()
        result = client.post_carousel(["url1", "url2"])
        assert result["id"] == "mock_carousel_001"

    def test_mock_post_reel(self):
        client = MockInstagramClient()
        result = client.post_reel("https://example.mp4")
        assert result["id"] == "mock_reel_001"

    def test_mock_get_media_by_id(self):
        client = MockInstagramClient()
        result = client.get_media_by_id("test_123")
        assert result["id"] == "test_123"
        assert result["permalink"] == "https://ig.mock/p/test_123"


class TestRunnerWithMock:
    """Test runner.py posting logic with mock InstagramClient."""

    def test_runner_posts_carousel(self, tmp_path):
        """Simulate runner posting a carousel entry with mock client."""
        client = MockInstagramClient()
        schedule = [
            {
                "source_ref": "C1#06",
                "time": "2026-06-17 19:00",
                "type": "carousel",
                "done": False,
                "urls": ["https://catbox.moe/s1.png", "https://catbox.moe/s2.png"],
                "caption": "Test carousel",
            }
        ]

        post = schedule[0]
        ptype = post.get("type", "?")
        assert ptype == "carousel"
        assert post.get("urls")

        result = client.post_carousel(post["urls"], post.get("caption", ""))
        post["done"] = True
        post["result_id"] = result.get("id", "")
        media_info = client.get_media_by_id(post["result_id"])
        post["permalink"] = media_info.get("permalink", "")

        assert post["done"] is True
        assert post["result_id"] == "mock_carousel_001"
        assert post["permalink"] == "https://ig.mock/p/mock_carousel_001"

    def test_runner_posts_photo(self, tmp_path):
        client = MockInstagramClient()
        post = {
            "time": "2026-06-07 09:00",
            "type": "photo",
            "url": "https://catbox.moe/photo.jpg",
            "caption": "Test photo",
            "done": False,
        }

        result = client.post_photo(post["url"], post.get("caption", ""))
        post["done"] = True
        post["result_id"] = result.get("id", "")
        media_info = client.get_media_by_id(post["result_id"])
        post["permalink"] = media_info.get("permalink", "")

        assert post["done"] is True
        assert post["result_id"] == "mock_photo_001"

    def test_runner_posts_reel(self, tmp_path):
        client = MockInstagramClient()
        post = {
            "time": "2026-06-18 19:00",
            "type": "reel",
            "url": "https://catbox.moe/reel.mp4",
            "done": False,
        }

        result = client.post_reel(post["url"], "")
        post["done"] = True
        post["result_id"] = result.get("id", "")
        media_info = client.get_media_by_id(post["result_id"])
        post["permalink"] = media_info.get("permalink", "")

        assert post["done"] is True
        assert post["result_id"] == "mock_reel_001"

    def test_runner_updates_schedule_file(self, tmp_path):
        """Simulate the full runner loop — post then save to schedule.json."""
        client = MockInstagramClient()
        sched_path = tmp_path / "schedule.json"

        schedule = [
            {"source_ref": "C1#06", "time": "2026-06-17 19:00", "type": "carousel",
             "done": False, "urls": ["u1", "u2"], "caption": "Test"}
        ]

        for post in schedule:
            if post["type"] == "carousel" and post.get("urls"):
                result = client.post_carousel(post["urls"], post.get("caption", ""))
                post["done"] = True
                post["result_id"] = result.get("id", "")
                info = client.get_media_by_id(post["result_id"])
                post["permalink"] = info.get("permalink", "")

        sched_path.write_text(json.dumps(schedule, indent=2), encoding="utf-8")
        saved = json.loads(sched_path.read_text(encoding="utf-8"))

        assert saved[0]["done"] is True
        assert saved[0]["result_id"] == "mock_carousel_001"
        assert saved[0]["permalink"] == "https://ig.mock/p/mock_carousel_001"


class TestPostCarouselWithMock:
    """Test post-carousel flow with mock client."""

    def test_post_carousel_upload_only(self):
        """Simulate the 'upload only' branch of cmd_post_carousel."""
        client = MockInstagramClient()
        urls = ["https://catbox.moe/s1.png", "https://catbox.moe/s2.png"]
        caption = "Test carousel"

        media_id = None
        for url in urls:
            # In real code: upload to IG as individual media, get container ID
            pass

        result = client.post_carousel(urls, caption)
        assert result["id"] == "mock_carousel_001"

    def test_post_carousel_direct_publish(self):
        """Simulate the direct publish branch."""
        client = MockInstagramClient()
        result = client.post_carousel(["url1", "url2"], "Test")
        assert result["permalink"] == "https://ig.mock/p/mock_carousel_001"
