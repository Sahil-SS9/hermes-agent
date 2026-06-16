"""Reference-anchored transplant generator for personal-brand imagery.

Pipeline (validated 2026-06-16, see brand_imagery_standard.md):
  select_recipe -> structured labels -> dual-anchor prompt (baoyu LAYOUT exemplar
  for designed density + STYLE/palette exemplar for the look) -> nano-banana-pro/
  edit -> mandatory analog finish. Budget-gated. Returns a finished PNG path, or
  None so the caller falls back to the legacy path.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Optional

import budget
import fal_client
import imagery_library as lib
import postprocess as pp
from config import (
    IMAGERY_EDIT_COST_GBP, IMAGERY_EDIT_MODEL,
    IMAGERY_HERO_MODEL, IMAGERY_SCENE_COST_GBP, IMAGERY_SCENE_MODEL,
)


def _model_for(recipe: dict) -> tuple[str, float]:
    """Tiered model + cost: infographics & hero scenes -> nano-pro; default
    (non-hero) scenes -> the ~3x cheaper nano non-pro."""
    if recipe.get("kind") == "scene" and recipe.get("ctype") != "hero":
        return IMAGERY_SCENE_MODEL, IMAGERY_SCENE_COST_GBP
    if recipe.get("kind") == "scene":  # hero scene
        return IMAGERY_HERO_MODEL, IMAGERY_EDIT_COST_GBP
    return IMAGERY_EDIT_MODEL, IMAGERY_EDIT_COST_GBP  # infographic
from infographic_content import build_ig_fields

_OUT = Path(__file__).resolve().parent / "output"

_CRAFT = (
    "Keep the brand craft constant: analog texture (film grain, halftone, subtle "
    "print/scanline), strong type hierarchy (distressed condensed display + clean "
    "labels + mono), designed information density, restrained composition. No human "
    "or anime character. All text crisp, correctly spelled, no gibberish."
)

# Scenes may include a figure (the 'figure' archetype) but never a fixed mascot or
# a real person; quality bar is concept-art, not generic stock or a flat glow.
_SCENE_CRAFT = (
    "Keep the brand craft: analog texture (film grain, halftone, subtle scanline), "
    "high-contrast cinematic lighting, restrained composition, concept-art quality "
    "(NOT generic stock, NOT a flat glow-on-black). Do not reproduce any specific "
    "real person or a fixed recurring mascot identity. Any text must be crisp."
)


def _labels(draft: dict) -> str:
    try:
        return build_ig_fields(draft).get("labels", "") or ""
    except Exception:  # noqa: BLE001
        return (draft.get("body_text") or "")[:300]


def _concept(draft: dict) -> str:
    """The subject/idea a scene should depict — visual_description, else the lede."""
    vd = (draft.get("visual_description") or "").strip()
    if vd:
        return vd[:200]
    body = (draft.get("body_text") or "").strip()
    first = re.split(r"(?<=[.!?])\s+", body)[0] if body else ""
    return (first or draft.get("title") or "").strip()[:200]


def build_edit_prompt(title: str, labels: str, palette_hex: str) -> str:
    """Compose the preserve-then-add prompt for the dual-anchor infographic call."""
    return (
        "Create an infographic. Use the FIRST reference image ONLY as the LAYOUT / "
        "structure template (reproduce its designed density and arrangement). Use "
        "the SECOND reference image ONLY as the visual STYLE and colour reference. "
        f"Title: \"{title}\". Content: {labels}\n\n"
        f"PALETTE: {palette_hex}.\n\n{_CRAFT}"
    )


def build_scene_prompt(title: str, concept: str, desc: str, palette_hex: str,
                       text_rule: str) -> str:
    """Compose the single-anchor scene prompt (transplant a composition, add subject)."""
    if text_rule == "none":
        t = "ABSOLUTELY NO text anywhere in the image."
    elif text_rule == "title_only":
        t = f'The ONLY text is the title: "{title}". No other text, no captions.'
    else:
        t = "Minimal text only."
    return (
        "Use the reference image as the STYLE and COMPOSITION anchor — match its mood, "
        f"palette discipline, lighting and composition. Create {desc}.\n\n"
        f"Subject / concept to depict: {concept}.\n\n"
        f"PALETTE: {palette_hex}.\n\n{t}\n\n{_SCENE_CRAFT}"
    )


def generate(draft: dict, brand: str, out_dir: Optional[Path] = None,
             ctype: Optional[str] = None) -> Optional[str]:
    """Generate one finished hero via the transplant path. None on skip/failure."""
    recipe = lib.select_recipe(draft, brand, ctype=ctype)
    if not recipe:
        return None  # not a transplantable type; caller uses the legacy fallback
    model, cost = _model_for(recipe)
    if not budget.can_spend(cost):
        print("[imagery_transplant] budget cap; skipping")
        return None

    out_dir = Path(out_dir or _OUT)
    title = (draft.get("title") or draft.get("topic") or "").strip()

    if recipe.get("kind") == "scene":
        prompt = build_scene_prompt(title, _concept(draft), recipe["desc"],
                                    recipe["hex"], recipe["text_rule"])
        urls = [fal_client.upload_file(recipe["anchor_path"])]
    else:
        prompt = build_edit_prompt(title, _labels(draft), recipe["hex"])
        urls = [fal_client.upload_file(recipe["layout_path"]),
                fal_client.upload_file(recipe["style_path"])]
    if not all(urls):
        print("[imagery_transplant] anchor upload failed")
        return None

    did = draft.get("id") or uuid.uuid4().hex[:8]
    raw = fal_client.generate_image_edit(
        prompt, urls, model=model,
        aspect=recipe["aspect"], output_dir=str(out_dir),
        filename=f"transplant_{brand}_{did}_raw.png",
    )
    if not raw or not os.path.exists(raw):
        return None
    _pick = recipe.get("layout") or recipe.get("archetype") or "?"
    budget.record(cost, label=f"transplant:{brand}:{recipe['palette']}:{_pick}")

    fin_dir = out_dir / "fal_images"
    fin_dir.mkdir(parents=True, exist_ok=True)
    fin = fin_dir / f"transplant_{brand}_{did}.png"
    try:
        pp.finish_file(raw, str(fin), light=recipe["light"])
    except Exception as exc:  # noqa: BLE001 (finish is enhancement, not gate)
        print(f"[imagery_transplant] finish failed: {exc}; returning raw")
        return raw
    print(f"[imagery_transplant] {brand} {recipe['palette']}|{_pick} -> {fin}")
    return str(fin)
