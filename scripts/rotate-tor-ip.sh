#!/bin/bash
set -euo pipefail
# Rotate Tor exit IP — send NEWNYM signal
# Wraps tor-newnym.py with sg for cookie auth.
# Usage: rotate-tor-ip.sh [--quiet]

QUIET=false
[ "${1:-}" = "--quiet" ] && QUIET=true

OUTPUT=$(sg debian-tor -c "/usr/bin/python3 /home/kensei/.hermes/scripts/tor-newnym.py" 2>&1) || RC=$?

if [ "$QUIET" = true ]; then
    exit "${RC:-0}"
fi
echo "$OUTPUT"
exit "${RC:-0}"