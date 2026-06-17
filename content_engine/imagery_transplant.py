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
import config as cfg
import fal_client
import gemini_vision
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
             ctype: Optional[str] = None, recipe: Optional[dict] = None,
             model_override: Optional[str] = None,
             cost_override: Optional[float] = None) -> Optional[str]:
    """Generate one finished hero via the transplant path. None on skip/failure.

    When ``recipe`` is given, it is used directly instead of calling
    ``lib.select_recipe``. When ``model_override`` is set, the model and its
    cost replace the recipe-derived model (``cost_override`` is required when
    ``model_override`` is not the recipe's default).
    """
    recipe = recipe or lib.select_recipe(draft, brand, ctype=ctype)
    if not recipe:
        return None  # not a transplantable type; caller uses the legacy fallback
    model, cost = _model_for(recipe)
    if model_override:
        model = model_override
        cost = cost_override if cost_override is not None else cost
    if not budget.can_spend(cost):
        print("[imagery_transplant] budget cap; skipping")
        return None

    out_dir = Path(out_dir or _OUT)
    title = (draft.get("title") or draft.get("topic") or "").strip()
    is_scene = recipe.get("kind") == "scene"

    if is_scene:
        base_prompt = build_scene_prompt(title, _concept(draft), recipe["desc"],
                                         recipe["hex"], recipe["text_rule"])
        urls = [fal_client.upload_file(recipe["anchor_path"])]
        qa_content = _concept(draft)
    else:
        base_prompt = build_edit_prompt(title, _labels(draft), recipe["hex"])
        urls = [fal_client.upload_file(recipe["layout_path"]),
                fal_client.upload_file(recipe["style_path"])]
        qa_content = _labels(draft)
    if not all(urls):
        print("[imagery_transplant] anchor upload failed")
        return None

    did = draft.get("id") or uuid.uuid4().hex[:8]
    _pick = recipe.get("layout") or recipe.get("archetype") or "?"
    fin_dir = out_dir / "fal_images"
    fin_dir.mkdir(parents=True, exist_ok=True)
    brief = {"title": title, "content": qa_content, "palette": recipe["hex"],
             "kind": recipe.get("kind", "infographic")}
    qa_on = cfg.IMAGERY_QA_ENABLED and gemini_vision.available()

    # Render, finish, then visual-QA. On a failing QA verdict we regenerate once
    # (budget permitting) with the issues appended, then accept the best result.
    best_fin: Optional[str] = None
    best_score = -1
    feedback = ""
    for attempt in range(2):
        if attempt and not budget.can_spend(cost):
            break  # no budget for a retry; keep what we have
        prompt = base_prompt if not feedback else (
            f"{base_prompt}\n\nFIX THESE ISSUES from the previous attempt: {feedback}")
        raw = fal_client.generate_image_edit(
            prompt, urls, model=model,
            aspect=recipe["aspect"], output_dir=str(out_dir),
            filename=f"transplant_{brand}_{did}_raw{attempt}.png",
        )
        if not raw or not os.path.exists(raw):
            break
        budget.record(cost, label=f"transplant:{brand}:{recipe['palette']}:{_pick}")

        # Per-attempt filename so a lower-scoring retry never overwrites a better
        # earlier attempt that best_fin may still point to.
        fin = fin_dir / f"transplant_{brand}_{did}_{attempt}.png"
        try:
            pp.finish_file(raw, str(fin), light=recipe["light"])
            fin_path = str(fin)
        except Exception as exc:  # noqa: BLE001 (finish is enhancement, not gate)
            print(f"[imagery_transplant] finish failed: {exc}; using raw")
            fin_path = raw

        if not qa_on:
            print(f"[imagery_transplant] {brand} {recipe['palette']}|{_pick} -> {fin_path}")
            return fin_path

        verdict = gemini_vision.qa_image(fin_path, brief)
        if verdict["score"] > best_score:
            best_score, best_fin = verdict["score"], fin_path
        print(f"[imagery_transplant] {brand} {recipe['palette']}|{_pick} "
              f"QA={verdict['score']}/10 {'PASS' if verdict['passed'] else 'FAIL'} "
              f"-> {fin_path}")
        if verdict["passed"]:
            return fin_path
        feedback = "; ".join(verdict["issues"])[:400] or "improve text legibility and on-brief accuracy"

    return best_fin
