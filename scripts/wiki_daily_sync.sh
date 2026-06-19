#!/bin/bash
# Wiki daily sync — commits and pushes any changes to GitHub
# Silent on no changes, brief log on push
set -euo pipefail

export HOME=/home/kensei
export GIT_TERMINAL_PROMPT=0
export PATH="/usr/bin:/home/kensei/.local/bin:$PATH"

WIKI_DIR="$HOME/wiki"
cd "$WIKI_DIR" || { echo "ERROR: cannot cd to $WIKI_DIR"; exit 1; }

# --- Auth setup ---
# Fetch the gh token at runtime and use GIT_ASKPASS to provide it to git.
# This bypasses the gh credential helper which can fail in cron environments.
GH_TOKEN=$(gh auth token 2>/dev/null) || {
    echo "ERROR: gh auth token failed — is gh logged in?"
    gh auth status 2>&1
    exit 1
}
export GH_TOKEN
export GIT_ASKPASS="$HOME/.hermes/scripts/git-askpass.sh"

# 1. Push any unpushed commits from a previous failed run (idempotent recovery)
if [[ -n "$(git log origin/main..HEAD --oneline 2>/dev/null)" ]]; then
  git push origin main 2>&1 || exit 128
fi

# 2. Detect new work
if git diff --quiet && git diff --cached --quiet && [ -z "$(git status --porcelain)" ]; then
    exit 0
fi

# 3. Commit + push (with retry — GitHub has transient auth hiccups)
git add -A
git commit -m "wiki sync: $(date +%Y-%m-%d_%H:%M:%S)"
for attempt in 1 2 3; do
  git push origin main 2>&1 && exit 0
  sleep $((attempt * 5))
done
exit 128
