"""
Live (incremental) update pipeline.

Short-lived process, triggered by systemd timer every 5 minutes (flock-guarded).
Cheap when idle: matches outside the odds/details window are skipped entirely.

Per tick:
  1. Season sync (once per day, after SEASON_SYNC_HOUR):
       - refresh latest_seasons.json
       - detect new season -> full season schedule crawl
       - rebuild current-season schedule file (captures postponements/results/new rounds)
  2. Odds window  [kickoff-0h, kickoff+3d], pre-match only:
       - P0: throttle 5min (3min within 1h of kickoff), P1: 90min
       - titan scrape -> empty -> nowscore fallback -> merge -> write
  3. Details window [kickoff-0h, kickoff+1d], pre-match only:
       - analysis refreshed once per day
  4. Weekly sweep (Monday): find matches past kickoff with no score -> live_pending.json
"""
import json, os, sys, time, random, datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import utils
from core import datetime_utils as dtu
from core import odds_store
from core import priority_provider
from core import playwright_fetcher
from core.odds_parser import (
    scrape_asian_handicap, scrape_asian_handicap_half,
    scrape_over_under, scrape_over_under_half,
    scrape_nowscore_both,
    fetch_euro_js_data, scrape_euro_from_oddslist,
)
from pipelines import schedule as sched
from pipelines import analysis_euro

# ─── Tunables ─────────────────────────────────────────────
ODDS_LOOKAHEAD_DAYS = 3
DETAILS_LOOKAHEAD_DAYS = 1
SEASON_SYNC_HOUR = 10

P0_INTERVAL = 5 * 60          # 5 min
P0_NEAR_INTERVAL = 3 * 60     # 3 min within 1h of kickoff
P0_NEAR_HOURS = 1
P1_INTERVAL = 90 * 60         # 90 min

ASIAN_COMPANIES = [1, 8, 12, 17]  # also the Over/Under company set
EURO_COMPANIES = [115, 281, 90, 104, 2]
SUBTYPES = ["full", "half"]

STATE_PATH = os.path.join(utils.DATA_DIR, "live_state.json")
PENDING_PATH = os.path.join(utils.DATA_DIR, "live_pending.json")

ODDS_VERSION = "v1"


# ─── State ─────────────────────────────────────────────────

