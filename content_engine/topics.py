"""Topic collector: football fixtures + brand topic banks + activity signals."""

import json
import random
import sys
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any

try:
    import requests
except ImportError:
    requests = None  # type: ignore

from config import FOOTBALL_API_BASE

# Activity collector — lazy loaded for sahil_twitter / sahil_linkedin
_ACTIVITY_COLLECTOR = None
_ACTIVITY_MARKER = None


def _load_activity():
    global _ACTIVITY_COLLECTOR, _ACTIVITY_MARKER
    if _ACTIVITY_COLLECTOR is not None:
        return True
    try:
        from activity_collector import collect_all as _ca, mark_signals_used as _msu
        _ACTIVITY_COLLECTOR = _ca
        _ACTIVITY_MARKER = _msu
        return True
    except ImportError:
        return False


TOPIC_BANKS: Dict[str, List[Dict]] = {
    "matchdaymaestro": [
        {"pillar": "live_predictions", "topic": "Next weekend's big fixtures"},
        {"pillar": "game_modes", "topic": "Strike501 daily challenge"},
        {"pillar": "friend_battles", "topic": "1v1 battle invitation"},
        {"pillar": "progression", "topic": "RPG level-up milestone"},
        {"pillar": "football_beat", "topic": "Weekly stat mic-drop"},
        {"pillar": "live_predictions", "topic": "Derby day prediction prompt"},
        {"pillar": "game_modes", "topic": "PlayerCombination T9 puzzle reveal"},
        {"pillar": "friend_battles", "topic": "Mini-league standings update"},
    ],
    "plenishd": [
        {"pillar": "product", "topic": "UK supermarket price comparison"},
        {"pillar": "voice", "topic": "Voice-first inventory update"},
        {"pillar": "kitchen", "topic": "Leftover-to-recipe hack"},
        {"pillar": "shopping", "topic": "Smart shopping list build"},
        {"pillar": "launch", "topic": "Pre-launch sign-up"},
        {"pillar": "product", "topic": "Fridge-scan to meal plan"},
        {"pillar": "kitchen", "topic": "Waste-less Wednesday tip"},
    ],
    "sahil_twitter": [
        {"pillar": "build_in_public", "topic": "Weekly indie dev update"},
        {"pillar": "ai_tools", "topic": "Claude Code workflow tip"},
        {"pillar": "sly_product", "topic": "Built-this-because problem"},
        {"pillar": "football", "topic": "Man United match reaction"},
        {"pillar": "wry", "topic": "AI industry observation"},
        {"pillar": "build_in_public", "topic": "App milestone screenshot"},
        {"pillar": "ai_tools", "topic": "Agentic loop pattern"},
        {"pillar": "tutorial", "topic": "How-to: content pipeline setup"},
        {"pillar": "tutorial", "topic": "Framework: feature decision guide"},
        {"pillar": "data", "topic": "Solo dev time breakdown"},
        {"pillar": "data", "topic": "Content output before vs after automation"},
        {"pillar": "promotion", "topic": "Plenishd problem-solution story"},
        {"pillar": "promotion", "topic": "MatchdayMaestro feature origin story"},
    ],
    "sahil_linkedin": [
        {"pillar": "pm_thought", "topic": "Context over models thesis"},
        {"pillar": "indie", "topic": "PM to indie builder journey"},
        {"pillar": "ai", "topic": "Enterprise AI adoption pattern"},
        {"pillar": "leadership", "topic": "Team velocity insight"},
        {"pillar": "pm_thought", "topic": "RAG chatbot case study"},
        {"pillar": "indie", "topic": "Four apps lesson learn"},
        {"pillar": "ai", "topic": "Vibe coding production reality"},
    ],
    "coachos": [
        {"pillar": "session_plan", "topic": "Grassroots drill of the week"},
        {"pillar": "coach_life", "topic": "Managing volunteers and parents"},
        {"pillar": "player_dev", "topic": "Age-appropriate tactics"},
        {"pillar": "community", "topic": "CoachOS feature walkthrough"},
        {"pillar": "session_plan", "topic": "Warm-up routine template"},
        {"pillar": "player_dev", "topic": "Tactics teaching for under-10s"},
    ],
}

# Map signal types to content pillars for LinkedIn (different from Twitter)
LINKEDIN_SIGNAL_MAP = {
    "github_push": "indie",
    "hermes_pr": "indie",
    "hermes_skill": "ai",
    "research_tool": "ai",
    "research_signal": "pm_thought",
    "gitradar_repo": "ai",
    "architecture": "ai",
}


