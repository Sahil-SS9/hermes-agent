"""Art director — one art brief per article, shared across hero + sections.

Replaces the keyword-scoring style selector (which collapsed 12 styles into
3-4 and produced style-cliche images with little article relevance). Instead a
single LLM pass reads the WHOLE article and returns a locked art brief:

  - one style, chosen for article fit and spread across the corpus (avoids
    recently-used styles)
  - a locked palette + central motif + shared art-direction rules
  - a unique hero prompt AND a unique prompt per section, all obeying the same
    palette/motif/style so the post reads as one designed set

The illustrator fills each prompt into the Codex CLI backend. Palette and motif
are shared; the concept of each image is its own section, so images are both
consistent (design) and distinct (content).
"""
from __future__ import annotations

import json
import re
from typing import Optional

# ── Curated, visually DISTINCT style library ────────────────────
# Curated from the old 12. "signal-hud" keeps the Dark Cyberpunk HUD look; the
# "Baoyu Infographic" explainer is its OWN distinct light/structured style
# (baoyu-infographic) — it is a legible diagram aesthetic, not the dark HUD, so
# it must stay selectable. The generic "Baoyu Article Illustrator" stays dropped
# (overlapped ink/chromatic). Each entry is described richly enough that the LLM
# can pick on genuine article fit.
STYLE_LIBRARY = [
    {
        "id": "mythic-tech-codex",
        "label": "Mythic Tech Codex",
        "look": "Edwardian/Victorian scientific-illustration plate; ink linework "
                "and antique watercolour; sepia and aged-paper tones; museum "
                "encyclopedia feel; cross-sections and labelled diagrams (no "
                "readable text).",
        "best_for": "frameworks, theory, first-principles mechanics, taxonomies.",
    },
    {
        "id": "ninth-observatory",
        "label": "The Ninth Observatory",
        "look": "systems-as-architecture; vast built spaces, cross-sections of "
                "halls/conveyors/archives; muted stone-and-brass palette; a "
                "single warm focal light; awe of scale.",
        "best_for": "infrastructure, pipelines, routing, memory systems, "
                    "orchestration, anything spatial.",
    },
    {
        "id": "chromatic-institute",
        "label": "Chromatic Institute",
        "look": "clean modern research abstraction; networked nodes and fields; "
                "confident saturated colour on light ground; Bauhaus-ish "
                "geometry; optimistic and precise.",
        "best_for": "research findings, model behaviour, networks, abstract "
                    "conceptual pieces.",
    },
    {
        "id": "signal-hud",
        "label": "Signal HUD",
        "look": "dark technical dashboard; neon data-flows and instrument panels "
                "on near-black; one glowing focal element; restrained, not "
                "rainbow; diagnostic mood (no readable text).",
        "best_for": "observability, evals, metrics, diagnostics, debugging, "
                    "production reliability. Use sparingly.",
    },
    {
        "id": "baoyu-infographic",
        "label": "Baoyu Infographic",
        "look": "clean modern explainer infographic; flat/isometric structured "
                "panels, flow arrows and stepwise layouts; confident soft palette "
                "(teal, coral, navy, amber on cream); highly legible diagrammatic "
                "storytelling; friendly and precise (no readable text or labels).",
        "best_for": "step-by-step explainers, comparisons, how-it-works "
                    "breakdowns, process/decision flows, PM frameworks.",
    },
    {
        "id": "ink-ember-studio",
        "label": "Ink & Ember Studio",
        "look": "painterly, human-centred contemporary fine art; warm emotive "
                "palette; real people and gesture; editorial-magazine feel.",
        "best_for": "leadership, culture, careers, trust, human-in-the-loop, "
                    "reflective essays.",
    },
    {
        "id": "saga-noir",
        "label": "Saga Noir Studio",
        "look": "bold graphic-novel mythology; high-contrast ink, dramatic "
                "silhouettes, limited spot colour; powerful and decisive.",
        "best_for": "high-stakes decisions, competitive strategy, transformation, "
                    "pivotal moments.",
    },
    {
        "id": "cosmic-postcard",
        "label": "Cosmic Postcard Atelier",
        "look": "mid-century Space Age retro-futurism; optimistic travel-poster "
                "composition; warm oranges/teals/cream; cinematic horizon.",
        "best_for": "futures, adoption curves, trajectories, opportunity, "
                    "forward-looking pieces.",
    },
    {
        "id": "pixel-art",
        "label": "Pixel Art",
        "look": "deliberate pixel-art; visible pixel blocks, limited palette, "
                "SNES/PICO-8 energy, optional CRT glow; playful but crafted.",
        "best_for": "tooling, CLIs, indie/retro, small-and-scrappy builder notes. "
                    "Rare specialist.",
    },
]

