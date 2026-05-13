#!/usr/bin/env bash
# Google Workspace OAuth re-auth shell wrapper.
#
# Usage:
#   stop the gateway (frees port 8000):
#     sudo systemctl stop hermes-gateway
#   run this helper:
#     ~/.hermes/scripts/google-oauth-capture.sh fusionfirststudios@gmail.com
#   copy the auth URL, open in browser via SSH tunnel, approve
#   restart the gateway:
#     sudo systemctl start hermes-gateway
#
# For SSH-tunnelled access:
#   open a second terminal: ssh -L 8000:localhost:8000 kensei@46.225.74.57 -N
#
# Outputs AUTH_URL between markers, then waits for callback.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

EMAIL="${1:?Usage: $0 <email-address>}"

if ss -tlnp 2>/dev/null | grep -q ':8000'; then
  echo "ERROR: port 8000 is in use. Stop the gateway first: sudo systemctl stop hermes-gateway"
  exit 1
fi

exec python3 -u "${SCRIPT_DIR}/google-oauth-capture.py" "$EMAIL"
