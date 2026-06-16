#!/usr/bin/env bash
# SahilBlog content pipeline - daily cron wrapper (no-agent).
#
# Runs the blog pipeline for all configured streams (ai, pm, builder),
# staging approved:false draft MDX posts into ~/repos/SahilBlog. The
# approval card is delivered to #content; a human flips approved:true
# via blog_publisher.approve(slug) which builds + pushes.
#
# Staggered after the 05:00 content-engine crons to avoid overlap.
set -euo pipefail

CE_ROOT="/home/kensei/repos/KenseiAgent/content_engine"
VENV_PY="/home/kensei/repos/KenseiAgent/.venv/bin/python"

cd "$CE_ROOT"

# Run the pipeline for all streams. Output is the cron message.
PYTHONPATH=. "$VENV_PY" -m blog.blog_pipeline --stream all 2>&1 || true

# Surface budget status so Sahil can see remaining image spend.
PYTHONPATH=. "$VENV_PY" -c "
import json, budget
print('budget:', json.dumps(budget.status()))
" 2>&1 || true