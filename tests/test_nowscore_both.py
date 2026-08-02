"""Tests for the nowscore both-tables (3in1) single-request optimization."""
import datetime as dt
import json
import os

import pytest

from core import odds_parser
from core import odds_store
from core.odds_parser import scrape_nowscore_both

UTC = dt.timezone.utc


# ─── scrape_nowscore_both ────────────────────────────────────

def _nowscore_html():
    """Two tables: idx 0 = Asian, idx 1 = Over/Under. Time in col 5, status col 6."""
    asian = (
        "<table>"
        "<tr><td>时</td><td>比分</td><td>主</td><td>盘</td><td>客</td><td>变化</td><td>状</td></tr>"
        "<tr><td>1</td><td></td><td>0.9</td><td>半球</td><td>1.0</td><td>10-01<br />02:39</td><td>即时</td></tr>"
        "</table>"
    )
    ou = (
        "<table>"
        "<tr><td>时</td><td>比分</td><td>大</td><td>盘</td><td>小</td><td>变化</td><td>状</td></tr>"
        "<tr><td>1</td><td></td><td>0.85</td><td>2.5</td><td>1.05</td><td>10-01<br />03:10</td><td>即时</td></tr>"
        "</table>"
    )
    return asian + ou


def _nowscore_html_ou_missing():
    """Only the Asian table present."""
    asian = (
        "<table>"
        "<tr><td>时</td><td>比分</td><td>主</td><td>盘</td><td>客</td><td>变化</td><td>状</td></tr>"
        "<tr><td>1</td><td></td><td>0.9</td><td>半球</td><td>1.0</td><td>10-01<br />02:39</td><td>即时</td></tr>"
        "</table>"
    )
    return asian


def test_scrape_nowscore_both_returns_both_tables(monkeypatch):
    calls = []

    def fake_fetch(url, referer=None, timeout=None):
        calls.append(url)
        return _nowscore_html()

    monkeypatch.setattr(odds_parser.playwright_fetcher, "fetch_text", fake_fetch)
    result = scrape_nowscore_both(12345, company_id=1, is_half=False)

    # one single request for both tables
    assert len(calls) == 1
    assert "3in1Odds.aspx" in calls[0] and "companyid=1" in calls[0]

    asian = result["asian"]
    assert asian is not None
    assert asian.company_id == 1
    assert asian.changes[0]["time"] == "10-1 02:39"
    assert asian.changes[0]["line"] == "半球"
    assert asian.changes[0]["home"] == 0.9
    assert asian.changes[0]["away"] == 1.0

    ou = result["over_under"]
    assert ou is not None
    assert ou.company_id == 1
    assert ou.changes[0]["big"] == 0.85
    assert ou.changes[0]["small"] == 1.05
    assert ou.changes[0]["line"] == "2.5"


def test_scrape_nowscore_both_ou_missing(monkeypatch):
    monkeypatch.setattr(odds_parser.playwright_fetcher, "fetch_text",
                        lambda *a, **k: _nowscore_html_ou_missing())
    result = scrape_nowscore_both(12345, company_id=1, is_half=False)
    assert result["asian"] is not None
    assert result["over_under"] is None


def test_scrape_nowscore_both_empty_html(monkeypatch):
    monkeypatch.setattr(odds_parser.playwright_fetcher, "fetch_text", lambda *a, **k: None)
    result = scrape_nowscore_both(12345, company_id=1, is_half=False)
    assert result == {"asian": None, "over_under": None}


def test_scrape_nowscore_both_half_param(monkeypatch):
    calls = []

    def fake_fetch(url, referer=None, timeout=None):
        calls.append(url)
        return _nowscore_html()

    monkeypatch.setattr(odds_parser.playwright_fetcher, "fetch_text", fake_fetch)
    scrape_nowscore_both(12345, company_id=1, is_half=True)
    assert "t=1" in calls[0]


# ─── batch asian.py backfills over_under ─────────────────────

def _make_comp():
    return {"id": 36, "name_en": "English Premier League", "name_cn": "英超"}


def _mock_item(odds_type, company_id, company_name, changes):
    from core import models
    cls = models.AsianOddsItem if odds_type == "asian" else models.OverUnderItem
    return cls(company_id=company_id, company_name=company_name, changes=changes)


