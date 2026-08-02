"""
Date/time helpers for the incremental (live) update pipeline.

Timezone conventions:
  - Schedule `match_time` strings ("2025-08-16 19:30") are Beijing time, naive.
  - All persisted timestamps (fetched_at, updated_at) are ISO 8601 UTC ("...Z").
  - Comparisons use aware UTC datetimes (canonical instant).
"""
import datetime as dt

BEIJING = dt.timezone(dt.timedelta(hours=8))
UTC = dt.timezone.utc


def beijing_now() -> dt.datetime:
    """Current time as aware UTC datetime (canonical instant)."""
    return dt.datetime.now(UTC)


def parse_match_time(match_time) -> dt.datetime:
    """Parse 'YYYY-MM-DD HH:MM' (Beijing naive) into aware UTC datetime. None on failure."""
    if not match_time:
        return None
    try:
        naive = dt.datetime.strptime(match_time[:16], "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return None
    beijing_aware = naive.replace(tzinfo=BEIJING)
    return beijing_aware.astimezone(UTC)


def is_pre_match(match: dict, now: dt.datetime = None) -> bool:
    """True if the match kickoff is strictly in the future."""
    if now is None:
        now = beijing_now()
    kickoff = parse_match_time(match.get("match_time", ""))
    if kickoff is None:
        return False
    return kickoff > now


def select_window(matches: list, now: dt.datetime = None,
                  lookback_h: int = 0, lookahead_d: int = 3) -> list:
    """Return matches whose kickoff falls within [now - lookback_h, now + lookahead_d]."""
    if now is None:
        now = beijing_now()
    start = now - dt.timedelta(hours=lookback_h)
    end = now + dt.timedelta(days=lookahead_d)
    result = []
    for m in matches:
        kickoff = parse_match_time(m.get("match_time", ""))
        if kickoff is None:
            continue
        if start <= kickoff <= end:
            result.append(m)
    return result


def iso_utc_now() -> str:
    """ISO 8601 UTC timestamp, e.g. '2025-07-31T07:31:13Z'."""
    return dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_current_season(comp: dict, is_cup: bool, latest: dict) -> str:
    """Return the latest season for a competition from latest_seasons.json."""
    group = "cups" if is_cup else "leagues"
    entry = latest.get(group, {}).get(str(comp["id"]), {})
    return entry.get("latest_season")
