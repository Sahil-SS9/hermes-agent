"""Reference-anchored transplant generator for personal-brand imagery.

Pipeline (validated 2026-06-16, see brand_imagery_standard.md):
  select_recipe -> structured labels -> dual-anchor prompt (baoyu LAYOUT exemplar
  for designed density + STYLE/palette exemplar for the look) -> nano-banana-pro/
  edit -> mandatory analog finish. Budget-gated. Returns a finished PNG path, or
  None so the caller falls back to the legacy path.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Optional

import budget
import fal_client
import imagery_library as lib
import postprocess as pp
from config import IMAGERY_EDIT_COST_GBP, IMAGERY_EDIT_MODEL
from infographic_content import build_ig_fields

_OUT = Path(__file__).resolve().parent / "output"

_CRAFT = (
    "Keep the brand craft constant: analog texture (film grain, halftone, subtle "
    "print/scanline), strong type hierarchy (distressed condensed display + clean "
    "labels + mono), designed information density, restrained composition. No human "
    "or anime character. All text crisp, correctly spelled, no gibberish."
)


def _labels(draft: dict) -> str:
    try:
        return build_ig_fields(draft).get("labels", "") or ""
    except Exception:  # noqa: BLE001
        return (draft.get("body_text") or "")[:300]


def build_edit_prompt(title: str, labels: str, palette_hex: str) -> str:
    """Compose the preserve-then-add prompt for the dual-anchor edit call."""
    return (
        "Create an infographic. Use the FIRST reference image ONLY as the LAYOUT / "
        "structure template (reproduce its designed density and arrangement). Use "
        "the SECOND reference image ONLY as the visual STYLE and colour reference. "
        f"Title: \"{title}\". Content: {labels}\n\n"
        f"PALETTE: {palette_hex}.\n\n{_CRAFT}"
    )


def generate(draft: dict, brand: str, out_dir: Optional[Path] = None,
             ctype: Optional[str] = None) -> Optional[str]:
    """Generate one finished hero via the transplant path. None on skip/failure."""
    recipe = lib.select_recipe(draft, brand, ctype=ctype)
    if not recipe:
        return None  # not infographic-family; caller uses the scene/hero fallback
    if not budget.can_spend(IMAGERY_EDIT_COST_GBP):
        print("[imagery_transplant] budget cap; skipping")
        return None

    out_dir = Path(out_dir or _OUT)
    title = (draft.get("title") or draft.get("topic") or "").strip()
    prompt = build_edit_prompt(title, _labels(draft), recipe["hex"])

    layout_url = fal_client.upload_file(recipe["layout_path"])
    style_url = fal_client.upload_file(recipe["style_path"])
    if not layout_url or not style_url:
        print("[imagery_transplant] anchor upload failed")
        return None

    did = draft.get("id") or uuid.uuid4().hex[:8]
    raw = fal_client.generate_image_edit(
        prompt, [layout_url, style_url], model=IMAGERY_EDIT_MODEL,
        aspect=recipe["aspect"], output_dir=str(out_dir),
        filename=f"transplant_{brand}_{did}_raw.png",
    )
    if not raw or not os.path.exists(raw):
        return None
    budget.record(IMAGERY_EDIT_COST_GBP,
                  label=f"transplant:{brand}:{recipe['palette']}:{recipe['layout']}")

    fin_dir = out_dir / "fal_images"
    fin_dir.mkdir(parents=True, exist_ok=True)
    fin = fin_dir / f"transplant_{brand}_{did}.png"
    try:
        pp.finish_file(raw, str(fin), light=recipe["light"])
    except Exception as exc:  # noqa: BLE001 (finish is enhancement, not gate)
        print(f"[imagery_transplant] finish failed: {exc}; returning raw")
        return raw
    print(f"[imagery_transplant] {brand} {recipe['palette']}|{recipe['layout']} -> {fin}")
    return str(fin)
