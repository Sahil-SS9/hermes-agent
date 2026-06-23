#!/usr/bin/env bash
set -euo pipefail
# Wrapper: monthly denji profile review cycle.
exec /home/kensei/.hermes/scripts/denji-review-cycle.sh --cycle monthly "$@"
