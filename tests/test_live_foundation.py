"""Unit tests for the live pipeline foundation modules."""
import datetime as dt
import logging
import os

import pytest

from core import datetime_utils as dtu
from core import odds_store
from core import priority_provider

logger = logging.getLogger(__name__)

UTC = dt.timezone.utc
BJ = dt.timezone(dt.timedelta(hours=8))


def _mk_match(sid, time_str):
    return {"schedule_id": sid, "match_time": time_str}


# ─── datetime_utils ──────────────────────────────────────────

def test_parse_match_time():
    d = dtu.parse_match_time("2026-08-16 03:00")
    assert d is not None
    assert d.tzinfo is not None
    # Beijing naive "2026-08-16 03:00" -> aware UTC (8h earlier)
    assert d.strftime("%Y-%m-%d %H:%M") == "2026-08-15 19:00"
    assert d.astimezone(BJ).strftime("%Y-%m-%d %H:%M") == "2026-08-16 03:00"
    assert dtu.parse_match_time("bad") is None


def test_is_pre_match():
    now = dt.datetime(2026, 8, 7, 0, 0, tzinfo=UTC)
    future = _mk_match(1, "2026-08-07 12:00")   # 04:00 UTC -> future
    assert dtu.is_pre_match(future, now) is True
    past = _mk_match(2, "2026-08-06 20:00")     # 12:00 UTC prev day -> past
    assert dtu.is_pre_match(past, now) is False
    eq = _mk_match(3, "2026-08-07 08:00")       # 00:00 UTC == now -> not future
    assert dtu.is_pre_match(eq, now) is False


def test_select_window():
    now = dt.datetime(2026, 8, 7, 0, 0, tzinfo=UTC)
    matches = [
        _mk_match(1, "2026-08-04 03:00"),   # before now -> excluded
        _mk_match(2, "2026-08-07 12:00"),   # today
        _mk_match(3, "2026-08-10 00:00"),   # within 3d
        _mk_match(4, "2026-08-11 00:00"),   # outside 3d
    ]
    sel = dtu.select_window(matches, now, lookback_h=0, lookahead_d=3)
    ids = sorted(m["schedule_id"] for m in sel)
    assert ids == [2, 3]


def test_resolve_current_season():
    latest = {"leagues": {"36": {"latest_season": "2026-2027"}}}
    comp = {"id": 36}
    assert dtu.resolve_current_season(comp, False, latest) == "2026-2027"
    assert dtu.resolve_current_season({"id": 99}, False, latest) is None


# ─── odds_store ──────────────────────────────────────────────

def test_merge_odds_changes_dedup_ordered():
    old = [
        {"time": "8-15 10:00", "line": "半球", "home": 0.9, "away": 1.0, "status": "初盘"},
        {"time": "8-15 12:00", "line": "半球", "home": 0.8, "away": 1.1, "status": "即时"},
    ]
    new = [
        {"time": "8-15 11:00", "line": "半球", "home": 0.85, "away": 1.05, "status": "即时"},
        {"time": "8-15 10:00", "line": "半球", "home": 0.9, "away": 1.0, "status": "初盘"},  # full dup of old[0]
        {"time": "8-15 11:00", "line": "半球", "home": 0.85, "away": 1.05, "status": "即时"},  # dup within new
    ]
    merged = odds_store.merge_odds_changes(old, new, "asian")
    # union, existing keeps stored order; unseen new rows appended at end
    assert merged == [
        {"time": "8-15 10:00", "line": "半球", "home": 0.9, "away": 1.0, "status": "初盘"},
        {"time": "8-15 12:00", "line": "半球", "home": 0.8, "away": 1.1, "status": "即时"},
        {"time": "8-15 11:00", "line": "半球", "home": 0.85, "away": 1.05, "status": "即时"},
    ]


def test_merge_odds_changes_empty_old():
    new = [{"time": "8-15 10:00", "line": "半球", "home": 0.9, "away": 1.0, "status": "初盘"}]
    assert odds_store.merge_odds_changes(None, new, "asian") == new


def test_change_key():
    c = {"time": "8-15 10:00", "line": "半球", "home": 0.9, "away": 1.0, "status": "初盘"}
    k1 = odds_store.change_key(c, "asian")
    k2 = odds_store.change_key(c, "asian")
    assert k1 == k2
    # over_under uses big/small fields instead of home/away -> different key
    k3 = odds_store.change_key(c, "over_under")
    assert k3 != k1
    # european uses home_win/draw/away_win
    euro = {"time": "8-15 10:00", "home_win": 1.5, "draw": 3.4, "away_win": 6.0}
    assert odds_store.change_key(euro, "european") != k1


def test_build_record_and_is_fresh(tmp_path):
    comp = {"id": 36, "name_en": "English Premier League"}
    rec = odds_store.build_record(1, 1, "澳门", "asian", "full",
                                  [{"time": "8-15 10:00", "line": "半球",
                                    "home": 0.9, "away": 1.0, "status": "初盘"}],
                                  comp, "2025-2026", "2025-08-16 03:00", "titan")
    assert rec["competition_id"] == 36
    assert rec["competition_name_en"] == "English Premier League"
    assert rec["source"] == "titan"
    assert rec["_version"] == "v1"
    assert odds_store.ODDS_VERSION == "v1"

    path = os.path.join(str(tmp_path), "1.json")
    odds_store.save_record(rec, path)
    assert os.path.isfile(path)

    loaded = odds_store.load_record(path)
    assert loaded["schedule_id"] == 1

    # fetched_at just now -> fresh for 300s
    assert odds_store.is_fresh(loaded, 300) is True
    # missing fetched_at -> stale
    del loaded["fetched_at"]
    assert odds_store.is_fresh(loaded, 300) is False
    # absent record -> stale
    assert odds_store.is_fresh(None, 300) is False


# ─── priority_provider ───────────────────────────────────────

def test_local_whitelist_provider(tmp_path):
    path = os.path.join(str(tmp_path), "live_priority.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"default": "P1", "dates": {"2026-08-08": [100, "101"], "2026-08-09": [102]}}')
    prov = priority_provider.LocalWhitelistProvider(path)
    pmap = prov.get_priority_map(["2026-08-08", "2026-08-09"])
    assert pmap == {100: "P0", 101: "P0", 102: "P0"}
    assert prov.all_sids() == {100, 101, 102}


def test_local_whitelist_provider_missing_file(tmp_path):
    prov = priority_provider.LocalWhitelistProvider(os.path.join(str(tmp_path), "nope.json"))
    assert prov.get_priority_map(["2026-08-08"]) == {}


def test_throttle_interval():
    from pipelines.live import _throttle_interval, P0_INTERVAL, P0_NEAR_INTERVAL, P1_INTERVAL
    now = dt.datetime(2026, 8, 7, 0, 0, tzinfo=UTC)
    kickoff_far = dt.datetime(2026, 8, 7, 20, 0, tzinfo=UTC)   # 20h out
    kickoff_near = dt.datetime(2026, 8, 7, 0, 30, tzinfo=UTC)  # 30m out
    assert _throttle_interval("P0", kickoff_far, now) == P0_INTERVAL
    assert _throttle_interval("P0", kickoff_near, now) == P0_NEAR_INTERVAL
    assert _throttle_interval("P1", kickoff_far, now) == P1_INTERVAL
