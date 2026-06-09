"""Quality-first, budget-capped image generation for content drafts.

Degrading FAL chain, then a free fallback:
  1. krea_medium  (~£0.02/img, aesthetic detail)   ── primary
  2. z_image      (~£0.008/img, fast + detailed)
  3. flux_klein   (~£0.0048/img, fast)
  4. Pollinations (free, no key) via image_generator

Each tier is tried until one returns an image, so a rate-limit or outage on the
primary degrades quality rather than failing. Budget target: image + video
under £5-10/month (video defaults to free local ffmpeg). Set CONTENT_IMAGE_MODEL
to override the primary without a code change.

Gemini/nano-banana were dropped: the available Google keys have no working
quota (verified 2026-05-30). Output is a local PNG so the asset can be attached
to Discord for review and later published through Postiz.
"""
import os
import uuid
from pathlib import Path
from typing import List, Optional

OUTPUT_ROOT = Path(__file__).resolve().parent / "output"

# Degrading quality/cost chain. The primary is overridable via env for tuning.
_PRIMARY = os.getenv("CONTENT_IMAGE_MODEL", "krea_medium").strip()
FAL_CHAIN: List[str] = [_PRIMARY] + [m for m in ("z_image", "flux_klein") if m != _PRIMARY]

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


# Default illustrated base. krea-class beats z-image turbo decisively; the prompt
# engine (Track A) supplies the art direction. Overridable via env.
from model_config import BASE_MODEL  # noqa: E402


def generate_draft_image(
    prompt: str,
    brand: str = "",
    platform: str = "",
    draft_id: str = "",
    model: Optional[str] = None,
    negative_prompt: str = "",
) -> Optional[str]:
    """Generate a raw (textless) base image down the degrading chain.

    Returns a local PNG path or None. The caller passes a finished prompt
    (use ``build_scene_prompt``). ``model`` overrides the primary for one call.
    """
    primary = model or BASE_MODEL
    chain = [primary] + [m for m in FAL_CHAIN if m != primary]

    # 1. FAL tiers, degrading on failure/rate-limit.
    for tier in chain:
        try:
            import fal_client

            path = fal_client.generate_image(
                prompt, model=tier, aspect="square", negative_prompt=negative_prompt
            )
            if path and os.path.exists(path):
                print(f"[draft_media] base generated via {tier}: {path}")
                return path
        except Exception as exc:  # noqa: BLE001 (provider failures must fall through)
            print(f"[draft_media] FAL {tier} failed: {exc}")

    # 2. Free fallback: Pollinations.
    try:
        from image_generator import _pollinations_generate

        img_bytes = _pollinations_generate(prompt)
        out_dir = OUTPUT_ROOT / (brand or "misc") / (platform or "x")
        out_dir.mkdir(parents=True, exist_ok=True)
        fpath = out_dir / f"{draft_id or uuid.uuid4().hex[:8]}_base.png"
        fpath.write_bytes(img_bytes)
        print(f"[draft_media] pollinations (free) saved: {fpath} ({len(img_bytes)} bytes)")
        return str(fpath)
    except Exception as exc:  # noqa: BLE001
        print(f"[draft_media] pollinations failed: {exc}")

    return None


def _headline_from(draft: dict) -> str:
    """Pick a short, punchy headline from the draft for the image overlay."""
    title = (draft.get("title") or "").strip()
    if 8 <= len(title) <= 70:
        return title
    body = (draft.get("body_text") or "").strip()
    # first sentence / line, trimmed
    for sep in ("\n", ". ", "! ", "? "):
        if sep in body:
            body = body.split(sep)[0]
            break
    body = body.lstrip("#@ ").strip()
    return (body[:68].rsplit(" ", 1)[0] if len(body) > 68 else body) or (title or "")