STYLE_IDS = {s["id"] for s in STYLE_LIBRARY}
STYLE_BY_ID = {s["id"]: s for s in STYLE_LIBRARY}

# Shared, non-negotiable output rules appended to every generated image prompt.
GLOBAL_IMAGE_RULES = (
    "No text, letters, numbers, captions, logos, watermarks, or UI screenshots "
    "anywhere in the image. 16:9 landscape. High detail, intentional editorial "
    "composition, not generic AI art."
)


def _styles_catalogue() -> str:
    lines = []
    for s in STYLE_LIBRARY:
        lines.append(f"- {s['id']} ({s['label']}): {s['look']} Best for: {s['best_for']}")
    return "\n".join(lines)


def _brief_system_prompt(recent_styles: list[str]) -> str:
    avoid = ", ".join(recent_styles) if recent_styles else "(none yet)"
    return (
        "You are the art director for a technical blog. Given one article, you "
        "design a single coherent illustration set: a hero image plus one image "
        "per section. All images in a post MUST share ONE style, ONE colour "
        "palette, and ONE recurring visual motif, so the post reads as a "
        "designed set — but each image's SUBJECT must come from its own "
        "section's actual argument, so they are not repetitive.\n\n"
        "Choose exactly one style from this catalogue by genuine fit to the "
        "article's substance:\n"
        f"{_styles_catalogue()}\n\n"
        f"Do NOT choose any of these recently-used styles unless none of the "
        f"others fit at all: {avoid}. Prefer variety across the blog.\n\n"
        "The palette must be specific (4-6 named colours or hex). The motif is a "
        "concrete recurring object/shape that can appear differently in each "
        "image. Every prompt must be a vivid, self-contained image description "
        "grounded in the specific ideas of that part of the article — never a "
        "generic scene picked just to suit the style.\n\n"
        "Return ONLY a JSON object, no prose, with this exact shape:\n"
        "{\n"
        '  "style": "<style id from the catalogue>",\n'
        '  "palette": "<4-6 specific colours>",\n'
        '  "motif": "<one concrete recurring visual motif>",\n'
        '  "art_direction": "<2-3 sentences of shared composition/mood rules>",\n'
        '  "hero_prompt": "<vivid hero image description, article-specific>",\n'
        '  "section_prompts": [\n'
        '    {"heading": "<section heading text>", "prompt": "<vivid, section-specific description>"}\n'
        "  ]\n"
        "}\n"
    )


def _brief_user_prompt(title: str, description: str, body_md: str,
                       stream: str, headings: list[str]) -> str:
    body = body_md.strip()
    if len(body) > 6000:
        body = body[:6000] + "\n...[truncated]"
    heads = "\n".join(f"- {h}" for h in headings) if headings else "(no sections; hero only)"
    return (
        f"STREAM: {stream}\n"
        f"TITLE: {title}\n"
        f"DECK: {description}\n\n"
        f"SECTION HEADINGS needing an image (in order):\n{heads}\n\n"
        f"FULL ARTICLE:\n{body}\n\n"
        "Design the illustration set. One section_prompts entry per heading "
        "above, in the same order. If there are no sections, return an empty "
        "section_prompts array."
    )


def _extract_json(text: str) -> Optional[dict]:
    """Pull the first balanced JSON object out of an LLM response."""
    if not text:
        return None
    # Prefer a fenced block if present.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        start = text.find("{")
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i + 1]
                    break
    if not candidate:
        return None
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return None


