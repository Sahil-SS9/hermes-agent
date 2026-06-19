#!/usr/bin/env bash
# Daily content review digest: generate cheap on-brand images for recent
# text+image drafts and deliver the batch to Discord, grouped by brand.
# Runs no_agent (the script IS the job). Delivery happens inside the Python
# (discord_digest), so the cron deliver target is 'local'.
set -euo pipefail

CE="/home/kensei/repos/KenseiAgent/content_engine"
cd "$CE"

# The gateway env does not carry FAL_KEY / DISCORD_BOT_TOKEN — source them.
set -a
# shellcheck disable=SC1091
source /home/kensei/.hermes/.env
set +a

export PYTHONPATH="${CE}:${PYTHONPATH:-}"

# Wrap in timeout to prevent FAL/Discord hangs from blocking the cron slot
# 300s matches the cron-level timeout; FAL image generation can take 90-300s
# when the API is slow (not locked — locked returns 403 instantly)
timeout 600 /home/kensei/repos/KenseiAgent/.venv/bin/python /home/kensei/repos/KenseiAgent/content_engine/content_engine.py review-digest --since-minutes 75 --max 3
