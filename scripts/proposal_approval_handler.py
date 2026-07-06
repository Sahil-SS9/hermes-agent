#!/usr/bin/env python3
"""
Proposal Approval Handler — polls #research-ops for !approve/!reject replies
to mashup review posts. Auto-files kanban triage tasks for approved proposals.
Token loaded from /home/kensei/.hermes/.env.
"""
import json, os, re, time, urllib.request, urllib.error, subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

TZ = timezone(timedelta(hours=1))
KENSEI_ID = "1506024421104812274"
# #research-ops channel ID
CHANNEL_ID = "1507448577784283367"
PROPOSALS_DIR = Path("/home/kensei/.hermes/runbooks/proposals")
STATE = Path("/home/kensei/.hermes/state/proposal-approval-state.json")


def get_token():
    dotenv = Path("/home/kensei/.hermes/.env")
    if dotenv.exists():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DISCORD_BOT_TOKEN="):
                key = line[len("DISCORD_BOT_TOKEN="):].strip().strip('"').strip("'")
                return key
    return os.environ.get("DISCORD_BOT_TOKEN", "")


def discord_api(endpoint, data=None):
    token = get_token()
    if not token:
        return {"_err": "no token"}
    url = f"https://discord.com/api/v10{endpoint}"
    hdrs = {"Authorization": f"Bot {token}", "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=hdrs, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return {"_skip": f"rate: {e.headers.get('Retry-After', 5)}"}
        return {"_err": f"HTTP {e.code}"}
    except Exception as e:
        return {"_err": str(type(e).__name__)}


def load_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, Exception):
            pass
    return {"approved": [], "rejected": [], "last_msg_id": None}


def save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=2), encoding="utf-8")


def parse_command(content):
    """Parse !approve <slug> or !reject <slug> from Discord message."""
    approve = re.search(r'!approve\s+([a-zA-Z0-9][-a-zA-Z0-9._]+)', content)
    if approve:
        return ("approve", approve.group(1).strip().rstrip('.'))
    reject = re.search(r'!reject\s+([a-zA-Z0-9][-a-zA-Z0-9._]+)', content)
    if reject:
        return ("reject", reject.group(1).strip().rstrip('.'))
    return (None, None)


def find_proposal_html(slug):
    """Find the most recent proposal HTML file containing this slug."""
    for f in sorted(PROPOSALS_DIR.glob("mashup-*.html"), reverse=True):
        text = f.read_text(encoding="utf-8", errors="replace")
        if f'id="{slug}"' in text or f'id="{slug}-' in text:
            return f, text
    return None, None


def extract_proposal(text, slug):
    """Extract the proposal section for a given slug from the HTML."""
    # Match from <section id="slug"> to </section>
    pattern = rf'(<section\s+id="{slug}"[^>]*>.*?</section>)'
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1)
    # Try partial match
    pattern = rf'(<section\s+id="{slug}-[^"]*"[^>]*>.*?</section>)'
    m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
    return m.group(1) if m else None


def extract_title(html_section):
    """Extract proposal title from HTML section."""
    m = re.search(r'<h2[^>]*>(.*?)</h2>', html_section, re.DOTALL)
    return m.group(1).strip() if m else "Proposal"


def extract_effort(html_section):
    """Extract effort estimate (S/M/L) from HTML section."""
    m = re.search(r'Effort:\s*(S|M|L|Small|Medium|Large)', html_section, re.IGNORECASE)
    if m:
        e = m.group(1)[0].upper()
        return {"S": "3", "M": "2", "L": "1"}.get(e, "2")
    return "2"


def create_kanban_triage(slug, title, html_section):
    """Create a kanban triage task for the approved proposal."""
    key = f"proposal-{slug}-{datetime.now(TZ).strftime('%Y-%m-%d')}"
    body = (
        f"Approved proposal from research mashup review.\n\n"
        f"---\n\n"
        f"{html_section}\n\n"
        f"---\n\n"
        f"Slug: `{slug}`\n"
        f"Approved via Discord by Sahil.\n"
        f"Route through Kensei Intake → Orchestrator → Octacon for build.\n"
    )
    priority = extract_effort(html_section)
    cmd = [
        "hermes", "kanban", "create", title,
        "--triage", "--priority", priority,
        "--body", body,
        "--idempotency-key", key,
        "--created-by", "proposal-approval-handler",
        "--tag", "proposal-approved",
        "--tag", "paper-mashup",
        "--json",
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        out = r.stdout.strip()
        if r.returncode == 0:
            try:
                return json.loads(out).get("id", out)
            except json.JSONDecodeError:
                return out
        else:
            return f"err: {r.stderr.strip()[:200]}"
    except Exception as e:
        return f"err: {e}"


def main():
    h = datetime.now(TZ).hour
    if h < 7 or h >= 22:
        return

    st = load_state()
    approved_ids = set(st.get("approved", []))
    rejected_ids = set(st.get("rejected", []))
    last_msg_id = st.get("last_msg_id")

    # Fetch recent messages
    msgs = discord_api(f"/channels/{CHANNEL_ID}/messages?limit=30")
    if not msgs or not isinstance(msgs, list):
        return

    new_last = last_msg_id
    actions = []

    for msg in msgs:
        mid = msg.get("id")
        if last_msg_id and int(mid) <= int(last_msg_id):
            continue

        # Must be a reply to a Kensei message
        ref = msg.get("message_reference")
        if not ref:
            continue
        ref_mid = ref.get("message_id")

        # Must be from Sahil (user, not bot)
        if msg.get("author", {}).get("bot", False):
            continue

        content = msg.get("content", "")
        action, slug = parse_command(content)
        if not action or not slug:
            continue

        # Verify the parent message is from Kensei (the mashup review)
        ref_msg = discord_api(f"/channels/{CHANNEL_ID}/messages/{ref_mid}")
        if not ref_msg or ref_msg.get("_err"):
            continue
        if ref_msg.get("author", {}).get("id") != KENSEI_ID:
            continue

        slug = slug.lower()
        if slug in approved_ids or slug in rejected_ids:
            continue

        # Find the proposal
        prop_file, prop_text = find_proposal_html(slug)
        if not prop_file:
            print(f"warn: slug '{slug}' not found in any proposal file")
            continue

        section = extract_proposal(prop_text, slug)
        if not section:
            print(f"warn: could not extract section for slug '{slug}'")
            continue

        title = extract_title(section)

        if action == "approve":
            tid = create_kanban_triage(slug, title, section)
            approved_ids.add(slug)
            actions.append(f"✓ approved: {slug} → kanban {tid}")
        elif action == "reject":
            rejected_ids.add(slug)
            actions.append(f"✗ rejected: {slug}")

        # Track highest message ID
        if new_last is None or int(mid) > int(new_last):
            new_last = mid

    if actions:
        st["approved"] = list(approved_ids)
        st["rejected"] = list(rejected_ids)
        st["last_msg_id"] = new_last
        save_state(st)
        for a in actions:
            print(a)


if __name__ == "__main__":
    main()
