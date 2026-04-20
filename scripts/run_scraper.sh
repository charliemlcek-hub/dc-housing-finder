#!/bin/bash
# Local scraper runner — invoked by launchd agents (see scripts/install_launchd.sh).
#
# Usage:
#   run_scraper.sh alerts    # 3-hourly: only send email for extraordinary fits
#   run_scraper.sh digest    # daily:    send full digest email
#
# Behavior:
#   1. Activate venv
#   2. Load .env (GMAIL_APP_PASSWORD)
#   3. Export DASHBOARD_URL for email links
#   4. Run main.py with appropriate flag
#   5. git add / commit / push any updates to docs/ + data/
set -euo pipefail

MODE="${1:-alerts}"
PROJECT_DIR="/Users/charliemlcek/Desktop/Claude Code Project/dc-housing-finder"
DASHBOARD_URL="https://charliemlcek-hub.github.io/dc-housing-finder/"
LOG_DIR="$PROJECT_DIR/logs"

mkdir -p "$LOG_DIR"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
LOG_FILE="$LOG_DIR/run-$(date -u +%Y%m%d).log"

exec >> "$LOG_FILE" 2>&1
echo "=========================================="
echo "[$TS] mode=$MODE"

cd "$PROJECT_DIR"

# Activate venv
# shellcheck disable=SC1091
source .venv/bin/activate

# Load .env (GMAIL_APP_PASSWORD). Doing it this way is resilient to commented/blank lines.
if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

export DASHBOARD_URL

# Run scraper
if [[ "$MODE" == "digest" ]]; then
    python main.py
else
    python main.py --alerts-only
fi

# Commit any changes (dashboard html, db state)
if ! git diff --quiet docs/index.html data/listings.db 2>/dev/null; then
    git add -f docs/index.html data/listings.db
    git commit -m "Update dashboard ($MODE, $(date -u +%Y-%m-%dT%H:%MZ))" || echo "nothing to commit"
    git push || echo "push failed"
else
    echo "no content changes to commit"
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] done"
