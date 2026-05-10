"""Telegram digest delivery."""
import os
from datetime import datetime
from typing import List

try:
    import requests
except ImportError:
    requests = None

# Default to Topic 22 "Content & Social" in Kensei Workspace
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CONTENT_CHAT_ID", "-1003922682700")
TELEGRAM_TOPIC_ID = os.getenv("TELEGRAM_CONTENT_TOPIC_ID", "22")


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


def send_message(text: str) -> bool:
    payload = _base_payload()
    payload["text"] = text
    return _send_payload("sendMessage", payload)


def send_photo(photo_path: str, caption: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or requests is None:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        payload = _base_payload()
        payload["caption"] = caption
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


def deliver_digest(drafts: List[dict]) -> bool:
    """Send a Telegram digest of drafts for approval to the configured topic."""
    if not drafts:
        return False

    today = datetime.now().strftime("%a %d %b")

    header = (
        f"<b>⚡ KENSEI Content Digest</b>\n"
        f"{today}  |  {len(drafts)} draft(s) pending\n\n"
        f"Reply <code>A:&lt;draft_id&gt;</code> to approve  |  "
        f"<code>R:&lt;draft_id&gt;</code> to reject"
    )
    send_message(header)

    for d in drafts:
        body = d["body_text"]
        brand_display = d.get("brand", "").replace("_", " ").title()
        plat = d.get("platform", "twitter")
        draft_id = d["id"]

        msg = (
            f"<b>Brand:</b> {brand_display}\n"
            f"<b>Platform:</b> {plat}\n"
            f"<b>ID:</b> <code>{draft_id}</code>\n"
            f"<b>Pillar:</b> {d.get('pillar', '')}\n\n"
            f"<i>{body[:400]}{'...' if len(body) > 400 else ''}</i>\n\n"
            f"<code>A:{draft_id}</code>  ✅  |  <code>R:{draft_id}</code>  ❌"
        )

        visual = d.get("visual_path")
        if visual and os.path.exists(visual):
            send_photo(visual, msg)
        else:
            send_message(msg)

    footer = (
        "<b>Quick actions:</b>\n"
        + "\n".join([f"<code>A:{d['id']}</code>" for d in drafts])
    )
    send_message(footer)
    return True
