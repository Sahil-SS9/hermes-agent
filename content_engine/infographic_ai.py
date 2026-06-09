"""Track B done properly: baoyu-style infographics as AI images.

NOT code-rendered. This ports baoyu's structured-prompt method (base prompt +
per-layout guideline + per-style guideline + content + exact text labels) and
sends it to a text-capable model (Seedream 4.5 default). Proven 2026-06-08 to
match baoyu's own examples with crisp, correct text at ~£0.032/image.

Replaces the dead CSS infographic.py.
"""
from __future__ import annotations

import hashlib
from typing import Optional, Tuple

from model_config import HERO_MODEL

IG_MODEL = "seedream45"          # workhorse: flawless text, ~£0.032
IG_FALLBACKS = ["nano_banana"]   # rare hero rescue if the workhorse fails

# ── concise layout guidelines (ported from baoyu skills/.../layouts) ─────────
LAYOUT_GUIDES = {
    "binary-comparison": "Side-by-side comparison split by a strong vertical divider with a VS decoration in the centre. Left = Item A, right = Item B, mirrored rows in matching positions, contrasting colour per side, main title centred at top, clear side labels, a bold takeaway across the bottom.",
    "comparison-table": "Two columns compared row by row with a clear header per column and a vertical divider; aligned rows, alternating row emphasis, title at top.",
    "do-dont": "Two clearly separated columns: a green DO column with ticks on the left, a red DON'T column with crosses on the right; short parallel items, title at top.",
    "feature-list": "A vertical numbered list of 3-5 points, each with a bold number badge, a short bold label and a one-line description; clear rhythm, title at top.",
    "grid-cards": "A 2x2 grid of four cards, each with a big number or icon and a short label; even spacing, title at top.",
    "funnel": "Stacked horizontal bands narrowing from top to bottom showing stages of a process; each band labelled; title at top.",
    "layers-stack": "Horizontal layers stacked vertically, like a tech stack, each layer labelled; title at top.",
    "priority-quadrants": "A 2x2 matrix with labelled x and y axes; the high-value quadrant highlighted; one short label per quadrant; title at top.",
    "mind-map": "A central node with the core idea and 3-4 branches radiating out to labelled sub-nodes; clean connectors; title at top.",
    "pyramid": "A 3-tier pyramid from broad base to narrow apex, each tier labelled in order of priority; title at top.",
    "venn": "Two overlapping circles labelled A and B with the intersection labelled; title at top.",
    "tree-hierarchy": "A top-down tree: one root node branching to 2-3 child nodes; clean connectors; title at top.",
    "bridge": "Two pillars connected by an arc spanning a gap, showing movement from a 'now' state on the left to a 'goal' state on the right; title at top.",
    "equation": "Three boxes in a row joined by + and = signs, showing A + B = C; the result box emphasised; title at top.",
    "circular-flow": "Four stages arranged in a circle with arrows showing a repeating cycle; each stage labelled; title at top.",
}

# ── concise style guidelines (ported from baoyu skills/.../styles) ───────────
STYLE_GUIDES = {
    "bold-graphic": "High-contrast bold-graphic comic style: heavy black outlines, primary colours (red, yellow, blue) on a dramatic dark ground with neon highlights, halftone dot patterns, action lines, chunky display typography, energetic.",
    "craft-handmade": "Hand-drawn paper-craft aesthetic: warm cream paper texture, soft saturated construction-paper colours, slightly imperfect hand-drawn shapes, simple cartoon icons, ample whitespace. Strictly hand-drawn, no photographic elements.",
    "hand-drawn-edu": "Hand-drawn educational style: warm cream paper, macaron pastel rounded cards as information zones, deep charcoal headlines, a coral-red accent for key data, hand-drawn wavy connector lines, simple cartoon icons (lightbulb, lock, tick), doodle stars and underlines, slight hand-drawn wobble, a bold centred takeaway at the bottom.",
    "technical-schematic": "Technical schematic / blueprint style: dark or off-white ground, fine precise line-work, monospace labels, measurement ticks and annotations, restrained accent colour, engineering-diagram feel.",
    "aged-academia": "Aged-academia style: cream antique paper with foxing, elegant serif typography, fine rules and ornaments, a scholarly restrained palette, classic textbook engraving feel.",
    "chalkboard": "Chalkboard style: dark green board, chalk-white hand-lettered text, hand-drawn diagrams and arrows, smudges and dusty texture, a warm yellow chalk accent.",
    "storybook-watercolor": "Children's storybook watercolour: soft hand-painted gouache and watercolour textures, visible paper grain, friendly rounded cartoon characters, a cheerful bright palette, wholesome and playful.",
    "retro": "Retro 1970s print style: warm mustard, rust and teal palette, halftone print texture, chunky rounded display type, vintage poster feel.",
}

