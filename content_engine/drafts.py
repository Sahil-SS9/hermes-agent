"""Template-based draft generator using brand voice rules."""
import random
import uuid
from datetime import datetime
from typing import List, Dict, Optional

# Voice pattern libraries extracted from skill references
HOOKS: Dict[str, List[str]] = {
    "matchdaymaestro": [
        "Will there be a goal in the next 10 minutes? You've got 30 seconds.",
        "Brace? Hat-trick? Off the bench heroics? You've got 47 ways to predict it.",
        "Your mate just challenged you. {stake} coins on the line. In or out?",
        "Day {day} of your prediction streak. One more for the Streak Shield bonus.",
        "{home} vs {away}. {derby_word}. Your prediction window opens at {time}.",
        "Last 10 minutes. {home} {home_score}, {away} {away_score}. Goal next? Card next? Make a call.",
        "Three of your mates are in the league. Two are above you. Time to fix that.",
        "{pct}% of MatchdayMaestro users predicted {team}. {pct_actual}% were wrong.",
    ],
    "plenishd": [
        "Opened the fridge. Saw three things. Built a week's meals. No app switch.",
        "Your shopping list just built itself from what you already have.",
        "UK supermarkets: same basket, different total. We checked all 9.",
        "Voice it in. Snap it. Tap once to checkout. We call it Plenishd.",
        "Leftover chicken + potato. We found 6 recipes. You probably have the extras.",
        "The average UK family throws away £720 of food a year. Plenishd changes that.",
    ],
    "sahil_twitter": [
        "Just shipped {feature}. {metric}.",
        "Best agentic workflow this month: {tool_combo}. {result}.",
        "Got tired of {problem}. Built {solution}. {status}.",
        "Every AI tool now has a '{feature}' feature. Nobody solved why it makes the model worse 30% of the time.",
        "Spent {hours} hours debugging {thing}. Fixed it in {minutes} minutes.",
        "{setup}. Every {audience} I know already {reaction}. The trauma is the brand at this point.",
    ],
    "sahil_linkedin": [
        "The PMs who win in 2026 aren't the ones with the best prompts. They're the ones with the best context.",
        "RAG chatbot at {company}: {metric_1} conversion lift, {metric_2} support reduction. Here's how.",
        "I moved from PM to indie builder. The hardest part wasn't the code. It was the context switching.",
        "Enterprise AI adoption stalls at three points. All of them are cultural, not technical.",
        "A well-scoped AI pilot beats a broad AI strategy every time. Here's the proof.",
    ],
    "coachos": [
        "Session done. Warm-up took 8 minutes. Drills ran 12. Cool-down 5. Logged in one tap.",
        "Grassroots coaches: you don't need a clipboard guru. You need a system that follows your approach.",
        "Under-10s tactics: keep it simple, keep it moving, keep it fun. Here's a session that does all three.",
        "Managing parent expectations is half the job. CoachOS keeps parents in the loop without the admin.",
        "Player progression isn't a spreadsheet. It's a conversation. Track both.",
    ],
}

CLOSERS: Dict[str, List[str]] = {
    "matchdaymaestro": [
        "Your move.",
        "Tap to play.",
        "Make the call.",
        "Climb the table.",
        "Predict. Compete. Win.",
    ],
    "plenishd": [
        "Snap it. Say it. Stock it.",
        "Pre-launch. UK only.",
        "Join the waitlist.",
        "No more spreadsheet shops.",
    ],
    "sahil_twitter": [
        "#buildinpublic",
        "#ClaudeCode",
        "#indiehacker",
        "#solofounder",
    ],
    "sahil_linkedin": [
        "What would you add?",
        "Am I wrong?",
        "Your experience?",
    ],
    "coachos": [
        "By coaches, for coaches.",
        "Pre-season ready.",
        "Session done. Admin done.",
    ],
}

PILLAR_MAP = {
    "live_predictions": "Live Predictions In Action",
    "game_modes": "Game Modes Beyond Predictions",
    "friend_battles": "Friend Battles & Social Competition",
    "progression": "Progression & Mastery",
    "football_beat": "The Football Beat",
    "product": "Product Features",
    "voice": "Voice-First",
    "kitchen": "Kitchen Hacks",
    "shopping": "Smart Shopping",
    "launch": "Launch",
    "build_in_public": "Build-In-Public",
    "ai_tools": "AI Tools & Stack",
    "sly_product": "Sly Product Mention",
    "football": "Football",
    "wry": "Wry Observation",
    "pm_thought": "PM Thought Leadership",
    "indie": "Indie Builder Journey",
    "ai": "AI Adoption",
    "leadership": "Leadership",
    "session_plan": "Session Planning",
    "coach_life": "Coach Life",
    "player_dev": "Player Development",
    "community": "Community",
}


