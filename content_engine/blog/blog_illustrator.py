"""Blog illustrator - hero + per-section images via Codex CLI.

Replaces the previous FAL/imagery_transplant path. Uses codex_image_gen
(Codex CLI with ChatGPT auth, zero marginal cost per image).

One hero image + up to BLOG_MAX_SECTION_IMAGES per-section images.
Section images are keyed by H2 heading text.

Palette locking: Codex CLI does text-to-image, not reference-anchored edit,
so palette locking via anchor images is not applicable. Instead, explicit
colour guidance is included in the prompt text derived from the SahilBlog
brand aesthetic (futuristic, halftone, neon-on-dark).

No budget gating — Codex uses ChatGPT auth (zero marginal cost per image).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import config
from blog.blog_streams import STREAMS
from blog.codex_image_gen import generate_hero, generate_section


def _extract_h2_headings(body_md: str) -> list[str]:
    """Extract H2 heading texts from markdown body."""
    out = []
    for line in body_md.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            out.append(m.group(1).strip())
    return out


def _palette_for_stream(stream: str) -> str:
    """Return palette guidance text for the stream.

    The image_palette_brand field in blog_streams is now advisory text,
    not an anchor selector. We map it to a descriptive prompt fragment.
    """
    brand = STREAMS.get(stream, {}).get("image_palette_brand", "sahil_twitter")
    if brand == "sahil_twitter":
        return "futuristic neon-on-dark with halftone textures, acid gradients, pixel grids"
    return "futuristic neon-on-dark with halftone textures"


def illustrate(
    draft: dict,
    out_dir: Optional[Path] = None,
    max_sections: Optional[int] = None,
    workdir: Optional[str] = None,
) -> dict:
    """Generate hero + per-section images via Codex CLI.

    Returns {hero_path: str|None, section_paths: {h2_heading: path}}.
    When all attempts fail, returns None for that image (caller handles).

    Args:
        draft: Blog draft dict with title, description, body_md, stream.
        out_dir: Directory for generated images (defaults to OUTPUT_DIR/blog_images).
        max_sections: Maximum section images (defaults to config.BLOG_MAX_SECTION_IMAGES).
        workdir: Working directory for codex CLI (defaults to SahilBlog repo).
    """
    stream = draft.get("stream", "ai")
    palette = _palette_for_stream(stream)

    if max_sections is None:
        max_sections = config.BLOG_MAX_SECTION_IMAGES

    out_path = Path(out_dir) if out_dir else Path(config.OUTPUT_DIR) / "blog_images"
    out_path.mkdir(parents=True, exist_ok=True)

    # Default workdir to SahilBlog repo (trusted in codex config).
    if workdir is None:
        workdir = str(getattr(config, "SAHILBLOG_REPO", str(Path.home())))

    result: dict = {"hero_path": None, "section_paths": {}}

    # Hero image.
    title = draft.get("title", "")
    description = draft.get("description", "")
    hero_out = str(out_path / "hero.png")
    hero = generate_hero(
        title=title,
        description=description,
        out_path=hero_out,
        palette=palette,
        workdir=workdir,
    )
    if hero:
        result["hero_path"] = hero

    # Section images, capped at max_sections.
    if max_sections <= 0:
        return result

    headings = _extract_h2_headings(draft.get("body_md", ""))
    for idx, heading in enumerate(headings[:max_sections], 1):
        section_out = str(out_path / f"section_{idx:02d}.png")
        img = generate_section(
            title=title,
            heading=heading,
            out_path=section_out,
            palette=palette,
            workdir=workdir,
        )
        if img:
            result["section_paths"][heading] = img

    return result

def _extract_diagram_spec(draft: dict) -> str | None:
    """Extract Mermaid diagram code from a blueprint-format draft.

    Searches the body_md for a ```mermaid code block. Returns the code
    block content (without the fences) or None if not found.
    """
    import re as _re
    body = draft.get("body_md", "") or ""
    m = _re.search(r"```mermaid\n(.*?)```", body, _re.DOTALL)
    if m:
        return m.group(1).strip()
    return None
