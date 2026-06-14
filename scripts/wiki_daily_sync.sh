#!/bin/bash
# Wiki daily sync — commits and pushes any changes to GitHub
# Silent on no changes, brief log on push
set -euo pipefail

export GIT_TERMINAL_PROMPT=0
export PATH="/usr/bin:/home/kensei/.local/bin:$PATH"

WIKI_DIR="$HOME/wiki"
cd "$WIKI_DIR" || { echo "ERROR: cannot cd to $WIKI_DIR"; exit 1; }

# Check for any changes
if git diff --quiet && git diff --cached --quiet && [ -z "$(git status --porcelain)" ]; then
    exit 0
fi

git add -A
git commit -m "wiki sync: $(date +%Y-%m-%d_%H:%M:%S)"

# Push with explicit error capture
if ! git push origin main 2>&1; then
    echo "ERROR: git push failed (exit $?)"
    exit 1
fi
