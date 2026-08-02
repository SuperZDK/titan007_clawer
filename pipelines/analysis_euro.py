"""
Pipeline A: Fetch analysis page → save structured match analysis data.
No longer coupled with European odds scraping.
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import js_fetcher
from core import models
from core.parser import extract_analysis
from core import utils

ANALYSIS_DIR = utils.ANALYSIS_DIR


def analysis_to_dict(page: models.AnalysisPage) -> dict:
    result = {
        "version": page.version,
        "match_info": {
            "hometeam": page.match_info.hometeam,
            "guestteam": page.match_info.guestteam,
            "match_time": page.match_info.match_time,
            "weather": page.match_info.weather,
        },
        "recent_home": [_recent_to_dict(m) for m in page.recent_home],
        "recent_away": [_recent_to_dict(m) for m in page.recent_away],
        "recent_home_home": [_recent_to_dict(m) for m in page.recent_home_home],
        "recent_away_away": [_recent_to_dict(m) for m in page.recent_away_away],
        "h2h": [_h2h_to_dict(m) for m in page.h2h],
        "standings": _standings_to_dict(page.standings),
        "lineup": _lineup_to_dict(page.lineup),
        "preview": page.match_preview,
        "tip": _tip_to_dict(page.tip),
    }
    return result


def _recent_to_dict(m):
    return {
        "date": m.date, "comp_type": m.comp_type, "comp_name": m.comp_name,
        "home_team": m.home_team, "away_team": m.away_team,
        "home_score": m.home_score, "away_score": m.away_score,
        "full_score": m.full_score, "handicap": m.handicap,
        "schedule_id": m.schedule_id, "is_home_side": m.is_home_side,
    }


def _h2h_to_dict(m):
    return {
        "date": m.date, "comp_name": m.comp_name,
        "home_team": m.home_team, "away_team": m.away_team,
        "home_score": m.home_score, "away_score": m.away_score,
        "full_score": m.full_score, "handicap": m.handicap,
        "schedule_id": m.schedule_id,
    }


def _standings_to_dict(st):
    if not st:
        return None
    return {
        "home_team": st.home_team, "away_team": st.away_team,
        "home_standing": _standing_row_to_dict(st.home_standing),
        "away_standing": _standing_row_to_dict(st.away_standing),
    }


def _standing_row_to_dict(sr):
    if not sr:
        return None
    return {
        "rank": sr.rank, "team_name": sr.team_name,
        "played": sr.played, "won": sr.won, "drawn": sr.drawn, "lost": sr.lost,
        "goals_for": sr.goals_for, "goals_against": sr.goals_against,
        "goal_diff": sr.goal_diff, "points": sr.points,
    }


def _lineup_to_dict(lineup):
    if not lineup:
        return None
    result = {}
    for attr in ("home_formation", "away_formation", "home_starting", "away_starting",
                 "home_subs", "away_subs", "home_coach", "away_coach",
                 "home_injuries", "away_injuries", "home_ratings", "away_ratings"):
        val = getattr(lineup, attr, None)
        if val:
            result[attr] = val
    return result if any(result.values()) else None


def _tip_to_dict(tip):
    if not tip:
        return None
    result = {}
    if tip.confidence_index:
        result["confidence_index"] = tip.confidence_index
    if tip.h2h_record:
        result["h2h_record"] = tip.h2h_record
    if tip.analysis:
        result["analysis"] = tip.analysis
    return result if result else None


def scrape_match(schedule_id: int, html_override: str = None):
    """Fetch analysis page, parse it, and return (page, raw_html) or (None, None)."""
    if html_override:
        html = html_override
    else:
        url = f"https://zq.titan007.com/analysis/{schedule_id}cn.htm"
        print(f"    Fetching analysis page: /analysis/{schedule_id}cn.htm")
        html = js_fetcher.fetch_url(url)
    if not html:
        print(f"    ERROR: Failed to fetch analysis page")
        return None, None
    page = extract_analysis(html)
    return page, html


def process_match(match_in: dict, comp, season: str, is_cup: bool):
    """Fetch analysis page for a single match and save it."""
    sid = match_in["schedule_id"]
    subdir = "cups" if is_cup else "leagues"
    dir_name = utils.schedule_dir_name(comp)
    analysis_season_dir = os.path.join(ANALYSIS_DIR, subdir, dir_name, season)
    os.makedirs(analysis_season_dir, exist_ok=True)

    analysis_path = os.path.join(analysis_season_dir, f"{sid}.json")
    if os.path.isfile(analysis_path):
        try:
            with open(analysis_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if not existing.get("error"):
                print(f"    [SKIP] Analysis already exists for SID={sid}")
                return
        except (json.JSONDecodeError, OSError):
            pass

    page, raw_html = scrape_match(sid)
    if not page or not raw_html:
        error_file = os.path.join(analysis_season_dir, f"{sid}.json")
        with open(error_file, "w", encoding="utf-8") as f:
            json.dump({"schedule_id": sid, "error": "fetch_failed"}, f, ensure_ascii=False, indent=2)
        return

    record = analysis_to_dict(page)
    for key in ("group_name", "round_name", "home_team_id", "away_team_id",
                "home_team", "away_team", "home_team_en", "away_team_en",
                "full_score", "half_score", "status", "sub_league",
                "sub_league_type", "sub_league_id", "is_aggregate",
                "match_time"):
        if key in match_in:
            record[key] = match_in[key]
    record["schedule_id"] = sid

    with open(analysis_path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    utils.update_match_index(record, comp, season, is_cup)
    print(f"      Version: {page.version} | {page.match_info.hometeam} vs {page.match_info.guestteam}")


def run_competition(comp, is_cup=False, seasons=None):
    """Scrape analysis pages for a competition."""
    name = comp.get("name_cn", str(comp["id"]))
    cid = comp["id"]
    subdir = "cups" if is_cup else "leagues"
    dir_name = utils.schedule_dir_name(comp)
    all_seasons = comp.get("available_seasons", [])
    target_seasons = seasons or all_seasons

    print(f"\n{'='*60}")
    print(f"{'CUP' if is_cup else 'LEAGUE'}: {name} (ID={cid})")
    print(f"{'='*60}")

    for season in target_seasons:
        if season not in all_seasons:
            print(f"\n  {season}: not in available_seasons, skipping")
            continue

        schedule = utils.load_schedule(comp, season, is_cup)
        if not schedule:
            print(f"\n  {season}: schedule file not found, skipping")
            continue
        dir_name, sched_data = schedule
        matches_in = sched_data.get("matches", [])
        if not matches_in:
            print(f"\n  {season}: no matches in schedule, skipping")
            continue

        print(f"\n  Season: {season} ({len(matches_in)} matches in schedule)")

        analysis_season_dir = os.path.join(ANALYSIS_DIR, subdir, dir_name, season)
        existing = utils.list_existing_ids(analysis_season_dir)

        pending = [m for m in matches_in if m["schedule_id"] not in existing]

        if not pending:
            print(f"    All {len(matches_in)} matches complete, skipping")
            continue

        print(f"    Pending: {len(pending)} matches")

        for idx, match_in in enumerate(pending, 1):
            progress = f"[{idx}/{len(pending)}]"
            print(f"    {progress} SID={match_in['schedule_id']} ({match_in.get('home_team','?')} vs {match_in.get('away_team','?')})")
            sys.stdout.flush()
            process_match(match_in, comp, season, is_cup)

    return {"competition_id": cid, "competition_name_cn": comp.get("name_cn", ""),
            "competition_name_en": comp.get("name_en", ""), "is_cup": is_cup}