# brand defaults for infographics (baoyu styles + the signed-off layouts)
BRAND_IG_STYLES = {
    "plenishd": ["craft-handmade", "hand-drawn-edu"],
    "coachos": ["technical-schematic", "bold-graphic"],
    "matchdaymaestro": ["bold-graphic"],
    "kicktionary": ["hand-drawn-edu", "storybook-watercolor", "chalkboard"],
    "sahil_twitter": ["bold-graphic", "technical-schematic"],
    "sahil_linkedin": ["technical-schematic", "aged-academia"],
}
BRAND_IG_LAYOUTS = {
    "plenishd": ["feature-list", "grid-cards", "comparison-table", "equation"],
    "coachos": ["priority-quadrants", "do-dont", "tree-hierarchy", "layers-stack"],
    "matchdaymaestro": ["comparison-table", "do-dont", "funnel", "grid-cards"],
    "kicktionary": ["mind-map", "do-dont", "equation", "circular-flow", "pyramid"],
    "sahil_twitter": ["binary-comparison", "do-dont", "bridge", "priority-quadrants"],
    "sahil_linkedin": ["priority-quadrants", "pyramid", "funnel", "tree-hierarchy", "bridge"],
}
_DEFAULT = "sahil_twitter"

# Brand palettes described for the model. Standout comes from anchoring emphasis
# on the brand accent and keeping strong figure-ground contrast.
BRAND_PALETTES = {
    "plenishd": "deep warm charcoal #2C2A28 base, Plenishd yellow #FBBF24 as the accent, fresh green #10B981 secondary, cream #F7EDE3 for light areas",
    "coachos": "near-black slate #111827 base, a single restrained emerald green #22C55E accent, light grey #E8E8E8 for text",
    "matchdaymaestro": "deep night navy #0F0F1A base, electric crimson #E11D48 accent, gold #FBBF24 secondary",
    "kicktionary": "bright friendly blue #1D4ED8 base, sunny yellow #FACC15 accent, coral #FB7185 and grass green #16A34A secondaries",
    "sahil_twitter": "near-black #0A0A0A base, electric indigo #6366F1 accent, acid lime #A3E635 secondary",
    "sahil_linkedin": "clean off-white #F2F2F2 base, deep indigo #4F46E5 accent, slate grey #64748B secondary",
}

TYPOGRAPHY = ("Typography: pair a bold, characterful display typeface for the title and the key "
              "figures with a clean, legible complementary typeface for the labels and body. "
              "Strong type hierarchy: an oversized title, clear medium labels, small neat annotations. "
              "Add generous letter-spacing on the kicker. Make every word sharp and perfectly legible.")

BASE_PROMPT = """Create a professional, polished infographic image. Aspect ratio 1:1 square.

Layout: {layout}
Style: {style}

Rules: follow the layout structure precisely for the information architecture;
apply the style aesthetics consistently throughout; keep wording concise and
highlight the key concepts; use ample whitespace and a clear visual hierarchy.
Every piece of text must be spelled exactly as given and be crisp and legible.

Layout guidelines: {layout_guide}

Style guidelines: {style_guide}

Colour direction: anchor the emphasis and accent colours on the brand palette
({palette}). Keep the {style} surface, but use the brand accent for the title,
the key numbers and the takeaway so they pop. Use a confident, high-contrast
complementary colour scheme so the graphic stands out in a busy social feed.
Use the colours only; never display hex codes, colour values, measurement
numbers or placeholder annotations as visible text. The only text in the image
is the labels listed below.

{typography}

Content to present:
{content}

Render EXACTLY these text labels, spelled exactly, and nothing else as text:
{labels}"""


