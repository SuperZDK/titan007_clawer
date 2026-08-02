"""
Schedule scraper - extracts match schedules from JS data files.
Handles: league rounds (R_X), cup rounds (GXXXXX), Swiss stage (SXXXXX).
"""
import re, json, time, random
from typing import Optional
from dataclasses import dataclass, field
from core import js_fetcher


def parse_team_map(js_text: str) -> dict:
    """Parse arrTeam: {team_id: {"cn": name_cn, "en": name_en}}."""
    m = re.search(r'var arrTeam\s*=\s*\[', js_text)
    if not m:
        return {}
    start = m.end()
    end = js_fetcher._find_matching_bracket(js_text, start - 1)
    if end < 0:
        return {}
    outer_text = js_text[start:end]
    team_map = {}
    idx = 0
    while idx < len(outer_text):
        if outer_text[idx] == '[':
            inner_end = js_fetcher._find_matching_bracket(outer_text, idx)
            if inner_end < 0:
                break
            vals = js_fetcher._parse_flat_array(outer_text[idx + 1:inner_end])
            if vals and len(vals) >= 3:
                tid = vals[0]
                if isinstance(tid, (int, float)):
                    tid = int(tid)
                    cn = str(vals[1] or "")
                    tw = str(vals[2] or "")
                    en = str(vals[3]) if len(vals) > 3 and vals[3] else ""
                    team_map[tid] = {"cn": cn or tw, "en": en}
            idx = inner_end + 1
        else:
            idx += 1
    return team_map


def _lookup_round_name(group_name: str, cup_kind: dict = None) -> str:
    """Map a jh group name to a readable round name.
    
    Convention:
      R_1, R_2 ... R_N  → league rounds
      GXXXXX or GXXXXXA → cup rounds (looked up in cup_kind)
      SXXXXXA           → Swiss/league phase (looked up by stripping S/suffix)
      Other             → kept as-is
    """
    if re.match(r'^R_\d+$', group_name):
        m = re.search(r'R_(\d+)', group_name)
        return f"Round {m.group(1)}"
    
    if cup_kind:
        # Extract base numeric ID from GXXXXX, GXXXXXA, or SXXXXXA
        m = re.search(r'[GS](\d+)', group_name)
        if m:
            base_id = m.group(1)
            if base_id in cup_kind:
                return cup_kind[base_id].get("en", "") or cup_kind[base_id].get("cn", "")
    
    return group_name


def _extract_team_id(val, team_map: dict) -> int:
    """Extract team ID from either an int or a nested array string.
    
    In cup qualifying, row[4]/row[5] can be a nested array like
    "[SID,comp_id,-1,datetime,home_id,away_id,...]". The home team ID
    is the 5th element (index 4) of the nested array.
    """
    if isinstance(val, int):
        return val
    if isinstance(val, str) and val.startswith('['):
        # Try to parse the nested array to find the team ID
        nested = js_fetcher._parse_flat_array(val[1:])
        if nested and len(nested) >= 5:
            try:
                return int(nested[4])
            except (ValueError, TypeError):
                pass
    return 0


