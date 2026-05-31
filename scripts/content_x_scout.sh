#!/usr/bin/env bash
# X auto-suggest scout: search Sahil's niches and post repurpose suggestions to
# the inbox. Dormant until the X API spend cap resets (2026-06-14); skips safely.
set -euo pipefail
CE="/home/kensei/repos/KenseiAgent/content_engine"
cd "$CE"
set -a
# shellcheck disable=SC1091
source /home/kensei/.hermes/.env
set +a
export PYTHONPATH="${CE}:${PYTHONPATH:-}"
/home/kensei/repos/KenseiAgent/.venv/bin/python x_scout.py