def _seed(brand, key):
    return int(hashlib.sha256(f"{brand}:{key}".encode()).hexdigest(), 16)


def pick(brand, key, layout=None, style=None):
    s = _seed(brand, key)
    styles = BRAND_IG_STYLES.get(brand, list(STYLE_GUIDES))
    layouts = BRAND_IG_LAYOUTS.get(brand, list(LAYOUT_GUIDES))
    return (style or styles[(s + 2) % len(styles)],
            layout or layouts[(s + 4) % len(layouts)])


def build_infographic_prompt(brand, content: dict, draft_id="",
                             layout=None, style=None) -> Tuple[str, str, str]:
    """Return (prompt, layout, style). ``content`` keys: title, body, labels."""
    brand = (brand or "").lower()
    style, layout = pick(brand, draft_id or content.get("title", "x"), layout, style)
    title = (content.get("title") or "").strip()
    body = (content.get("body") or "").strip()
    labels = (content.get("labels") or title).strip()
    prompt = BASE_PROMPT.format(
        layout=layout, style=style,
        layout_guide=LAYOUT_GUIDES.get(layout, LAYOUT_GUIDES["feature-list"]),
        style_guide=STYLE_GUIDES.get(style, STYLE_GUIDES["bold-graphic"]),
        palette=BRAND_PALETTES.get(brand, BRAND_PALETTES[_DEFAULT]),
        typography=TYPOGRAPHY,
        content=(f"Title: {title}\n{body}").strip(),
        labels=labels,
    )
    return prompt, layout, style


def generate_infographic(brand, content: dict, draft_id="", platform="twitter",
                         layout=None, style=None, out_dir: Optional[str] = None) -> Optional[str]:
    """Generate a finished infographic image (text is rendered by the model, so
    no Pillow overlay is applied). Budget-gated; degrades workhorse->hero.
    ``layout`` lets the router pass a content-matched layout."""
    import os
    import uuid
    from pathlib import Path
    import fal_client
    import budget
    from fal_client import MODEL_COST_GBP

    import re

    prompt, layout, style = build_infographic_prompt(brand, content, draft_id, layout=layout, style=style)
    # Sanitise anything that becomes a path component (brand/draft_id are
    # internal, but never trust input into a filesystem path).
    safe_brand = re.sub(r"[^a-z0-9_-]", "", (brand or "").lower()) or "misc"
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "", draft_id or "") or uuid.uuid4().hex[:8]
    out_dir = out_dir or str(Path(__file__).resolve().parent / "output" / safe_brand / "infographic")
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    fname = f"{safe_id}_{style}_{layout}.png"

    for model in [IG_MODEL] + IG_FALLBACKS:
        cost = MODEL_COST_GBP.get(model, 0.032)
        if not budget.can_spend(cost):
            print(f"[infographic_ai] budget cap; skip {model}")
            continue
        print(f"[infographic_ai] {brand} {style}/{layout} via {model}")
        path = fal_client.generate_image(prompt, model=model, aspect="square",
                                         output_dir=out_dir, filename=fname)
        if path and os.path.exists(path):
            budget.record(cost, label=f"ig:{model}:{draft_id}")
            # Record the model prompt so the dashboard can show how this
            # infographic was generated. Best-effort.
            try:
                from database import update_draft_image_prompt
                if draft_id:
                    update_draft_image_prompt(draft_id, prompt)
            except Exception as exc:  # noqa: BLE001
                print(f"[infographic_ai] could not persist image prompt: {exc}")
            return path
    return None
