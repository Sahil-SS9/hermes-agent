#!/bin/bash
# Wiki daily sync — commits and pushes any changes to GitHub
# Silent on no changes, brief log on push

WIKI_DIR="$HOME/wiki"
cd "$WIKI_DIR" || exit 1

# Check for any changes
if git diff --quiet && git diff --cached --quiet && [ -z "$(git status --porcelain)" ]; then
    # Silent — nothing to commit
    exit 0
fi

git add -A
git commit -m "wiki sync: $(date +%Y-%m-%d_%H:%M:%S)"
git push origin main 2>&1