def _signal_to_topic(signal: dict, platform: str) -> Dict[str, Any]:
    """Convert an activity signal into a topic dict with activity_data metadata."""
    variables = signal["variables"]

    # Build a human-readable topic label based on signal type
    signal_type = signal["signal_type"]
    if signal_type == "github_push":
        topic = f"Just pushed {variables['repo_name']}"
    elif signal_type == "hermes_pr":
        topic = f"Submitted: {variables['pr_title']}"
    elif signal_type == "hermes_skill":
        topic = f"New skill: {variables['skill_name']}"
    elif signal_type == "research_tool":
        topic = f"Tool: {variables['title']}"
    elif signal_type == "research_signal":
        topic = f"Signal: {variables['title']}"
    elif signal_type == "gitradar_repo":
        topic = f"Radar: {variables['repo_name']}"
    elif signal_type == "architecture":
        topic = f"Arch: {variables['topic_label']}"
    else:
        topic = f"Update: {signal_type}"

    # LinkedIn uses different pillar mapping than Twitter's direct pillar
    if platform == "linkedin":
        pillar = LINKEDIN_SIGNAL_MAP.get(signal_type, "indie")
    else:
        pillar = signal["pillar"]

    return {
        "id": str(uuid.uuid4())[:8],
        "pillar": pillar,
        "topic": topic,
        "activity_data": {
            "signal_type": signal_type,
            "variables": variables,
            "signal_id": signal["signal_id"],
        },
    }


def get_topics(brand: str, count: int = 6) -> List[Dict]:
    """Return N topic objects, mixing real activity for personal brands with static banks."""

    # ── Personal brands: mix real activity + static fallback ──
    if brand in ("sahil_twitter", "sahil_linkedin") and _load_activity():
        platform = "twitter" if brand == "sahil_twitter" else "linkedin"
        try:
            result = _ACTIVITY_COLLECTOR()
            signals = result["signals"]
            state = result["state"]
        except Exception as e:
            print(f"[topics] activity_collector failed: {e}", file=sys.stderr)
            signals = []
            state = {"used_signals": []}

        topics: List[Dict] = []
        used_ids: List[str] = []

        # Convert signals to topic objects up to count
        for signal in signals[:count]:
            topic = _signal_to_topic(signal, platform)
            topics.append(topic)
            used_ids.append(signal["signal_id"])

        # Mark as used so they don't repeat
        if used_ids and state.get("used_signals") is not None:
            try:
                _ACTIVITY_MARKER(state, used_ids)
            except Exception as e:
                print(f"[topics] mark_signals_used failed: {e}", file=sys.stderr)

        # Fill remaining slots with static topics if needed
        if len(topics) < count:
            bank = TOPIC_BANKS.get(brand, [])
            if bank:
                for t in random.sample(bank, min(count - len(topics), len(bank))):
                    topics.append({"id": str(uuid.uuid4())[:8], **t})

        return topics

    # ── MatchdayMaestro: football fixtures + static topics ──
    if brand == "matchdaymaestro":
        topics = []
        fixtures = fetch_fixtures()
        if fixtures:
            for f in fixtures[:count]:
                topics.append({
                    "id": str(uuid.uuid4())[:8],
                    "pillar": "live_predictions",
                    "topic": f"{f['home']} vs {f['away']} — {f['date']}",
                    "fixture": f,
                })
        if len(topics) < count:
            needed = count - len(topics)
            for t in random.sample(TOPIC_BANKS.get(brand, []), min(needed, len(TOPIC_BANKS.get(brand, [])))):
                topics.append({"id": str(uuid.uuid4())[:8], **t})
        return topics

    # ── Other brands: pure static topics ──
    topics = []
    bank = TOPIC_BANKS.get(brand, [])
    if bank:
        for t in random.sample(bank, min(count, len(bank))):
            topics.append({"id": str(uuid.uuid4())[:8], **t})
    return topics


def fetch_fixtures() -> List[Dict]:
    """Try free football-data.org for Premier League next matches.

    Returns [] on any failure; logs the failure mode to stderr so a silent
    "no fixtures returned" doesn't get mistaken for "API is fine, just no matches".
    """
    if requests is None:
        print("fetch_fixtures: requests not installed", file=sys.stderr)
        return []
    try:
        url = f"{FOOTBALL_API_BASE}/competitions/PL/matches?status=SCHEDULED&matchday=38"
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            print(f"fetch_fixtures: HTTP {resp.status_code}", file=sys.stderr)
            return []
        data = resp.json()
        matches = []
        for m in data.get("matches", [])[:6]:
            matches.append({
                "home": m["homeTeam"]["shortName"],
                "away": m["awayTeam"]["shortName"],
                "date": m["utcDate"][:10],
                "time": m["utcDate"][11:16],
            })
        return matches
    except (requests.RequestException, ValueError, KeyError) as exc:
        print(f"fetch_fixtures: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []