#!/bin/bash
# Vault daily pull — fetches latest project docs from GitHub
# Silent on success, errors printed on failure

VAULT_DIR="$HOME/vaults/obsidian-master"
cd "$VAULT_DIR" || exit 1

git pull --ff-only origin main 2>&1 || exit 1

# Silent on success
