"""
Rebuild index and spot-check referee/venue fields.
"""
import json, os, random

d = r"D:\data\vscode_file\titan007\analysis\leagues"

def compute_match_key(league_en, season, home_en, away_en, match_date):
    parts = [
        league_en.lower().replace(" ", "_"),
        season,
        home_en.lower().replace(" ", "_"),
        away_en.lower().replace(" ", "_"),
        match_date[:10],
    ]
    return "_".join(parts)

all_entries = {}
total = 0

for league in sorted(os.listdir(d)):
    ld = os.path.join(d, league)
    if not os.path.isdir(ld):
        continue
    for season in sorted(os.listdir(ld)):
        sd = os.path.join(ld, season)
        if not os.path.isdir(sd):
            continue
        for fname in os.listdir(sd):
            if not fname.endswith(".json"):
                continue
            fp = os.path.join(sd, fname)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    r = json.load(f)
            except Exception:
                continue
            if "error" in r:
                continue
            sid = r.get("schedule_id")
            if not sid:
                continue
            match_time = r.get("match_time", "")
            match_date = match_time[:10] if match_time else ""
            mkey = compute_match_key(
                league, season,
                r.get("home_team_en", ""),
                r.get("away_team_en", ""),
                match_date,
            )
            entry = {
                "match_key": mkey,
                "titan007_id": sid,
                "sofascore_id": None,
                "jingcai_id": None,
                "league_name_en": league.replace("_", " "),
                "league_name_cn": "",
                "season": season,
                "home_team_en": r.get("home_team_en", ""),
                "home_team_cn": r.get("home_team", ""),
                "away_team_en": r.get("away_team_en", ""),
                "away_team_cn": r.get("away_team", ""),
                "match_date": match_date,
                "kickoff": match_time[11:16] if len(match_time) >= 16 else "",
                "full_score": r.get("full_score", ""),
                "half_score": r.get("half_score", ""),
                "status": r.get("status"),
                "is_cup": False,
            }
            all_entries[mkey] = entry
            total += 1

print(f"Total entries rebuilt: {total}")

# Spot check referee/venue
print("\n=== referee/venue spot check (15 random samples) ===")
sample_keys = random.sample(list(all_entries.keys()), min(15, len(all_entries)))
for mkey in sample_keys:
    e = all_entries[mkey]
    sid = e["titan007_id"]
    league_fs = e["league_name_en"].replace(" ", "_")
    season = e["season"]
    fp = os.path.join(d, league_fs, season, f"{sid}.json")
    with open(fp, "r", encoding="utf-8") as f:
        r = json.load(f)
    mi = r.get("match_info", {})
    ver = r.get("version", "?")
    has_ref = bool(mi.get("referee"))
    has_ven = bool(mi.get("venue"))
    has_wth = bool(mi.get("weather"))
    has_tmp = bool(mi.get("temperature"))
    print(f"  SID={sid} v={ver}: wth={has_wth} tmp={has_tmp} ref={has_ref} ven={has_ven}")

# Save index
idx_dir = r"D:\data\vscode_file\titan007\index"
os.makedirs(idx_dir, exist_ok=True)
with open(os.path.join(idx_dir, "match_index.json"), "w", encoding="utf-8") as f:
    json.dump({"version": "1.0", "matches": all_entries}, f, ensure_ascii=False, indent=2)
print(f"\nIndex saved ({len(all_entries)} entries).")
