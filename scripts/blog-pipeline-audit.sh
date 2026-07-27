#!/usr/bin/env bash
# Blog pipeline audit wrapper.
#
# Resolves the audit script relative to this wrapper's own location so the
# correct (worktree) copy runs, then forwards BLOG_AUDIT_ENGINE_ROOT /
# BLOG_AUDIT_BLOG_ROOT env overrides to the audit (production defaults are
# preserved when the overrides are absent).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"
PYTHONPATH="${REPO_ROOT}/content_engine" python3 "${REPO_ROOT}/content_engine/tools/blog_pipeline_audit.py"
