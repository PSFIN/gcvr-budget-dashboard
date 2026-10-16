#!/usr/bin/env bash
# Refresh the budget dashboard: pull the latest code from GitHub, rebuild the page
# from the Streamline data in pacing.db, and publish it to the web root.
# Run by budget-update.timer every day at 8:00 AM Eastern; safe to run by hand any time.
set -euo pipefail

# Everything lives inside main() and the script ends with "exit": bash reads the whole
# function before running it, so the "git reset" below can safely replace this very file.
main() {
    local APP_DIR="${APP_DIR:-/home/ubuntu/budget-dashboard}"
    local WEB_ROOT="${WEB_ROOT:-/var/www/budget}"
    export PACING_DIR="${PACING_DIR:-/home/ubuntu/gulf-coast-pacing}"
    # The 2026 budget targets are private (this repo is public): they live only here, never in Git.
    export BUDGETS_FILE="${BUDGETS_FILE:-/home/ubuntu/budget-data/budgets_2026.json}"
    # Private snapshots (one per day) used for the "change vs last week" in the Teams message.
    export HISTORY_DIR="${HISTORY_DIR:-/home/ubuntu/budget-data/history}"

    cd "$APP_DIR"
    git fetch --quiet origin main
    if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
        git reset --hard --quiet origin/main
        echo "$(date '+%F %T') code updated to $(git rev-parse --short HEAD)"
    fi

    # The template in the repo is never modified: the finished page is written
    # straight to the web root (atomically, so visitors never see a half-written
    # file). Only index.html is published; scripts and .git stay off the web.
    # Teams: posts the written summary on Mondays only (NOTIFY=daily for every day, NOTIFY=off for never).
    # It needs the private webhook file /home/ubuntu/budget-data/teams_webhook.url and is skipped without it.
    # FORCE_NOTIFY=1 posts right now, whatever the day.
    local notify_args=(--notify "${NOTIFY:-monday}")
    if [ -n "${FORCE_NOTIFY:-}" ]; then notify_args+=(--force-notify); fi
    python3 build_dashboard.py --out "$WEB_ROOT/index.html" "${notify_args[@]}"
}

main "$@"
exit