def extract_schedule(js_text: str, sub_league_label: str = None,
                     sub_league_type: int = None, cup_kind: dict = None) -> Optional[dict]:
    """Extract schedule from JS data.
    
    Args:
      js_text: Raw JS file content
      sub_league_label: For leagues with sub-leagues (e.g., "Playoffs", "Championship Group")
      sub_league_type: 1=regular league, 0=playoff/qualification
      cup_kind: Pre-parsed arrCupKind for cup round name mapping
    """
    comp_info = js_fetcher.extract_competition_info(js_text)
    if not comp_info:
        return None

    team_map = parse_team_map(js_text)
    
    if cup_kind is None:
        cup_kind = js_fetcher.parse_cup_kind(js_text)
    is_cup = bool(cup_kind) or comp_info.get("name_cn", "").find("杯") >= 0

    # Sub-league info
    if sub_league_label is None:
        sub_leagues = js_fetcher.parse_sub_league_info(js_text)
        # Will be filled per-match below
    else:
        sub_leagues = []

    all_matches = []
    rounds_dict = {}

    # Parse ALL jh[...] groups
    for m in re.finditer(r'jh\["([^"]+)"\]\s*=\s*\[', js_text):
        group_name = m.group(1)
        
        # Skip non-match groups (standings tables start with S)
        # SXXXXX typically contains team standings, not matches
        if group_name.startswith('S') and not group_name.startswith('SG'):
            continue
            
        outer_start = m.end(0) - 1
        outer_end = js_fetcher._find_matching_bracket(js_text, outer_start)
        if outer_end < 0:
            continue

        round_name = _lookup_round_name(group_name, cup_kind)
        
        # For this group, determine the sub-league
        # Groups inside a sub-league file all belong to that sub-league
        sl_label = sub_league_label
        sl_type = sub_league_type
        
        # If no explicit sub-league, try to infer from sub_leagues list
        if sl_label is None and sub_leagues:
            # Check if group_name corresponds to a sub-league
            for sl in sub_leagues:
                if len(sl) >= 5:
                    sid = str(sl[0])
                    sname = str(sl[3] or sl[1] or "")
                    stype = sl[4]
                    # Most sub-leagues have their own JS file, so this won't match
                    # But for single-file sub-leagues (Scottish split), check
                    if sid == group_name:
                        sl_label = sname
                        sl_type = stype
                        break

        inner = outer_start + 1
        while inner < outer_end:
            if js_text[inner] == '[':
                inner_start = inner + 1
                inner_end = js_fetcher._find_matching_bracket(js_text, inner)
                if inner_end < 0:
                    break
                
                row_text = js_text[inner_start:inner_end]
                row = js_fetcher._parse_flat_array(row_text)
                
                if not row:
                    inner = inner_end + 1
                    continue
                
                # Check if this is a tie container with nested leg data
                # (common in cup knockout/qualifying rounds)
                has_nested_legs = False
                if len(row) >= 5:
                    has_nested_legs = (
                        isinstance(row[4], str) and row[4].startswith('[')
                    ) or (
                        isinstance(row[5], str) and row[5].startswith('[')
                    )
                
                if has_nested_legs:
                    for leg_idx in [4, 5]:
                        if leg_idx >= len(row):
                            continue
                        if isinstance(row[leg_idx], str) and row[leg_idx].startswith('['):
                            nested_text = js_fetcher._find_matching_bracket(
                                row[leg_idx], 0)
                            if nested_text > 0:
                                leg_row = js_fetcher._parse_flat_array(
                                    row[leg_idx][1:nested_text])
                            else:
                                leg_row = js_fetcher._parse_flat_array(
                                    row[leg_idx][1:])
                            
                            if leg_row and len(leg_row) >= 15:
                                _add_match_from_row(leg_row, group_name, round_name,
                                                    sl_label, sl_type, team_map,
                                                    all_matches, rounds_dict)
                    
                    # Also add tie-level entry with aggregate data
                    if len(row) >= 7:
                        tie_match = _make_match_from_tie(row, group_name, round_name,
                                                         sl_label, sl_type, team_map)
                        if tie_match:
                            # Only add if not duplicate of a leg
                            leg_sids = {m["schedule_id"] for m in all_matches}
                            if tie_match["schedule_id"] not in leg_sids:
                                all_matches.append(tie_match)
                                rkey = group_name
                                if rkey not in rounds_dict:
                                    rounds_dict[rkey] = {
                                        "group_name": group_name,
                                        "round_name": round_name,
                                        "matches": []
                                    }
                                rounds_dict[rkey]["matches"].append(tie_match)
                else:
                    # Regular match row
                    _add_match_from_row(row, group_name, round_name,
                                        sl_label, sl_type, team_map,
                                        all_matches, rounds_dict)

                inner = inner_end + 1
            else:
                inner += 1

    if not all_matches:
        return None

    return {
        "competition_id": comp_info.get("id", 0),
        "competition_name_cn": comp_info.get("name_cn", ""),
        "competition_name_en": comp_info.get("name_en", ""),
        "season": comp_info.get("season", ""),
        "is_cup": is_cup,
        "total_matches": len(all_matches),
        "matches": all_matches,
        "rounds": {name: rd for name, rd in sorted(
            rounds_dict.items(),
            key=lambda x: (
                int(re.search(r'\d+', x[1].get("round_name", "")).group())
                if re.search(r'\d+', x[1].get("round_name", ""))
                else 999,
            )
        )},
    }


