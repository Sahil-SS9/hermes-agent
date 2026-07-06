#!/usr/bin/env bash
# GitNexus daily re-index of KenseiAgent codebase
# Keeps the code knowledge graph current with HEAD
set -euo pipefail

REPO="/home/kensei/repos/KenseiAgent"
GITNEXUS="/home/kensei/.hermes/node/bin/gitnexus"
LOG_DIR="/home/kensei/.hermes/logs/gitnexus"
mkdir -p "$LOG_DIR"

# Get current HEAD
HEAD_COMMIT=$(cd "$REPO" && git rev-parse --short HEAD)

# Check if index is stale
INDEXED_COMMIT=$("$GITNEXUS" status --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('lastCommit','')[:12])" 2>/dev/null || echo "unknown")

if [ "$HEAD_COMMIT" == "$INDEXED_COMMIT" ]; then
    # Index is current — silent
    exit 0
fi

# Check if full rebuild needed (previous run crashed)
NEEDS_FULL=false
if "$GITNEXUS" status --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('incrementalInProgress') else 1)" 2>/dev/null; then
    NEEDS_FULL=true
fi

LOG_FILE="$LOG_DIR/reindex-$(date +%Y%m%d-%H%M%S).log"

if $NEEDS_FULL; then
    # Full rebuild — detach to background (can exceed 300s scheduler limit)
    echo "Full rebuild required (previous run incomplete) — starting background re-index"
    nohup bash -c "
        echo '=== GitNexus Full Rebuild ===' > '$LOG_FILE'
        echo 'Started: $(date)' >> '$LOG_FILE'
        timeout 600 '$GITNEXUS' analyze '$REPO' --force >> '$LOG_FILE' 2>&1
        echo 'Exit code: '$?' — $(date)' >> '$LOG_FILE'
    " > /dev/null 2>&1 < /dev/null &
    # Suppress PID output — log it instead
    echo "Full rebuild started (pid $!) — log: $LOG_FILE" >> "$LOG_DIR/reindex-history.log"
    exit 0
else
    # Incremental update — should complete within 280s
    timeout 280 "$GITNEXUS" analyze "$REPO" --force 2>&1
    echo "GitNexus re-index complete at $(date '+%d/%m/%y %H:%M:%S')"
fi
