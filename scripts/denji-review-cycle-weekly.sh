#!/usr/bin/env bash
# Wrapper: weekly denji profile review cycle.
# Separated from the generic wrapper so the cron scheduler can call it without arguments.
exec /home/kensei/.hermes/scripts/denji-review-cycle.sh --cycle weekly "$@"