def test_asian_batch_backfills_over_under(tmp_path, monkeypatch):
    import pipelines.asian as p_a
    monkeypatch.setattr(p_a, "ODDS_DIR", str(tmp_path))
    monkeypatch.setitem(p_a.SCRAPER_MAP, "full", lambda sid, cid: None)  # titan asian empty

    ns_calls = []

    def fake_both(sid, cid, is_half=False):
        ns_calls.append((sid, cid, is_half))
        return {
            "asian": _mock_item("asian", cid, "澳门", [{"time": "10-1 02:39", "line": "半球", "home": 0.9, "away": 1.0, "status": "即时"}]),
            "over_under": _mock_item("over_under", cid, "澳门", [{"time": "10-1 03:10", "line": "2.5", "big": 0.85, "small": 1.05, "status": "即时"}]),
        }

    monkeypatch.setattr(p_a, "scrape_nowscore_both", fake_both)

    comp = _make_comp()
    p_a.process_match_odds(777, comp, "2025-2026", False, companies=[1], subtypes=["full"], match_time="2025-10-02 03:00")

    asian_path = os.path.join(str(tmp_path), "asian", "leagues", "English_Premier_League", "2025-2026", "777", "1.json")
    ou_path = os.path.join(str(tmp_path), "over_under", "leagues", "English_Premier_League", "2025-2026", "777", "1.json")
    assert os.path.isfile(asian_path)
    assert os.path.isfile(ou_path)

    asian_rec = json.load(open(asian_path, encoding="utf-8"))
    ou_rec = json.load(open(ou_path, encoding="utf-8"))
    assert asian_rec["odds_type"] == "asian"
    assert ou_rec["odds_type"] == "over_under"
    assert ou_rec["source"] == "nowscore"      # backfill uses full build_record format
    assert ou_rec["competition_id"] == 36
    assert ou_rec["match_time"] == "2025-10-02 03:00"
    assert ou_rec["changes"][0]["big"] == 0.85


def test_asian_batch_skips_backfill_if_sibling_exists(tmp_path, monkeypatch):
    import pipelines.asian as p_a
    monkeypatch.setattr(p_a, "ODDS_DIR", str(tmp_path))
    monkeypatch.setitem(p_a.SCRAPER_MAP, "full", lambda sid, cid: None)

    # pre-existing over_under file -> must NOT be overwritten
    ou_path = os.path.join(str(tmp_path), "over_under", "leagues", "English_Premier_League", "2025-2026", "778", "1.json")
    os.makedirs(os.path.dirname(ou_path), exist_ok=True)
    with open(ou_path, "w", encoding="utf-8") as f:
        json.dump({"odds_type": "over_under", "marker": "keep"}, f)

    def fake_both(sid, cid, is_half=False):
        return {
            "asian": _mock_item("asian", cid, "澳门", [{"time": "10-1 02:39", "line": "半球", "home": 0.9, "away": 1.0, "status": "即时"}]),
            "over_under": _mock_item("over_under", cid, "澳门", [{"time": "10-1 03:10", "line": "2.5", "big": 0.85, "small": 1.05, "status": "即时"}]),
        }

    monkeypatch.setattr(p_a, "scrape_nowscore_both", fake_both)

    comp = _make_comp()
    p_a.process_match_odds(778, comp, "2025-2026", False, companies=[1], subtypes=["full"], match_time="")

    kept = json.load(open(ou_path, encoding="utf-8"))
    assert kept.get("marker") == "keep"        # untouched


# ─── batch over_under.py backfills asian ─────────────────────

def test_over_under_batch_backfills_asian(tmp_path, monkeypatch):
    import pipelines.over_under as p_ou
    monkeypatch.setattr(p_ou, "ODDS_DIR", str(tmp_path))
    monkeypatch.setitem(p_ou.SCRAPER_MAP, "full", lambda sid, cid: None)

    def fake_both(sid, cid, is_half=False):
        return {
            "asian": _mock_item("asian", cid, "澳门", [{"time": "10-1 02:39", "line": "半球", "home": 0.9, "away": 1.0, "status": "即时"}]),
            "over_under": _mock_item("over_under", cid, "澳门", [{"time": "10-1 03:10", "line": "2.5", "big": 0.85, "small": 1.05, "status": "即时"}]),
        }

    monkeypatch.setattr(p_ou, "scrape_nowscore_both", fake_both)

    comp = _make_comp()
    p_ou.process_match_odds(779, comp, "2025-2026", False, companies=[1], subtypes=["full"], match_time="")

    ou_path = os.path.join(str(tmp_path), "over_under", "leagues", "English_Premier_League", "2025-2026", "779", "1.json")
    asian_path = os.path.join(str(tmp_path), "asian", "leagues", "English_Premier_League", "2025-2026", "779", "1.json")
    assert os.path.isfile(ou_path)
    assert os.path.isfile(asian_path)
    asian_rec = json.load(open(asian_path, encoding="utf-8"))
    assert asian_rec["odds_type"] == "asian"
    assert asian_rec["source"] == "nowscore"


