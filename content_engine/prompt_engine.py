"""Track A: art-direction prompt engine for illustrated/photographic images.

Replaces the old constant per-brand ``visual_descs`` dict (the cause of every
post for a brand looking identical) with rich, fully art-directed prompts that
vary per post. Proven 2026-06-08: the same cheap model goes from "embarrassingly
poor" to good purely on prompt craft, so this is the main quality lever.

A prompt is composed from: subject + composition + lighting + medium/lens +
palette + mood + quality tail + strong negatives. Each axis rotates by a
deterministic hash of the draft id, so a brand's output is varied but
reproducible (no random churn between runs).

Usage:
    p, neg, model = build_illustrated_prompt(brand, subject_hint, draft_id)
"""
from __future__ import annotations

import hashlib
from typing import Optional, Tuple

from model_config import BASE_MODEL, HERO_MODEL

QUALITY = ("photorealistic, sharp focus, high detail, high dynamic range, "
           "professional, well composed")
ILLUS_QUALITY = ("highly detailed, clean linework, cohesive palette, "
                 "professional illustration, well composed")
NEGATIVE = ("text, letters, words, captions, watermark, logo, signature, gibberish, "
            "cartoon, lowres, oversaturated, harsh flash, cluttered, messy, amateur, "
            "deformed hands, extra fingers, blurry, jpeg artifacts, plastic skin, distorted")

