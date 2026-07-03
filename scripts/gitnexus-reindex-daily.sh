#!/usr/bin/env bash
# GitNexus daily re-index of KenseiAgent codebase
# Keeps the code knowledge graph current with HEAD
set -euo pipefail

REPO="/home/kensei/repos/KenseiAgent"
GITNEXUS="/home/kensei/.hermes/node/bin/gitnexus"

# Get current HEAD
HEAD_COMMIT=$(cd "$REPO" && git rev-parse --short HEAD)

# Check if index is stale
INDEXED_COMMIT=$("$GITNEXUS" status --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('lastCommit','')[:12])" 2>/dev/null || echo "unknown")

if [ "$HEAD_COMMIT" == "$INDEXED_COMMIT" ]; then
    echo "[SILENT]"
    exit 0
fi

echo "Re-indexing KenseiAgent at $HEAD_COMMIT (was $INDEXED_COMMIT)"
"$GITNEXUS" analyze "$REPO" --force 2>&1
echo "GitNexus re-index complete at $(date '+%d/%m/%y %H:%M:%S')"
