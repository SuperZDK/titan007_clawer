import json, os, shutil

ODDS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "odds")
TYPES = {"asian", "european", "over_under"}

stats = {"asian": 0, "european": 0, "over_under": 0, "unknown": 0, "deleted_sid": 0, "deleted_mixed": 0}


def _detect_type(data: dict) -> str:
    for k in data:
        if k in TYPES:
            return k
    return "unknown"


def _normalize_company_name(cid: int) -> str:
    known = {1: "澳门", 2: "betfair", 8: "365", 90: "易胜博", 104: "Interwetten", 115: "威廉希尔", 281: "365"}
    return known.get(cid, "")


def _build_record(sid: int, company: dict, odds_type: str) -> dict:
    record = {
        "schedule_id": sid,
        "company_id": company["company_id"],
        "company_name": company.get("company_name", "") or _normalize_company_name(company["company_id"]),
        "odds_type": odds_type,
        "_version": "v1",
        "changes": company.get("changes", []),
    }
    return record


def _write_company(record: dict, target_dir: str):
    sid = record["schedule_id"]
    cid = record["company_id"]
    match_dir = os.path.join(target_dir, str(sid))
    os.makedirs(match_dir, exist_ok=True)
    path = os.path.join(match_dir, f"{cid}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return path


def process_old_sid_file(path: str, odds_type: str, target_dir: str):
    """
    Process old {sid}.json files that contain multiple companies under
    a single top-level key (e.g. {'european': [{...}, ...]}).
    Splits into individual {sid}/{cid}.json files.
    """
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    companies = data.get(odds_type, [])
    if not companies:
        return 0

    sid = data.get("schedule_id", 0)
    if not sid:
        fname = os.path.basename(path)
        sid_str = fname.replace(".json", "")
        if sid_str.isdigit():
            sid = int(sid_str)
    if not sid:
        return 0

    count = 0
    for company in companies:
        record = _build_record(sid, company, odds_type)
        _write_company(record, target_dir)
        count += 1
    return count


def process_euro_cid_file(path: str, target_dir: str):
    """
    Process old european {sid}_{cid}.json files.
    Converts to new format and moves to {sid}/{cid}.json.
    """
    fname = os.path.basename(path)
    stem = fname.replace(".json", "")
    parts = stem.split("_")
    if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return False
    sid, cid = int(parts[0]), int(parts[1])

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    record = {
        "schedule_id": sid,
        "company_id": cid,
        "company_name": data.get("company_name", "") or _normalize_company_name(cid),
        "odds_type": "european",
        "_version": "v1",
        "changes": data.get("changes", []),
    }
    _write_company(record, target_dir)
    return True


def walk_and_sort():
    # Walk through all three odds type directories
    for root, dirs, files in os.walk(ODDS_DIR):
        # Determine which odds type subdir we're in
        rel = os.path.relpath(root, ODDS_DIR)
        parts = rel.replace("\\", "/").split("/")
        current_type = parts[0] if parts and parts[0] in TYPES else None
        if not current_type:
            continue

        # league_cup, dir_name, season
        sub_path = os.path.relpath(root, os.path.join(ODDS_DIR, current_type))
        sub_parts = sub_path.replace("\\", "/").split("/")
        # sub_parts should look like ["leagues", "EPL", "2025-2026"]

        if len(sub_parts) < 3:
            continue

        league_cup = sub_parts[0]
        dir_name = sub_parts[1]
        season = sub_parts[2]

        target_dir = os.path.join(ODDS_DIR, current_type, league_cup, dir_name, season)

        for fname in files:
            if not fname.endswith(".json"):
                continue
            path = os.path.join(root, fname)
            stem = fname.replace(".json", "")
            parent_basename = os.path.basename(os.path.dirname(path))

            # Already in {sid}/{cid}.json format -> skip
            if parent_basename.isdigit() and stem.isdigit():
                continue

            # Case 1: {sid}_{cid}.json (old european format)
            if "_" in stem and stem.split("_")[0].isdigit() and stem.split("_")[1].isdigit():
                if current_type == "european":
                    print(f"  [EURO] {os.path.relpath(path, ODDS_DIR)}")
                    process_euro_cid_file(path, target_dir)
                    os.remove(path)
                    stats[current_type] += 1
                    stats["deleted_mixed"] += 1
                continue

            # Case 2: {sid}.json (old format with mixed companies)
            if stem.isdigit():
                sid = int(stem)
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                odds_type = _detect_type(data)

                # Determine actual target dir based on content type
                if odds_type in TYPES:
                    actual_target = os.path.join(ODDS_DIR, odds_type, league_cup, dir_name, season)
                    count = process_old_sid_file(path, odds_type, actual_target)
                    if count:
                        print(f"  [{odds_type.upper():10s}] {os.path.relpath(path, ODDS_DIR)} → {odds_type}/.../{sid}/  ({count} companies)")
                        stats[odds_type] += count
                        stats["deleted_sid"] += 1
                        os.remove(path)
                    else:
                        stats["unknown"] += 1
                else:
                    print(f"  [UNKNOWN] {os.path.relpath(path, ODDS_DIR)} (key: {list(data.keys())})")
                    stats["unknown"] += 1
                continue

            # Case 3: some other json file (skip)
            print(f"  [SKIP] {os.path.relpath(path, ODDS_DIR)}")


def clean_empty_dirs():
    for root, dirs, files in os.walk(ODDS_DIR, topdown=False):
        if root == ODDS_DIR:
            continue
        try:
            if not os.listdir(root):
                os.rmdir(root)
                print(f"  [CLEAN] Removed empty directory: {os.path.relpath(root, ODDS_DIR)}")
        except (OSError, PermissionError):
            pass


def main():
    print("=" * 60)
    print("  Sorting odds data into {type}/{league_cup}/{name}/{season}/{sid}/{cid}.json")
    print("=" * 60)

    walk_and_sort()
    clean_empty_dirs()

    print("\n" + "=" * 60)
    print("  Statistics")
    print("=" * 60)
    print(f"  Companies extracted:")
    print(f"    asian:       {stats['asian']}")
    print(f"    european:    {stats['european']}")
    print(f"    over_under:  {stats['over_under']}")
    print(f"    unknown:     {stats['unknown']}")
    print(f"  Old files deleted:")
    print(f"    {{sid}}.json (multi-company):  {stats['deleted_sid']}")
    print(f"    {{sid}}_{{cid}}.json:           {stats['deleted_mixed']}")
    print("=" * 60)
    print("  Done.")


if __name__ == "__main__":
    main()
