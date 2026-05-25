#!/usr/bin/env bash
set -euo pipefail
cd /home/kensei/.hermes/scripts
# Fetch calendar events
python3 calendar_brief_combined.py >/dev/null 2>&1
# Format and output concise Discord summary + HTML attachment
python3 calendar_brief_format.py
