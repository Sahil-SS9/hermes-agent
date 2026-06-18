"""Blog illustrator - hero + per-section images via imagery_transplant.

Reuses imagery_transplant.generate (the validated nano-banana-pro/edit
dual-anchor transplant). One hero image + up to BLOG_MAX_SECTION_IMAGES
per-section images. Section images are keyed by H2 heading text.

Style consistency (Task 2): ONE image recipe is selected per post. The hero's
palette is locked across all section images so the post has zero intra-post
style drift. Section layouts vary for visual interest within the locked palette.

Budget-gated via budget.can_spend. When the budget cap blocks, all image
generation is skipped (degrades to a text-only post).

BUDGET NOTE (decision for Sahil):
  hero + 3 sections x 3 streams = ~1.4/day = ~42/mo at 0.12 GBP/img.
  This exceeds the 10 GBP/mo cap. Default to hero + 1 section
  (BLOG_MAX_SECTION_IMAGES=1 in config) which is ~0.24/day = ~7.2/mo,
  under the cap. The budget gate further protects against overspend.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import budget
import config
import imagery_library as lib
from blog.blog_streams import STREAMS
from imagery_transplant import generate  # exposed as bi.generate for monkeypatching


def _extract_h2_headings(body_md: str) -> list[str]:
    """Extract H2 heading texts from markdown body."""
    out = []
    for line in body_md.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            out.append(m.group(1).strip())
    return out


def _section_draft(title: str, heading: str, body_md: str) -> dict:
    """Build a mini-draft for a section so imagery_transplant can label it."""
    return {
        "title": f"{title} - {heading}",
        "body_text": heading,
        "topic": heading,
        "format": "infographic",
    }


def illustrate(draft: dict, out_dir: Optional[Path] = None,
              max_sections: Optional[int] = None,
              budget_label_prefix: Optional[str] = None,
              budget_ledger_path: Optional[str] = None) -> dict:
    """Generate hero + per-section images via the transplant path.

    Locks ONE palette per post: the hero recipe is selected first, then every
    section forces the same palette (with a fresh layout for visual variety).
    All images use BLOG_IMAGE_MODEL (nano-banana-2/edit) via model_override.

    Returns {hero_path: str|None, section_paths: {h2_heading: path}}.
    When the budget cap blocks, all generation is skipped.

    When ``budget_label_prefix`` and ``budget_ledger_path`` are set, spend
    is routed to the separate envelope (back-population) instead of the
    monthly ledger.
    """
    stream = draft.get("stream", "ai")
    brand = STREAMS.get(stream, {}).get("image_palette_brand", "sahil_twitter")
    if max_sections is None:
        max_sections = config.BLOG_MAX_SECTION_IMAGES

    out_dir = Path(out_dir) if out_dir else Path(config.OUTPUT_DIR) / "blog_images"
    out_dir.mkdir(parents=True, exist_ok=True)

    result = {"hero_path": None, "section_paths": {}}

    # Budget check upfront: if we can't even afford the hero, skip everything.
    cost = config.BLOG_IMAGE_COST_GBP
    if not budget.can_spend(cost, ledger_path=budget_ledger_path):
        print("[blog_illustrator] budget cap; skipping all images")
        return result

    # Select ONE recipe for the hero to lock the palette.
    hero_recipe = lib.select_recipe(
        {"title": draft.get("title", ""), "body_text": draft.get("description", ""),
         "topic": draft.get("title", ""), "format": "infographic"},
        brand, ctype="infographic",
    )
    locked_palette = hero_recipe["palette"] if hero_recipe else None

    # Hero image.
    hero_draft = {
        "title": draft.get("title", ""),
        "body_text": draft.get("description", ""),
        "topic": draft.get("title", ""),
        "format": "infographic",
    }
    hero = generate(hero_draft, brand=brand, out_dir=out_dir, ctype="infographic",
                    recipe=hero_recipe,
                    model_override=config.BLOG_IMAGE_MODEL,
                    cost_override=config.BLOG_IMAGE_COST_GBP,
                    budget_label_prefix=budget_label_prefix,
                    budget_ledger_path=budget_ledger_path)
    if hero:
        result["hero_path"] = hero

    # Section images, capped at max_sections. Same locked palette, fresh layout.
    if max_sections <= 0:
        return result

    headings = _extract_h2_headings(draft.get("body_md", ""))
    for heading in headings[:max_sections]:
        if not budget.can_spend(cost, ledger_path=budget_ledger_path):
            print(f"[blog_illustrator] budget cap after {len(result['section_paths'])} sections")
            break
        sec_draft = _section_draft(draft.get("title", ""), heading, draft.get("body_md", ""))
        sec_recipe = lib.select_recipe(
            sec_draft, brand, ctype="infographic", palette=locked_palette,
        )
        img = generate(sec_draft, brand=brand, out_dir=out_dir, ctype="infographic",
                       recipe=sec_recipe,
                       model_override=config.BLOG_IMAGE_MODEL,
                       cost_override=config.BLOG_IMAGE_COST_GBP,
                       budget_label_prefix=budget_label_prefix,
                       budget_ledger_path=budget_ledger_path)
        if img:
            result["section_paths"][heading] = img

    return result