"""Cost-first image generation for content drafts.

Order, cheapest-first:
  1. FAL flux_klein  (~£0.0048/img, tested working) via fal_client
  2. Pollinations    (free, no key) via image_generator

Both save a local PNG so the asset can be attached to Discord for review and,
later, published through Postiz. Gemini/nano-banana were dropped: the available
Google keys have no working quota (verified 2026-05-30).
"""
import os
import uuid
from pathlib import Path
from typing import Optional

OUTPUT_ROOT = Path(__file__).resolve().parent / "output"

# On-brand art direction so even an un-enriched prompt looks intentional.
# Brand palettes are the canonical ones from the project brief.
BRAND_STYLE = {
    "plenishd": "warm dark background #2C2A28, Plenishd yellow #FBBF24 accent, modern, appetising, clean sans-serif",
    "coachos": "editorial near-monochrome, restrained green accent, premium sports design, clean grid, high contrast",
    "matchdaymaestro": "bold matchday energy, stadium-night palette, punchy football graphic, high contrast",
    "sahil_twitter": "dark terminal aesthetic, monospace code overlay, build-in-public, minimal",
    "sahil_linkedin": "professional editorial graphic, clean typography, grey tones with a single accent, restrained",
}


def build_prompt(brand: str, body_text: str, visual_description: str = "") -> str:
    """Derive an on-brand image prompt. Prefers an explicit art-directed prompt."""
    style = BRAND_STYLE.get((brand or "").lower(), "modern, clean, high-contrast social media graphic")
    core = (visual_description or body_text or "social media visual").strip()
    return (
        f"Social media graphic for {brand}. {core[:240]}. "
        f"Style: {style}. No watermark, no gibberish text, professional, eye-catching."
    )


def generate_draft_image(
    prompt: str,
    brand: str = "",
    platform: str = "",
    draft_id: str = "",
    model: str = "flux_klein",
) -> Optional[str]:
    """Generate an image cheapest-first. Returns a local PNG path, or None.

    The caller passes a finished prompt (use ``build_prompt`` if none supplied).
    """
    # 1. Cheap FAL (flux_klein) — tested working, ~£0.0048/img.
    try:
        import fal_client

        path = fal_client.generate_image(prompt, model=model, aspect="square")
        if path and os.path.exists(path):
            return path
    except Exception as exc:  # noqa: BLE001 — provider failures must fall through
        print(f"[draft_media] FAL failed: {exc}")

    # 2. Free fallback: Pollinations.
    try:
        from image_generator import _pollinations_generate

        img_bytes = _pollinations_generate(prompt)
        out_dir = OUTPUT_ROOT / (brand or "misc") / (platform or "x")
        out_dir.mkdir(parents=True, exist_ok=True)
        fpath = out_dir / f"{draft_id or uuid.uuid4().hex[:8]}.png"
        fpath.write_bytes(img_bytes)
        print(f"[draft_media] pollinations saved: {fpath} ({len(img_bytes)} bytes)")
        return str(fpath)
    except Exception as exc:  # noqa: BLE001
        print(f"[draft_media] pollinations failed: {exc}")

    return None
