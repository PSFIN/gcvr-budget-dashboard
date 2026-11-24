#!/usr/bin/env bash
# Rebuild both dashboard pages from the data already on the server: no git pull, no Streamline call,
# no Teams post, no history snapshot. Run by the unit settings service (deploy/settings_api.py) after
# someone saves a unit edit in Version 2; safe to run by hand.
set -euo pipefail

APP_DIR="${APP_DIR:-/home/ubuntu/budget-dashboard}"
WEB_ROOT="${WEB_ROOT:-/var/www/budget}"
export PACING_DIR="${PACING_DIR:-/home/ubuntu/gulf-coast-pacing}"
export BUDGETS_FILE="${BUDGETS_FILE:-/home/ubuntu/budget-data/budgets_2026.json}"
unset HISTORY_DIR

cd "$APP_DIR"
v2_args=()
if [ -e "${V2_FLAG:-/home/ubuntu/budget-data/enable_v2}" ]; then
    v2_args+=(--v2-out "$WEB_ROOT/v2/index.html")
fi
python3 build_dashboard.py --out "$WEB_ROOT/index.html" --notify off ${v2_args[@]+"${v2_args[@]}"}
