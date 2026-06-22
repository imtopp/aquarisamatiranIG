"""SlotManager — load, nearest, add, remove, sync slots."""
import datetime
import json
import os
from pathlib import Path

import httpx

from nixfw import config

WIB = datetime.timezone(datetime.timedelta(hours=7))

SLOTS_PATH = Path(__file__).resolve().parent / "slots.json"


DAYS_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
CRONJOB_API = "https://api.cron-job.org/jobs"


class SlotManager:
    def __init__(self, path: Path = SLOTS_PATH):
        self.path = path
        self.slots = []
        self._load()

    def _load(self):
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.slots = data.get("slots", [])
        else:
            self.slots = [
                {"id": "weekday-19", "days": [0, 1, 2, 3], "time": "19:00", "cron_id": 7783398, "title": "Weekday 19:00 WIB"},
                {"id": "fri-15", "days": [4], "time": "15:00", "cron_id": 7783399, "title": "Jumat 15:00 WIB"},
                {"id": "weekend-09", "days": [5, 6], "time": "09:00", "cron_id": 7783400, "title": "Weekend 09:00 WIB"},
                {"id": "lunch-12", "days": [0, 1, 2, 3, 4], "time": "12:00", "cron_id": 7783402, "title": "Lunch 12:00 WIB"},
            ]
            self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"slots": self.slots}, indent=2, ensure_ascii=False), encoding="utf-8")

    def nearest_slot(self, now: datetime.datetime | None = None, occupied: set | None = None) -> str:
        """Return nearest upcoming slot as 'YYYY-MM-DD HH:MM', skipping occupied times."""
        now = now or datetime.datetime.now(WIB)
        occupied = occupied or set()
        wday = now.weekday()
        hour = now.hour
        minute = now.minute

        best_dt = None
        best_time = None

        for slot in self.slots:
            hh, mm = slot["time"].split(":")
            h, m = int(hh), int(mm)
            for dw in slot["days"]:
                days_ahead = dw - wday
                if days_ahead < 0 or (days_ahead == 0 and (h < hour or (h == hour and m <= minute))):
                    days_ahead += 7
                target = now + datetime.timedelta(days=days_ahead)
                target = target.replace(hour=h, minute=m, second=0, microsecond=0)
                ts = target.strftime("%Y-%m-%d %H:%M")
                if ts in occupied:
                    continue
                if best_dt is None or target < best_dt:
                    best_dt = target
                    best_time = slot["time"]

        if best_dt:
            return best_dt.strftime("%Y-%m-%d") + " " + best_time
        fallback = now + datetime.timedelta(days=1)
        return fallback.strftime("%Y-%m-%d") + " 19:00"

    def add_slot(self, slot_id: str, days: list[int], time: str, cron_id: int = 0, title: str = "") -> bool:
        if any(s["id"] == slot_id for s in self.slots):
            return False
        self.slots.append({
            "id": slot_id, "days": days, "time": time,
            "cron_id": cron_id, "title": title or slot_id,
        })
        self.save()
        return True

    def remove_slot(self, slot_id: str) -> bool:
        before = len(self.slots)
        self.slots = [s for s in self.slots if s["id"] != slot_id]
        if len(self.slots) < before:
            self.save()
            return True
        return False

    @staticmethod
    def _slot_priority(time_str: str) -> int:
        return {"19:00": 4, "15:00": 3, "12:00": 2, "09:00": 1}.get(time_str, 0)

    def next_occurrences(self, n: int = 14, occupied: set | None = None) -> list[dict]:
        now = datetime.datetime.now(WIB)
        occupied = occupied or set()
        results = []
        seen_dates = set()

        for offset in range(n * 7):
            if len(results) >= n:
                break
            target = now + datetime.timedelta(days=offset)
            date_key = target.strftime("%Y-%m-%d")
            if date_key in seen_dates:
                continue
            wday = target.weekday()
            candidates = []
            for slot in self.slots:
                if wday in slot["days"]:
                    hh, mm = slot["time"].split(":")
                    h, m = int(hh), int(mm)
                    dt = target.replace(hour=h, minute=m, second=0, microsecond=0)
                    ts = dt.strftime("%Y-%m-%d %H:%M")
                    if ts in occupied:
                        continue
                    if offset == 0 and dt <= now:
                        continue
                    candidates.append((self._slot_priority(slot["time"]), slot["time"], ts))
            if candidates:
                candidates.sort(key=lambda x: -x[0])
                best = candidates[0]
                hh, mm = best[1].split(":")
                dt = target.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
                day_name = DAYS_ID[wday]
                results.append({
                    "label": f"{day_name} {best[1]}",
                    "iso": dt.strftime("%Y-%m-%d %H:%M"),
                })
                seen_dates.add(date_key)

        return results

    def format_list(self) -> str:
        lines = []
        for s in self.slots:
            days_str = ", ".join(DAYS_ID[d] for d in sorted(s["days"]))
            cron = f" (cron #{s['cron_id']})" if s.get("cron_id") else ""
            lines.append(f"• `{s['id']}` — {s['time']} — {days_str}{cron}")
        return "\n".join(lines) if lines else "(belum ada slot)"

    def _build_cron_body(self, slot: dict) -> dict:
        hh, mm = slot["time"].split(":")
        return {
            "job": {
                "enabled": True,
                "title": slot.get("title", slot["id"]),
                "saveResponses": True,
                "url": f"https://api.github.com/repos/{config.GH_REPO}/actions/workflows/scheduler.yml/dispatches",
                "requestMethod": 1,
                "schedule": {
                    "timezone": "Asia/Jakarta",
                    "hours": [int(hh)],
                    "mdays": [-1],
                    "minutes": [int(mm)],
                    "months": [-1],
                    "wdays": [(d + 1) % 7 for d in slot["days"]],
                },
                "extendedData": {
                    "headers": {
                        "Accept": "application/vnd.github.v3+json",
                        "Authorization": f"Bearer {os.environ.get('GH_PAT', '')}",
                        "Content-Type": "application/json",
                    },
                    "body": '{"ref":"main"}',
                },
            }
        }

    async def sync_cronjob(self) -> str:
        token = os.environ.get("CRONJOB_TOKEN") or os.environ.get("CRONJOB_API_KEY", "")
        if not token:
            return "❌ CRONJOB_TOKEN / CRONJOB_API_KEY gak ada di .env"
        changed = False
        results = []
        async with httpx.AsyncClient(timeout=15) as client:
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            for slot in self.slots:
                cid = slot.get("cron_id")
                body = self._build_cron_body(slot)
                try:
                    if cid:
                        resp = await client.patch(f"{CRONJOB_API}/{cid}", json=body, headers=headers)
                        if resp.status_code == 404:
                            results.append(f"  {slot['id']}: job #{cid} not found, re-creating...")
                            slot["cron_id"] = 0
                            cid = 0
                            resp = await client.put(CRONJOB_API, json=body, headers=headers)
                            if resp.status_code == 200:
                                new_id = resp.json().get("jobId", 0)
                                slot["cron_id"] = new_id
                                changed = True
                                results.append(f"  {slot['id']}: re-created (job #{new_id})")
                            else:
                                results.append(f"  {slot['id']}: re-create failed HTTP {resp.status_code}")
                        else:
                            results.append(f"  {slot['id']}: update HTTP {resp.status_code}")
                    else:
                        resp = await client.put(CRONJOB_API, json=body, headers=headers)
                        if resp.status_code == 200:
                            new_id = resp.json().get("jobId", 0)
                            slot["cron_id"] = new_id
                            changed = True
                            results.append(f"  {slot['id']}: created (job #{new_id})")
                        else:
                            results.append(f"  {slot['id']}: create failed HTTP {resp.status_code}")
                except Exception as e:
                    results.append(f"  {slot['id']}: ❌ {e}")
        if changed:
            self.save()
        return "\n".join(results)
