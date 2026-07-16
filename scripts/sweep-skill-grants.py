#!/usr/bin/env python3
"""Cron entrypoint: TTL fallback sweep for temporary skill grants.

Thin wrapper over tools.skill_grants.sweep_expired_grants (repo is source of
truth). Portable: sys.path is derived from __file__ so the wrapper runs from
any checkout location, not a hardcoded absolute path.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.skill_grants import sweep_expired_grants

n = sweep_expired_grants(ttl_hours=24)
if n:
    print(json.dumps({"expired_grants_revoked": n, "ttl_hours": 24}))
