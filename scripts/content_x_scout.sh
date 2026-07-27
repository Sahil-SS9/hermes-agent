#!/usr/bin/env bash
# X auto-suggest scout: search Sahil niches and post repurpose suggestions to
# the inbox. Dormant until the X API spend cap resets (2026-06-14); skips safely.
# P13: CONTENT_SCOUT_DRY_RUN=1 short-circuits before xurl/Discord invocation.
set -euo pipefail

if [[ "${CONTENT_SCOUT_DRY_RUN:-0}" == "1" ]]; then
  echo "dry-run: would run x_scout (xurl fetch + Discord inbox post)"
  exit 0
fi

HERMES_HOME_DIR="${HERMES_HOME:-$HOME/.hermes}"
CE="/home/kensei/repos/KenseiAgent/content_engine"
cd "$CE"
set -a
# shellcheck disable=SC1091
source "${HERMES_HOME_DIR}/.env"
set +a
export PYTHONPATH="${CE}:${PYTHONPATH:-}"
/home/kensei/repos/KenseiAgent/.venv/bin/python x_scout.py