# Per brand -> genre -> art-direction axes. {subject} is the per-post hook.
# Genres mirror the signed-off Track A taxonomy.
GENRES = {
    "plenishd": {
        "food_photo": {
            "base": "Warm editorial food photography of {subject}",
            "comp": ["overhead flat-lay with generous negative space",
                     "tight 45-degree hero angle, shallow focus",
                     "rustic table scene, ingredients scattered around"],
            "light": ["golden natural morning light, soft shadows",
                      "warm side light through a kitchen window"],
            "medium": ["shot on an 85mm lens at f/2.0, creamy bokeh",
                       "shot on a 50mm lens, crisp appetising detail"],
            "palette": "amber, warm-neutral and cream tones",
            "mood": "appetising, inviting, homely",
            "quality": QUALITY, "model": BASE_MODEL,
        },
        "craft_kitchen": {
            "base": "Hand-drawn editorial illustration of {subject}",
            "comp": ["cosy kitchen scene, ingredients laid out neatly",
                     "charming recipe-card composition with space at top"],
            "light": ["soft warm daylight", "gentle morning glow"],
            "medium": ["gouache and ink with kraft-paper texture",
                       "warm watercolour with visible paper grain"],
            "palette": "muted amber, cream and soft green",
            "mood": "charming, warm, homely",
            "quality": ILLUS_QUALITY, "model": BASE_MODEL,
        },
    },
    "coachos": {
        "editorial_sport": {
            "base": "Premium editorial sports photography of {subject}",
            "comp": ["tight three-quarter close-up, negative space upper third",
                     "wide cinematic frame, lone figure, clean grid composition"],
            "light": ["soft diffused overcast morning light from camera-left",
                      "flat grey natural light, dew on the grass catching light"],
            "medium": ["85mm lens at f/2.0, creamy bokeh of an empty pitch",
                       "documentary 35mm, matte filmic texture"],
            "palette": "near-monochrome desaturated grade with a single muted emerald-green accent",
            "mood": "quiet, determined, high craft",
            "quality": QUALITY, "model": BASE_MODEL,
        },
        "analytics_illustration": {
            "base": "Sophisticated editorial illustration of {subject}",
            "comp": ["clean modern sports-analytics layout, stylised pitch elements",
                     "minimal schematic composition, generous whitespace"],
            "light": ["even studio lighting", "flat editorial lighting"],
            "medium": ["clean vector-leaning illustration, subtle grain",
                       "premium infographic-style rendering"],
            "palette": "near-monochrome with a restrained green accent",
            "mood": "precise, premium, modern",
            "quality": ILLUS_QUALITY, "model": BASE_MODEL,
        },
    },
    "matchdaymaestro": {
        "matchday_hero": {
            "base": "Cinematic matchday-night illustration of {subject}",
            "comp": ["dramatic low hero angle under floodlights",
                     "dynamic action framing, deep stadium backdrop"],
            "light": ["intense stadium floodlights, dramatic rim light",
                      "crimson and gold rim light against deep blue night"],
            "medium": ["premium sports-poster render, ultra detailed",
                       "hyper-detailed cinematic illustration"],
            "palette": "deep navy night with electric crimson and gold accents",
            "mood": "energetic, epic, high-contrast",
            "quality": ILLUS_QUALITY, "model": HERO_MODEL,
        },
        # Reference-set learning: mythic engraved hero posters read as premium.
        "engraved_legend": {
            "base": "Dark mythic engraved poster of {subject} as a footballing legend",
            "comp": ["monumental low-angle heroic figure, stadium ruins and floodlight shafts behind",
                     "tight dramatic portrait, ornate engraved detail, ball and boots rendered like ancient relics"],
            "light": ["single dramatic shaft of floodlight through smoke, deep chiaroscuro",
                      "ember-lit haze catching fine engraved linework"],
            "medium": ["antique copperplate engraving with ink wash, heavy paper grain",
                       "dark etched poster art, dense crosshatch shading"],
            "palette": "charcoal black and desaturated navy with a faint crimson-gold glow",
            "mood": "mythic, reverent, epic",
            "quality": ILLUS_QUALITY, "model": BASE_MODEL,
        },
        "bold_poster": {
            "base": "Bold dynamic matchday poster illustration of {subject}",
            "comp": ["stylised silhouette, high-contrast graphic poster art",
                     "punchy diagonal composition, strong focal subject"],
            "light": ["dramatic floodlit backlight", "high-contrast stadium glow"],
            "medium": ["graphic poster illustration, flat bold shapes",
                       "screen-print poster aesthetic"],
            "palette": "deep navy with electric crimson and gold",
            "mood": "punchy, energetic",
            "quality": ILLUS_QUALITY, "model": BASE_MODEL,
        },
    },
    "kicktionary": {
        "storybook": {
            "base": "Award-winning children's picture-book watercolour illustration of {subject}",
            "comp": ["friendly mid-action poses, open sky at the top",
                     "playful balanced composition, rounded characters"],
            "light": ["soft natural sunlight", "bright cheerful daylight"],
            "medium": ["hand-painted gouache and watercolour, visible paper grain, gentle ink linework",
                       "soft watercolour textures, modern kids'-book illustration"],
            "palette": "cheerful grass-green, sky-blue and sunny yellow",
            "mood": "joyful, wholesome, educational",
            "quality": ILLUS_QUALITY, "model": BASE_MODEL,
        },
        "comic": {
            "base": "Ligne-claire comic panel of {subject}",
            "comp": ["dynamic action lines, clear focal character",
                     "bold panel composition, expressive motion"],
            "light": ["flat bright comic lighting", "cheerful even lighting"],
            "medium": ["clean bold outlines, flat cheerful colours, European comic style",
                       "ligne-claire ink with flat colour fills"],
            "palette": "bright primary palette",
            "mood": "fun, lively, educational",
            "quality": ILLUS_QUALITY, "model": BASE_MODEL,
        },
    },
    "sahil_twitter": {
        # Modelled on the 2026-06 reference set (~/Reference Images): dense
        # cyberpunk HUD posters — layered diegetic interface panels, a strong
        # character focal point, neon rim light, extreme detail density.
        # Panels carry abstract glyphs only; real text is overlaid in Pillow.
        "hud_poster": {
            "base": "Hyper-detailed cyberpunk anime poster of {subject}",
            "comp": ["lone focal character centre-frame surrounded by layered floating holographic HUD panels and status readouts with abstract glyphs",
                     "dense diegetic interface panels framing the edges, dramatic depth, rain-slick neon cityscape behind the focal subject"],
            "light": ["glowing violet and magenta neon rim light against near-black, volumetric haze",
                      "electric cyan and green terminal glow, deep shadow, cinematic contrast"],
            "medium": ["ultra-detailed digital anime illustration, intricate gear and cable detail, crisp rendering",
                       "premium cyberpunk key-art quality, dense environmental storytelling props"],
            "palette": "near-black with electric violet, magenta and acid-green accents",
            "mood": "intense, technical, obsessive craft",
            "quality": ILLUS_QUALITY, "model": HERO_MODEL,
        },
        "dark_engraving": {
            "base": "Dark vintage engraved-etching poster of {subject}",
            "comp": ["monumental centred heroic figure emerging from shadow, ruined classical architecture behind",
                     "tight dramatic three-quarter portrait, ornate engraved detail filling the frame"],
            "light": ["single shaft of pale light from above, deep chiaroscuro",
                      "smoky atmospheric glow catching fine engraved linework"],
            "medium": ["antique copperplate engraving and ink wash, heavy paper grain, Gustave Doré influence",
                       "dark academia etching, dense crosshatch shading"],
            "palette": "desaturated sepia-green and charcoal black with a faint gold glow",
            "mood": "epic, mythic, timeless",
            "quality": ILLUS_QUALITY, "model": BASE_MODEL,
        },
        "ai_concept": {
            "base": "Striking conceptual editorial tech illustration: {subject}",
            "comp": ["sleek isometric three-quarter perspective, negative space top-right",
                     "central glowing focal metaphor, dramatic depth"],
            "light": ["dramatic chiaroscuro lighting, volumetric haze",
                      "moody key light, deep shadow"],
            "medium": ["premium WIRED-cover render, intricate circuit-trace detail, crisp 3D-render quality",
                       "sophisticated editorial tech illustration, fine detail"],
            "palette": "deep near-black with electric indigo and acid-lime accents",
            "mood": "sophisticated, cinematic, intelligent",
            "quality": ILLUS_QUALITY, "model": HERO_MODEL,
        },
        "retro_tech": {
            "base": "Retro 1970s technical illustration of {subject}",
            "comp": ["vintage science-magazine layout, centred subject",
                     "charming retro diagram composition"],
            "light": ["flat retro print lighting", "even vintage illustration light"],
            "medium": ["halftone print texture, vintage science-magazine aesthetic",
                       "screen-print retro illustration with grain"],
            "palette": "warm mustard, rust and teal",
            "mood": "charming, nostalgic, clever",
            "quality": ILLUS_QUALITY, "model": BASE_MODEL,
        },
    },
    "sahil_linkedin": {
        "editorial_concept": {
            "base": "Restrained professional editorial illustration: {subject}",
            "comp": ["uncluttered composition, single clear focal idea, generous whitespace",
                     "clean modern business-magazine layout"],
            "light": ["soft neutral studio light", "even editorial lighting"],
            "medium": ["sophisticated business-magazine illustration, subtle texture",
                       "premium minimal editorial render"],
            "palette": "muted grey tones with one restrained indigo accent",
            "mood": "considered, premium, professional",
            "quality": ILLUS_QUALITY, "model": BASE_MODEL,
        },
    },
}

