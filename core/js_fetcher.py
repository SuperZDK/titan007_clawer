"""
Fetch JS schedule data from zq.titan007.com.
Handles: s{id}.js (League), s{id}_{subId}.js (SubLeague), c{id}.js (Cup), sea{id}.js (Season list).
"""
import re, json, time
from typing import Optional
from urllib.parse import urljoin

from . import playwright_fetcher

BASE = "https://zq.titan007.com"
REFERER = "https://zq.titan007.com/"

def _build_ver(seed: Optional[int] = None) -> str:
    ts = seed or int(time.time())
    return f"?version=202607{ts % 10000:04d}"

def _decode(data: bytes) -> str:
    try:
        return data.decode("gbk")
    except UnicodeDecodeError:
        return data.decode("utf-8-sig", errors="replace")

def fetch_url(url: str, accept: str = "text/html,*/*", max_retry: int = 2) -> Optional[str]:
    data = playwright_fetcher.fetch_bytes(url, referer=REFERER, accept=accept, timeout=30000, max_retry=max_retry)
    if data is not None:
        return _decode(data)
    return None


# ─── Season list (sea{id}.js) ─────────────────────────────────────────

def fetch_seasons(comp_id: int) -> Optional[list]:
    """Fetch available seasons for a competition from sea{id}.js."""
    url = f"{BASE}/jsData/LeagueSeason/sea{comp_id}.js{_build_ver()}"
    text = fetch_url(url, accept="application/javascript,*/*")
    if not text:
        return None
    m = re.search(r"var arrSeason\s*=\s*\[(.*?)\]", text)
    if not m:
        return None
    return [s.strip().strip("'\"") for s in m.group(1).split(",")]


# ─── Sub-ID discovery ─────────────────────────────────────────────────

def _parse_arr_sub_league(html: str) -> list:
    """Parse arrSubLeague variable from HTML/JS text."""
    m = re.search(r'var arrSubLeague\s*=\s*\[(.*?)\];', html)
    if not m:
        return []
    # Parse outer array - each element is [...]
    items = _parse_flat_array('[' + m.group(1) + ']')
    # arrSubLeague is a 2D array. Parse it bracket by bracket.
    result = []
    text = m.group(1)
    idx = 0
    while idx < len(text):
        if text[idx] == '[':
            end = _find_matching_bracket(text, idx)
            if end < 0:
                break
            row = _parse_flat_array(text[idx + 1:end])
            if row:
                result.append(row)
            idx = end + 1
        else:
            idx += 1
    return result


def _find_main_sub_id(js_text: str) -> Optional[str]:
    """Parse arrSubLeague from JS text, return sub-ID for the main league (type=1)."""
    sub_leagues = _parse_arr_sub_league(js_text)
    for sl in sub_leagues:
        if len(sl) >= 5:
            sid = sl[0]
            stype = sl[4]
            if stype == 1 and isinstance(sid, (int, float)):
                return str(int(sid))
    return None


def discover_sub_id(comp_id: int, season: str, url_type: str) -> Optional[str]:
    """Fetch the season page to discover sub-ID for JS data path."""
    if url_type == "SubLeague":
        page = f"/cn/SubLeague/{season}/{comp_id}.html"
    else:
        page = f"/cn/League/{season}/{comp_id}.html"
    html = fetch_url(f"{BASE}{page}")
    if not html:
        return None

    pattern = rf"s{comp_id}_(\d+)\.js"
    m = re.search(pattern, html)
    return m.group(1) if m else None


# ─── Match schedule data ──────────────────────────────────────────────

def fetch_match_data(comp_id: int, season: str, is_cup: bool = False, url_type: str = "League") -> Optional[str]:
    """Fetch the JS file containing match schedule data.
    
    For cups: c{id}.js
    For leagues: first try s{id}.js, if fails discover sub-ID and try s{id}_{subId}.js.
    If the discovered sub-ID is a non-league sub-league (e.g., playoff final),
    resolves to the main league sub-ID via arrSubLeague.
    """
    if is_cup:
        path = f"/jsData/matchResult/{season}/c{comp_id}.js"
    else:
        path = f"/jsData/matchResult/{season}/s{comp_id}.js"

    text = fetch_url(f"{BASE}{path}{_build_ver()}", accept="application/javascript,*/*")

    if text and 'jh["' in text:
        return text

    # If standard path failed and not a cup, try sub-ID discovery
    if not is_cup:
        sub_id = discover_sub_id(comp_id, season, url_type)
        if sub_id:
            path = f"/jsData/matchResult/{season}/s{comp_id}_{sub_id}.js"
            text = fetch_url(f"{BASE}{path}{_build_ver()}", accept="application/javascript,*/*")
            if text and 'jh["' in text:
                # Check if this JS has arrSubLeague with a main league sub-ID
                main_sub_id = _find_main_sub_id(text)
                if main_sub_id and main_sub_id != sub_id:
                    path = f"/jsData/matchResult/{season}/s{comp_id}_{main_sub_id}.js"
                    text = fetch_url(f"{BASE}{path}{_build_ver()}", accept="application/javascript,*/*")
                    if text and 'jh["' in text:
                        return text
                return text

    return None


# ─── Extract schedule IDs from JS data ────────────────────────────────

