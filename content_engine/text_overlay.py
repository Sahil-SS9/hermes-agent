"""Crisp headline overlay on a treated background.

The base image is generated textless; all words are rendered here with Pillow
in brand fonts, so spelling is always correct and layout is controllable.
Editorial layout: brand badge top-left, headline over a bottom gradient scrim.
"""
from __future__ import annotations

import textwrap
import uuid
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from brand_style import FONTS, for_brand

OUTPUT_ROOT = Path(__file__).resolve().parent / "output"

# platform -> (w, h); mirrors config.PLATFORM_FORMATS image_size
SIZES = {
    "twitter": (1200, 1200),
    "instagram": (1080, 1350),
    "tiktok": (1080, 1920),
    "linkedin": (1200, 627),
}


def _font(key: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONTS[key], size)


def _fit_cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Resize + centre-crop the base image to exactly (w, h)."""
    img = img.convert("RGB")
    scale = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((left, top, left + w, top + h))


def _bottom_scrim(img: Image.Image, hex_colour: str, frac: float = 0.55, strength: float = 0.92) -> Image.Image:
    """Darken the lower portion with a vertical gradient for text legibility."""
    w, h = img.size
    r, g, b = (int(hex_colour.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    grad = np.zeros((h, w, 3), dtype=np.float32)
    start = int(h * (1 - frac))
    ramp = np.zeros(h, dtype=np.float32)
    ramp[start:] = np.linspace(0, strength, h - start)
    base = np.asarray(img, dtype=np.float32)
    scrim = np.array([r, g, b], dtype=np.float32)
    a = ramp[:, None, None]
    out = base * (1 - a) + scrim[None, None, :] * a
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


def _fit_headline(draw, text: str, max_w: int, start_px: int, min_px: int = 40):
    """Shrink font until the longest wrapped line fits max_w. Returns (font, lines)."""
    for size in range(start_px, min_px - 1, -4):
        font = _font("display", size)
        # estimate chars-per-line from average glyph width
        avg = max(1, draw.textlength("AVERAGEglyph", font=font) / 12)
        wrap_at = max(8, int(max_w / avg))
        lines = textwrap.wrap(text, width=wrap_at) or [text]
        if all(draw.textlength(ln, font=font) <= max_w for ln in lines) and len(lines) <= 4:
            return font, lines
    font = _font("display", min_px)
    return font, textwrap.wrap(text, width=max(8, int(max_w / max(1, draw.textlength("AVERAGEglyph", font=font) / 12)))) or [text]


def compose(
    background_path: str,
    brand: str,
    headline: str,
    platform: str = "twitter",
    badge: Optional[str] = None,
    sub: str = "",
    out_path: Optional[str] = None,
) -> str:
    visuals = for_brand(brand)
    colours = visuals["text"]
    w, h = SIZES.get(platform, (1200, 1200))

    img = _fit_cover(Image.open(background_path), w, h)
    img = _bottom_scrim(img, colours["scrim"])
    draw = ImageDraw.Draw(img)

    margin = int(w * 0.06)
    max_w = w - 2 * margin

    # ── brand badge (top-left) ──
    badge_text = (badge or visuals.get("badge") or brand).upper()
    badge_font = _font("bold", max(20, int(h * 0.022)))
    draw.text((margin, margin), badge_text, fill=colours["badge"], font=badge_font)

    # ── headline (bottom block) ──
    head_font, lines = _fit_headline(draw, headline.strip(), max_w, start_px=int(h * 0.085))
    line_h = int((head_font.getbbox("Ay")[3] - head_font.getbbox("Ay")[1]) * 1.18)

    sub_font = _font("medium", max(22, int(h * 0.026)))
    sub_h = (line_h + int(h * 0.02)) if sub else 0

    block_h = len(lines) * line_h + sub_h
    y = h - margin - block_h

    for ln in lines:
        draw.text((margin, y), ln, fill=colours["headline"], font=head_font)
        y += line_h
    if sub:
        y += int(h * 0.012)
        draw.text((margin, y), sub.strip(), fill=colours["sub"], font=sub_font)

    out_dir = OUTPUT_ROOT / (brand or "misc") / (platform or "x")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_path or str(out_dir / f"{uuid.uuid4().hex[:8]}.png")
    img.save(out, "PNG")
    return out