def _add_match_from_row(row, group_name, round_name, sl_label, sl_type,
                         team_map, all_matches, rounds_dict):
    """Parse a flat match row and add to results."""
    try:
        sid = int(row[0])
    except (ValueError, IndexError, TypeError):
        return
    if sid < 100:
        return

    match_time = str(row[3]) if len(row) > 3 else ""
    home_id = _extract_team_id(row[4], team_map) if len(row) > 4 else 0
    away_id = _extract_team_id(row[5], team_map) if len(row) > 5 else 0
    home_info = team_map.get(home_id, {})
    away_info = team_map.get(away_id, {})

    match = {
        "schedule_id": sid,
        "group_name": group_name,
        "round_name": round_name,
        "match_time": match_time,
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_team": home_info.get("cn", ""),
        "away_team": away_info.get("cn", ""),
        "home_team_en": home_info.get("en", ""),
        "away_team_en": away_info.get("en", ""),
        "full_score": str(row[6]) if len(row) > 6 and row[6] else None,
        "half_score": str(row[7]) if len(row) > 7 and row[7] else None,
        "status": int(row[10]) if len(row) > 10 and row[10] is not None else 0,
    }
    if sl_label:
        match["sub_league"] = sl_label
    if sl_type is not None:
        match["sub_league_type"] = sl_type

    all_matches.append(match)
    if group_name not in rounds_dict:
        rounds_dict[group_name] = {
            "group_name": group_name,
            "round_name": round_name,
            "matches": []
        }
    rounds_dict[group_name]["matches"].append(match)


def _make_match_from_tie(row, group_name, round_name, sl_label, sl_type, team_map):
    """Create an aggregate match entry from a tie-level row."""
    try:
        sid = int(row[0])
    except (ValueError, IndexError, TypeError):
        return None
    if sid < 100:
        return None

    # For ties, home/away teams come from the nested leg data at row[4]/row[5]
    home_id = 0
    away_id = 0
    for leg_idx, team_idx in [(4, 4), (5, 5)]:
        if isinstance(row[leg_idx], str) and row[leg_idx].startswith('['):
            nested = js_fetcher._parse_flat_array(row[leg_idx][1:])
            if nested and len(nested) > team_idx:
                try:
                    tid = int(nested[team_idx])
                    if leg_idx == 4:
                        home_id = tid
                    else:
                        away_id = tid
                except (ValueError, TypeError):
                    pass

    home_info = team_map.get(home_id, {})
    away_info = team_map.get(away_id, {})
    agg_score = str(row[6]) if len(row) > 6 and row[6] else None

    match = {
        "schedule_id": sid,
        "group_name": group_name,
        "round_name": round_name,
        "match_time": str(row[3]) if len(row) > 3 else "",
        "home_team_id": home_id,
        "away_team_id": away_id,
        "home_team": home_info.get("cn", ""),
        "away_team": away_info.get("cn", ""),
        "home_team_en": home_info.get("en", ""),
        "away_team_en": away_info.get("en", ""),
        "full_score": agg_score,
        "is_aggregate": True,
    }
    if sl_label:
        match["sub_league"] = sl_label
    if sl_type is not None:
        match["sub_league_type"] = sl_type
    return match
