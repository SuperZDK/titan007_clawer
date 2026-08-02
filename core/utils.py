import json, os
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "crawler_config.json")
COMP_CONFIG_PATH = os.path.join(BASE_DIR, "config", "competitions_config.json")
DATA_DIR = os.path.join(BASE_DIR, "data")
SCHEDULE_DIR = os.path.join(DATA_DIR, "schedule")
ANALYSIS_DIR = os.path.join(DATA_DIR, "analysis")
ODDS_DIR = os.path.join(DATA_DIR, "odds")
INDEX_DIR = os.path.join(DATA_DIR, "index")
INDEX_PATH = os.path.join(INDEX_DIR, "match_index.json")
LATEST_SEASONS_PATH = os.path.join(DATA_DIR, "latest_seasons.json")

COMPANY_NAMES = {
    "asian":       {1: "澳门", 8: "365", 12: "易胜博", 17: "明升"},
    "over_under":  {1: "澳门", 8: "365", 12: "易胜博", 17: "明升"},
    "european":    {2: "betfair", 90: "易胜博", 104: "Interwetten", 115: "威廉希尔", 281: "365"},
}


def get_company_name(odds_type: str, company_id: int) -> str:
    return COMPANY_NAMES.get(odds_type, {}).get(company_id, "")


def load_crawler_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_competitions_config():
    with open(COMP_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def find_comp(config, comp_id, is_cup=False):
    group = config["cups"] if is_cup else config["leagues"]
    for c in group:
        if c["id"] == comp_id:
            return c
    return None


def schedule_dir_name(comp):
    return comp.get("name_en", str(comp["id"])).replace(" ", "_")


def load_schedule(comp, season, is_cup=False):
    subdir = "cups" if is_cup else "leagues"
    dir_name = schedule_dir_name(comp)
    path = os.path.join(SCHEDULE_DIR, subdir, dir_name, f"{season}.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return dir_name, json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def load_latest_seasons():
    if not os.path.isfile(LATEST_SEASONS_PATH):
        return {"leagues": {}, "cups": {}}
    try:
        with open(LATEST_SEASONS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"leagues": {}, "cups": {}}


def save_latest_seasons(data):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LATEST_SEASONS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def list_existing_ids(data_dir: str) -> set:
    """Return set of schedule IDs (int) that have odds data on disk.
    Supports new format ({sid}/{cid}.json) and old flat format ({sid}.json).
    """
    ids = set()
    if not os.path.isdir(data_dir):
        return ids

    for entry in os.listdir(data_dir):
        entry_path = os.path.join(data_dir, entry)

        if os.path.isdir(entry_path) and entry.isdigit():
            ids.add(int(entry))
            continue

        if entry.endswith(".json"):
            sid_str = entry[:-5]
            if sid_str.isdigit():
                try:
                    with open(entry_path, "r", encoding="utf-8") as f:
                        content = json.load(f)
                    if not content.get("error"):
                        ids.add(int(sid_str))
                except (json.JSONDecodeError, OSError):
                    continue

    return ids


# ─── Match Index ───

def compute_match_key(league_en, season, home_en, away_en, match_date):
    parts = [
        league_en.lower().replace(" ", "_"),
        season,
        home_en.lower().replace(" ", "_"),
        away_en.lower().replace(" ", "_"),
        match_date[:10],
    ]
    return "_".join(parts)


def load_match_index():
    if not os.path.isfile(INDEX_PATH):
        return {}
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("matches", {})
    except (json.JSONDecodeError, OSError):
        return {}


def save_match_index(matches):
    os.makedirs(INDEX_DIR, exist_ok=True)
    data = {"version": "2.0", "matches": matches}
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_match_index(record, comp, season, is_cup):
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
    index_matches = load_match_index()
    index_matches[match_key] = entry
    save_match_index(index_matches)
    return match_key