def _find_matching_bracket(text: str, start: int) -> int:
    """Find position of matching ']' for a '[' at start."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == '[':
            depth += 1
        elif text[i] == ']':
            depth -= 1
            if depth == 0:
                return i
    return -1


def extract_schedule_ids(js_text: str, max_ids: int = 50, is_cup: bool = False) -> list:
    """Extract schedule IDs from jh[...] arrays. Returns list of (sid, group_name, match_array).
    
    A match row must have at least 15 elements (filters out non-match sub-arrays).
    For cups, SIDs can be shorter (2-5 digit tie IDs for qualifying rounds).
    For leagues, SIDs are typically 7 digits.
    """
    results = []
    for m in re.finditer(r'jh\["([^"]+)"\]\s*=\s*\[', js_text):
        group_name = m.group(1)
        outer_start = m.end(0) - 1
        outer_end = _find_matching_bracket(js_text, outer_start)
        if outer_end < 0:
            continue

        inner = outer_start + 1
        while inner < outer_end:
            if js_text[inner] == '[':
                inner_start = inner + 1
                inner_end = _find_matching_bracket(js_text, inner)
                if inner_end < 0:
                    break
                row_text = js_text[inner_start:inner_end]
                row = _parse_flat_array(row_text)
                if row and len(row) >= 15:
                    try:
                        sid = int(row[0])
                    except (ValueError, IndexError, TypeError):
                        sid = None
                    if sid is not None and sid >= 100:
                        results.append((sid, group_name, row))
                        if len(results) >= max_ids:
                            return results
                inner = inner_end + 1
            else:
                inner += 1
    return results


def _parse_flat_array(text: str) -> list:
    """Parse a flat JS array (e.g. 1,'abc',null) into Python list."""
    result = []
    token = ""
    in_str, str_char = False, None
    depth = 0
    for ch in text:
        if in_str:
            if ch == '\\':
                pass
            elif ch == str_char:
                in_str = False
            token += ch
        elif ch in ('"', "'"):
            in_str = True
            str_char = ch
            token += ch
        elif ch in '([':
            depth += 1
            token += ch
        elif ch in ')]':
            depth -= 1
            token += ch
        elif ch == ',' and depth == 0:
            result.append(_parse_js_value(token))
            token = ""
        else:
            token += ch
    if token.strip():
        result.append(_parse_js_value(token))
    return result


def _parse_js_value(token: str):
    """Parse a single JS value."""
    token = token.strip()
    if not token:
        return None
    if (token.startswith("'") and token.endswith("'")) or \
       (token.startswith('"') and token.endswith('"')):
        return token[1:-1]
    if token in ("null", "undefined", ""):
        return None
    try:
        return int(token) if "." not in token else float(token)
    except ValueError:
        return token


# ─── Extract competition info from JS header ──────────────────────────

def extract_league_info(js_text: str) -> Optional[dict]:
    """Extract league info from var arrLeague in JS data."""
    m = re.search(r"var arrLeague\s*=\s*\[(.*?)\]", js_text)
    if not m:
        return None
    items = _parse_flat_array(m.group(1))
    if len(items) >= 5:
        return {
            "id": items[0],
            "name_cn": items[1],
            "name_tw": items[2],
            "name_en": items[3],
            "season": items[4],
        }
    return None


def parse_cup_kind(js_text: str) -> dict:
    """Parse arrCupKind: {group_id: {"cn": name_cn, "en": name_en}}."""
    result = {}
    m = re.search(r'var arrCupKind\s*=\s*\[', js_text)
    if not m:
        return result
    start = m.end() - 1
    end = _find_matching_bracket(js_text, start)
    if end < 0:
        return result
    raw = js_text[start + 1:end]
    idx = 0
    while idx < len(raw):
        if raw[idx] == '[':
            inner_end = _find_matching_bracket(raw, idx)
            if inner_end < 0:
                break
            vals = _parse_flat_array(raw[idx + 1:inner_end])
            # Format: [id, parent_id, name_cn, name_tw, name_en, ...]
            if vals and len(vals) >= 5:
                gid = str(vals[0])
                name_cn = str(vals[2] or "")
                name_en = str(vals[4] or "")
                if name_cn or name_en:
                    result[gid] = {"cn": name_cn, "en": name_en}
            idx = inner_end + 1
        else:
            idx += 1
    return result


def parse_sub_league_info(js_text: str) -> list:
    """Parse arrSubLeague: list of [id, name_cn, name_tw, name_en, type, ...]."""
    result = []
    m = re.search(r'var arrSubLeague\s*=\s*\[', js_text)
    if not m:
        return result
    start = m.end() - 1
    end = _find_matching_bracket(js_text, start)
    if end < 0:
        return result
    raw = js_text[start + 1:end]
    idx = 0
    while idx < len(raw):
        if raw[idx] == '[':
            inner_end = _find_matching_bracket(raw, idx)
            if inner_end < 0:
                break
            vals = _parse_flat_array(raw[idx + 1:inner_end])
            if vals:
                result.append(vals)
            idx = inner_end + 1
        else:
            idx += 1
    return result


def extract_cup_info(js_text: str) -> Optional[dict]:
    m = re.search(r"var arrCup\s*=\s*\[(.*?)\]", js_text)
    if not m:
        return None
    items = _parse_flat_array(m.group(1))
    if len(items) >= 5:
        return {"id": items[0], "name_cn": items[1], "name_tw": items[2],
                "name_en": items[3], "season": items[4]}
    return None


def extract_competition_info(js_text: str) -> Optional[dict]:
    return extract_league_info(js_text) or extract_cup_info(js_text)
