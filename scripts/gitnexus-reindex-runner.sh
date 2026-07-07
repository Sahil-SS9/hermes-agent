#!/usr/bin/env bash
# GitNexus re-index runner — detached worker for gitnexus-reindex-daily.sh
# Arguments: <log_file> <gitnexus_bin> <repo_path> <mode: full|incremental>
set -euo pipefail

LOG_FILE="$1"
GITNEXUS="$2"
REPO="$3"
MODE="$4"

if [ "$MODE" = "full" ]; then
    echo "=== GitNexus Full Rebuild ===" > "$LOG_FILE"
    echo "Started: $(date)" >> "$LOG_FILE"
    timeout 600 "$GITNEXUS" analyze "$REPO" --force >> "$LOG_FILE" 2>&1
    echo "Exit code: $? — $(date)" >> "$LOG_FILE"
else
    echo "=== GitNexus Incremental Re-index ===" > "$LOG_FILE"
    echo "Started: $(date)" >> "$LOG_FILE"
    timeout 600 "$GITNEXUS" analyze "$REPO" >> "$LOG_FILE" 2>&1
    echo "Exit code: $? — $(date)" >> "$LOG_FILE"
fi