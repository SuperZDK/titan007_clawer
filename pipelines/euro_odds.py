import json, os, sys, time, random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.odds_parser import scrape_euro_from_oddslist, fetch_euro_js_data
from core import utils

EURO_DIR = os.path.join(utils.ODDS_DIR, "european")
ODDS_VERSION = "v1"


def process_match_odds(schedule_id: int, comp, season: str, is_cup: bool,
                       companies: list = None):
    """Fetch European odds for one match for the given companies."""
    subdir = "cups" if is_cup else "leagues"
    dir_name = utils.schedule_dir_name(comp)
    season_dir = os.path.join(EURO_DIR, subdir, dir_name, season)
    match_dir = os.path.join(season_dir, str(schedule_id))

    companies = companies or [115, 281, 90, 104, 2]

    # Check which companies are already saved
    os.makedirs(match_dir, exist_ok=True)
    existing = set()
    try:
        for fname in os.listdir(match_dir):
            if fname.endswith(".json"):
                cid_str = fname[:-5]
                if cid_str.isdigit():
                    existing.add(int(cid_str))
    except OSError:
        pass

    pending = [c for c in companies if c not in existing]
    if not pending:
        return

    # Fetch JS data once, reuse for all companies
    js_text = fetch_euro_js_data(schedule_id)
    if not js_text:
        print(f"      [euro] Failed to fetch JS data for SID={schedule_id}")
        return

    for cid in pending:
        print(f"      [euro] SID={schedule_id} cid={cid}")
        sys.stdout.flush()

        try:
            item = scrape_euro_from_oddslist(schedule_id, cid, js_text)
            if item and item.changes:
                rec = {
                    "schedule_id": schedule_id,
                    "company_id": cid,
                    "company_name": item.company_name or utils.get_company_name("european", cid),
                    "odds_type": "european",
                    "_version": ODDS_VERSION,
                    "changes": item.changes,
                }
                with open(os.path.join(match_dir, f"{cid}.json"), "w", encoding="utf-8") as f:
                    json.dump(rec, f, ensure_ascii=False, indent=2)
                print(f"        Saved ({len(item.changes)} changes)")
            else:
                print(f"        No data")
        except Exception as e:
            print(f"        ERROR: {e}")

        time.sleep(random.uniform(1.0, 2.0))


def _collect_existing(season_dir: str) -> dict:
    """Return {sid: {cid, ...}} for matches that have euro odds files."""
    result = {}
    if not os.path.isdir(season_dir):
        return result
    for entry in os.listdir(season_dir):
        entry_path = os.path.join(season_dir, entry)
        if not entry.isdigit():
            continue
        cids = set()
        try:
            for fname in os.listdir(entry_path):
                if fname.endswith(".json"):
                    cid_str = fname[:-5]
                    if cid_str.isdigit():
                        cids.add(int(cid_str))
            if cids:
                result[int(entry)] = cids
        except OSError:
            continue
    return result


def run_competition(comp, is_cup=False, seasons=None, companies=None):
    """Scrape European odds for a competition."""
    name = comp.get("name_cn", str(comp["id"]))
    cid = comp["id"]
    subdir = "cups" if is_cup else "leagues"
    dir_name = utils.schedule_dir_name(comp)
    all_seasons = comp.get("available_seasons", [])
    target_seasons = seasons or all_seasons
    companies = companies or [115, 281, 90, 104, 2]

    print(f"\n{'='*60}")
    print(f"EURO ODDS: {name} (ID={cid})")
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

        season_dir = os.path.join(EURO_DIR, subdir, dir_name, season)
        existing = _collect_existing(season_dir)

        pending = []
        for m in matches_in:
            sid = m["schedule_id"]
            existing_cids = existing.get(sid, set())
            needed = [c for c in companies if c not in existing_cids]
            if needed:
                pending.append((sid, needed))

        if not pending:
            print(f"    All {len(matches_in)} matches complete, skipping")
            continue

        print(f"    Pending: {len(pending)} matches")

        for idx, (sid, needed_cids) in enumerate(pending, 1):
            progress = f"[{idx}/{len(pending)}]"
            match_in = next((m for m in matches_in if m["schedule_id"] == sid), {})
            print(f"    {progress} SID={sid} ({match_in.get('home_team','?')} vs {match_in.get('away_team','?')})")
            sys.stdout.flush()

            process_match_odds(sid, comp, season, is_cup, needed_cids)

            time.sleep(random.uniform(1.0, 2.0))

    return {"competition_id": cid, "competition_name_cn": comp.get("name_cn", ""),
            "competition_name_en": comp.get("name_en", ""), "is_cup": is_cup}
