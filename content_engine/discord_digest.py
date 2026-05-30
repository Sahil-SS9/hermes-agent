"""Deterministic Discord delivery of the content review, grouped by brand.

Posts the actual draft copy paired with its generated image so Sahil reviews the
real content (not an HTML file of path strings). Uses the Discord REST API
directly with ``DISCORD_BOT_TOKEN`` (the same bot the gateway already runs), so
delivery is deterministic and independent of the agent's formatting.
"""
import os
import time
from collections import OrderedDict
from datetime import datetime
from typing import List, Optional

import requests

DISCORD_API = "https://discord.com/api/v10"
DEFAULT_CHANNEL = "1507448580649123900"
CONTENT_LIMIT = 1900  # Discord hard limit is 2000; leave headroom.

# Stable brand display order for the digest.
BRAND_ORDER = [
    "matchdaymaestro", "plenishd", "coachos", "sahil_twitter", "sahil_linkedin",
]

_TYPE_BADGE = {"text": "📝", "text+image": "🖼️", "text+video": "🎬", "video": "🎬"}


def _token() -> str:
    return os.getenv("DISCORD_BOT_TOKEN", "").strip()


def _headers() -> dict:
    return {"Authorization": f"Bot {_token()}"}


def _channel_type(channel_id: str) -> Optional[int]:
    """Return the Discord channel type (15 = forum), or None on error."""
    try:
        r = requests.get(f"{DISCORD_API}/channels/{channel_id}", headers=_headers(), timeout=20)
        if r.status_code == 200:
            return r.json().get("type")
    except Exception as exc:  # noqa: BLE001
        print(f"[discord_digest] channel lookup failed: {exc}")
    return None


def _create_forum_thread(forum_id: str, name: str, content: str) -> Optional[str]:
    """Create a forum post (thread) and return its id (== the thread channel id)."""
    url = f"{DISCORD_API}/channels/{forum_id}/threads"
    body = {"name": name[:100], "message": {"content": (content or "​")[:CONTENT_LIMIT]}}
    for _ in range(4):
        try:
            r = requests.post(url, headers={**_headers(), "Content-Type": "application/json"},
                              json=body, timeout=30)
        except Exception as exc:  # noqa: BLE001
            print(f"[discord_digest] thread create error: {exc}")
            return None
        if r.status_code in (200, 201):
            return r.json().get("id")
        if r.status_code == 429:
            retry_after = float(r.json().get("retry_after", 1.0)) if r.content else 1.0
            time.sleep(min(retry_after + 0.25, 5.0))
            continue
        print(f"[discord_digest] thread create failed {r.status_code}: {r.text[:200]}")
        return None
    return None


def _post(channel_id: str, content: str, file_path: Optional[str] = None) -> bool:
    """Post one message (optionally with a single image attachment). Retries on 429."""
    url = f"{DISCORD_API}/channels/{channel_id}/messages"
    headers = _headers()
    content = (content or "").strip()[:CONTENT_LIMIT]

    for attempt in range(4):
        try:
            if file_path and os.path.exists(file_path):
                with open(file_path, "rb") as fh:
                    files = {"files[0]": (os.path.basename(file_path), fh, "image/png")}
                    resp = requests.post(
                        url, headers=headers, data={"content": content},
                        files=files, timeout=60,
                    )
            else:
                resp = requests.post(
                    url, headers={**headers, "Content-Type": "application/json"},
                    json={"content": content or "​"}, timeout=30,
                )
        except Exception as exc:  # noqa: BLE001
            print(f"[discord_digest] post error: {exc}")
            return False

        if resp.status_code in (200, 201):
            return True
        if resp.status_code == 429:
            retry_after = float(resp.json().get("retry_after", 1.0)) if resp.content else 1.0
            time.sleep(min(retry_after + 0.25, 5.0))
            continue
        print(f"[discord_digest] post failed {resp.status_code}: {resp.text[:200]}")
        return False
    return False


def _group_by_brand(drafts: List[dict]) -> "OrderedDict[str, list]":
    groups: "OrderedDict[str, list]" = OrderedDict()
    # Seed known brands in canonical order, then any extras as they appear.
    for b in BRAND_ORDER:
        groups[b] = []
    for d in drafts:
        groups.setdefault(d.get("brand", "other"), []).append(d)
    return OrderedDict((b, items) for b, items in groups.items() if items)


def deliver_discord_digest(drafts: List[dict], channel_id: str = DEFAULT_CHANNEL) -> bool:
    """Deliver the review grouped by brand. Skips drafts with empty body_text."""
    if not _token():
        print("[discord_digest] DISCORD_BOT_TOKEN not set — cannot deliver.")
        return False

    drafts = [d for d in drafts if (d.get("body_text") or "").strip()]
    if not drafts:
        print("[discord_digest] no non-empty drafts to deliver.")
        return False

    groups = _group_by_brand(drafts)
    counts = ", ".join(f"{b}={len(items)}" for b, items in groups.items())
    stamp = datetime.now().strftime("%d/%m/%y %H:%M")
    header = f"📝 **KENSEI Content Review** · {stamp} · {len(drafts)} drafts\nCoverage: {counts}"

    # Forum channels (type 15) reject direct messages: open a daily review thread
    # and post the cards inside it. Text channels post directly.
    target = channel_id
    if _channel_type(channel_id) == 15:
        thread_id = _create_forum_thread(channel_id, f"Content Review · {stamp}", header)
        if not thread_id:
            print("[discord_digest] could not open forum thread.")
            return False
        target = thread_id
    else:
        _post(channel_id, header)

    delivered = 0
    for brand, items in groups.items():
        _post(target, f"──────── **{brand}** · {len(items)} ────────")
        time.sleep(0.4)
        for i, d in enumerate(items, 1):
            ct = d.get("content_type", "text")
            badge = _TYPE_BADGE.get(ct, "📝")
            note = "  ·  🎬 _video generates on approval_" if "video" in ct else ""
            card = f"{badge} **{i}/{len(items)}** `{ct}` · {d.get('platform','')}  ·  `{d.get('id','')}`{note}"
            body = (d.get("body_text") or "").strip()
            img = d.get("ai_image_path") if "image" in ct else None
            ok = _post(target, f"{card}\n{body}", file_path=img)
            delivered += 1 if ok else 0
            time.sleep(0.6)  # stay under Discord channel rate limits

    print(f"[discord_digest] delivered {delivered}/{len(drafts)} drafts to {target}")
    return delivered > 0