def _load_state() -> dict:
    if not os.path.isfile(STATE_PATH):
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict) -> None:
    os.makedirs(utils.DATA_DIR, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _load_pending() -> dict:
    if not os.path.isfile(PENDING_PATH):
        return {}
    try:
        with open(PENDING_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_pending(data: dict) -> None:
    os.makedirs(utils.DATA_DIR, exist_ok=True)
    with open(PENDING_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─── Selection helpers ─────────────────────────────────────

def _enabled_competitions(config: dict) -> tuple:
    leagues = [c for c in config.get("leagues", []) if c.get("crawl", {}).get("enabled", False)]
    cups = [c for c in config.get("cups", []) if c.get("crawl", {}).get("enabled", False)]
    return leagues, cups


def _throttle_interval(priority: str, kickoff: dt.datetime, now: dt.datetime) -> int:
    if priority == "P0":
        if kickoff - now <= dt.timedelta(hours=P0_NEAR_HOURS):
            return P0_NEAR_INTERVAL
        return P0_INTERVAL
    return P1_INTERVAL


def _odds_path(odds_type: str, subdir: str, dir_name: str, season: str,
               sid: int, cid: int, subtype: str) -> str:
    base = os.path.join(utils.ODDS_DIR, odds_type, subdir, dir_name, season, str(sid))
    if odds_type == "european":
        return os.path.join(base, f"{cid}.json")
    fname = f"{cid}.json" if subtype == "full" else f"{cid}_half.json"
    return os.path.join(base, fname)


# ─── Season sync ───────────────────────────────────────────

def run_season_sync(config: dict, now: dt.datetime, dry_run: bool = False):
    """Refresh latest_seasons, crawl any new season schedule, rebuild current schedule."""
    leagues, cups = _enabled_competitions(config)
    comps = [(c, False) for c in leagues] + [(c, True) for c in cups]
    if not comps:
        return

    print(f"\n  SEASON SYNC ({now:%Y-%m-%d})")
    if not dry_run:
        sched.update_latest_seasons(config)

    latest = utils.load_latest_seasons()
    for comp, is_cup in comps:
        season = dtu.resolve_current_season(comp, is_cup, latest)
        if not season:
            print(f"    {comp.get('name_cn','?')}: no latest_season, skip")
            continue

        aug = dict(comp)
        all_seasons = latest.get("cups" if is_cup else "leagues", {}).get(str(comp["id"]), {})
        aug["available_seasons"] = all_seasons.get("all_seasons", comp.get("available_seasons", []))

        if dry_run:
            print(f"    {comp.get('name_cn','?')}: sync season={season}")
            continue
        try:
            sched.process_competition(aug, is_cup=is_cup, seasons=[season], force=False)
        except Exception as e:
            print(f"    {comp.get('name_cn','?')}: schedule sync ERROR: {e}")
        time.sleep(random.uniform(1.0, 2.0))


# ─── Odds window ───────────────────────────────────────────

def _process_match_odds(match: dict, comp: dict, season: str, is_cup: bool,
                        priority: str, now: dt.datetime,
                        force: bool = False, dry_run: bool = False) -> dict:
    sid = match["schedule_id"]
    subdir = "cups" if is_cup else "leagues"
    dir_name = utils.schedule_dir_name(comp)
    match_time = match.get("match_time", "")
    kickoff = dtu.parse_match_time(match_time)
    interval = _throttle_interval(priority, kickoff, now)

    stats = {"asian": 0, "over_under": 0, "european": 0, "skipped": 0}

    # Asian + Over/Under (merged loop: one nowscore request feeds both)
    for st in SUBTYPES:
        for cid in ASIAN_COMPANIES:  # same as OU_COMPANIES
            asian_path = _odds_path("asian", subdir, dir_name, season, sid, cid, st)
            ou_path = _odds_path("over_under", subdir, dir_name, season, sid, cid, st)
            asian_rec = odds_store.load_record(asian_path)
            ou_rec = odds_store.load_record(ou_path)
            asian_need = force or not odds_store.is_fresh(asian_rec, interval)
            ou_need = force or not odds_store.is_fresh(ou_rec, interval)
            if not asian_need and not ou_need:
                stats["skipped"] += 2
                continue
            if dry_run:
                if asian_need:
                    print(f"    [asian/{st}] SID={sid} cid={cid} -> {priority}")
                    stats["asian"] += 1
                if ou_need:
                    print(f"    [over_under/{st}] SID={sid} cid={cid} -> {priority}")
                    stats["over_under"] += 1
                continue
            # try titan for each side that is needed
            asian_item = None
            ou_item = None
            asian_source = None
            ou_source = None
            if asian_need:
                if st == "full":
                    asian_item = scrape_asian_handicap(sid, cid)
                else:
                    asian_item = scrape_asian_handicap_half(sid, cid)
                if asian_item and asian_item.changes:
                    asian_source = "titan"
            if ou_need:
                if st == "full":
                    ou_item = scrape_over_under(sid, cid)
                else:
                    ou_item = scrape_over_under_half(sid, cid)
                if ou_item and ou_item.changes:
                    ou_source = "titan"
            # one nowscore request if either side is still empty
            if (asian_need and asian_source is None) or (ou_need and ou_source is None):
                both = scrape_nowscore_both(sid, cid, is_half=(st == "half"))
                if asian_need and asian_source is None and both["asian"]:
                    asian_item = both["asian"]
                    asian_source = "nowscore"
                if ou_need and ou_source is None and both["over_under"]:
                    ou_item = both["over_under"]
                    ou_source = "nowscore"
            if asian_item and asian_item.changes:
                merged = odds_store.merge_odds_changes(asian_rec.get("changes") if asian_rec else None, asian_item.changes, "asian")
                new_rec = odds_store.build_record(
                    sid, cid, asian_item.company_name, "asian", st, merged,
                    comp, season, match_time, asian_source)
                odds_store.save_record(new_rec, asian_path)
                stats["asian"] += 1
            if ou_item and ou_item.changes:
                merged = odds_store.merge_odds_changes(ou_rec.get("changes") if ou_rec else None, ou_item.changes, "over_under")
                new_rec = odds_store.build_record(
                    sid, cid, ou_item.company_name, "over_under", st, merged,
                    comp, season, match_time, ou_source)
                odds_store.save_record(new_rec, ou_path)
                stats["over_under"] += 1
            time.sleep(random.uniform(1.0, 2.0))

    # European odds (JS fetched once per match)
    euro_pending = []
    for cid in EURO_COMPANIES:
        path = _odds_path("european", subdir, dir_name, season, sid, cid, "full")
        rec = odds_store.load_record(path)
        if force or not odds_store.is_fresh(rec, interval):
            euro_pending.append((cid, path, rec))
    if euro_pending:
        if dry_run:
            print(f"    [european] SID={sid} cids={[p[0] for p in euro_pending]} -> {priority}")
            stats["european"] += len(euro_pending)
        else:
            js_text = fetch_euro_js_data(sid)
            for cid, path, rec in euro_pending:
                if not js_text:
                    break
                item = scrape_euro_from_oddslist(sid, cid, js_text)
                if item and item.changes:
                    merged = odds_store.merge_odds_changes(rec.get("changes") if rec else None, item.changes, "european")
                    new_rec = odds_store.build_record(
                        sid, cid, item.company_name, "european", "full", merged,
                        comp, season, match_time, "titan")
                    odds_store.save_record(new_rec, path)
                    stats["european"] += 1
                time.sleep(random.uniform(1.0, 2.0))

    return stats


# ─── Details (analysis) window ─────────────────────────────

def _process_match_details(match: dict, comp: dict, season: str, is_cup: bool,
                           now: dt.datetime, state: dict,
                           force: bool = False, dry_run: bool = False):
    sid = match["schedule_id"]
    today = now.strftime("%Y-%m-%d")
    last = state.get("last_analysis", {}).get(str(sid))
    if not force and last == today:
        return
    if dry_run:
        print(f"    [analysis] SID={sid} -> refresh once/day")
        return

    try:
        analysis_euro.process_match(match, comp, season, is_cup)
        state.setdefault("last_analysis", {})[str(sid)] = today
    except Exception as e:
        print(f"    [analysis] SID={sid} ERROR: {e}")


# ─── Weekly sweep (postponement safety net) ────────────────

def run_weekly_sweep(config: dict, now: dt.datetime, dry_run: bool = False):
    """Find matches past kickoff with no full_score -> live_pending.json."""
    latest = utils.load_latest_seasons()
    pending = _load_pending()
    leagues, cups = _enabled_competitions(config)
    comps = [(c, False) for c in leagues] + [(c, True) for c in cups]
    found = 0

    print(f"\n  WEEKLY SWEEP ({now:%Y-%m-%d})")
    for comp, is_cup in comps:
        season = dtu.resolve_current_season(comp, is_cup, latest)
        if not season:
            continue
        schedule = utils.load_schedule(comp, season, is_cup)
        if not schedule:
            continue
        _, sched_data = schedule
        for m in sched_data.get("matches", []):
            kickoff = dtu.parse_match_time(m.get("match_time", ""))
            if kickoff is None or kickoff >= now:
                continue
            if m.get("full_score"):
                continue
            sid = m["schedule_id"]
            key = str(sid)
            if key not in pending:
                pending[key] = {
                    "schedule_id": sid,
                    "competition": comp.get("name_cn", ""),
                    "season": season,
                    "match_time": m.get("match_time", ""),
                    "detected": now.strftime("%Y-%m-%d"),
                    "note": "kickoff passed, no score (postponed?)",
                }
                found += 1

    if not dry_run:
        _save_pending(pending)
    print(f"    new pending: {found}, total tracked: {len(pending)}")


# ─── Main tick ─────────────────────────────────────────────

def run_tick(now: dt.datetime = None, dry_run: bool = False,
             force: bool = False, skip_season_sync: bool = False):
    """One tick of the live pipeline. `now` is aware UTC datetime."""
    if now is None:
        now = dtu.beijing_now()
    config = utils.load_competitions_config()
    state = _load_state()

    print(f"LIVE TICK @ {now:%Y-%m-%d %H:%M:%S} UTC (dry_run={dry_run})")

    # 1. Season sync once per day after SEASON_SYNC_HOUR
    sync_key = now.strftime("%Y-%m-%d")
    if (not skip_season_sync and not dry_run
            and now.hour >= SEASON_SYNC_HOUR
            and state.get("last_season_sync") != sync_key):
        run_season_sync(config, now)
        state["last_season_sync"] = sync_key
        _save_state(state)
    elif dry_run:
        run_season_sync(config, now, dry_run=True)

    # 2-3. Windows per enabled competition
    latest = utils.load_latest_seasons()
    provider = priority_provider.get_provider()
    leagues, cups = _enabled_competitions(config)
    comps = [(c, False) for c in leagues] + [(c, True) for c in cups]

    for comp, is_cup in comps:
        season = dtu.resolve_current_season(comp, is_cup, latest)
        if not season:
            continue
        schedule = utils.load_schedule(comp, season, is_cup)
        if not schedule:
            continue
        _, sched_data = schedule
        matches = sched_data.get("matches", [])
        if not matches:
            continue

        odds_matches = dtu.select_window(matches, now, lookback_h=0, lookahead_d=ODDS_LOOKAHEAD_DAYS)
        odds_matches = [m for m in odds_matches if dtu.is_pre_match(m, now)]
        detail_matches = dtu.select_window(matches, now, lookback_h=0, lookahead_d=DETAILS_LOOKAHEAD_DAYS)
        detail_matches = [m for m in detail_matches if dtu.is_pre_match(m, now)]

        if not odds_matches and not detail_matches:
            continue

        name = comp.get("name_cn", str(comp["id"]))
        print(f"\n  {name} (ID={comp['id']}) season={season} "
              f"odds={len(odds_matches)} details={len(detail_matches)}")

        dates = sorted({dtu.parse_match_time(m["match_time"]).strftime("%Y-%m-%d")
                        for m in odds_matches if dtu.parse_match_time(m["match_time"])})
        prio_map = provider.get_priority_map(dates)
        default_prio = "P1"

        for m in odds_matches:
            sid = m["schedule_id"]
            priority = prio_map.get(sid, default_prio)
            print(f"    [odds] SID={sid} ({m.get('home_team','?')} vs {m.get('away_team','?')}) {m['match_time']} {priority}")
            sys.stdout.flush()
            _process_match_odds(m, comp, season, is_cup, priority, now,
                                force=force, dry_run=dry_run)

        for m in detail_matches:
            _process_match_details(m, comp, season, is_cup, now, state,
                                   force=force, dry_run=dry_run)

    # 4. Weekly sweep (Monday)
    if not dry_run and now.weekday() == 0:
        week_key = f"{now.isocalendar()[0]}-{now.isocalendar()[1]}"
        if state.get("last_weekly_sweep") != week_key:
            run_weekly_sweep(config, now)
            state["last_weekly_sweep"] = week_key

    _save_state(state)
    playwright_fetcher.close()
    print("\n  LIVE TICK DONE")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Live tick")
    p.add_argument("--now", default=None, help="Now override 'YYYY-MM-DD HH:MM' (Beijing)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true")
    p.add_argument("--skip-season-sync", action="store_true")
    args = p.parse_args()

    _now = None
    if args.now:
        naive = dt.datetime.strptime(args.now, "%Y-%m-%d %H:%M")
        _now = naive.replace(tzinfo=dt.timezone(dt.timedelta(hours=8))).astimezone(dt.timezone.utc)
    run_tick(now=_now, dry_run=args.dry_run, force=args.force,
             skip_season_sync=args.skip_season_sync)
