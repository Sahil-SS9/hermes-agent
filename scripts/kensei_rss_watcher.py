#!/usr/bin/env python3
"""KENSEI RSS Watcher — lightweight blog/feed monitor using only stdlib.

No external dependencies. Uses urllib + xml.etree.ElementTree for RSS/Atom parsing.
Tracks seen articles in ~/.hermes/runbooks/rss-watcher/state.json.

Usage:
    python3 kensei_rss_watcher.py scan          # scan all feeds
    python3 kensei_rss_watcher.py list          # list tracked feeds
    python3 kensei_rss_watcher.py add <name> <url>   # add a feed
    python3 kensei_rss_watcher.py remove <name>      # remove a feed
    python3 kensei_rss_watcher.py articles             # list unread articles
    python3 kensei_rss_watcher.py read <id>            # mark article read
"""

import os
import sys
import json
import hashlib
import urllib.request
from pathlib import Path
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

STATE_DIR = Path.home() / ".hermes" / "runbooks" / "rss-watcher"
STATE_FILE = STATE_DIR / "state.json"
CONFIG_FILE = STATE_DIR / "feeds.json"

# ─── Setup ───────────────────────────────────────────────────────────

STATE_DIR.mkdir(parents=True, exist_ok=True)

if not CONFIG_FILE.exists():
    # Default feeds: AI/tech news relevant to Sahil's stack and job hunt
    DEFAULT_FEEDS = {
        "hn-ai": {"name": "Hacker News AI", "url": "https://hnrss.org/newest?q=AI+artificial+intelligence", "enabled": True},
        "hn-react-native": {"name": "HN React Native", "url": "https://hnrss.org/newest?q=react+native+expo", "enabled": True},
        "hn-product-manager": {"name": "HN Product Management", "url": "https://hnrss.org/newest?q=product+manager+PM", "enabled": True},
        "expo-blog": {"name": "Expo Blog", "url": "https://blog.expo.dev/feed", "enabled": True},
        "react-native-blog": {"name": "React Native Blog", "url": "https://reactnative.dev/blog/rss.xml", "enabled": True},
        "convex-blog": {"name": "Convex Blog", "url": "https://news.convex.dev/rss/", "enabled": True},
        "supabase-blog": {"name": "Supabase Blog", "url": "https://supabase.com/rss.xml", "enabled": True},
        "nousresearch": {"name": "Nous Research", "url": "https://nousresearch.com/rss.xml", "enabled": False},
    }
    CONFIG_FILE.write_text(json.dumps(DEFAULT_FEEDS, indent=2), encoding="utf-8")

if not STATE_FILE.exists():
    STATE_FILE.write_text(json.dumps({"seen": {}, "articles": {}}, indent=2), encoding="utf-8")


def load_config() -> dict:
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def load_state() -> dict:
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")


# ─── Feed Parsing ────────────────────────────────────────────────────

NS_MAP = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def _ns(tag: str) -> str:
    if ":" in tag:
        prefix, name = tag.split(":", 1)
        return f"{{{NS_MAP.get(prefix, '')}}}{name}"
    return tag


