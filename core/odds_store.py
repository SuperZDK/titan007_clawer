"""
Odds persistence layer for the incremental (live) pipeline.

Data contract (stable primary key = schedule_id + odds_type + odds_subtype + company_id):
  {
    "schedule_id": int,
    "company_id": int,
    "company_name": str,
    "odds_type": "asian" | "over_under" | "european",
    "odds_subtype": "full" | "half",          # asian/ou only
    "competition_id": int,
    "competition_name_en": str,
    "season": str,
    "match_time": "YYYY-MM-DD HH:MM",         # Beijing, from schedule
    "source": "titan" | "nowscore",
    "fetched_at": "ISO8601 UTC",
    "_version": "v1",
    "changes": [ ... ]
  }

Change-row dedup key:
  asian / over_under: (time, line, home/big, away/small, status)
  european:           (time, home_win, draw, away_win)
"""
import json, os
from typing import Optional

ODDS_VERSION = "v1"


def change_key(change: dict, odds_type: str):
    if odds_type == "european":
        return (
            change.get("time"),
            change.get("home_win"),
            change.get("draw"),
            change.get("away_win"),
        )
    if odds_type == "over_under":
        return (
            change.get("time"),
            change.get("line"),
            change.get("big"),
            change.get("small"),
            change.get("status"),
        )
    return (
        change.get("time"),
        change.get("line"),
        change.get("home"),
        change.get("away"),
        change.get("status"),
    )


def merge_odds_changes(existing: list, new: list, odds_type: str) -> list:
    """Union of two change lists, deduped by change_key, preserving order.

    Existing rows keep their stored order; rows present only in `new` are
    appended at the end. Safe against page-side truncation (never drops rows).
    """
    merged = list(existing or [])
    seen = {change_key(c, odds_type) for c in merged}
    for row in new or []:
        key = change_key(row, odds_type)
        if key not in seen:
            merged.append(row)
            seen.add(key)
    return merged


def load_record(path: str) -> Optional[dict]:
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_record(rec: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)


def build_record(schedule_id: int, company_id: int, company_name: str,
                 odds_type: str, odds_subtype: str, changes: list,
                 comp: dict, season: str, match_time: str,
                 source: str, fetched_at: str = None) -> dict:
    rec = {
        "schedule_id": schedule_id,
        "company_id": company_id,
        "company_name": company_name,
        "odds_type": odds_type,
        "odds_subtype": odds_subtype,
        "competition_id": comp["id"],
        "competition_name_en": comp.get("name_en", ""),
        "season": season,
        "match_time": match_time,
        "source": source,
        "fetched_at": fetched_at or _iso_now(),
        "_version": ODDS_VERSION,
        "changes": changes,
    }
    return rec


def is_fresh(rec: Optional[dict], interval_seconds: int, now_iso: str = None) -> bool:
    """True if the record was fetched within interval_seconds."""
    if not rec or not rec.get("fetched_at"):
        return False
    try:
        from datetime import datetime
        last = datetime.strptime(rec["fetched_at"], "%Y-%m-%dT%H:%M:%SZ")
        ref = datetime.strptime(now_iso or _iso_now(), "%Y-%m-%dT%H:%M:%SZ")
        return (ref - last).total_seconds() < interval_seconds
    except (ValueError, TypeError):
        return False


def _iso_now() -> str:
    from . import datetime_utils
    return datetime_utils.iso_utc_now()
