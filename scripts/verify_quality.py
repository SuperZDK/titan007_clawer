"""
Quick data quality verification.
"""
import json, os, random

d = r'D:\data\vscode_file\titan007\analysis\leagues'
INDEX = r'D:\data\vscode_file\titan007\index\match_index.json'

# 1. Index stats
with open(INDEX, "r", encoding="utf-8") as f:
    idx = json.load(f)
matches = idx["matches"]
print(f"Index entries: {len(matches)}")

from collections import Counter
league_counts = Counter()
for v in matches.values():
    league_counts[v["league_name_en"]] += 1
print("By league:")
for l, c in sorted(league_counts.items(), key=lambda x: -x[1]):
    seas = set(v["season"] for v in matches.values() if v["league_name_en"] == l)
    print(f"  {l}: {c} matches ({len(seas)} seasons: {sorted(seas)})")

# 2. Collect all files
files = []
for league in os.listdir(d):
    ld = os.path.join(d, league)
    if not os.path.isdir(ld):
        continue
    for season in os.listdir(ld):
        sd = os.path.join(ld, season)
        if not os.path.isdir(sd):
            continue
        for fname in os.listdir(sd):
            if fname.endswith(".json"):
                files.append((league, season, os.path.join(sd, fname)))

files.sort()
print(f"\nTotal JSON files: {len(files)}")

# Check 2025-2026 completeness
expected = {
    "English_Premier_League": {"2023-2024": 380, "2024-2025": 380, "2025-2026": 380},
    "La_Liga": {"2023-2024": 380, "2024-2025": 380, "2025-2026": 380},
    "Serie_A": {"2023-2024": 380, "2024-2025": 380, "2025-2026": 380},
    "Bundesliga": {"2023-2024": 306, "2024-2025": 306, "2025-2026": 306},
    "Ligue_1": {"2023-2024": 306, "2024-2025": 306, "2025-2026": 306},
}
counts = {}
for league, season, fp in files:
    counts[(league, season)] = counts.get((league, season), 0) + 1

print("\nExpected vs Actual file counts:")
for league, seasons in sorted(expected.items()):
    for season, exp in sorted(seasons.items()):
        act = counts.get((league, season), 0)
        status = "OK" if act == exp else f"MISMATCH (expected {exp})"
        print(f"  {league}/{season}: {act} {status}")

# 3. Sample 300 files for data quality
print(f"\nSampling {min(300, len(files))} files for quality check...")
sample = random.sample(files, min(300, len(files)))
stats = {
    "has_version": 0, "match_info": 0, "weather": 0, "referee": 0, "venue": 0,
    "preview": 0, "tip": 0, "standings": 0, "h2h": 0, "group_name": 0,
    "home_team_en": 0, "half_score": 0, "full_score": 0, "error": 0,
    "recent_home_home": 0, "recent_away_away": 0,
}
versions = {}
recent_lens = []
recent_home_home_lens = []
recent_away_away_lens = []
h2h_lens = []

for league, season, fp in sample:
    with open(fp, "r", encoding="utf-8") as f:
        r = json.load(f)
    if "error" in r:
        stats["error"] += 1
        continue
    for k in ("match_info", "preview", "tip", "standings", "h2h",
              "group_name", "home_team_en", "half_score", "full_score"):
        if r.get(k):
            stats[k] += 1
    mi = r.get("match_info") or {}
    if mi.get("weather"): stats["weather"] += 1
    if mi.get("referee"): stats["referee"] += 1
    if mi.get("venue"): stats["venue"] += 1

    if r.get("version"):
        stats["has_version"] += 1
        v = r["version"]
        versions[v] = versions.get(v, 0) + 1

    rh = r.get("recent_home", [])
    if rh:
        recent_lens.append(len(rh))

    rhh = r.get("recent_home_home", [])
    if rhh:
        stats["recent_home_home"] += 1
        recent_home_home_lens.append(len(rhh))

    raa = r.get("recent_away_away", [])
    if raa:
        stats["recent_away_away"] += 1
        recent_away_away_lens.append(len(raa))

    h2h = r.get("h2h", [])
    if h2h:
        h2h_lens.append(len(h2h))

valid = len(sample) - stats["error"]
print(f"  Sampled: {len(sample)} (valid: {valid}, errors: {stats['error']})")
print()

print("Field coverage (valid samples only):")
for k in ("has_version", "match_info", "weather", "referee", "venue",
          "preview", "tip", "standings", "h2h", "group_name",
          "home_team_en", "half_score", "full_score",
          "recent_home_home", "recent_away_away"):
    pct = stats[k] / valid * 100
    print(f"  {k}: {stats[k]}/{valid} ({pct:.1f}%)")

if recent_lens:
    print(f"\n  recent_home: avg={sum(recent_lens)/len(recent_lens):.0f}  range={min(recent_lens)}~{max(recent_lens)}")
if recent_home_home_lens:
    print(f"  recent_home_home: avg={sum(recent_home_home_lens)/len(recent_home_home_lens):.0f}  range={min(recent_home_home_lens)}~{max(recent_home_home_lens)}")
if recent_away_away_lens:
    print(f"  recent_away_away: avg={sum(recent_away_away_lens)/len(recent_away_away_lens):.0f}  range={min(recent_away_away_lens)}~{max(recent_away_away_lens)}")
if h2h_lens:
    print(f"  h2h: avg={sum(h2h_lens)/len(h2h_lens):.0f}  range={min(h2h_lens)}~{max(h2h_lens)}")

print(f"\nVersion distribution:")
for v, c in sorted(versions.items()):
    print(f"  {v}: {c} ({c/valid*100:.1f}%)")
