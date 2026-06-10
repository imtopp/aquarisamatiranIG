import os
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class InstagramError(Exception):
    ...


_WEEKDAYS = {"senin": 0, "selasa": 1, "rabu": 2, "kamis": 3, "jumat": 4, "sabtu": 5, "minggu": 6,
              "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def parse_schedule(text: str) -> int:
    """Parse jadwal kayak 'Mon 19:00' atau '2026-06-08 19:00' ke unix timestamp."""
    text = text.strip()

    # Coba format: YYYY-MM-DD HH:MM
    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M")
        return int(dt.timestamp())
    except ValueError:
        pass

    # Coba format: Day HH:MM (misal "Mon 19:00" atau "Senin 19:00")
    import re
    m = re.match(r"(\w+)\s+(\d{1,2}):(\d{2})", text)
    if m:
        day_str, h, mi = m.group(1).lower(), int(m.group(2)), int(m.group(3))
        target_wday = _WEEKDAYS.get(day_str)
        if target_wday is None:
            raise ValueError(f"Hari '{day_str}' ngga dikenal. Pake: Senin/Rabu/Jumat atau Mon/Wed/Fri")
        now = datetime.now()
        days_ahead = target_wday - now.weekday()
        if days_ahead <= 0 or (days_ahead == 0 and now.hour >= h):
            days_ahead += 7
        dt = (now + timedelta(days=days_ahead)).replace(hour=h, minute=mi, second=0, microsecond=0)
        return int(dt.timestamp())

    raise ValueError("Format jadwal: 'Mon 19:00' / 'Senin 19:00' / '2026-06-08 19:00'")


@dataclass
class InstagramClient:
    access_token: str = ""
    ig_user_id: str = field(default_factory=lambda: os.getenv("IG_USER_ID", ""))
    api_version: str = "v22.0"
    base_url: str = ""

    def __post_init__(self):
        # Prioritaskan FB_PAGE_TOKEN (graph.facebook.com), fallback IG_ACCESS_TOKEN (graph.instagram.com)
        fb_token = os.getenv("FB_PAGE_TOKEN") or os.getenv("FB_ACCESS_TOKEN", "")
        ig_token = os.getenv("IG_ACCESS_TOKEN", "")
        if fb_token:
            self.access_token = fb_token
            self.base_url = "https://graph.facebook.com"
        elif ig_token:
            self.access_token = ig_token
            self.base_url = "https://graph.instagram.com"
        else:
            raise InstagramError("FB_PAGE_TOKEN atau IG_ACCESS_TOKEN wajib diisi di .env")
        if not self.ig_user_id:
            raise InstagramError("IG_USER_ID wajib diisi di .env")

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{self.api_version}/{path.lstrip('/')}"

    def _get(self, path: str, params: dict | None = None) -> dict:
        p = {"access_token": self.access_token, **(params or {})}
        r = requests.get(self._url(path), params=p)
        if not r.ok:
            raise InstagramError(f"GET {path} gagal: {r.status_code} {r.text}")
        return r.json()

    def _post(self, path: str, data: dict | None = None, params: dict | None = None) -> dict:
        p = {"access_token": self.access_token, **(params or {})}
        r = requests.post(self._url(path), data=data, params=p)
        if not r.ok:
            raise InstagramError(f"POST {path} gagal: {r.status_code} {r.text}")
        return r.json()

    # ── Profile ──

    def get_profile(self) -> dict:
        if "facebook.com" in self.base_url:
            return self._get(f"{self.ig_user_id}", {"fields": "id,username,profile_picture_url,followers_count,media_count"})
        return self._get("me", {"fields": "user_id,username,account_type,profile_picture_url,followers_count,media_count"})

    # ── Media ──

    def get_media(self, limit: int = 25) -> list[dict]:
        data = self._get(f"{self.ig_user_id}/media", {"fields": "id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count", "limit": limit})
        return data.get("data", [])

    def get_media_by_id(self, media_id: str) -> dict:
        return self._get(media_id, {"fields": "id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count"})

    # ── Publishing ──

    def _create_container(self, media_type: str, media_url: str, caption: str = "", scheduled_publish_time: int | None = None, **extra) -> str:
        if media_type == "STORIES":
            url_key = "video_url" if extra.get("video_url") else "image_url"
            data = {"media_type": "STORIES", url_key: media_url, "caption": caption}
        else:
            data = {"media_type": media_type, "caption": caption, **extra}
            if media_type in ("VIDEO", "REELS"):
                data["video_url"] = media_url
            elif media_type == "IMAGE":
                data["image_url"] = media_url
        if scheduled_publish_time is not None:
            data["published"] = False
            data["scheduled_publish_time"] = scheduled_publish_time
        result = self._post(f"{self.ig_user_id}/media", data)
        container_id = result.get("id")
        if not container_id:
            raise InstagramError(f"Gagal buat container: {result}")
        return container_id

    def _wait_for_container(self, container_id: str, timeout: int = 120, interval: int = 3) -> dict:
        for _ in range(timeout // interval):
            status = self._get(container_id, {"fields": "status_code,status"})
            sc = status.get("status_code") or status.get("status", "")
            if sc == "FINISHED":
                return status
            if sc == "ERROR":
                error_msg = status.get("error_message", "unknown")
                raise InstagramError(f"Container {container_id} error: {error_msg}")
            time.sleep(interval)
        raise InstagramError(f"Container {container_id} timeout setelah {timeout}s")

    def _publish(self, container_id: str, retries: int = 3, delay: int = 5) -> dict:
        last_error = None
        for attempt in range(1, retries + 1):
            try:
                return self._post(f"{self.ig_user_id}/media_publish", {"creation_id": container_id})
            except InstagramError as e:
                last_error = e
                err_msg = str(e)
                if "Media ID is not available" in err_msg or "media is not ready" in err_msg:
                    if attempt < retries:
                        print(f"   ⏳ Media belum siap, coba lagi ({attempt}/{retries}) dalam {delay}s...")
                        time.sleep(delay)
                        continue
                raise
        raise last_error  # type: ignore[misc]

    def post_photo(self, image_url: str, caption: str = "", scheduled_publish_time: int | None = None) -> dict:
        container_id = self._create_container("IMAGE", image_url, caption, scheduled_publish_time=scheduled_publish_time)
        if scheduled_publish_time is not None:
            return {"id": container_id, "scheduled": True, "scheduled_publish_time": scheduled_publish_time}
        return self._publish(container_id)

    def post_carousel(self, image_urls: list[str], caption: str = "", scheduled_publish_time: int | None = None) -> dict:
        child_ids = []
        for url in image_urls:
            result = self._post(f"{self.ig_user_id}/media", {
                "image_url": url,
                "is_carousel_item": True,
            })
            cid = result.get("id")
            if not cid:
                raise InstagramError(f"Gagal buat carousel item: {result}")
            child_ids.append(cid)
            print(f"   🖼️  Item container: {cid}")
            time.sleep(1)

        carousel_data = {
            "media_type": "CAROUSEL",
            "children": ",".join(child_ids),
            "caption": caption,
        }
        if scheduled_publish_time is not None:
            carousel_data["published"] = False
            carousel_data["scheduled_publish_time"] = scheduled_publish_time
        carousel_result = self._post(f"{self.ig_user_id}/media", carousel_data)
        carousel_id = carousel_result.get("id")
        if not carousel_id:
            raise InstagramError(f"Gagal buat carousel container: {carousel_result}")
        print(f"   📦 Carousel container: {carousel_id}")

        if scheduled_publish_time is not None:
            return {"id": carousel_id, "scheduled": True, "scheduled_publish_time": scheduled_publish_time}

        # Tunggu container ready sebelum publish
        self._wait_for_container(carousel_id, timeout=60, interval=3)
        return self._publish(carousel_id)

    def post_video(self, video_url: str, caption: str = "", wait: bool = True, scheduled_publish_time: int | None = None) -> dict:
        container_id = self._create_container("VIDEO", video_url, caption, scheduled_publish_time=scheduled_publish_time)
        if scheduled_publish_time is not None:
            return {"id": container_id, "scheduled": True, "scheduled_publish_time": scheduled_publish_time}
        if wait:
            self._wait_for_container(container_id)
        return self._publish(container_id)

    def post_reel(self, video_url: str, caption: str = "", share_to_feed: bool = False, wait: bool = True, scheduled_publish_time: int | None = None) -> dict:
        container_id = self._create_container("REELS", video_url, caption, scheduled_publish_time=scheduled_publish_time, share_to_feed=share_to_feed)
        if scheduled_publish_time is not None:
            return {"id": container_id, "scheduled": True, "scheduled_publish_time": scheduled_publish_time}
        if wait:
            self._wait_for_container(container_id)
        return self._publish(container_id)

    def post_story(self, media_url: str, media_type: str = "IMAGE", caption: str = "") -> dict:
        params = {"media_type": "STORIES"}
        if media_type == "IMAGE":
            params["image_url"] = media_url
        else:
            params["video_url"] = media_url
        if caption:
            params["caption"] = caption
        result = self._post(f"{self.ig_user_id}/media", params)
        container_id = result.get("id")
        if not container_id:
            raise InstagramError(f"Gagal buat story container: {result}")
        return self._publish(container_id)

    # ── Delete / Takedown ──

    def _delete(self, path: str, params: dict | None = None) -> dict:
        p = {"access_token": self.access_token, **(params or {})}
        r = requests.delete(self._url(path), params=p)
        if not r.ok:
            raise InstagramError(f"DELETE {path} gagal: {r.status_code} {r.text}")
        return r.json()

    def delete_media(self, media_id: str) -> dict:
        return self._delete(media_id)

    # ── Comments ──

    def get_comments(self, media_id: str) -> list[dict]:
        data = self._get(f"{media_id}/comments", {"fields": "id,text,username,timestamp"})
        return data.get("data", [])

    def reply_comment(self, comment_id: str, message: str) -> dict:
        return self._post(f"{comment_id}/replies", {"message": message})

    def hide_comment(self, comment_id: str) -> dict:
        return self._post(f"{comment_id}/hide")

    def unhide_comment(self, comment_id: str) -> dict:
        return self._post(f"{comment_id}/unhide")

    # ── Insights ──

    def get_account_insights(self, metric: str = "impressions,reach,profile_views,follower_count") -> dict:
        return self._get(f"{self.ig_user_id}/insights", {"metric": metric, "period": "day"})

    def get_media_insights(self, media_id: str, metric: str = "impressions,reach,engagement,saved") -> dict:
        return self._get(f"{media_id}/insights", {"metric": metric})

    # ── Hashtags ──

    def search_hashtag(self, hashtag: str) -> dict:
        return self._get(f"ig_hashtag_search", {"user_id": self.ig_user_id, "q": hashtag})

    def get_hashtag_media(self, hashtag_id: str) -> list[dict]:
        data = self._get(f"{hashtag_id}/top_media", {"user_id": self.ig_user_id, "fields": "id,caption,media_type,media_url,permalink"})
        return data.get("data", [])