def fetch_feed(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "KENSEI-RSS-Watcher/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def parse_rss(xml: str, feed_id: str) -> list[dict]:
    root = ET.fromstring(xml)
    articles = []
    
    # RSS 2.0
    if root.tag == "rss" or root.tag.endswith("rss"):
        channel = root.find("channel")
        if channel is None:
            return articles
        feed_title = channel.findtext("title", feed_id)
        for item in channel.findall("item"):
            title = item.findtext("title", "Untitled").strip()
            link = item.findtext("link", "").strip()
            pub_date = item.findtext("pubDate", "")
            desc = item.findtext("description", "")
            article_id = hashlib.sha256((link or title).encode()).hexdigest()[:16]
            articles.append({
                "id": article_id,
                "title": title,
                "url": link,
                "published": pub_date,
                "summary": desc[:200] if desc else "",
                "feed": feed_id,
                "feed_title": feed_title,
            })
    
    # Atom
    elif root.tag == _ns("atom:feed") or root.tag.endswith("feed"):
        feed_title = root.findtext(_ns("atom:title"), feed_id)
        for entry in root.findall(_ns("atom:entry")):
            title = entry.findtext(_ns("atom:title"), "Untitled").strip()
            link_el = entry.find(_ns("atom:link"))
            link = link_el.get("href", "").strip() if link_el is not None else ""
            pub_date = entry.findtext(_ns("atom:updated"), "")
            summary = entry.findtext(_ns("atom:summary"), "")
            article_id = hashlib.sha256((link or title).encode()).hexdigest()[:16]
            articles.append({
                "id": article_id,
                "title": title,
                "url": link,
                "published": pub_date,
                "summary": summary[:200] if summary else "",
                "feed": feed_id,
                "feed_title": feed_title,
            })
    
    return articles


# ─── Commands ────────────────────────────────────────────────────────

def cmd_scan() -> None:
    config = load_config()
    state = load_state()
    new_count = 0
    
    for feed_id, feed in config.items():
        if not feed.get("enabled", True):
            continue
        try:
            xml = fetch_feed(feed["url"])
            articles = parse_rss(xml, feed_id)
        except Exception as exc:
            print(f"  ⚠️  {feed['name']}: {exc}")
            continue
        
        feed_new = 0
        for a in articles:
            key = f"{feed_id}:{a['id']}"
            if key not in state["seen"]:
                state["seen"][key] = datetime.now(timezone.utc).isoformat()
                state["articles"][key] = a
                feed_new += 1
                new_count += 1
        
        if feed_new > 0:
            print(f"  📰 {feed['name']}: {feed_new} new")
    
    save_state(state)
    print(f"\n📊 Total new: {new_count}")


def cmd_list() -> None:
    config = load_config()
    print("Tracked feeds:")
    for fid, f in config.items():
        status = "✅" if f.get("enabled") else "❌"
        print(f"  {status} {f['name']} | {f['url']}")


def cmd_articles() -> None:
    state = load_state()
    config = load_config()
    unread = []
    for key, a in state["articles"].items():
        if key not in state.get("read", {}):
            unread.append(a)
    
    if not unread:
        print("No unread articles.")
        return
    
    print(f"Unread articles ({len(unread)}):\n")
    for i, a in enumerate(unread[:30], 1):
        feed_name = config.get(a["feed"], {}).get("name", a["feed"])
        print(f"  [{i}] {a['title']}")
        print(f"       Feed: {feed_name} | {a['published'][:10] if a['published'] else '?'}")
        print(f"       {a['url']}")
        if a["summary"]:
            print(f"       {a['summary'][:100]}...")
        print()


def cmd_read(idx_str: str) -> None:
    state = load_state()
    unread = [k for k in state["articles"] if k not in state.get("read", {})]
    try:
        idx = int(idx_str) - 1
        key = unread[idx]
    except (ValueError, IndexError):
        print("Invalid article index.")
        return
    
    state.setdefault("read", {})[key] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    a = state["articles"][key]
    print(f"Marked read: {a['title'][:60]}")


def cmd_add(name: str, url: str) -> None:
    config = load_config()
    slug = name.lower().replace(" ", "-")[:30]
    config[slug] = {"name": name, "url": url, "enabled": True}
    CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"Added feed: {name}")


def cmd_remove(name: str) -> None:
    config = load_config()
    for slug, f in list(config.items()):
        if f["name"].lower() == name.lower() or slug == name:
            del config[slug]
            CONFIG_FILE.write_text(json.dumps(config, indent=2), encoding="utf-8")
            print(f"Removed: {f['name']}")
            return
    print("Feed not found.")


# ─── Main ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "scan":
        cmd_scan()
    elif args[0] == "list":
        cmd_list()
    elif args[0] == "articles":
        cmd_articles()
    elif args[0] == "read" and len(args) > 1:
        cmd_read(args[1])
    elif args[0] == "add" and len(args) > 2:
        cmd_add(args[1], args[2])
    elif args[0] == "remove" and len(args) > 1:
        cmd_remove(args[1])
    else:
        print(__doc__)
