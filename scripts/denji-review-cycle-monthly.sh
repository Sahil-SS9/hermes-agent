#!/usr/bin/env bash
set -euo pipefail
# Wrapper: monthly denji profile review cycle.
# Separated so the cron scheduler can call it without arguments.
#
# W1-R (Batch 1): exec canonical repository-relative scripts/denji-review-cycle.py
# with --cycle monthly, rather than absent ~/.hermes/scripts/denji-review-cycle.sh.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/denji-review-cycle.py" --cycle monthly "$@"
