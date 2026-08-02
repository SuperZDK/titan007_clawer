"""
Priority provider: decides P0 (high-frequency) vs P1 (low-frequency) per match.

Interface:
    get_priority_map(dates) -> {schedule_id: "P0"|"P1"}

Default implementation reads a local whitelist JSON:
    config/live_priority.json
        {
          "default": "P1",
          "dates": {
            "2025-10-04": [2789130, 2789131, ...]   # P0 schedule_ids for that date
          }
        }

When the main project's "今日竞彩可投注赛事" table is ready, implement a
provider backed by it and swap it in (get_provider returns the right one).
"""
import json, os
from typing import Optional

from core import utils

PRIORITY_PATH = os.path.join(utils.BASE_DIR, "config", "live_priority.json")


class BasePriorityProvider:
    def get_priority_map(self, dates) -> dict:
        raise NotImplementedError


class LocalWhitelistProvider(BasePriorityProvider):
    """P0 = schedule_ids listed under the match date in live_priority.json."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or PRIORITY_PATH
        self._data = self._load()

    def _load(self) -> dict:
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}

    def get_priority_map(self, dates) -> dict:
        default = self._data.get("default", "P1")
        date_map = self._data.get("dates", {})
        result = {}
        for d in dates:
            if d not in date_map:
                continue
            for sid in date_map[d]:
                try:
                    result[int(sid)] = "P0"
                except (ValueError, TypeError):
                    continue
        return result

    def all_sids(self) -> set:
        sids = set()
        for d, ids in self._data.get("dates", {}).items():
            for sid in ids:
                try:
                    sids.add(int(sid))
                except (ValueError, TypeError):
                    continue
        return sids


def get_provider() -> BasePriorityProvider:
    return LocalWhitelistProvider()