# ─── live merged loop: one nowscore request feeds both ───────

def _stale_now():
    return dt.datetime(2026, 8, 7, 0, 0, tzinfo=UTC)


def _match(sid=999, time_str="2026-08-07 20:00"):
    return {"schedule_id": sid, "match_time": time_str}


def _as_path(tmp_path, odds_type, sid, cid, st):
    from pipelines.live import _odds_path
    return _odds_path(odds_type, "leagues", "English_Premier_League", "2025-2026", sid, cid, st)


def test_live_merged_loop_single_nowscore_request(tmp_path, monkeypatch):
    import pipelines.live as p_live
    # point storage at tmp
    monkeypatch.setattr(p_live.utils, "ODDS_DIR", str(tmp_path))

    ns_calls = []

    def fake_both(sid, cid, is_half=False):
        ns_calls.append((sid, cid, is_half))
        return {
            "asian": _mock_item("asian", cid, "澳门", [{"time": "10-1 02:39", "line": "半球", "home": 0.9, "away": 1.0, "status": "即时"}]),
            "over_under": _mock_item("over_under", cid, "澳门", [{"time": "10-1 03:10", "line": "2.5", "big": 0.85, "small": 1.05, "status": "即时"}]),
        }

    monkeypatch.setattr(p_live, "scrape_nowscore_both", fake_both)
    # titan returns nothing -> both sides fall through to nowscore
    monkeypatch.setattr(p_live, "scrape_asian_handicap", lambda *a, **k: None)
    monkeypatch.setattr(p_live, "scrape_over_under", lambda *a, **k: None)

    m = _match()
    stats = p_live._process_match_odds(
        m, _make_comp(), "2025-2026", False, "P1",
        _stale_now(), force=True, dry_run=False)

    # 4 companies x 2 subtypes, but only full (subtype loop covers both)...
    # merged loop iterates full AND half; titan empty -> nowscore for both st.
    # ASIAN_COMPANIES has 4 cids; for each: one nowscore request (both st = 2 req per cid)
    assert stats["asian"] == 8    # 4 cids x 2 subtypes
    assert stats["over_under"] == 8
    assert len(ns_calls) == 8     # one 3in1 request per (cid, st)

    # both types actually written to disk
    asian_path = _as_path(tmp_path, "asian", 999, 1, "full")
    ou_path = _as_path(tmp_path, "over_under", 999, 1, "full")
    assert os.path.isfile(asian_path)
    assert os.path.isfile(ou_path)
    asian_rec = json.load(open(asian_path, encoding="utf-8"))
    ou_rec = json.load(open(ou_path, encoding="utf-8"))
    assert asian_rec["source"] == "nowscore"
    assert ou_rec["source"] == "nowscore"
    assert ou_rec["odds_subtype"] == "full"


def test_live_merged_loop_titan_succeeds_no_nowscore(tmp_path, monkeypatch):
    import pipelines.live as p_live
    monkeypatch.setattr(p_live.utils, "ODDS_DIR", str(tmp_path))

    ns_calls = []
    monkeypatch.setattr(p_live, "scrape_nowscore_both",
                        lambda *a, **k: (ns_calls.append(a) or {"asian": None, "over_under": None}))

    asian_item = _mock_item("asian", 1, "澳门", [{"time": "10-1 02:39", "line": "半球", "home": 0.9, "away": 1.0, "status": "即时"}])
    ou_item = _mock_item("over_under", 1, "澳门", [{"time": "10-1 03:10", "line": "2.5", "big": 0.85, "small": 1.05, "status": "即时"}])
    for name, item in (("scrape_asian_handicap", asian_item), ("scrape_asian_handicap_half", asian_item),
                       ("scrape_over_under", ou_item), ("scrape_over_under_half", ou_item)):
        monkeypatch.setattr(p_live, name, lambda *a, _i=item, **k: _i)

    m = _match(999)
    p_live._process_match_odds(m, _make_comp(), "2025-2026", False, "P1",
                               _stale_now(), force=True, dry_run=False)

    assert ns_calls == []   # titan served both sides, no nowscore needed

    asian_rec = json.load(open(_as_path(tmp_path, "asian", 999, 1, "full"), encoding="utf-8"))
    assert asian_rec["source"] == "titan"
