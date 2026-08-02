"""
Batch split: loads index ONCE, processes all files, saves index ONCE.
Much faster than per-match index writes.

Usage:
  python scripts/batch_split.py [--leagues] [--cups]
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANALYSIS_DIR = os.path.join(BASE_DIR, "analysis")
CONFIG_PATH = os.path.join(BASE_DIR, "competitions_config.json")
INDEX_DIR = os.path.join(BASE_DIR, "index")
INDEX_PATH = os.path.join(INDEX_DIR, "match_index.json")


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_match_key(league_en, season, home_en, away_en, match_date):
    parts = [
        league_en.lower().replace(" ", "_"),
        season,
        home_en.lower().replace(" ", "_"),
        away_en.lower().replace(" ", "_"),
        match_date[:10],
    ]
    return "_".join(parts)


def load_index():
    if not os.path.isfile(INDEX_PATH):
        return {}
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("matches", {})
    except (json.JSONDecodeError, OSError):
        return {}


def save_index(matches):
    os.makedirs(INDEX_DIR, exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump({"version": "1.0", "matches": matches}, f, ensure_ascii=False, indent=2)


def build_entry(record, comp, season, is_cup):
    league_en = comp.get("name_en", str(comp["id"]))
    league_cn = comp.get("name_cn", "")
    home_en = record.get("home_team_en", "")
    away_en = record.get("away_team_en", "")
    home_cn = record.get("home_team", "")
    away_cn = record.get("away_team", "")
    match_time = record.get("match_time", "")
    match_date = match_time[:10] if match_time else ""
    match_key = compute_match_key(league_en, season, home_en, away_en, match_date)
    return match_key, {
        "match_key": match_key,
        "titan007_id": record["schedule_id"],
        "sofascore_id": None,
        "jingcai_id": None,
        "league_name_en": league_en,
        "league_name_cn": league_cn,
        "season": season,
        "home_team_en": home_en,
        "home_team_cn": home_cn,
        "away_team_en": away_en,
        "away_team_cn": away_cn,
        "match_date": match_date,
        "kickoff": match_time[11:16] if len(match_time) >= 16 else "",
        "full_score": record.get("full_score", ""),
        "half_score": record.get("half_score", ""),
        "status": record.get("status"),
        "is_cup": is_cup,
    }


def split_competition(comp, is_cup):
    subdir = "cups" if is_cup else "leagues"
    dir_name = comp.get("name_en", str(comp["id"])).replace(" ", "_")
    seasons = comp.get("available_seasons", [])
    total_split = 0

    for season in seasons:
        src = os.path.join(ANALYSIS_DIR, subdir, dir_name, f"{season}.json")
        if not os.path.isfile(src):
            continue

        with open(src, "r", encoding="utf-8") as f:
            data = json.load(f)

        results = data.get("results", [])
        if not results:
            continue

        out_dir = os.path.join(ANALYSIS_DIR, subdir, dir_name, season)
        os.makedirs(out_dir, exist_ok=True)

        count = 0
        for record in results:
            sid = record.get("schedule_id")
            if not sid:
                continue
            dst = os.path.join(out_dir, f"{sid}.json")
            if os.path.isfile(dst):
                continue
            with open(dst, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
            count += 1

        print(f"    {season}: {count} new files (from {len(results)} total)")
        total_split += count

    return total_split


def build_index(comp, is_cup):
    subdir = "cups" if is_cup else "leagues"
    dir_name = comp.get("name_en", str(comp["id"])).replace(" ", "_")
    seasons = comp.get("available_seasons", [])
    index_entries = {}
    total = 0

    for season in seasons:
        src_dir = os.path.join(ANALYSIS_DIR, subdir, dir_name, season)
        if not os.path.isdir(src_dir):
            continue

        for fname in sorted(os.listdir(src_dir)):
            if not fname.endswith(".json"):
                continue
            sid = fname[:-5]
            if not sid.isdigit():
                continue
            fpath = os.path.join(src_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    record = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            if "error" in record:
                continue

            match_key, entry = build_entry(record, comp, season, is_cup)
            index_entries[match_key] = entry
            total += 1

        print(f"    {season}: {total} index entries (cumulative)")

    return index_entries, total


def main():
    config = load_config()

    # Phase 1: split all big JSONs into individual files
    print("Phase 1: Splitting big JSONs into individual files...")
    total_split = 0
    for comp in config["leagues"]:
        dir_name = comp.get("name_en", str(comp["id"])).replace(" ", "_")
        has_big = any(
            os.path.isfile(os.path.join(ANALYSIS_DIR, "leagues", dir_name, f"{s}.json"))
            for s in comp.get("available_seasons", [])
        )
        if has_big:
            print(f"\nLeague: {comp['name_cn']} ({dir_name})")
            n = split_competition(comp, False)
            print(f"  Split {n} matches")
            total_split += n

    for comp in config["cups"]:
        dir_name = comp.get("name_en", str(comp["id"])).replace(" ", "_")
        has_big = any(
            os.path.isfile(os.path.join(ANALYSIS_DIR, "cups", dir_name, f"{s}.json"))
            for s in comp.get("available_seasons", [])
        )
        if has_big:
            print(f"\nCup: {comp['name_cn']} ({dir_name})")
            n = split_competition(comp, True)
            print(f"  Split {n} matches")
            total_split += n

    print(f"\nTotal split: {total_split} matches")

    # Phase 2: rebuild index from all individual files
    print("\nPhase 2: Rebuilding match index...")
    all_entries = {}
    grand_total = 0

    for comp in config["leagues"]:
        dir_name = comp.get("name_en", str(comp["id"])).replace(" ", "_")
        season_dir = os.path.join(ANALYSIS_DIR, "leagues", dir_name)
        has_individual = any(
            os.path.isdir(os.path.join(season_dir, s))
            for s in comp.get("available_seasons", [])
        )
        if has_individual:
            print(f"\nLeague: {comp['name_cn']} ({dir_name})")
            entries, n = build_index(comp, False)
            all_entries.update(entries)
            grand_total += n

    for comp in config["cups"]:
        dir_name = comp.get("name_en", str(comp["id"])).replace(" ", "_")
        season_dir = os.path.join(ANALYSIS_DIR, "cups", dir_name)
        has_individual = any(
            os.path.isdir(os.path.join(season_dir, s))
            for s in comp.get("available_seasons", [])
        )
        if has_individual:
            print(f"\nCup: {comp['name_cn']} ({dir_name})")
            entries, n = build_index(comp, True)
            all_entries.update(entries)
            grand_total += n

    save_index(all_entries)
    print(f"\n{'='*50}")
    print(f"Done. {grand_total} matches indexed.")


if __name__ == "__main__":
    main()
