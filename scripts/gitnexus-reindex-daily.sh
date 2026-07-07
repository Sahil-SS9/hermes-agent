#!/usr/bin/env bash
# GitNexus daily re-index of KenseiAgent codebase
# Keeps the code knowledge graph current with HEAD
# Detaches to background via setsid+disown to avoid cron scheduler timeout
set -euo pipefail

REPO="/home/kensei/repos/KenseiAgent"
GITNEXUS="/home/kensei/.hermes/node/bin/gitnexus"
RUNNER="/home/kensei/.hermes/scripts/gitnexus-reindex-runner.sh"
LOG_DIR="/home/kensei/.hermes/logs/gitnexus"
mkdir -p "$LOG_DIR"

# Get current HEAD (full SHA for comparison)
HEAD_COMMIT=$(cd "$REPO" && git rev-parse HEAD)

# Check if index is stale
INDEXED_COMMIT=$("$GITNEXUS" status --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('lastCommit',''))" 2>/dev/null || echo "unknown")

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
    echo "Full rebuild required (previous run incomplete) — starting background re-index"
    # setsid = new session fully detached from cron's process group
    # disown = remove from parent shell's job table
    setsid "$RUNNER" "$LOG_FILE" "$GITNEXUS" "$REPO" full > /dev/null 2>&1 < /dev/null &
    disown
    echo "Full rebuild started (pid $!) — log: $LOG_FILE" >> "$LOG_DIR/reindex-history.log"
    exit 0
else
    # Incremental update — fully detached
    setsid "$RUNNER" "$LOG_FILE" "$GITNEXUS" "$REPO" incremental > /dev/null 2>&1 < /dev/null &
    disown
    echo "Incremental re-index started (pid $!) — log: $LOG_FILE"
    echo "GitNexus re-index started at $(date '+%d/%m/%y %H:%M:%S')"
fi