def _fill_hook(template: str, topic: Dict) -> str:
    """Substitute placeholders with topic data or random values.

    One random value per placeholder per call (matches original behaviour:
    multiple occurrences of {key} in a template all resolve to the same value).
    """
    fixture = topic.get("fixture", {})
    subs = {
        "stake": str(random.choice([50, 100, 200, 500])),
        "day": str(random.randint(3, 28)),
        "hours": str(random.choice([2, 3, 4, 6, 8])),
        "minutes": str(random.choice([5, 10, 15, 20, 30])),
        "feature": random.choice(["multi-store split", "voice inventory", "basket fill", "recipe engine", "prediction engine v3"]),
        "metric": random.choice(["60% lift", "3x faster", "saved £6.40", "shipped in 48h"]),
        "tool_combo": random.choice(["Claude Code + Hermes", "Agentic loop + tmux", "MCP + Claude API", "Supabase + Convex"]),
        "result": random.choice(["3-4x speed", "zero context loss", "same brain, wildly different output"]),
        "problem": random.choice(["family dinner arguments", "spreadsheet shops", "context switching", "fridge mystery items"]),
        "solution": random.choice(["Plenishd", "a PM suite", "an agentic loop", "MatchdayMaestro"]),
        "status": random.choice(["Pre-launch. UK only.", "Still debugging the UI flow.", "Works. Still in shock."]),
        "pct": str(random.choice([67, 78, 89, 92, 95])),
        "pct_actual": str(random.choice([9, 11, 12, 23])),
        "team": random.choice(["Liverpool", "Arsenal", "Man City", "Spurs", "Chelsea", "Newcastle"]),
        "home": fixture.get("home", "Home"),
        "away": fixture.get("away", "Away"),
        "home_score": str(random.randint(0, 2)),
        "away_score": str(random.randint(0, 2)),
        "time": fixture.get("time", "3pm"),
        "derby_word": random.choice(["North London Derby", "Manchester Derby", "Merseyside Derby", "Big match"]),
        "company": random.choice(["SoftwareOne", "Kinexio"]),
        "metric_1": random.choice(["20-30%", "25-35%", "15-20%"]),
        "metric_2": random.choice(["45%", "55%", "60%"]),
        "thing": random.choice(["a Convex schema mismatch", "a deployment pipeline", "a Zustand store"]),
        "setup": random.choice(["United winning 1-0 at half time", "The 'one more feature' phase"]),
        "audience": random.choice(["United fan", "indie hacker"]),
        "reaction": random.choice(["pacing", "already crying"]),
    }
    out = template
    for key, value in subs.items():
        out = out.replace("{" + key + "}", value)
    return out


def generate_drafts(brand: str, topics: List[Dict], platform: Optional[str] = None) -> List[Dict]:
    """Generate 1-3 draft posts per topic using voice templates."""
    drafts: List[Dict] = []
    brand_key = brand
    hooks_pool = HOOKS.get(brand_key, [])
    closers_pool = CLOSERS.get(brand_key, ["Follow for more."])

    platforms = [platform] if platform else ["twitter"]

    for topic in topics:
        for plat in platforms:
            # Pick 1-2 variations per topic
            variations = random.sample(hooks_pool, min(2, len(hooks_pool))) if len(hooks_pool) >= 2 else hooks_pool[:1]
            for hook_tpl in variations:
                hook = _fill_hook(hook_tpl, topic)
                # Build body: hook + 1-2 lines of context + closer
                context_lines = _build_context(brand, topic["pillar"])
                closer = random.choice(closers_pool) if random.random() > 0.3 else ""
                body_parts = [hook] + context_lines
                if closer:
                    body_parts.append(closer)
                body = "\n\n".join(body_parts)

                draft_id = f"{brand[:4]}_{str(uuid.uuid4())[:8]}"
                drafts.append({
                    "id": draft_id,
                    "brand": brand,
                    "platform": plat,
                    "pillar": topic.get("pillar", "general"),
                    "topic": topic.get("topic", ""),
                    "title": topic.get("topic", ""),
                    "body_text": body,
                })
    return drafts


def _build_context(brand: str, pillar: str) -> List[str]:
    """Add one or two lines of body copy based on brand and pillar."""
    if brand == "matchdaymaestro":
        if pillar == "live_predictions":
            return [
                "47 prediction types. 30-second windows. Speed bonuses for the quick."
            ]
        elif pillar == "game_modes":
            return [
                "Strike501. PlayerCombination. Daily Quizzes. More than just predictions."
            ]
        elif pillar == "friend_battles":
            return [
                "1v1 battles with real coin stakes. Friend-vs-friend. No anonymous noise."
            ]
        elif pillar == "progression":
            return [
                "Rookie to The Maestro. 50 levels. 57 achievements. Your progression, your pace."
            ]
        else:
            return ["Predict. Compete. Win."]
    elif brand == "plenishd":
        return ["Snap your fridge. Say what you need. Stock the kitchen. One app."]
    elif brand.startswith("sahil"):
        return ["Shipping apps. Breaking things. Fixing them. Repeat."]
    elif brand == "coachos":
        return ["Grassroots coaching. Simplified sessions. Less admin. More football."]
    return []
