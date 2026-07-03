"""Playwright-based X.com web poster for engagement scout.

Uses browser automation to perform quote tweets and replies on X.com,
bypassing the API Basic tier restriction on arbitrary interactions.

Auth flow:
  1. If saved session exists in STORAGE_DIR, loads it silently
  2. If not, launches headed browser via Xvfb, navigates to X.com login
  3. User logs in manually in the VNC-viewable browser window
  4. Session state saved for future headless use

Usage:
  python engagement_x_poster.py login          # First-time auth setup
  python engagement_x_poster.py qt <tweet_id> <text>  # Quote tweet
  python engagement_x_poster.py reply <tweet_id> <text>  # Reply
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

STORAGE_DIR = Path.home() / ".x-browser-state"
STORAGE_FILE = STORAGE_DIR / "auth_state.json"
XVFB_DISPLAY = ":99"


def _ensure_xvfb() -> bool:
    """Start Xvfb virtual display if not already running."""
    result = subprocess.run(
        ["pgrep", "-x", "Xvfb"], capture_output=True, text=True, timeout=5,
    )
    if result.returncode == 0:
        return True  # Already running

    subprocess.Popen(
        ["Xvfb", XVFB_DISPLAY, "-screen", "0", "1280x720x24"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # Wait for it to start
    for _ in range(10):
        r = subprocess.run(["pgrep", "-x", "Xvfb"], capture_output=True, timeout=3)
        if r.returncode == 0:
            return True
        time.sleep(0.5)
    return False


def _make_browser():
    """Create a Playwright browser instance with stealth + persistent context."""
    from playwright.sync_api import sync_playwright
    import playwright_stealth

    pw = sync_playwright().start()

    STORAGE_DIR.mkdir(parents=True, exist_ok=True)

    browser = pw.chromium.launch(
        headless=False,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
        ],
    )

    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        locale="en-GB",
        timezone_id="Europe/London",
        storage_state=STORAGE_FILE if STORAGE_FILE.exists() else None,
    )

    page = context.new_page()
    playwright_stealth.stealth_sync(page)
    return pw, browser, context, page


def login() -> bool:
    """First-time login to X.com. Opens a browser window via Xvfb, waits for you
    to log in manually, then saves the session for future headless use."""
    print("[xposter] Starting Xvfb virtual display...")
    _ensure_xvfb()
    os.environ["DISPLAY"] = XVFB_DISPLAY

    print("[xposter] Launching browser. Log into X.com in the window, then press Enter here.")
    pw, browser, context, page = _make_browser()

    page.goto("https://x.com/login", wait_until="networkidle")
    print(f"[xposter] Browser opened at {page.url}")
    print("[xposter] 👆 Complete login in the browser window (may need email→phone→password).")
    input("[xposter] Press Enter AFTER you've logged in successfully...")

    # Save auth state
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(STORAGE_FILE))
    print(f"[xposter] Session saved to {STORAGE_FILE}")

    # Verify we're logged in
    page.goto("https://x.com/home", wait_until="networkidle")
    if "login" in page.url.lower():
        print("[xposter] ❌ Still seeing login page. Session may not be valid.")
        browser.close()
        pw.stop()
        return False

    print(f"[xposter] ✅ Logged in. Current URL: {page.url}")
    browser.close()
    pw.stop()
    return True


def _ensure_logged_in(page) -> bool:
    """Check if logged in by navigating to home. Return True if ok."""
    page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)
    if "login" in page.url.lower():
        print("[xposter] ❌ Not logged in. Run 'login' command first.")
        return False
    return True


def quote_tweet(tweet_id: str, text: str) -> bool:
    """Quote tweet via X.com web UI."""
    import playwright_stealth

    print(f"[xposter] Quote tweeting {tweet_id}...")

    os.environ["DISPLAY"] = XVFB_DISPLAY
    if not STORAGE_FILE.exists():
        print("[xposter] ❌ No saved session. Run 'login' first.")
        return False

    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        locale="en-GB",
        storage_state=str(STORAGE_FILE),
    )
    page = context.new_page()
    playwright_stealth.stealth_sync(page)

    try:
        if not _ensure_logged_in(page):
            browser.close()
            pw.stop()
            return False

        # Navigate to the tweet
        tweet_url = f"https://x.com/i/web/status/{tweet_id}"
        page.goto(tweet_url, wait_until="networkidle", timeout=30000)
        time.sleep(2)

        # Click the "Repost" button (the quote/retweet button)
        # Try multiple selector strategies
        repost_btn = None
        selectors = [
            'button[aria-label="Repost"]',
            'button[data-testid="retweet"]',
            '//div[@role="button" and .//span[text()="Repost"]]',
            'button:has-text("Repost")',
            '[data-testid="retweetConfirm"]',
        ]
        for sel in selectors:
            try:
                if sel.startswith("//"):
                    btn = page.locator("xpath=" + sel).first
                else:
                    btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    repost_btn = btn
                    break
            except Exception:
                continue

        if not repost_btn:
            print("[xposter] ❌ Could not find Repost button")
            browser.close()
            pw.stop()
            return False

        repost_btn.click()
        time.sleep(1)

        # Click "Quote" from the dropdown
        quote_btn = None
        quote_selectors = [
            '//span[text()="Quote"]/ancestor::div[@role="menuitem"]',
            'div[role="menuitem"]:has-text("Quote")',
            'a:has-text("Quote")',
            '[data-testid="quote"]',
        ]
        for sel in quote_selectors:
            try:
                if sel.startswith("//"):
                    btn = page.locator("xpath=" + sel).first
                else:
                    btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    quote_btn = btn
                    break
            except Exception:
                continue

        if not quote_btn:
            print("[xposter] ❌ Could not find Quote option")
            browser.close()
            pw.stop()
            return False

        quote_btn.click()
        time.sleep(1.5)

        # Type the quote text into the composer
        text_area = None
        text_selectors = [
            'div[aria-label="Post text"]',
            '[data-testid="tweetTextarea_0"]',
            'div[role="textbox"]',
            'div[contenteditable="true"]',
        ]
        for sel in text_selectors:
            try:
                ta = page.locator(sel).first
                if ta.is_visible(timeout=2000):
                    text_area = ta
                    break
            except Exception:
                continue

        if not text_area:
            print("[xposter] ❌ Could not find text composer")
            browser.close()
            pw.stop()
            return False

        text_area.click()
        time.sleep(0.3)
        page.keyboard.type(text, delay=20)
        time.sleep(0.5)

        # Click the "Post" button
        post_btn = None
        post_selectors = [
            'button[data-testid="tweetButton"]',
            'button:has-text("Post")',
            'div[data-testid="tweetButton"]',
        ]
        for sel in post_selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    post_btn = btn
                    break
            except Exception:
                continue

        if not post_btn:
            print("[xposter] ❌ Could not find Post button")
            browser.close()
            pw.stop()
            return False

        post_btn.click()
        time.sleep(3)

        print(f"[xposter] ✅ Quote tweet posted for {tweet_id}")
        browser.close()
        pw.stop()
        return True

    except Exception as exc:
        print(f"[xposter] ❌ Error: {exc}")
        browser.close()
        pw.stop()
        return False


def reply_to_tweet(tweet_id: str, text: str) -> bool:
    """Reply to a tweet via X.com web UI."""
    import playwright_stealth

    print(f"[xposter] Replying to {tweet_id}...")

    os.environ["DISPLAY"] = XVFB_DISPLAY
    if not STORAGE_FILE.exists():
        print("[xposter] ❌ No saved session. Run 'login' first.")
        return False

    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        locale="en-GB",
        storage_state=str(STORAGE_FILE),
    )
    page = context.new_page()
    playwright_stealth.stealth_sync(page)

    try:
        if not _ensure_logged_in(page):
            browser.close()
            pw.stop()
            return False

        tweet_url = f"https://x.com/i/web/status/{tweet_id}"
        page.goto(tweet_url, wait_until="networkidle", timeout=30000)
        time.sleep(2)

        # Click reply button
        reply_btn = None
        reply_selectors = [
            'button[aria-label="Reply"]',
            'button[data-testid="reply"]',
            '//div[@role="button" and .//span[text()="Reply"]]',
            'button:has-text("Reply")',
        ]
        for sel in reply_selectors:
            try:
                if sel.startswith("//"):
                    btn = page.locator("xpath=" + sel).first
                else:
                    btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    reply_btn = btn
                    break
            except Exception:
                continue

        if not reply_btn:
            print("[xposter] ❌ Could not find Reply button")
            browser.close()
            pw.stop()
            return False

        reply_btn.click()
        time.sleep(1.5)

        # Type reply text
        text_area = None
        text_selectors = [
            'div[aria-label="Post text"]',
            '[data-testid="tweetTextarea_0"]',
            'div[role="textbox"]',
        ]
        for sel in text_selectors:
            try:
                ta = page.locator(sel).first
                if ta.is_visible(timeout=2000):
                    text_area = ta
                    break
            except Exception:
                continue

        if not text_area:
            print("[xposter] ❌ Could not find text composer")
            browser.close()
            pw.stop()
            return False

        text_area.click()
        time.sleep(0.3)
        page.keyboard.type(text, delay=20)
        time.sleep(0.5)

        # Click Reply button
        post_btn = None
        post_selectors = [
            'button[data-testid="tweetButton"]',
            'button:has-text("Reply")',
            '//span[text()="Reply"]/ancestor::button',
        ]
        for sel in post_selectors:
            try:
                if sel.startswith("//"):
                    btn = page.locator("xpath=" + sel).first
                else:
                    btn = page.locator(sel).first
                if btn.is_visible(timeout=2000):
                    post_btn = btn
                    break
            except Exception:
                continue

        if not post_btn:
            print("[xposter] ❌ Could not find post button")
            browser.close()
            pw.stop()
            return False

        post_btn.click()
        time.sleep(3)

        print(f"[xposter] ✅ Reply posted for {tweet_id}")
        browser.close()
        pw.stop()
        return True

    except Exception as exc:
        print(f"[xposter] ❌ Error: {exc}")
        browser.close()
        pw.stop()
        return False


def is_authenticated() -> bool:
    """Quick check if we have a saved session."""
    return STORAGE_FILE.exists()


# ── CLI ──

def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1]

    if command == "login":
        ok = login()
        print("✅ Login complete." if ok else "❌ Login failed.")
    elif command == "qt" and len(sys.argv) >= 4:
        ok = quote_tweet(sys.argv[2], sys.argv[3])
        print("✅ Quote posted." if ok else "❌ Quote failed.")
    elif command == "reply" and len(sys.argv) >= 4:
        ok = reply_to_tweet(sys.argv[2], sys.argv[3])
        print("✅ Reply posted." if ok else "❌ Reply failed.")
    elif command == "status":
        print(f"Session exists: {is_authenticated()}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
