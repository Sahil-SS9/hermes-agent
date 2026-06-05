#!/bin/bash
# Rotate Tor exit IP — send NEWNYM signal
# Wraps tor-newnym.py with sg for cookie auth.
# Usage: rotate-tor-ip.sh [--quiet]

QUIET=false
if [ "$1" = "--quiet" ]; then QUIET=true; fi

OUTPUT=$(sg debian-tor -c "/usr/bin/python3 /home/kensei/.hermes/scripts/tor-newnym.py" 2>&1)
RC=$?

if [ "$QUIET" = true ]; then
    exit $RC
fi
echo "$OUTPUT"
exit $RC