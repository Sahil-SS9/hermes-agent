"""Discord-based approval workflow for blog posts.

State machine:
  staged → pending_approval → approved → build → push (live)
                             → rejected → [removed from tracker, draft stays hidden]
                             → amended → [re-staged, re-requested]

Tracker file: blog_topics/pending_approvals.jsonl
"""

from __future__ import annotations
import json
import logging
import re
from datetime import datetime, date
from pathlib import Path
from typing import Optional

logger = logging.getLogger("blog_approval")

TRACKER_PATH = Path(__file__).resolve().parent.parent / "blog_topics" / "pending_approvals.jsonl"
APPROVAL_CHANNEL = "#blog-approvals"

# ── State management ──────────────────────────────────────────────

def _read_tracker() -> list[dict]:
    if not TRACKER_PATH.exists():
        return []
    entries = []
    for line in TRACKER_PATH.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries

def _write_tracker(entries: list[dict]) -> None:
    TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TRACKER_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

def _approval_id(slug: str) -> str:
    return f"{date.today().isoformat()}-{slug}"

# ── Commands ──────────────────────────────────────────────────────

def request(slug: str, title: str, stream: str, tier: str = "",
            mdx_path: str = "") -> str:
    """Register a draft for Discord approval. Returns approval_id."""
    entries = _read_tracker()
    if any(e.get("slug") == slug and e.get("status") == "pending" for e in entries):
        logger.info("Approval already pending for %s", slug)
    else:
        entry = {
            "approval_id": _approval_id(slug),
            "slug": slug,
            "title": title,
            "stream": stream,
            "tier": tier,
            "mdx_path": mdx_path,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
            "approved_at": None,
            "discord_message_id": None,
            "notes": "",
        }
        entries.append(entry)
        _write_tracker(entries)
        logger.info("Approval requested: %s (%s)", _approval_id(slug), title)
    return _approval_id(slug)


def pending() -> list[dict]:
    """Return all entries in pending state."""
    return [e for e in _read_tracker() if e.get("status") == "pending"]


def approve(slug: str) -> bool:
    """Mark a pending slug as approved. Returns False if not found."""
    entries = _read_tracker()
    for e in entries:
        if e.get("slug") == slug and e.get("status") == "pending":
            e["status"] = "approved"
            e["approved_at"] = datetime.utcnow().isoformat()
            _write_tracker(entries)
            logger.info("Approved: %s", slug)
            return True
    logger.warning("No pending approval found for slug: %s", slug)
    return False


def reject(slug: str, reason: str = "") -> None:
    entries = _read_tracker()
    for e in entries:
        if e.get("slug") == slug and e.get("status") == "pending":
            e["status"] = "rejected"
            e["notes"] = reason
            _write_tracker(entries)
            logger.info("Rejected: %s (%s)", slug, reason)
            return


def amend(slug: str, notes: str = "") -> None:
    """Mark an item for amendment (not yet rejected — sahil will edit and re-stage)."""
    entries = _read_tracker()
    for e in entries:
        if e.get("slug") == slug and e.get("status") == "pending":
            e["status"] = "amend"
            e["notes"] = notes
            _write_tracker(entries)
            logger.info("Amendment requested: %s", slug)
            return


def remove(slug: str) -> None:
    """Remove an entry entirely (after successful publish or full discard)."""
    entries = _read_tracker()
    entries = [e for e in entries if e.get("slug") != slug]
    _write_tracker(entries)


def summary(entry: dict) -> str:
    """Build a Discord-friendly approval request message."""
    lines = [
        "━━━ **📝  Draft Ready for Review** ━━━",
        f"**Title:** {entry.get('title', 'Untitled')}",
        f"**Stream:** `{entry.get('stream', '?')}`  **Tier:** `{entry.get('tier', '?')}`",
        f"**Slug:** `{entry.get('slug', '?')}`",
        f"**Approval ID:** `{entry.get('approval_id', '?')}`",
        f"**File:** `{entry.get('mdx_path', '?')}`",
        "",
        "**Reply in this thread:**",
        "  `!approve <slug>` — build + push to production",
        "  `!reject <slug> [reason]` — block, draft stays hidden",
        "  `!amend <slug> [notes]` — needs edits before approval",
    ]
    return "\n".join(lines)


def publish(slug: str) -> dict:
    """Build + push an approved slug. Clears from tracker on success."""
    from blog.blog_publisher import approve as publish_approve
    result = publish_approve(slug)
    if result.get("status") == "ok":
        remove(slug)
    return result


# ── Command parsing for Discord replies ──────────────────────────

def parse_discord_command(text: str) -> Optional[dict]:
    """Parse a Discord reply into a structured command.

    Accepted formats:
      !approve <slug>
      !reject <slug> [reason...]
      !amend <slug> [notes...]

    Returns dict with keys: {'command': str, 'slug': str, 'args': str} or None.
    """
    m = re.match(r"^!(approve|reject|amend)\s+(\S+)\s*(.*)", text.strip(), re.IGNORECASE)
    if not m:
        return None
    return {
        "command": m.group(1).lower(),
        "slug": m.group(2),
        "args": m.group(3).strip(),
    }


def handle_discord_command(text: str) -> dict:
    """Process a Discord command string and return a result dict.

    Returns:
        {"handled": True, "action": str, "slug": str, "message": str} or
        {"handled": False, "message": str}
    """
    cmd = parse_discord_command(text)
    if not cmd:
        return {"handled": False, "message": "Unknown command. Use `!approve <slug>`, `!reject <slug>`, or `!amend <slug>`."}

    slug = cmd["slug"]
    action = cmd["command"]

    if action == "approve":
        if approve(slug):
            result = publish(slug)
            if result.get("status") == "ok":
                return {
                    "handled": True, "action": "approved", "slug": slug,
                    "message": f"✅ **{slug}** approved and published (build + push OK).",
                }
            else:
                return {
                    "handled": True, "action": "build_failed", "slug": slug,
                    "message": f"⚠️ **{slug}** approved but **build failed** (rc={result.get('build_rc', '?')}). Draft staged, review locally.",
                }
        return {"handled": True, "action": "not_found", "slug": slug,
                "message": f"❌ No pending approval found for `{slug}`."}

    elif action == "reject":
        reject(slug, cmd["args"])
        return {"handled": True, "action": "rejected", "slug": slug,
                "message": f"❌ **{slug}** rejected."}

    elif action == "amend":
        amend(slug, cmd["args"])
        return {"handled": True, "action": "amended", "slug": slug,
                "message": f"✏️ **{slug}** marked for amendment. Edit the MDX locally and re-stage."}

    return {"handled": False, "message": "Unexpected error."}
