#!/usr/bin/env python3
"""
Misa-Misa Auto-Join v4 — REST-only sidecar.
No discord.py. No WebSocket conflict with Hermes gateway.
Polls Discord REST API for user VC status, then posts a text message
in #general to trigger the Hermes gateway's /voice join handler.
"""
import time, requests, os, sys
from pathlib import Path

USER_ID = "797682085224513547"
GUILD_ID = "1506021204363051249"
TEXT_CHANNEL_ID = "1506021205797507266"
BOT_TOKEN = "MTUwNjAyNDQyMTEwNDgxMjI3NA.GbJiwB.DZmBXSSltowpePLQ6NREsQtDn83BrseiocQ0Mg"

PID_FILE = Path("/tmp/misa-auto-join.pid")
LOG_FILE = Path("/tmp/misa-auto-join.log")
HEADERS = {"Authorization": f"Bot {BOT_TOKEN}", "Content-Type": "application/json"}


def log(msg):
    ts = time.strftime("%d/%m/%y %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


def get_user_vc():
    """Returns channel_id (string) if user is in a VC, None otherwise."""
    try:
        r = requests.get(
            f"https://discord.com/api/v10/guilds/{GUILD_ID}/voice-states/{USER_ID}",
            headers=HEADERS, timeout=5
        )
        return r.json().get("channel_id") if r.status_code == 200 else None
    except Exception as e:
        log(f"VC check error: {e}")
        return None


def get_bot_channels():
    """
    Returns set of channel IDs the bot can see.
    We check if the bot can access the voice channel the user is in.
    """
    try:
        # Get bot user ID
        r = requests.get("https://discord.com/api/v10/users/@me", headers=HEADERS, timeout=5)
        if r.status_code != 200:
            return set()
        
        # Check if bot is in a voice channel via its own voice state
        bot_id = "1506024421104812274"
        r2 = requests.get(
            f"https://discord.com/api/v10/guilds/{GUILD_ID}/voice-states/{bot_id}",
            headers=HEADERS, timeout=5
        )
        if r2.status_code == 200:
            cid = r2.json().get("channel_id")
            return {cid} if cid else set()
        return set()
    except Exception as e:
        log(f"Bot VC check error: {e}")
        return set()


def send_command(cmd):
    """Send a message to #general text channel."""
    try:
        r = requests.post(
            f"https://discord.com/api/v10/channels/{TEXT_CHANNEL_ID}/messages",
            json={"content": cmd},
            headers=HEADERS,
            timeout=10
        )
        if r.status_code == 200:
            return r.json().get("id")  # message ID
        else:
            log(f"Send msg failed: {r.status_code} {r.text[:100]}")
            return None
    except Exception as e:
        log(f"Send msg error: {e}")
        return None


def main_loop():
    log("Misa-Misa Auto-Join v4 starting (REST-only)")
    log(f"Watching user {USER_ID}")

    last_user_vc = None
    join_sent = False  # prevents spamming /voice join every 10s
    idle_count = 0

    while True:
        try:
            user_vc = get_user_vc()
            bot_vcs = get_bot_channels()

            user_in = user_vc is not None
            bot_in = len(bot_vcs) > 0

            # User entered a VC and bot isn't there
            if user_in and not bot_in and not join_sent:
                log(f"User in VC {user_vc[:15]}, sending /voice join")
                msg_id = send_command("/voice join")
                if msg_id:
                    log(f"Sent /voice join (msg: {msg_id[:10]})")
                    join_sent = True
                    idle_count = 0
                else:
                    log("Failed to send /voice join")

            # User left VC, reset flag
            elif not user_in:
                join_sent = False

            # Check if the command actually worked — bot should be in VC after ~20s
            if join_sent:
                idle_count += 1
                if idle_count >= 3:  # ~30s have passed
                    # Re-check bot VC status
                    bot_vcs = get_bot_channels()
                    if len(bot_vcs) > 0:
                        log(f"Bot confirmed in VC: {bot_vcs}")
                        join_sent = False
                        idle_count = 0
                    else:
                        log("Bot still not in VC, re-sending")
                        send_command("/voice join")
                        idle_count = 0

            # Also send /voice leave if bot is alone in VC (user left while we weren't looking)
            if bot_in and not user_in:
                log("Bot in VC but user left — sending /voice leave")
                send_command("/voice leave")
                join_sent = False
                idle_count = 0

            time.sleep(12)

        except KeyboardInterrupt:
            log("Shutting down")
            break
        except Exception as e:
            log(f"Error: {e}")
            time.sleep(30)


if __name__ == "__main__":
    PID_FILE.write_text(str(os.getpid()))
    main_loop()
