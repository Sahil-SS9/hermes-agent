"""Topic collector: football fixtures + brand topic banks."""
import json
import random
import uuid
from datetime import datetime, timedelta
from typing import List, Dict

try:
    import requests
except ImportError:
    requests = None  # type: ignore

from config import FOOTBALL_API_BASE

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
    ],
    "sahil_linkedin": [
        {"pillar": "pm_thought", "topic": "Context over models thesis"},
        {"pillar": "indie", "topic": "PM to indie builder journey"},
        {"pillar": "ai", "topic": "Enterprise AI adoption pattern"},
        {"pillar": "leadership", "topic": "Team velocity insight"},
        {"pillar": "pm_thought", "topic": "RAG chatbot case study"},
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


def fetch_fixtures() -> List[Dict]:
    """Try free football-data.org for Premier League next matches."""
    if requests is None:
        return []
    try:
        url = f"{FOOTBALL_API_BASE}/competitions/PL/matches?status=SCHEDULED&matchday=38"
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
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
    except Exception:
        return []


def get_topics(brand: str, count: int = 3) -> List[Dict]:
    """Return N topic objects, mixing football fixtures for MMaestro and static banks for others."""
    topics: List[Dict] = []
    if brand == "matchdaymaestro":
        fixtures = fetch_fixtures()
        if fixtures:
            for f in fixtures[:count]:
                topics.append({
                    "id": str(uuid.uuid4())[:8],
                    "pillar": "live_predictions",
                    "topic": f"{f['home']} vs {f['away']} — {f['date']}",
                    "fixture": f,
                })
        # fallback to static topics if API fails
        if len(topics) < count:
            needed = count - len(topics)
            for t in random.sample(TOPIC_BANKS.get(brand, []), min(needed, len(TOPIC_BANKS.get(brand, [])))):
                topics.append({"id": str(uuid.uuid4())[:8], **t})
    else:
        bank = TOPIC_BANKS.get(brand, [])
        if bank:
            for t in random.sample(bank, min(count, len(bank))):
                topics.append({"id": str(uuid.uuid4())[:8], **t})
    return topics
