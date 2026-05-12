"""Telegram digest delivery — mailbox-format aligned."""
import json as _json
import os
from datetime import datetime
from typing import List, Optional

try:
    import requests
except ImportError:
    requests = None

# Default to Topic 22 "Content & Social" in Kensei Workspace
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CONTENT_CHAT_ID", "-1003922682700")
TELEGRAM_TOPIC_ID = os.getenv("TELEGRAM_CONTENT_TOPIC_ID", "22")


def _approval_keyboard(draft_id: str) -> dict:
    """Inline keyboard for per-draft approve/reject/view."""
    return {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"approve_draft|{draft_id}"},
                {"text": "❌ Reject",  "callback_data": f"reject_draft|{draft_id}"},
                {"text": "📄 View",    "callback_data": f"view_draft|{draft_id}"},
            ]
        ]
    }


def _send_payload(endpoint: str, payload: dict) -> bool:
    if not TELEGRAM_BOT_TOKEN or requests is None:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{endpoint}"
    try:
        r = requests.post(url, json=payload, timeout=30)
        return r.status_code == 200
    except Exception:
        return False


def _base_payload() -> dict:
    base = {"chat_id": TELEGRAM_CHAT_ID, "parse_mode": "HTML"}
    if TELEGRAM_TOPIC_ID:
        base["message_thread_id"] = int(TELEGRAM_TOPIC_ID)
    return base


def send_message(text: str, draft_id: Optional[str] = None) -> bool:
    payload = _base_payload()
    payload["text"] = text
    if draft_id:
        payload["reply_markup"] = _approval_keyboard(draft_id)
    return _send_payload("sendMessage", payload)


def send_photo(photo_path: str, caption: str, draft_id: Optional[str] = None) -> bool:
    if not TELEGRAM_BOT_TOKEN or requests is None:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        payload = _base_payload()
        payload["caption"] = caption
        if draft_id:
            payload["reply_markup"] = _json.dumps(_approval_keyboard(draft_id))
        with open(photo_path, "rb") as f:
            r = requests.post(url, data=payload, files={"photo": f}, timeout=60)
        return r.status_code == 200
    except Exception:
        return False


def send_document(doc_path: str, caption: str = "") -> bool:
    if not TELEGRAM_BOT_TOKEN or requests is None:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        payload = _base_payload()
        payload["caption"] = caption
        payload["parse_mode"] = "HTML"
        with open(doc_path, "rb") as f:
            r = requests.post(url, data=payload, files={"document": f}, timeout=60)
        return r.status_code == 200
    except Exception:
        return False


def _brand_emoji(brand: str) -> str:
    """Visual anchor per brand."""
    mapping = {
        "matchdaymaestro": "⚽",
        "plenishd": "🍽️",
        "coachos": "📋",
        "sahil_linkedin": "💼",
        "sahil_twitter": "🧵",
    }
    return mapping.get(brand.lower(), "📝")


def _format_draft(d: dict) -> str:
    """Format a single draft entry for the digest."""
    body = d.get("body_text", "")
    brand = d.get("brand", "").replace("_", " ").title()
    brand_emoji = _brand_emoji(d.get("brand", ""))
    plat = d.get("platform", "twitter")
    pillar = d.get("pillar", "")
    draft_id = d["id"]

    # Truncate body to 280 chars (one Tweet length) with clean break
    preview = body[:280] if len(body) <= 280 else body[:277] + "..."

    msg = (
        f"{brand_emoji} <b>{brand}</b> | <code>{plat}</code>\n"
        f"Pillar: {pillar}\n"
        f"ID: <code>{draft_id}</code>\n\n"
        f"<i>{preview}</i>"
    )
    return msg


def deliver_digest(drafts: List[dict]) -> bool:
    """Send a Telegram digest of drafts for approval. Mailbox-format aligned."""
    if not drafts:
        return False

    today = datetime.now().strftime("%a %d %b")
    total = len(drafts)

    # Count per brand for the header
    brand_counts = {}
    for d in drafts:
        b = d.get("brand", "unknown").replace("_", " ").title()
        brand_counts[b] = brand_counts.get(b, 0) + 1

    brand_summary = " ".join(
        f"{_brand_emoji(b.lower().replace(' ', '_'))} {b}: {c}"
        for b, c in sorted(brand_counts.items())
    )

    header = (
        f"<b>⚡ KENSEI Content Digest</b>\n"
        f"{today}  |  {total} draft(s) pending\n\n"
        f"{brand_summary}\n\n"
        f"Tap ✅ to approve, ❌ to reject, or 📄 to view full text."
    )
    send_message(header)

    for d in drafts:
        msg = _format_draft(d)
        draft_id = d["id"]
        visual = d.get("visual_path")

        if visual and os.path.exists(visual):
            send_photo(visual, msg, draft_id=draft_id)
        else:
            send_message(msg, draft_id=draft_id)

    footer = (
        f"<b>{total} draft(s) above</b> — review complete?\n"
        f"Buttons above are live: ✅ approve, ❌ reject, 📄 view full text."
    )
    send_message(footer)
    return True
