"""Imagery recipe selection — rotate palette x baoyu-layout for variety.

DNA is the CRAFT thread (analog texture, type hierarchy, designed density), NOT a
fixed palette. This picks, per draft:
  * a palette from a brand-allowed set, rotated to avoid recent repeats
  * a baoyu infographic LAYOUT matching the draft's content shape
so consecutive posts look genuinely different while staying on-brand. The
reference-anchored transplant generator (imagery_transplant) consumes the recipe.

Validated 2026-06-16 (see brand_imagery_standard.md). Anchors live under
config.IMAGERY_ANCHORS_DIR (baoyu-screenshots/...).
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from config import IMAGERY_ANCHORS_DIR, IMAGERY_ROTATION_MEMORY
from content_router import content_type_for

_BAOYU = Path(IMAGERY_ANCHORS_DIR) / "baoyu-screenshots"
_LAYOUT_DIR = _BAOYU / "infographic-layouts"
_STYLE_DIR = _BAOYU / "infographic-styles"
_ASTYLE_DIR = _BAOYU / "article-illustrator-styles"
_ROTATION = Path(__file__).resolve().parent / "output" / "imagery_rotation.json"

# Palette system. `hex` is the explicit palette instruction; `style` is the baoyu
# exemplar that carries the look; `brands` gates which brands may use it.
PALETTES: dict[str, dict] = {
    "cyber_neon": {
        "hex": "deep near-black #00000E background, electric blue #3847FF, magenta "
               "#BD2EFF and cyan #2EE6FF neon accents",
        "light": False, "style": _STYLE_DIR / "cyberpunk-neon.webp",
        "brands": ("sahil_twitter", "sahil_linkedin"),
    },
    "acid_duotone": {
        "hex": "black background, cobalt blue #1D4ED8 and acid yellow #E3FF00 "
               "duotone with white, bold and high-energy",
        "light": False, "style": _STYLE_DIR / "bold-graphic.webp",
        "brands": ("sahil_twitter",),
    },
    "synthwave": {
        "hex": "deep purple #1A0B2E background, hot pink #FF6AC1, sunset orange "
               "#FF8A3D and cyan #00E0FF, retro synthwave",
        "light": False, "style": _ASTYLE_DIR / "retro.webp",
        "brands": ("sahil_twitter",),
    },
    "blueprint_mono": {
        "hex": "dark navy #0A1A2F blueprint background, cyan #5FE0FF technical "
               "linework, off-white #E6F2FF, faint grid",
        "light": False, "style": _STYLE_DIR / "technical-schematic.webp",
        "brands": ("sahil_twitter", "sahil_linkedin"),
    },
    "warm_editorial": {
        "hex": "warm parchment/cream #F2E8D5 background, charcoal #1A1A1A ink and "
               "one deep red #C0392B accent, vintage letterpress, LIGHT not dark",
        "light": True, "style": _STYLE_DIR / "aged-academia.webp",
        "brands": ("sahil_twitter", "sahil_linkedin"),
    },
}

# content_router type -> candidate baoyu layout stems (the dense, designed shapes)
LAYOUT_MAP: dict[str, list[str]] = {
    "comparison": ["comparison-table", "scale-balance"],
    "flowchart": ["funnel", "journey-path", "bridge", "circular-flow"],
    "timeline": ["timeline-horizontal", "journey-path"],
    "framework": ["mind-map", "nested-circles", "priority-quadrants", "venn",
                  "fishbone", "tree-hierarchy"],
    "infographic": ["pyramid", "iceberg", "feature-list", "layers-stack", "grid-cards"],
}
_DEFAULT_LAYOUTS = LAYOUT_MAP["infographic"]


def _layout_path(stem: str) -> Path:
    return _LAYOUT_DIR / f"{stem}.webp"


def _existing(stems: list[str]) -> list[str]:
    return [s for s in stems if _layout_path(s).exists()]


def _palettes_for(brand: str) -> list[str]:
    out = [name for name, p in PALETTES.items()
           if brand in p["brands"] and Path(p["style"]).exists()]
    # Fall back to any palette with an existing style asset if brand-gating empties.
    return out or [n for n, p in PALETTES.items() if Path(p["style"]).exists()]


def _load_rotation() -> dict:
    try:
        return json.loads(_ROTATION.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _record_rotation(brand: str, key: str) -> None:
    data = _load_rotation()
    hist = data.get(brand, [])
    hist.append(key)
    data[brand] = hist[-(IMAGERY_ROTATION_MEMORY * 2):]
    _ROTATION.parent.mkdir(parents=True, exist_ok=True)
    _ROTATION.write_text(json.dumps(data, indent=2))


def _pick(options: list[str], recent: list[str], rng: random.Random) -> str:
    """Pick avoiding recent; if all are recent, pick the least-recently-used."""
    fresh = [o for o in options if o not in recent]
    if fresh:
        return rng.choice(fresh)
    # all seen recently: choose the one that appeared longest ago
    return min(options, key=lambda o: -recent[::-1].index(o) if o in recent else 0)


def is_transplant_type(ctype: str) -> bool:
    """Transplant covers the infographic family. Scene/hero fall back elsewhere."""
    return ctype in LAYOUT_MAP


def select_recipe(draft: dict, brand: str, ctype: str | None = None,
                  seed: int | None = None) -> dict | None:
    """Choose {palette, layout, style_path, layout_path, hex, light, aspect} for a
    draft. Returns None when the draft is not an infographic-family type (the
    caller then uses a non-transplant path). Records the pick for rotation.
    """
    ctype = ctype or content_type_for(draft)
    if not is_transplant_type(ctype):
        return None
    layouts = _existing(LAYOUT_MAP.get(ctype, _DEFAULT_LAYOUTS)) or _existing(_DEFAULT_LAYOUTS)
    palettes = _palettes_for(brand)
    if not layouts or not palettes:
        return None

    rng = random.Random(seed)
    rotation = _load_rotation().get(brand, [])
    recent_pal = [k.split("|", 1)[0] for k in rotation][-IMAGERY_ROTATION_MEMORY:]
    recent_lay = [k.split("|", 1)[1] for k in rotation if "|" in k][-IMAGERY_ROTATION_MEMORY:]

    palette = _pick(palettes, recent_pal, rng)
    layout = _pick(layouts, recent_lay, rng)
    _record_rotation(brand, f"{palette}|{layout}")

    p = PALETTES[palette]
    return {
        "palette": palette, "layout": layout,
        "layout_path": _layout_path(layout), "style_path": Path(p["style"]),
        "hex": p["hex"], "light": p["light"], "ctype": ctype,
        "aspect": "4:5",
    }