def generate_post_image(
    draft: dict,
    model: Optional[str] = None,
    output_dir: Optional[str] = None,
    scene_prompt: Optional[str] = None,
) -> Optional[str]:
    """Full branded pipeline: textless base -> brand treatment -> headline overlay.

    Returns the path to the finished, publish-ready PNG (or None).
    ``scene_prompt`` overrides the auto-built base prompt (e.g. repurpose cron).
    """
    import postprocess
    import text_overlay
    from brand_style import for_brand
    from prompt_templates import build_scene_prompt, negative_prompt

    brand = (draft.get("brand") or "").lower()
    platform = draft.get("platform") or "twitter"
    draft_id = draft.get("id") or uuid.uuid4().hex[:8]

    # Route: data/comparison/list posts become AI infographics (text rendered by
    # the model, no overlay). Scene/hero posts stay illustrated. scene_prompt
    # (legacy/repurpose) always takes the illustrated path.
    if scene_prompt is None:
        from content_router import is_infographic

        if is_infographic(draft):
            import infographic_ai
            from infographic_content import build_ig_fields

            # Structure the flat draft text into layout-aware labels (left/right
            # sides, do/don't, ordered points) so the infographic reads cleanly.
            fields = build_ig_fields(draft)
            content = {
                "title": (draft.get("title") or draft.get("topic") or "").strip(),
                "body": (draft.get("body_text") or "")[:300],
                "labels": (draft.get("ig_labels") or fields["labels"]).strip(),
            }
            ig = infographic_ai.generate_infographic(
                brand, content, draft_id=draft_id, platform=platform,
                layout=draft.get("ig_layout") or fields["layout"],
            )
            if ig:
                print(f"[draft_media] infographic image: {ig}")
                return ig
            print("[draft_media] infographic path failed; falling back to illustrated")

    import budget
    from fal_client import MODEL_COST_GBP
    from model_config import HERO_COST_THRESHOLD_GBP, HERO_MODEL

    # Track A art direction. An explicit scene_prompt (e.g. repurpose cron) wins;
    # otherwise the prompt engine builds a rich per-post illustrated prompt from a
    # single subject hook, replacing the old constant per-brand visual_descs.
    if scene_prompt:
        prompt, neg = scene_prompt, negative_prompt()
        chosen = model or BASE_MODEL
    else:
        from prompt_engine import build_illustrated_prompt

        subject = (draft.get("visual_description") or draft.get("title")
                   or draft.get("topic") or (draft.get("body_text", "") or "")[:80]).strip()
        prompt, neg, eng_model = build_illustrated_prompt(
            brand, subject, draft_id=draft_id,
            force_hero=bool(model and model == HERO_MODEL),
        )
        chosen = model or eng_model

    # Budget gate: a hero model only runs if the month's cap allows it; otherwise
    # degrade to the cheap base. All successful paid gens are recorded.
    cost = MODEL_COST_GBP.get(chosen, 0.02)
    if cost > HERO_COST_THRESHOLD_GBP and not budget.can_spend(cost):
        print(f"[draft_media] budget cap hit; {chosen} -> {BASE_MODEL}")
        chosen = BASE_MODEL
        cost = MODEL_COST_GBP.get(chosen, 0.02)

    base = generate_draft_image(
        prompt, brand=brand, platform=platform, draft_id=draft_id,
        model=chosen, negative_prompt=neg,
    )
    if not base or not os.path.exists(base):
        return None
    # Persist the exact prompt fed to the model so the dashboard drawer can show
    # what generated this image. Best-effort; never fail media gen over it.
    try:
        from database import update_draft_image_prompt
        update_draft_image_prompt(draft_id, prompt)
    except Exception as exc:  # noqa: BLE001
        print(f"[draft_media] could not persist image prompt: {exc}")
    if cost > 0:
        budget.record(cost, label=f"{chosen}:{draft_id}")

    try:
        treated = postprocess.process_file(base, base.replace(".png", "_t.png"), brand)
        headline = _headline_from(draft)
        sub = draft.get("visual_sub", "") or ""
        # Kicker gives the post a message anchor; highlight gives colour pop on
        # the headline. Both optional; eyebrow falls back to the pillar label.
        eyebrow = (draft.get("eyebrow") or (draft.get("pillar", "") or "").replace("_", " ")
                   or draft.get("topic", "")).strip()
        highlight = (draft.get("highlight") or "").strip()
        final = text_overlay.compose(
            treated, brand, headline, platform=platform,
            badge=for_brand(brand).get("badge"), sub=sub,
            eyebrow=eyebrow, highlight=highlight,
        )
        print(f"[draft_media] branded image: {final}")
        return final
    except Exception as exc:  # noqa: BLE001 (finishing must not lose the base)
        print(f"[draft_media] finishing failed ({exc}); returning raw base")
        return base


def generate_draft_video(
    image_path: str, caption: str = "", brand: str = "", draft_id: str = "",
) -> Optional[str]:
    """Free motion video (ffmpeg) from a generated image + caption. mp4 or None.

    A paid AI-video model (FAL seedance/wan) can be slotted in later as a
    budget-gated upgrade; ffmpeg keeps the default at zero cost.
    """
    if not image_path or not os.path.exists(image_path):
        print("[draft_media] video needs a base image; none available.")
        return None
    try:
        from video_generator import create_image_slideshow_video

        out_dir = OUTPUT_ROOT / (brand or "misc") / "video"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = str(out_dir / f"{draft_id or uuid.uuid4().hex[:8]}.mp4")
        # No burned-in caption: the post copy carries the text, and multiline
        # captions trip a PIL anchor limitation. The clip is a clean branded
        # motion shot of the image. (caption kept in the signature for a future
        # AI-video upgrade that can use it as the generation prompt.)
        path = create_image_slideshow_video(
            image_paths=[image_path],
            captions=None,
            output_path=out,
            duration_per_image=5.0,
        )
        if path and os.path.exists(path):
            print(f"[draft_media] video saved: {path}")
            return path
    except Exception as exc:  # noqa: BLE001
        print(f"[draft_media] video generation failed: {exc}")
    return None
