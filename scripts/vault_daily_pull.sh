#!/bin/bash
# Vault daily pull — fetches latest project docs from GitHub
# Silent on success, errors printed on failure
# Includes retry with exponential backoff for transient auth/network failures
set -euo pipefail

export HOME=/home/kensei
export GIT_TERMINAL_PROMPT=0
export PATH="/usr/bin:/home/kensei/.local/bin:$PATH"

VAULT_DIR="$HOME/vaults/obsidian-master"
cd "$VAULT_DIR" || { echo "ERROR: cannot cd to $VAULT_DIR"; exit 1; }

# Retry loop: up to 3 attempts with 10s, 30s backoff
MAX_ATTEMPTS=3
for attempt in $(seq 1 $MAX_ATTEMPTS); do
    GIT_OUTPUT=$(git pull --ff-only origin main 2>&1) && {
        # Success — silent exit
        exit 0
    }
    GIT_EXIT=$?

    if [ "$attempt" -lt "$MAX_ATTEMPTS" ]; then
        SLEEP=$(( attempt * 10 ))
        echo "WARN: git pull attempt $attempt/$MAX_ATTEMPTS failed (exit $GIT_EXIT), retrying in ${SLEEP}s..."
        sleep "$SLEEP"
    else
        echo "ERROR: git pull failed after $MAX_ATTEMPTS attempts (last exit $GIT_EXIT)"
        echo "$GIT_OUTPUT"
        exit 1
    fi
done