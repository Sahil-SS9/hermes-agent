#!/bin/bash
# KENSEI Memory Watchdog — checks available RAM, alerts via cron delivery when low
# Runs as a no_agent cron: stdout = message, empty = silent, non-zero exit = alert
# Route: Topic 20 (System Health + Alerts). Silent when healthy.

THRESHOLD_MB=${1:-512}

AVAILABLE_KB=$(grep MemAvailable /proc/meminfo | awk '{print $2}')
AVAILABLE_MB=$((AVAILABLE_KB / 1024))

if [ "$AVAILABLE_MB" -lt "$THRESHOLD_MB" ]; then
    TOP3=$(ps aux --sort=-%mem | head -4 | tail -3 | awk '{printf "    %s (%s%%)\\n", $11, $4}')
    echo "🔴 Memory alert · ${AVAILABLE_MB}MB free (threshold: ${THRESHOLD_MB}MB)"
    echo ""
    echo "<b>Top consumers</b>"
    echo "$TOP3" | while read -r line; do echo "• <code>$line</code>"; done
    exit 0
fi

# Under threshold — silent, no delivery
exit 0
