#!/usr/bin/env bash
set -euo pipefail
# Wrapper: quarterly denji profile review cycle.
exec /home/kensei/.hermes/scripts/denji-review-cycle.sh --cycle quarterly "$@"
