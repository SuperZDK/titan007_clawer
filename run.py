"""
Titan007 Scraper - Restructured
Pipelines:
  analysis: Analysis page           (zq.titan007.com)
  asian:    Asian handicap          (vip.titan007.com)
  ou:       Over/Under              (vip.titan007.com)
  euro:     European odds           (1x2.titan007.com)
  schedule: Match schedule          (zq.titan007.com)

Execution order: by season descending, across all leagues.
  11 leagues → 2025 season → 2024 season → ... → 2016 season
"""
import argparse, sys, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import utils
from pipelines import analysis_euro, asian, over_under, euro_odds, schedule as sched
from pipelines import live as live_pipeline

TARGET_LEAGUES = [
    (36, "cross", "English_Premier_League"),
    (31, "cross", "La_Liga"),
    (8,  "cross", "Bundesliga"),
    (34, "cross", "Serie_A"),
    (11, "cross", "Ligue_1"),
    (37, "cross", "EFL_Championship"),
    (23, "cross", "Primeira_Liga"),
    (16, "cross", "Eredivisie"),
    (25, "single", "J1_League"),
    (273,"cross", "A-League"),
    (284,"single", "J2_League"),
]

YEARS = list(range(2025, 2015, -1))  # [2025, 2024, ..., 2016]

DEFAULT_EURO_COMPANIES = [115, 281, 90, 104, 2]
DEFAULT_ASIAN_COMPANIES = [1, 8, 12, 17]
DEFAULT_OU_COMPANIES = [1, 8, 12, 17]
DEFAULT_SUBTYPES = ["full", "half"]


def _find_comp(config, cid):
    for c in config["leagues"]:
        if c["id"] == cid:
            return c
    return None


def _run_pipelines(comp, season, args, asian_subtypes, ou_subtypes):
    """Run enabled pipelines for one league + one season."""
    cid = comp["id"]
    name = comp.get("name_cn", str(cid))

    if args.run_analysis:
        print(f"\n{'#'*60}")
        print(f"# Analysis: {name} (ID={cid}) | {season}")
        print(f"{'#'*60}")
        analysis_euro.run_competition(comp, is_cup=False, seasons=[season])

    if args.run_asian:
        print(f"\n{'#'*60}")
        print(f"# Asian: {name} (ID={cid}) | {season}")
        print(f"{'#'*60}")
        asian.run_competition(
            comp, is_cup=False, seasons=[season],
            companies=args.asian_companies, subtypes=asian_subtypes,
        )

    if args.run_ou:
        print(f"\n{'#'*60}")
        print(f"# Over/Under: {name} (ID={cid}) | {season}")
        print(f"{'#'*60}")
        over_under.run_competition(
            comp, is_cup=False, seasons=[season],
            companies=args.ou_companies, subtypes=ou_subtypes,
        )

    if args.run_euro:
        print(f"\n{'#'*60}")
        print(f"# Euro: {name} (ID={cid}) | {season}")
        print(f"{'#'*60}")
        euro_odds.run_competition(
            comp, is_cup=False, seasons=[season],
            companies=args.euro_companies,
        )


