#!/usr/bin/env bash
set -euo pipefail
cd /home/kensei/repos/KenseiAgent
PYTHONPATH=/home/kensei/repos/KenseiAgent/content_engine python3 /home/kensei/repos/KenseiAgent/content_engine/tools/blog_pipeline_audit.py
