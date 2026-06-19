#!/usr/bin/env bash
# Weekly GitHub Radar — full re-evaluation mode
# Runs the main discover script with --mode weekly to re-scan
# cached repos and flag those with new pushes.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/github-radar-discover.py" --mode weekly