def _validate(brief: dict, headings: list[str]) -> Optional[dict]:
    """Coerce/validate an LLM brief into a usable shape, or None if unusable."""
    if not isinstance(brief, dict):
        return None
    style = str(brief.get("style", "")).strip()
    if style not in STYLE_IDS:
        # Try loose match on label/id fragments.
        low = style.lower()
        style = next((sid for sid in STYLE_IDS if sid in low or low in sid), "")
        if not style:
            return None
    hero = str(brief.get("hero_prompt", "")).strip()
    if not hero:
        return None
    palette = str(brief.get("palette", "")).strip()
    motif = str(brief.get("motif", "")).strip()
    direction = str(brief.get("art_direction", "")).strip()

    # Map section prompts back to headings by order, tolerant of count drift.
    raw_sections = brief.get("section_prompts") or []
    section_prompts: dict[str, str] = {}
    if isinstance(raw_sections, list):
        for i, h in enumerate(headings):
            if i < len(raw_sections) and isinstance(raw_sections[i], dict):
                p = str(raw_sections[i].get("prompt", "")).strip()
                if p:
                    section_prompts[h] = p
    return {
        "style": style,
        "palette": palette,
        "motif": motif,
        "art_direction": direction,
        "hero_prompt": hero,
        "section_prompts": section_prompts,
    }


def compose_prompt(image_concept: str, brief: dict) -> str:
    """Combine a per-image concept with the post's shared art direction into a
    single Codex prompt. This is what guarantees hero/section consistency."""
    style = STYLE_BY_ID.get(brief["style"], {})
    parts = [
        f"Create an illustration in the {style.get('label', brief['style'])} style.",
        f"Style/medium: {style.get('look', '')}",
    ]
    if brief.get("palette"):
        parts.append(f"Colour palette (use consistently): {brief['palette']}.")
    if brief.get("motif"):
        parts.append(f"Recurring visual motif to include: {brief['motif']}.")
    if brief.get("art_direction"):
        parts.append(f"Shared art direction: {brief['art_direction']}")
    parts.append(f"This image depicts: {image_concept}")
    parts.append(GLOBAL_IMAGE_RULES)
    return "\n\n".join(p for p in parts if p)


def build_art_brief(
    draft: dict,
    headings: list[str],
    recent_styles: Optional[list[str]] = None,
    llm=None,
) -> Optional[dict]:
    """Produce a validated art brief for a post via one LLM pass.

    draft: {title, description, body_md, stream}
    headings: section headings that need images (hero is always included)
    recent_styles: style ids used recently, to spread variety
    llm: optional callable(system, user) -> str (injected for tests); defaults
         to the content-engine longform chain.

    Returns the validated brief dict, or None if the LLM path is unavailable
    (caller falls back to a deterministic brief).
    """
    recent_styles = recent_styles or []
    if llm is None:
        try:
            from llm_generate import _call_llm, _llm_configs

            def llm(system: str, user: str) -> Optional[str]:
                for cfg in _llm_configs(longform=True):
                    body = _call_llm(system, user, cfg, timeout=180, max_tokens=4000)
                    if body:
                        return body
                return None
        except Exception:
            return None

    system = _brief_system_prompt(recent_styles)
    user = _brief_user_prompt(
        draft.get("title", ""), draft.get("description", ""),
        draft.get("body_md", ""), draft.get("stream", "ai"), headings,
    )
    try:
        raw = llm(system, user)
    except Exception:
        return None
    brief = _extract_json(raw or "")
    if brief is None:
        return None
    return _validate(brief, headings)


def fallback_brief(draft: dict, headings: list[str],
                   recent_styles: Optional[list[str]] = None) -> dict:
    """Deterministic brief when the LLM path is unavailable.

    Picks the least-recently-used style so variety survives, uses the title +
    deck as the shared concept, and gives every image the same base concept
    (still consistent, just not individually art-directed).
    """
    recent = recent_styles or []
    ordered = [s["id"] for s in STYLE_LIBRARY if s["id"] not in recent] or list(STYLE_IDS)
    style = ordered[0]
    title = draft.get("title", "")
    desc = draft.get("description", "")
    concept = f"{title}. {desc}".strip(". ")
    return {
        "style": style,
        "palette": "",
        "motif": "",
        "art_direction": "",
        "hero_prompt": concept,
        "section_prompts": {h: f"{h} — in the context of: {concept}" for h in headings},
    }
