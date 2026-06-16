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

# content_router type -> the infographic family gate (which types get a transplant
# at all). Layout CHOICE within these is decided by match_layout (semantic), not by
# picking from this broad pool — see below.
LAYOUT_MAP: dict[str, list[str]] = {
    "comparison": ["comparison-table", "scale-balance"],
    "flowchart": ["funnel", "journey-path", "bridge", "circular-flow"],
    "timeline": ["timeline-horizontal", "journey-path"],
    "framework": ["mind-map", "nested-circles", "priority-quadrants", "venn",
                  "fishbone", "tree-hierarchy"],
    "infographic": ["pyramid", "iceberg", "feature-list", "layers-stack", "grid-cards"],
}

# Semantic layout matching. A specific layout carries MEANING (priority-quadrants
# = Eisenhower 2x2, venn = overlap, fishbone = cause analysis, timeline = sequence)
# and must only be used when the content actually has that shape — otherwise the
# template distorts the topic. Each entry: (cue tokens, layouts to allow). Order
# matters: the first matching cue group wins.
_CUE_LAYOUTS: list[tuple[tuple[str, ...], list[str]]] = [
    (("quadrant", "matrix", "2x2", "2 x 2", "urgent", "prioritis", "prioritiz",
      "eisenhower"), ["priority-quadrants"]),
    (("venn", "overlap", "intersection", "in common", "shared between",
      "where they meet"), ["venn", "nested-circles"]),
    (("root cause", "why does", "causes of", "fishbone", "contributing factor"),
     ["fishbone"]),
    (("timeline", "history of", "roadmap", "evolution", "over time", "milestones"),
     ["timeline-horizontal", "journey-path"]),
    ((" vs ", " vs.", "versus", "compared to"), ["comparison-table", "scale-balance"]),
    (("pros and cons", "pros/cons", "trade-off", "tradeoff", "weigh", "for and against"),
     ["scale-balance"]),
    (("do and don", "do/don", "do's and", "dos and don"), ["do-dont"]),
    (("level", "tier", "maturity", " stack", "hierarchy", "ladder", "pyramid of"),
     ["pyramid", "layers-stack", "tree-hierarchy"]),
    (("step", "steps", "process", "pipeline", "stages", "workflow", "funnel",
      "how i ", "how to"), ["funnel", "journey-path"]),
    (("hidden", "what you see", "beneath the surface", "iceberg", "tip of"),
     ["iceberg"]),
    (("org chart", "reporting line", "tree of", "taxonomy", "breakdown of"),
     ["tree-hierarchy"]),
    (("mind map", "map of", "ecosystem of", "landscape of", "branches"),
     ["mind-map", "nested-circles"]),
]
# Safe, semantically-neutral layouts when no specific cue fires. Deliberately
# EXCLUDES quadrants/venn/fishbone/timeline so they never appear uncued.
_GENERAL_LAYOUTS = ["feature-list", "grid-cards", "pyramid", "iceberg", "layers-stack"]
_DEFAULT_LAYOUTS = _GENERAL_LAYOUTS

# ── Non-infographic (scene) path ──────────────────────────────────────────
# For scene/hero content the win comes from transplanting one of Sahil's rich
# reference COMPOSITIONS (not inventing a sparse "glow on black"). Each archetype
# is a folder of his refs under scene-anchors/. `desc` is the composition brief;
# `text` is the text rule (scenes are mostly textless or title-only).
_SCENE_DIR = Path(IMAGERY_ANCHORS_DIR) / "scene-anchors"
SCENE_ARCHETYPES: dict[str, dict] = {
    "abstract": {"desc": "an abstract conceptual illustration that symbolises the idea "
                 "through form, data, particles, networks and light (no literal objects)",
                 "text": "title_only"},
    "mythic": {"desc": "a mythic, statuary hero composition — Greek-myth gravitas, marble "
               "and shadow, dramatic single subject", "text": "title_only"},
    "atmospheric": {"desc": "a moody, cinematic atmospheric scene with depth, haze and "
                    "volumetric light — environment over subject", "text": "none"},
    "tarot": {"desc": "an ornate mystical tarot-card composition with a symbolic central "
              "figure or object and a decorative border", "text": "title_only"},
    "creature": {"desc": "a bold, iconic creature/mascot-style hero — playful, vivid, "
                 "high-impact", "text": "title_only"},
    "figure": {"desc": "a lone stylised figure/agent within a tech environment (varied "
               "subject, NO fixed recurring identity, not a mascot)", "text": "none"},
}
# Cue -> archetypes, most-specific first. Default leans abstract (safe, characterless).
_SCENE_CUES: list[tuple[tuple[str, ...], list[str]]] = [
    (("philosophy", "theory", "ghost in", "consciousness", "meaning of", "nature of",
      "essence", "what is ", "why does"), ["abstract", "tarot"]),
    (("manifesto", "principle", "belief", "vision", "the future of", "why we",
      "identity", "first principles"), ["mythic", "abstract"]),
    (("launch", "shipped", "introducing", "announcing", "meet ", "v1", "now live"),
     ["creature", "mythic"]),
    (("story", "journey", "week ", "diary", "log", "how it went", "lessons", "retro",
      "post-mortem", "postmortem"), ["figure"]),
]
# NOTE: 'atmospheric' is defined in SCENE_ARCHETYPES but PARKED — its validation
# output read as a generic stock room, not concept-art. Re-enable once it has
# stronger anchors/brief. Until then it is never selected.
_DEFAULT_SCENE = ["abstract", "mythic"]
_SCENE_TYPES = {"scene", "hero", "metaphor", "typography"}


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


