#!/usr/bin/env python3
"""Discord approval handler for CeeCee content drafts.

Polls #content for !approve/!reject/!amend commands and updates the
content_engine SQLite database. Silent when no commands found.
"""
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CHANNEL_ID = "1507448580649123900"
DB_PATH = Path("/home/kensei/repos/KenseiAgent/content_engine/db/content_engine.db")
STATE_PATH = Path("/home/kensei/.hermes/state/ceecee-approval-state.json")
DOTENV_PATH = Path("/home/kensei/.hermes/.env")


def get_token() -> str:
    """Read DISCORD_BOT_TOKEN from .env."""
    if DOTENV_PATH.exists():
        for line in DOTENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DISCORD_BOT_TOKEN="):
                return line[len("DISCORD_BOT_TOKEN="):].strip().strip('"').strip("'")
    return os.environ.get("DISCORD_BOT_TOKEN", "")


def discord_api(endpoint: str, data: dict | None = None) -> dict | list | None:
    """Call the Discord REST API. Returns parsed JSON or None on error."""
    token = get_token()
    if not token:
        return None
    url = f"https://discord.com/api/v10{endpoint}"
    headers = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        url, data=body, headers=headers, method="POST" if data else "GET"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return None
        return None
    except Exception:
        return None


def load_state() -> dict:
    """Load processed message IDs from state file."""
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            pass
    return {"processed": [], "last": 0}


def save_state(st: dict) -> None:
    """Persist processed message IDs to state file."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(st), encoding="utf-8")


def parse_command(text: str) -> dict | None:
    """Parse a Discord command string.

    Returns dict with keys: command, draft_id, args or None.
    """
    m = re.match(
        r"^!(approve|reject|amend)\s+(\S+)\s*(.*)",
        text.strip(),
        re.IGNORECASE,
    )
    if not m:
        return None
    return {
        "command": m.group(1).lower(),
        "draft_id": m.group(2),
        "args": m.group(3).strip(),
    }


def update_draft_status(draft_id: str, command: str, args: str) -> str | None:
    """Update the draft status in the content_engine database.

    Returns a human-readable result message or None if draft not found.
    """
    if not DB_PATH.exists():
        return "Database not found"

    conn = sqlite3.connect(str(DB_PATH))
    try:
        row = conn.execute(
            "SELECT id, status FROM drafts WHERE id = ?", (draft_id,)
        ).fetchone()
        if not row:
            return None

        now = datetime.now(timezone.utc).isoformat()

        if command == "approve":
            conn.execute(
                "UPDATE drafts SET status = 'approved', approved_at = ? WHERE id = ?",
                (now, draft_id),
            )
            msg = f"Approved {draft_id}"

        elif command == "reject":
            conn.execute(
                "UPDATE drafts SET status = 'rejected', rejected_at = ? WHERE id = ?",
                (now, draft_id),
            )
            msg = f"Rejected {draft_id}"
            if args:
                msg += f" — {args}"

        elif command == "amend":
            conn.execute(
                "UPDATE drafts SET status = 'amended' WHERE id = ?",
                (draft_id,),
            )
            msg = f"Amended {draft_id}"
            if args:
                msg += f" — {args}"

        else:
            return f"Unknown command: {command}"

        conn.commit()
        return msg
    finally:
        conn.close()


def add_reaction(message_id: str, emoji: str = "✅") -> bool:
    """Add a reaction emoji to a Discord message (PUT endpoint)."""
    token = get_token()
    if not token:
        return False
    url = (
        f"https://discord.com/api/v10/channels/{CHANNEL_ID}"
        f"/messages/{message_id}/reactions/{emoji}/@me"
    )
    headers = {"Authorization": f"Bot {token}"}
    req = urllib.request.Request(url, data=b"", headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=10):
            return True
    except urllib.error.HTTPError:
        return False
    except Exception:
        return False


def main() -> None:
    st = load_state()
    processed = set(st.get("processed", []))

    messages = discord_api(
        f"/channels/{CHANNEL_ID}/messages?limit=20"
    )
    if not messages or not isinstance(messages, list):
        return

    for msg in messages:
        mid = msg.get("id")
        if mid in processed:
            continue

        content = msg.get("content", "")
        cmd = parse_command(content)
        if not cmd:
            continue

        draft_id = cmd["draft_id"]
        result = update_draft_status(draft_id, cmd["command"], cmd["args"])

        if result is None:
            add_reaction(mid, "❓")
        else:
            add_reaction(mid, "✅")
            print(result)

        processed.add(mid)

    st["processed"] = list(processed)
    st["last"] = int(time.time())
    save_state(st)


if __name__ == "__main__":
    main()
