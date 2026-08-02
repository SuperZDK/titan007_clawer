# Data Contract: Live (Incremental) Odds Pipeline

Scope: `pipelines/live.py` — the short-lived, systemd-timer-driven pipeline that keeps
odds/details fresh for upcoming matches. It is **append-only** and idempotent; it never
rewrites history that is already persisted by the batch pipelines (`asian.py`,
`over_under.py`, `euro_odds.py`).

## Stable keys

| Key | Value |
|---|---|
| Partition | `(schedule_id, odds_type, odds_subtype, company_id)` |
| Row (change) | `(time, line, home/big, away/small, status)` |

- `odds_type` ∈ `{asian, over_under, european}`
- `odds_subtype` ∈ `{full, half}` (european is always `full`)
- Changes are de-duplicated on `(time, line, home/big, away/small, status)`, existing
  rows keep their stored order and new snapshots only append unseen rows.

## File layout (identical to batch pipelines)

```
data/odds/{odds_type}/{leagues|cups}/{dir_name}/{season}/{sid}/{cid}.json
    cid.json          → full
    cid_half.json     → half   (asian / over_under)
    cid.json          → full   (european)
```

`dir_name` = `comp["name_en"].replace(" ", "_")`, same as `utils.schedule_dir_name()`.

## Record schema (per odds file)

```json
{
  "schedule_id": 2789129,
  "company_id": 1,
  "company_name": "澳门",
  "odds_type": "asian",
  "odds_subtype": "full",
  "competition_id": 36,
  "competition_name_en": "English Premier League",
  "season": "2025-2026",
  "match_time": "2025-08-16 03:00",
  "source": "titan" | "nowscore",
  "fetched_at": "2026-07-31T13:09:58Z",
  "_version": "v1",
  "changes": [
    {"time": "8-16 02:30", "line": "半球", "home": 0.84, "away": 1.02, "status": "即时"}
  ]
}
```

### Field notes

- `match_time`: Beijing naive datetime string (`YYYY-MM-DD HH:MM`), copied from schedule.
- `fetched_at`: ISO8601 UTC (`%Y-%m-%dT%H:%M:%SZ`). Batch records written before this
  contract have no `fetched_at`; `is_fresh()` treats them as stale and the next live tick
  re-fetches and upgrades them to this schema.
- `changes[*].time`: titan/nowscore native format `M-d HH:MM`, no year. Do not convert.
- Numeric odds may be `int` or `float`; consumers must accept both.

## Upsert semantics

| Condition | Behavior |
|---|---|
| File missing | Write full record |
| File exists, `fetched_at` within throttle window | Skip (no I/O) |
| File exists, stale or `--force` | Fetch new snapshot, `merge(new, old)` preserving order & dedup, overwrite atomically |
| titan scrape empty | fallback to nowscore (`source="nowscore"`), else leave file untouched |
| nowscore fallback (asian/over_under) | single `3in1Odds.aspx` request parses BOTH tables; the sibling odds type is written too if its record is missing (batch) or missing/stale (live) |
| Post-kickoff | never touched again (window is pre-match only) |

## Merge definition (`core/odds_store.merge_odds_changes`)

Union of existing + new rows, deduped on the row key
`(time, line, home/big, away/small, status)` (european: `home_win/draw/away_win`).

- Existing rows keep their stored order.
- Rows present only in the new snapshot are appended at the end.
- Safe against page-side truncation: never drops a row that is already persisted.

## State & sweep files (data/)

| File | Purpose |
|---|---|
| `live_state.json` | last season-sync date, per-sid last analysis refresh, last weekly sweep ISO week |
| `live_pending.json` | matches past kickoff with no `full_score`, detected by the Monday sweep (postponement safety net) |

`live_pending.json` entry:

```json
{
  "schedule_id": 2789129,
  "competition": "J1 联赛",
  "season": "2026-2027",
  "match_time": "2026-08-07 18:30",
  "detected": "2026-08-10",
  "note": "kickoff passed, no score (postponed?)"
}
```
