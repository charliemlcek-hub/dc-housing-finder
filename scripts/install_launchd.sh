#!/bin/bash
# Install the DC Housing Finder launchd agents on this Mac.
#
# What this does:
#   1. Copies the plists to ~/Library/LaunchAgents/
#   2. Registers them with launchctl (loads the schedule)
#   3. Runs a single scrape immediately to populate the dashboard
#
# What this does NOT do:
#   - Send you an unexpected email (first run is --alerts-only; won't email unless extraordinary fit found)
#   - Keep your Mac awake (see note at bottom)
set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
AGENTS_DIR="$HOME/Library/LaunchAgents"

mkdir -p "$AGENTS_DIR"

for plist in com.charliemlcek.dchousing.alerts.plist com.charliemlcek.dchousing.digest.plist; do
    target="$AGENTS_DIR/$plist"
    cp "$SCRIPT_DIR/$plist" "$target"
    # Unload if already loaded (idempotent re-install)
    launchctl unload "$target" 2>/dev/null || true
    launchctl load "$target"
    echo "✓ Loaded $plist"
done

echo ""
echo "Agents loaded:"
launchctl list | grep dchousing || echo "  (none showing — check errors above)"

echo ""
echo "NEXT STEPS:"
echo "  1. Run a test scrape now to populate the dashboard:"
echo "     bash \"$SCRIPT_DIR/run_scraper.sh\" digest"
echo ""
echo "  2. Keep your Mac from sleeping during scrape windows:"
echo "     System Settings → Battery → Options → 'Prevent automatic sleeping' when plugged in"
echo ""
echo "  3. Uninstall later with: bash \"$SCRIPT_DIR/uninstall_launchd.sh\""