def match_layout(draft: dict) -> list[str]:
    """Return semantically-valid layout stems for the draft, most-specific first.

    A specific layout only fires when its meaning is cued in the title/body; this
    prevents e.g. an Eisenhower priority-quadrants template being slapped on a
    topic that is not a 2x2. Falls back to neutral general layouts. Results are
    filtered to those whose anchor file exists.
    """
    text = ((draft.get("title") or "") + " " + (draft.get("body_text") or "")
            + " " + (draft.get("topic") or "")).lower()
    for cues, layouts in _CUE_LAYOUTS:
        if any(c in text for c in cues):
            hit = _existing(layouts)
            if hit:
                return hit
    return _existing(_GENERAL_LAYOUTS)


def _scene_dir(arc: str) -> Path:
    return _SCENE_DIR / arc


def _existing_scenes(arcs: list[str]) -> list[str]:
    return [a for a in arcs if _scene_dir(a).is_dir()
            and any(_scene_dir(a).glob("*.[jpw]*"))]


def match_scene(draft: dict) -> list[str]:
    """Return scene archetypes whose meaning is cued by the draft, else neutral
    defaults. Filtered to archetypes that have anchor files."""
    text = ((draft.get("title") or "") + " " + (draft.get("body_text") or "")
            + " " + (draft.get("topic") or "")).lower()
    for cues, arcs in _SCENE_CUES:
        if any(c in text for c in cues):
            hit = _existing_scenes(arcs)
            if hit:
                return hit
    return _existing_scenes(_DEFAULT_SCENE) or _existing_scenes(list(SCENE_ARCHETYPES))


def _scene_anchor(arc: str, rng: random.Random) -> Path | None:
    files = sorted(p for p in _scene_dir(arc).iterdir()
                   if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
    return rng.choice(files) if files else None


def is_transplant_type(ctype: str) -> bool:
    """Infographic family (dense layouts). Scene family handled separately."""
    return ctype in LAYOUT_MAP


def is_scene_type(ctype: str) -> bool:
    return ctype in _SCENE_TYPES


def _select_scene(draft: dict, brand: str, ctype: str, rng: random.Random) -> dict | None:
    arcs = match_scene(draft)
    palettes = _palettes_for(brand)
    if not arcs or not palettes:
        return None
    rotation = _load_rotation().get(brand, [])
    recent_pal = [k.split("|", 1)[0] for k in rotation][-IMAGERY_ROTATION_MEMORY:]
    recent_arc = [k.split("|", 1)[1] for k in rotation if "|" in k][-IMAGERY_ROTATION_MEMORY:]
    palette = _pick(palettes, recent_pal, rng)
    arc = _pick(arcs, recent_arc, rng)
    anchor = _scene_anchor(arc, rng)
    if not anchor:
        return None
    _record_rotation(brand, f"{palette}|{arc}")
    p = PALETTES[palette]
    meta = SCENE_ARCHETYPES[arc]
    return {
        "kind": "scene", "palette": palette, "archetype": arc,
        "anchor_path": anchor, "hex": p["hex"], "light": p["light"],
        "ctype": ctype, "desc": meta["desc"], "text_rule": meta["text"], "aspect": "4:5",
    }


def select_recipe(draft: dict, brand: str, ctype: str | None = None,
                  seed: int | None = None) -> dict | None:
    """Choose an imagery recipe for a draft. Returns a dict with `kind`:
      * "infographic" — dual-anchor (baoyu layout + style/palette)
      * "scene"       — single-anchor (a Sahil archetype ref)
    or None for content types we don't transplant. Records the pick for rotation.
    """
    ctype = ctype or content_type_for(draft)
    rng = random.Random(seed)

    if is_transplant_type(ctype):
        # Layout chosen by semantic cue, never the broad pool, so a meaning-
        # bearing layout cannot misrepresent the content.
        layouts = match_layout(draft) or _existing(_DEFAULT_LAYOUTS)
        palettes = _palettes_for(brand)
        if not layouts or not palettes:
            return None
        rotation = _load_rotation().get(brand, [])
        recent_pal = [k.split("|", 1)[0] for k in rotation][-IMAGERY_ROTATION_MEMORY:]
        recent_lay = [k.split("|", 1)[1] for k in rotation if "|" in k][-IMAGERY_ROTATION_MEMORY:]
        palette = _pick(palettes, recent_pal, rng)
        layout = _pick(layouts, recent_lay, rng)
        _record_rotation(brand, f"{palette}|{layout}")
        p = PALETTES[palette]
        return {
            "kind": "infographic", "palette": palette, "layout": layout,
            "layout_path": _layout_path(layout), "style_path": Path(p["style"]),
            "hex": p["hex"], "light": p["light"], "ctype": ctype, "aspect": "4:5",
        }

    if is_scene_type(ctype):
        return _select_scene(draft, brand, ctype, rng)

    return None