_DEFAULT_BRAND = "sahil_twitter"


def _seed(draft_id: str, brand: str) -> int:
    return int(hashlib.sha256(f"{brand}:{draft_id}".encode()).hexdigest(), 16)


def _pick(seq, seed: int, salt: int = 0):
    return seq[(seed + salt) % len(seq)]


def pick_genre(brand: str, draft_id: str, pillar: str = "") -> str:
    """Deterministically choose a genre for this brand+post."""
    genres = list(GENRES.get(brand, GENRES[_DEFAULT_BRAND]).keys())
    return _pick(genres, _seed(draft_id, brand), salt=7)


def build_illustrated_prompt(
    brand: str,
    subject_hint: str,
    draft_id: str = "",
    genre: Optional[str] = None,
    force_hero: bool = False,
) -> Tuple[str, str, str]:
    """Return (prompt, negative_prompt, model_key) for an illustrated base image.

    ``subject_hint`` is the per-post hook (topic/title/scene). It is the ONLY
    free-text input; everything else is art-directed and rotated by draft id.
    """
    brand = (brand or "").lower()
    book = GENRES.get(brand, GENRES[_DEFAULT_BRAND])
    g = genre if genre in book else pick_genre(brand, draft_id)
    spec = book[g]
    seed = _seed(draft_id, brand)

    subject = (subject_hint or "the subject").strip().rstrip(".")
    parts = [
        spec["base"].format(subject=subject) + ".",
        _pick(spec["comp"], seed, 1) + ".",
        _pick(spec["light"], seed, 2) + ".",
        _pick(spec["medium"], seed, 3) + ".",
        f"Colour palette: {spec['palette']}.",
        f"Mood: {spec['mood']}.",
        spec["quality"] + ".",
        "No text anywhere in the image.",
    ]
    prompt = " ".join(parts)
    model = HERO_MODEL if force_hero else spec.get("model", BASE_MODEL)
    return prompt, NEGATIVE, model


if __name__ == "__main__":
    for b in GENRES:
        p, n, m = build_illustrated_prompt(b, "a worked example subject", draft_id="demo123")
        print(f"\n## {b}  (model={m})\n{p}")
