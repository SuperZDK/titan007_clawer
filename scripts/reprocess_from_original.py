"""
Reprocess odds data from the original titan007 project.
Read-only source: titan007/odds/
Writes to: titan007_pro/data/odds/{type}/{league_cup}/{dir_name}/{season}/{sid}/*.json
"""
import json, os, sys

OLD_ROOT = r"D:\data\VSCode_file\vscode_file\titan007\odds"
NEW_ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "odds")

TYPES_MAP = {
    "asian":           ("asian",       "full"),
    "asian_half":       ("asian",       "half"),
    "over_under":      ("over_under",  "full"),
    "over_under_half":  ("over_under",  "half"),
    "european":        ("european",    None),
}

KNOWN_COMPANY_NAMES = {
    1: "澳门", 2: "betfair", 8: "365", 90: "易胜博",
    104: "Interwetten", 115: "威廉希尔", 281: "365",
}

stats = {"files_read": 0, "companies_written": 0, "errors": 0}
type_counts = {}


def _normalize_company_name(cid: int, name: str = "") -> str:
    return name or KNOWN_COMPANY_NAMES.get(cid, "")


def make_filename(cid: int, subtype: str) -> str:
    if subtype == "half":
        return f"{cid}_half.json"
    return f"{cid}.json"


def process_file(src_path: str, league_cup: str, dir_name: str, season: str):
    """Read a single {sid}.json from old project and write all odds types."""
    fname = os.path.basename(src_path)
    if not fname.endswith(".json"):
        return
    sid_str = fname.replace(".json", "")
    if not sid_str.isdigit():
        return
    sid = int(sid_str)

    try:
        with open(src_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"  [ERROR] Reading {os.path.relpath(src_path, OLD_ROOT)}: {e}")
        stats["errors"] += 1
        return

    stats["files_read"] += 1

    # Walk through all top-level keys (skip non-data keys)
    for key, companies in data.items():
        if key in ("schedule_id", "_version"):
            continue

        mapping = TYPES_MAP.get(key)
        if not mapping:
            print(f"  [SKIP] Unknown key '{key}' in {os.path.relpath(src_path, OLD_ROOT)}")
            continue

        odds_type, subtype = mapping
        type_counts[key] = type_counts.get(key, 0) + 1

        if not isinstance(companies, list) or not companies:
            continue

        target_dir = os.path.join(NEW_ROOT, odds_type, league_cup, dir_name, season, str(sid))
        os.makedirs(target_dir, exist_ok=True)

        for company in companies:
            if not isinstance(company, dict):
                continue
            cid = company.get("company_id", 0)
            if not cid:
                continue

            record = {
                "schedule_id": sid,
                "company_id": cid,
                "company_name": _normalize_company_name(cid, company.get("company_name", "")),
                "odds_type": odds_type,
                "_version": "v1",
                "changes": company.get("changes", []),
            }
            if subtype:
                record["odds_subtype"] = subtype

            fname_out = make_filename(cid, subtype)
            out_path = os.path.join(target_dir, fname_out)

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, indent=2)
            stats["companies_written"] += 1


def walk_source():
    """Walk old project odds directory and process every JSON file."""
    total = 0
    for root, dirs, files in os.walk(OLD_ROOT):
        rel = os.path.relpath(root, OLD_ROOT).replace("\\", "/")
        parts = rel.split("/")

        if len(parts) < 3:
            continue
        league_cup, dir_name, season = parts[0], parts[1], parts[2]

        if league_cup not in ("leagues", "cups"):
            continue

        for fname in files:
            if not fname.endswith(".json"):
                continue
            src = os.path.join(root, fname)
            process_file(src, league_cup, dir_name, season)
            total += 1
            if total % 500 == 0:
                print(f"  Progress: {total} files processed...", flush=True)


def print_stats():
    print("\n" + "=" * 60)
    print("  Reprocess Statistics")
    print("=" * 60)
    print(f"  Files read:          {stats['files_read']}")
    print(f"  Companies written:   {stats['companies_written']}")
    print(f"  Errors:              {stats['errors']}")
    print(f"\n  Data types extracted:")
    for key in sorted(type_counts):
        type_name = f"{key:25s}"
        print(f"    {type_name}  {type_counts[key]} files")
    print("=" * 60)


def main():
    print("=" * 60, flush=True)
    print(f"  Source: {OLD_ROOT}", flush=True)
    print(f"  Target: {NEW_ROOT}", flush=True)
    print("=" * 60, flush=True)

    if not os.path.isdir(OLD_ROOT):
        print(f"\n  ERROR: Source directory not found: {OLD_ROOT}", flush=True)
        return

    print("  Starting...", flush=True)
    walk_source()
    print_stats()
    print("  Done.", flush=True)


if __name__ == "__main__":
    main()
