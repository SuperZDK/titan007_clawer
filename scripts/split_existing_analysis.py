"""
Split existing per-season big JSON files into per-match individual JSONs.
Also populates index/match_index.json.

Usage:
  python scripts/split_existing_analysis.py
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


def find_comp(config, cid, is_cup):
    group = config["cups"] if is_cup else config["leagues"]
    for c in group:
        if c["id"] == cid:
            return c
    return None


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


def update_index(record, comp, season, is_cup):
    league_en = comp.get("name_en", str(comp["id"]))
    league_cn = comp.get("name_cn", "")
    home_en = record.get("home_team_en", "")
    away_en = record.get("away_team_en", "")
    home_cn = record.get("home_team", "")
    away_cn = record.get("away_team", "")
    match_time = record.get("match_time", "")
    match_date = match_time[:10] if match_time else ""
    match_key = compute_match_key(league_en, season, home_en, away_en, match_date)
    entry = {
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
    index_matches = load_index()
    index_matches[match_key] = entry
    save_index(index_matches)
    return match_key


def split_file(subdir, dir_name, season, comp, is_cup):
    src = os.path.join(ANALYSIS_DIR, subdir, dir_name, f"{season}.json")
    if not os.path.isfile(src):
        return 0

    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = data.get("results", [])
    if not results:
        return 0

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
        update_index(record, comp, season, is_cup)
        count += 1
        if count % 50 == 0:
            print(f"    ... split {count}/{len(results)}")

    return count


def main():
    config = load_config()
    total = 0

    # Leagues
    for comp in config["leagues"]:
        dir_name = comp.get("name_en", str(comp["id"])).replace(" ", "_")
        seasons = comp.get("available_seasons", [])
        found = False
        for season in seasons:
            src = os.path.join(ANALYSIS_DIR, "leagues", dir_name, f"{season}.json")
            if os.path.isfile(src):
                if not found:
                    print(f"\n{'='*50}")
                    print(f"League: {comp['name_cn']} ({dir_name})")
                    found = True
                print(f"  Season {season} ...", end=" ", flush=True)
                n = split_file("leagues", dir_name, season, comp, False)
                print(f"{n} matches")
                total += n
        if found:
            print(f"  Total for {comp['name_cn']}: {total} entries")

    # Cups
    for comp in config["cups"]:
        dir_name = comp.get("name_en", str(comp["id"])).replace(" ", "_")
        seasons = comp.get("available_seasons", [])
        found = False
        for season in seasons:
            src = os.path.join(ANALYSIS_DIR, "cups", dir_name, f"{season}.json")
            if os.path.isfile(src):
                if not found:
                    print(f"\n{'='*50}")
                    print(f"Cup: {comp['name_cn']} ({dir_name})")
                    found = True
                print(f"  Season {season} ...", end=" ", flush=True)
                n = split_file("cups", dir_name, season, comp, True)
                print(f"{n} matches")
                total += n

    print(f"\n{'='*50}")
    print(f"Done. {total} total matches split into individual files.")


if __name__ == "__main__":
    main()
