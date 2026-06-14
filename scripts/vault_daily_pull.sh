#!/bin/bash
# Vault daily pull — fetches latest project docs from GitHub
# Silent on success, errors printed on failure
set -euo pipefail

export HOME=/home/kensei
export GIT_TERMINAL_PROMPT=0
export PATH="/usr/bin:/home/kensei/.local/bin:$PATH"

VAULT_DIR="$HOME/vaults/obsidian-master"
cd "$VAULT_DIR" || { echo "ERROR: cannot cd to $VAULT_DIR"; exit 1; }

if ! git pull --ff-only origin main 2>&1; then
    echo "ERROR: git pull failed (exit $?)"
    exit 1
fi