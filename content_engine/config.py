"""KENSEI Content Engine — Configuration."""
import os
from pathlib import Path

BASE_DIR = Path("/home/kensei/repos/KenseiAgent/content_engine")
OUTPUT_DIR = BASE_DIR / "output"
DB_PATH = BASE_DIR / "db" / "content_engine.db"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
(DB_PATH.parent).mkdir(parents=True, exist_ok=True)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
# Telegram delivery targets
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CONTENT_CHAT_ID", "-1003922682700")
TELEGRAM_TOPIC_ID = os.getenv("TELEGRAM_CONTENT_TOPIC_ID", "22")

# Postiz DB connection (fallback values for self-hosted)
FOOTBALL_API_BASE = "https://api.football-data.org/v4"

# Font paths (system fallback; prefer Roboto or Inter if available)
FONT_DIR = Path("/usr/share/fonts/truetype")


def font_path(name: str, fallback: str = "DejaVuSans.ttf") -> Path:
    candidates = [
        FONT_DIR / "roboto" / f"{name}.ttf",
        FONT_DIR / "inter" / f"{name}.ttf",
        FONT_DIR / "liberation" / f"{name}.ttf",
        FONT_DIR / f"{name}.ttf",
        FONT_DIR / "dejavu" / f"{name}.ttf",
    ]
    for c in candidates:
        if c.exists():
            return c
    fb = FONT_DIR / "dejavu" / fallback
    if fb.exists():
        return fb
    # ultimate fallback
    return FONT_DIR / fallback


BRANDS = {
    "matchdaymaestro": {
        "display": "MatchdayMaestro",
        "handle": "@MaestroMatchday",
        "colour": "#FBBF24",
        "bg": "#0F0F1A",
        "accent": "#E11D48",
        "platforms": ["twitter", "instagram", "tiktok"],
        "primary": "gamified",
        "secondary": "fpl_official",
    },
    "plenishd": {
        "display": "Plenishd",
        "handle": "@PlenishdApp",
        "colour": "#FBBF24",
        "bg": "#2C2A28",
        "accent": "#10B981",
        "platforms": ["twitter", "instagram", "linkedin"],
        "primary": "warm_practical",
        "secondary": "witty",
    },
    "sahil_twitter": {
        "display": "Sahil",
        "handle": "@SahilSaghir",
        "colour": "#C0C0C0",
        "bg": "#0A0A0A",
        "accent": "#8B0000",
        "platforms": ["twitter"],
        "primary": "direct_specific",
        "secondary": "wry",
    },
    "sahil_linkedin": {
        "display": "Sahil",
        "handle": "Sahil Saghir",
        "colour": "#C0C0C0",
        "bg": "#0A0A0A",
        "accent": "#8B0000",
        "platforms": ["linkedin"],
        "primary": "authoritative",
        "secondary": "opinion_having",
    },
    "coachos": {
        "display": "CoachOS",
        "handle": "@CoachOSApp",
        "colour": "#22C55E",
        "bg": "#111827",
        "accent": "#16A34A",
        "platforms": ["twitter", "instagram", "linkedin"],
        "primary": "direct_credible",
        "secondary": "coach_to_coach",
    },
}
