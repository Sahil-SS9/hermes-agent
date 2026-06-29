#!/bin/bash
# PR-to-Blog daily pipeline — no-agent script for Hermes cron.
# Scans for merged PRs, generates blog posts, distributes to social.
set -euo pipefail

cd /home/kensei/repos/KenseiAgent/content_engine
set -a
. ~/.hermes/.env
set +a

PYTHONPATH=. ../.venv/bin/python -m blog.pr_to_blog 2>&1
