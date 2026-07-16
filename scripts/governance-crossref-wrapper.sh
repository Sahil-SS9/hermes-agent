#!/usr/bin/env bash
set -euo pipefail
# governance-crossref-wrapper.sh
# Wrapper for governance-crossref.py - checks if Denji review exists, runs cross-reference.
# Silent when no review file found (cron-output-contract).
#
# W1-S (Batch 1): resolves the crossref script relative to this wrapper own
# location (repository-relative) rather than the absent
# ~/.hermes/scripts/governance-crossref.py. The active implementation was
# restored from scripts/archive/governance-crossref.py.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CROSSREF="${SCRIPT_DIR}/governance-crossref.py"
LOGBOARD="${HERMES_HOME:-/home/kensei/.hermes}/governance/logboard"

# Find the latest Denji profile review JSON
REVIEW=$(ls -t "$LOGBOARD"/denji-profile-review-*.json 2>/dev/null | head -1 || true)

if [ -z "$REVIEW" ]; then
    # Silent - no review to cross-reference
    exit 0
fi

# Check if review was already cross-referenced today
REVIEW_DATE=$(stat -c %Y "$REVIEW" 2>/dev/null || true)
LAST_CROSSREF=$(stat -c %Y "$LOGBOARD"/cross-ref-*.md 2>/dev/null | sort -rn | head -1 || true)

if [ -n "$LAST_CROSSREF" ] && [ "$REVIEW_DATE" -le "$LAST_CROSSREF" ]; then
    # Already cross-referenced - silent
    exit 0
fi

# Run cross-reference
python3 "$CROSSREF" "$REVIEW"
