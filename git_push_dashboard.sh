#!/bin/bash
# Pushes updated dashboard files to GitHub Pages every 2 minutes.
# Runs independently of the scrape cycle — just watches docs/ for changes.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="$SCRIPT_DIR/logs/git_push.log"

cd "$SCRIPT_DIR"

git add docs/index.html docs/live_feed.html docs/daily_report.html docs/market_report.html docs/weekly_report.html docs/monthly_report.html 2>> "$LOG" || exit 0

if git diff --cached --quiet; then
    exit 0  # nothing changed, skip
fi

git commit -m "Dashboard update $(date '+%Y-%m-%d %H:%M')" >> "$LOG" 2>&1
git push origin main >> "$LOG" 2>&1
echo "=== $(date '+%Y-%m-%d %H:%M:%S') pushed ===" >> "$LOG"
