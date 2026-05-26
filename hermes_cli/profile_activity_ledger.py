"""Append-only profile activity ledger for governance/audit events.

The ledger is intentionally passive by default. Callers should use
``record_event_if_enabled`` for inline hooks so production behaviour is unchanged
unless ``governance.profile_activity_ledger.enabled`` is true.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from hermes_constants import get_default_hermes_root
from hermes_cli.config import load_config

logger = logging.getLogger(__name__)

FEATURE_FLAG_NAME = "governance.profile_activity_ledger.enabled"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS activity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    occurred_at INTEGER NOT NULL,
    source TEXT NOT NULL,
    actor_profile TEXT,
    target_profile TEXT,
    event_type TEXT NOT NULL,
    object_type TEXT,
    object_id TEXT,
    board TEXT,
    status_from TEXT,
    status_to TEXT,
    summary TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_events_occurred_at ON activity_events(occurred_at);
CREATE INDEX IF NOT EXISTS idx_activity_events_target_profile ON activity_events(target_profile);
CREATE INDEX IF NOT EXISTS idx_activity_events_event_type ON activity_events(event_type);
CREATE INDEX IF NOT EXISTS idx_activity_events_object ON activity_events(object_type, object_id);
CREATE INDEX IF NOT EXISTS idx_activity_events_board ON activity_events(board);

CREATE TRIGGER IF NOT EXISTS activity_events_no_update
BEFORE UPDATE ON activity_events
BEGIN
    SELECT RAISE(ABORT, 'activity_events is append-only; UPDATE is forbidden');
END;

CREATE TRIGGER IF NOT EXISTS activity_events_no_delete
BEFORE DELETE ON activity_events
BEGIN
    SELECT RAISE(ABORT, 'activity_events is append-only; DELETE is forbidden');
END;
"""


def _governance_root() -> Path:
    return get_default_hermes_root() / "governance"


def ledger_db_path() -> Path:
    return _governance_root() / "profile-activity-ledger.sqlite"


def ledger_jsonl_dir() -> Path:
    return _governance_root() / "logboard" / "profile-activity-ledger"


def is_enabled(cfg: Optional[dict[str, Any]] = None) -> bool:
    if cfg is None:
        try:
            cfg = load_config() or {}
        except Exception:
            return False
    value = (((cfg.get("governance") or {}).get("profile_activity_ledger") or {}).get("enabled"))
    return bool(value)


def _connect() -> sqlite3.Connection:
    path = ledger_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_SCHEMA)
    return conn


def _canonical_payload(payload: Optional[dict[str, Any]]) -> str:
    if not payload:
        return "{}"
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _make_event_id(
    *,
    source: str,
    event_type: str,
    object_type: Optional[str],
    object_id: Optional[str],
    occurred_at: int,
    payload_json: str,
) -> str:
    basis = json.dumps(
        {
            "source": source,
            "event_type": event_type,
            "object_type": object_type,
            "object_id": object_id,
            "occurred_at": occurred_at,
            "payload": payload_json,
            "nonce": uuid.uuid4().hex,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "pal_" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def _mirror_path(occurred_at: int) -> Path:
    day = time.strftime("%Y-%m-%d", time.gmtime(occurred_at))
    return ledger_jsonl_dir() / f"{day}.jsonl"


def _append_jsonl_once(row: dict[str, Any]) -> None:
    mirror_path = _mirror_path(int(row["occurred_at"]))
    mirror_path.parent.mkdir(parents=True, exist_ok=True)
    event_id = str(row["event_id"])
    if mirror_path.exists():
        try:
            with mirror_path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if event_id in line:
                        try:
                            if json.loads(line).get("event_id") == event_id:
                                return
                        except json.JSONDecodeError:
                            continue
        except OSError:
            pass
    with mirror_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False, default=str) + "\n")


def append_event(
    *,
    source: str,
    event_type: str,
    event_id: Optional[str] = None,
    actor_profile: Optional[str] = None,
    target_profile: Optional[str] = None,
    object_type: Optional[str] = None,
    object_id: Optional[str] = None,
    board: Optional[str] = None,
    status_from: Optional[str] = None,
    status_to: Optional[str] = None,
    summary: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
    occurred_at: Optional[int] = None,
) -> str:
    """Append an activity event and mirror it to JSONL.

    ``event_id`` is the idempotency key. If it already exists, the existing row
    is left untouched and the JSONL mirror is not duplicated.
    """

    occurred = int(occurred_at or time.time())
    payload_json = _canonical_payload(payload)
    resolved_event_id = event_id or _make_event_id(
        source=source,
        event_type=event_type,
        object_type=object_type,
        object_id=object_id,
        occurred_at=occurred,
        payload_json=payload_json,
    )
    created_at = int(time.time())

    row = {
        "event_id": resolved_event_id,
        "occurred_at": occurred,
        "source": source,
        "actor_profile": actor_profile,
        "target_profile": target_profile,
        "event_type": event_type,
        "object_type": object_type,
        "object_id": object_id,
        "board": board,
        "status_from": status_from,
        "status_to": status_to,
        "summary": summary,
        "payload_json": payload_json,
        "created_at": created_at,
    }

    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO activity_events (
                event_id, occurred_at, source, actor_profile, target_profile,
                event_type, object_type, object_id, board, status_from,
                status_to, summary, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["event_id"],
                row["occurred_at"],
                row["source"],
                row["actor_profile"],
                row["target_profile"],
                row["event_type"],
                row["object_type"],
                row["object_id"],
                row["board"],
                row["status_from"],
                row["status_to"],
                row["summary"],
                row["payload_json"],
                row["created_at"],
            ),
        )
        inserted = cur.rowcount == 1
    if inserted:
        _append_jsonl_once(row)
    return resolved_event_id


def record_event_if_enabled(*, cfg: Optional[dict[str, Any]] = None, **kwargs: Any) -> Optional[str]:
    if not is_enabled(cfg):
        return None
    try:
        return append_event(**kwargs)
    except Exception as exc:  # audit hooks must never break primary flows
        logger.warning("profile activity ledger write failed: %s", exc, exc_info=True)
        return None
