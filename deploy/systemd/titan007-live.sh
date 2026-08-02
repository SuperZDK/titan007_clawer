#!/usr/bin/env bash
# Titan007 live tick wrapper: flock-guarded, so overlapping ticks (a run
# longer than the 5-min timer interval) are skipped instead of racing.
set -euo pipefail

exec /usr/bin/flock -n /run/titan007-live.lock \
    /opt/titan007_pro/.venv/bin/python /opt/titan007_pro/run.py --pipeline live
