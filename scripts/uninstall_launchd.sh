#!/bin/bash
# Uninstall the DC Housing Finder launchd agents.
set -euo pipefail

AGENTS_DIR="$HOME/Library/LaunchAgents"
for plist in com.charliemlcek.dchousing.alerts.plist com.charliemlcek.dchousing.digest.plist; do
    target="$AGENTS_DIR/$plist"
    if [[ -f "$target" ]]; then
        launchctl unload "$target" 2>/dev/null || true
        rm "$target"
        echo "✓ Removed $plist"
    fi
done
echo ""
echo "Remaining dchousing agents:"
launchctl list | grep dchousing || echo "  (none)"
