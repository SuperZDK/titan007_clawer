import json, os, sys, time, random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.js_fetcher import fetch_match_data, fetch_seasons
from core.schedule import extract_schedule
from core import utils


def process_competition(comp, is_cup=False, seasons=None, force=False):
    """Fetch and save schedule for a competition."""
    name = comp.get("name_cn", str(comp["id"]))
    cid = comp["id"]
    subdir = "cups" if is_cup else "leagues"
    dir_name = utils.schedule_dir_name(comp)
    latest_data = utils.load_latest_seasons()
    latest_entry = latest_data.get(subdir, {}).get(str(cid), {})
    latest_season = latest_entry.get("latest_season")

    all_seasons = comp.get("available_seasons", [])
    target_seasons = seasons or all_seasons

    print(f"\n{'='*60}")
    print(f"SCHEDULE: {name} (ID={cid})")
    print(f"{'='*60}")
    print(f"  Latest season: {latest_season or 'unknown'}")

    for season in target_seasons:
        if season not in all_seasons:
            print(f"\n  {season}: not in available_seasons, skipping")
            continue

        season_dir = os.path.join(utils.SCHEDULE_DIR, subdir, dir_name)
        filepath = os.path.join(season_dir, f"{season}.json")
        season_exists = os.path.isfile(filepath)
        is_latest = (season == latest_season)

        if season_exists:
            if is_latest:
                print(f"\n  {season}: latest season, re-fetching")
            elif force:
                print(f"\n  {season}: --force, re-fetching")
            else:
                print(f"\n  {season}: exists, skip (use --force to override)")
                continue
        else:
            print(f"\n  {season}: new, fetching")

        js_text = fetch_match_data(cid, season, is_cup)
        if not js_text:
            print(f"    Failed to fetch JS data")
            continue

        result = extract_schedule(js_text)
        if not result:
            print(f"    No match data found")
            continue

        result.pop("rounds", None)

        os.makedirs(season_dir, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"    Saved ({result.get('total_matches', 0)} matches)")

        for match in result.get("matches", []):
            try:
                utils.update_match_index(match, comp, season, is_cup)
            except Exception as e:
                pass

        time.sleep(random.uniform(0.5, 1.5))

    return {"competition_id": cid, "competition_name_cn": name, "is_cup": is_cup}


def update_latest_seasons(config):
    """Fetch latest seasons for all leagues and cups, save to latest_seasons.json.

    Resilience:
      - retries transient failures (up to MAX_SEASON_RETRIES)
      - on persistent failure, keeps the previous successful value and records
        last_error / error_count instead of clobbering with empty data
      - marks new competitions as never_fetched until first success
    """
    from core.js_fetcher import fetch_seasons

    data = utils.load_latest_seasons()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    MAX_SEASON_RETRIES = 3

    for group_key, group_name in [("leagues", "leagues"), ("cups", "cups")]:
        for comp in config.get(group_name, []):
            cid = str(comp["id"])
            name = comp.get("name_cn", cid)
            print(f"  {name} (ID={cid})...", end=" ")
            sys.stdout.flush()

            seasons = None
            for attempt in range(MAX_SEASON_RETRIES):
                try:
                    seasons = fetch_seasons(comp["id"])
                except Exception:
                    seasons = None
                if seasons and len(seasons) > 0:
                    break
                if attempt < MAX_SEASON_RETRIES - 1:
                    time.sleep(random.uniform(1.5, 3.0))

            if group_key not in data:
                data[group_key] = {}
            prev = data[group_key].get(cid, {})

            if seasons and len(seasons) > 0:
                entry = {
                    "latest_season": seasons[0],
                    "all_seasons": seasons,
                    "updated_at": now,
                }
                data[group_key][cid] = entry
                print(f"  latest={seasons[0]} ({len(seasons)} seasons)")
            else:
                # Keep previous value; record the failure.
                if prev and prev.get("latest_season"):
                    prev["last_error"] = "fetch_failed"
                    prev["error_count"] = prev.get("error_count", 0) + 1
                    prev["updated_at"] = now
                    data[group_key][cid] = prev
                    print(f"  FAILED, keeping {prev['latest_season']} (err#{prev['error_count']})")
                else:
                    data[group_key][cid] = {
                        "latest_season": None,
                        "all_seasons": [],
                        "updated_at": now,
                        "never_fetched": True,
                    }
                    print("  never_fetched")
            time.sleep(random.uniform(0.3, 1.0))

    utils.save_latest_seasons(data)
    print(f"\nSaved to {utils.LATEST_SEASONS_PATH}")
