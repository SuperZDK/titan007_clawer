import json, os, sys, time, random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.odds_parser import scrape_asian_handicap, scrape_asian_handicap_half, scrape_nowscore_both
from core import utils, odds_store

ODDS_DIR = utils.ODDS_DIR
ODDS_VERSION = "v1"

SCRAPER_MAP = {
    "full": scrape_asian_handicap,
    "half": scrape_asian_handicap_half,
}


def _backfill_sibling(schedule_id: int, comp, season: str, is_cup: bool,
                      cid: int, st: str, item, match_time: str) -> bool:
    """Write the sibling odds type (over_under) from a nowscore request,
    only if the local file does not exist yet. Full build_record format."""
    subdir = "cups" if is_cup else "leagues"
    dir_name = utils.schedule_dir_name(comp)
    match_dir = os.path.join(ODDS_DIR, "over_under", subdir, dir_name, season, str(schedule_id))
    filename = f"{cid}.json" if st == "full" else f"{cid}_half.json"
    path = os.path.join(match_dir, filename)
    if os.path.isfile(path):
        return False
    rec = odds_store.build_record(schedule_id, cid, item.company_name, "over_under",
                                  st, item.changes, comp, season, match_time, "nowscore")
    odds_store.save_record(rec, path)
    return True


def process_match_odds(schedule_id: int, comp, season: str, is_cup: bool,
                       companies: list = None, subtypes: list = None,
                       match_time: str = ""):
    """Fetch Asian handicap odds for one match."""
    subdir = "cups" if is_cup else "leagues"
    dir_name = utils.schedule_dir_name(comp)
    season_dir = os.path.join(ODDS_DIR, "asian", subdir, dir_name, season)
    match_dir = os.path.join(season_dir, str(schedule_id))

    companies = companies or [1]
    subtypes = subtypes or ["full"]

    for cid in companies:
        for st in subtypes:
            filename = f"{cid}.json" if st == "full" else f"{cid}_half.json"
            filepath = os.path.join(match_dir, filename)

            if os.path.isfile(filepath):
                continue

            scraper = SCRAPER_MAP.get(st)
            if not scraper:
                continue

            print(f"      [asian/{st}] SID={schedule_id} cid={cid}")
            sys.stdout.flush()

            try:
                item = scraper(schedule_id, cid)
                if item is None or not item.changes:
                    print(f"        titan empty, trying nowscore")
                    both = scrape_nowscore_both(schedule_id, cid, is_half=(st == "half"))
                    item = both["asian"]
                    if both["over_under"] and both["over_under"].changes:
                        if _backfill_sibling(schedule_id, comp, season, is_cup,
                                             cid, st, both["over_under"], match_time):
                            print(f"        backfilled over_under/{st} cid={cid}")
                if item and item.changes:
                    rec = {
                        "schedule_id": schedule_id,
                        "company_id": cid,
                        "company_name": item.company_name,
                        "odds_type": "asian",
                        "odds_subtype": st,
                        "_version": ODDS_VERSION,
                        "changes": item.changes,
                    }
                    os.makedirs(match_dir, exist_ok=True)
                    with open(filepath, "w", encoding="utf-8") as f:
                        json.dump(rec, f, ensure_ascii=False, indent=2)
                    print(f"        Saved ({len(item.changes)} changes)")
                else:
                    print(f"        No data")
            except Exception as e:
                print(f"        ERROR: {e}")


def _collect_existing(season_dir: str) -> dict:
    """Return {sid: {stem, ...}} where stem is '1' or '1_half'."""
    result = {}
    if not os.path.isdir(season_dir):
        return result
    for entry in os.listdir(season_dir):
        entry_path = os.path.join(season_dir, entry)
        if not entry.isdigit():
            continue
        files = set()
        try:
            for fname in os.listdir(entry_path):
                if fname.endswith(".json"):
                    files.add(fname[:-5])
            result[int(entry)] = files
        except OSError:
            continue
    return result


def run_competition(comp, is_cup=False, seasons=None,
                    companies=None, subtypes=None):
    """Scrape Asian handicap for a competition."""
    name = comp.get("name_cn", str(comp["id"]))
    cid = comp["id"]
    subdir = "cups" if is_cup else "leagues"
    dir_name = utils.schedule_dir_name(comp)
    all_seasons = comp.get("available_seasons", [])
    target_seasons = seasons or all_seasons
    companies = companies or [1]
    subtypes = subtypes or ["full"]

    print(f"\n{'='*60}")
    print(f"ASIAN: {name} (ID={cid})")
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

        print(f"\n  Season: {season} ({len(matches_in)} matches)")

        season_dir = os.path.join(ODDS_DIR, "asian", subdir, dir_name, season)
        existing = _collect_existing(season_dir)

        pending = []
        for m in matches_in:
            sid = m["schedule_id"]
            files = existing.get(sid, set())
            needed = False
            for ac in companies:
                for st in subtypes:
                    key = f"{ac}" if st == "full" else f"{ac}_half"
                    if key not in files:
                        needed = True
                        break
                if needed:
                    break
            if needed:
                pending.append(m)

        if not pending:
            print(f"    All {len(matches_in)} matches complete, skipping")
            continue

        print(f"    Pending: {len(pending)} matches")

        for idx, match_in in enumerate(pending, 1):
            progress = f"[{idx}/{len(pending)}]"
            sid = match_in["schedule_id"]
            print(f"    {progress} SID={sid} ({match_in.get('home_team','?')} vs {match_in.get('away_team','?')})")
            sys.stdout.flush()

            process_match_odds(sid, comp, season, is_cup, companies, subtypes,
                               match_in.get("match_time", ""))
            time.sleep(random.uniform(1.0, 2.0))

    return {"competition_id": cid, "competition_name_cn": comp.get("name_cn", ""),
            "competition_name_en": comp.get("name_en", ""), "is_cup": is_cup}