def main():
    parser = argparse.ArgumentParser(description="Titan007 Scraper - Restructured")
    parser.add_argument("--pipeline", choices=["analysis", "asian", "ou", "euro", "both", "schedule", "live"],
                        default="both", help="Which pipeline to run")
    parser.add_argument("--league", type=int, help="Single league/cup ID")
    parser.add_argument("--season", action="append", help="Override season(s)")
    parser.add_argument("--type", choices=["league", "cup"], default="league",
                        help="Competition type (for schedule pipeline)")
    parser.add_argument("--force", action="store_true",
                        help="Force re-fetch existing schedule files")
    parser.add_argument("--update-latest", action="store_true",
                        help="Update latest_seasons.json from website")
    parser.add_argument("--euro-companies", type=int, nargs="*",
                        default=DEFAULT_EURO_COMPANIES,
                        help="European odds company IDs")
    parser.add_argument("--asian-companies", type=int, nargs="*",
                        default=DEFAULT_ASIAN_COMPANIES,
                        help="Asian handicap company IDs")
    parser.add_argument("--ou-companies", type=int, nargs="*",
                        default=DEFAULT_OU_COMPANIES,
                        help="Over/Under company IDs")
    parser.add_argument("--full-only", action="store_true",
                        help="Skip half-time odds (both asian and ou)")
    parser.add_argument("--asian-full-only", action="store_true",
                        help="Asian handicap: skip half-time")
    parser.add_argument("--ou-full-only", action="store_true",
                        help="Over/Under: skip half-time")
    parser.add_argument("--list-leagues", action="store_true", help="List target leagues")
    parser.add_argument("--now", default=None, help="Live tick: override now 'YYYY-MM-DD HH:MM' (Beijing)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Live tick: preview actions without fetching/writing")
    parser.add_argument("--skip-season-sync", action="store_true",
                        help="Live tick: skip daily season sync")
    args = parser.parse_args()

    # Attach pipeline flags to args for _run_pipelines
    args.run_analysis = args.pipeline in ("analysis", "both")
    args.run_asian = args.pipeline in ("asian", "both")
    args.run_ou = args.pipeline in ("ou", "both")
    args.run_euro = args.pipeline in ("euro", "both")

    config = utils.load_competitions_config()

    # ─── Update latest seasons ──────────────────────────────
    if args.update_latest:
        sched.update_latest_seasons(config)
        return

    # ─── Live incremental pipeline ─────────────────────────
    if args.pipeline == "live":
        import datetime as dt
        now = None
        if args.now:
            naive = dt.datetime.strptime(args.now, "%Y-%m-%d %H:%M")
            now = naive.replace(tzinfo=dt.timezone(dt.timedelta(hours=8))).astimezone(dt.timezone.utc)
        live_pipeline.run_tick(now=now, dry_run=args.dry_run, force=args.force,
                               skip_season_sync=args.skip_season_sync)
        return

    if args.list_leagues:
        print(f"{'ID':>4} {'Name':12}")
        print("-" * 20)
        for cid, _, _ in TARGET_LEAGUES:
            comp = _find_comp(config, cid)
            if comp:
                print(f"  {cid:4d} {comp['name_cn']:12s}")
        return

    asian_subtypes = ["full"] if (args.full_only or args.asian_full_only) else DEFAULT_SUBTYPES
    ou_subtypes = ["full"] if (args.full_only or args.ou_full_only) else DEFAULT_SUBTYPES

    # ─── Schedule pipeline ──────────────────────────────────
    if args.pipeline == "schedule":
        is_cup = (args.type == "cup")

        def _resolve_comp(cid):
            if is_cup:
                return utils.find_comp(config, cid, is_cup=True)
            return _find_comp(config, cid)

        if args.league:
            comp = _resolve_comp(args.league)
            if not comp:
                print(f"{'Cup' if is_cup else 'League'} ID {args.league} not found")
                return

            if args.season:
                target = args.season
            else:
                record = utils.load_latest_seasons()
                grp = "cups" if is_cup else "leagues"
                entry = record.get(grp, {}).get(str(args.league))
                if entry and entry.get("all_seasons"):
                    target = entry["all_seasons"]
                else:
                    target = comp.get("available_seasons", [])

            sched.process_competition(comp, is_cup=is_cup, seasons=target,
                                      force=args.force)
        else:
            if is_cup:
                all_comps = config.get("cups", [])
            else:
                all_comps = [_resolve_comp(cid) for cid, _, _ in TARGET_LEAGUES]
                all_comps = [c for c in all_comps if c]

            for comp in all_comps:
                if args.season:
                    target = args.season
                else:
                    record = utils.load_latest_seasons()
                    grp = "cups" if is_cup else "leagues"
                    entry = record.get(grp, {}).get(str(comp["id"]))
                    if entry and entry.get("all_seasons"):
                        target = entry["all_seasons"]
                    else:
                        target = comp.get("available_seasons", [])

                sched.process_competition(comp, is_cup=is_cup, seasons=target,
                                          force=args.force)

        print(f"\n{'='*60}")
        print(f"  SCHEDULE DONE")
        print(f"{'='*60}")
        return

    # ─── Single league mode (non-schedule) ─────────────────
    if args.league:
        cid = args.league
        comp = _find_comp(config, cid)
        if not comp:
            print(f"League ID {cid} not found")
            return

        sfmt = next((f for c, f, _ in TARGET_LEAGUES if c == cid), None)
        if args.season:
            for season in args.season:
                _run_pipelines(comp, season, args, asian_subtypes, ou_subtypes)
        else:
            for y in YEARS:
                season = f"{y}-{y+1}" if sfmt == "cross" else str(y)
                if season not in comp.get("available_seasons", []):
                    continue
                _run_pipelines(comp, season, args, asian_subtypes, ou_subtypes)

        print(f"\n{'='*60}")
        print(f"  ALL DONE — {comp['name_cn']}")
        print(f"{'='*60}")
        return

    # ─── Default: all leagues, season-first (non-schedule) ─
    print(f"\n{'='*60}")
    print(f"  Target: {len(TARGET_LEAGUES)} leagues, 4 pipelines")
    print(f"  Order: season-first across all leagues (newest → oldest)")
    print(f"{'='*60}")

    if args.season:
        for season in args.season:
            for cid, _, _ in TARGET_LEAGUES:
                comp = _find_comp(config, cid)
                if not comp:
                    continue
                if season not in comp.get("available_seasons", []):
                    continue
                _run_pipelines(comp, season, args, asian_subtypes, ou_subtypes)
    else:
        done_any = False
        for y in YEARS:
            cross_season = f"{y}-{y+1}"
            single_season = str(y)
            for cid, sfmt, _ in TARGET_LEAGUES:
                comp = _find_comp(config, cid)
                if not comp:
                    continue
                season = cross_season if sfmt == "cross" else single_season
                if season not in comp.get("available_seasons", []):
                    continue
                done_any = True
                _run_pipelines(comp, season, args, asian_subtypes, ou_subtypes)

        if not done_any:
            print("\n  No matching seasons found for any league.")

    print(f"\n{'='*60}")
    print(f"  ALL DONE")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
