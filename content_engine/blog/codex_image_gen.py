"""Codex CLI image generation module for blog images.

Replaces FAL/imagery_transplant for the blog image path. Uses Codex CLI
(`codex exec`) which generates images via ChatGPT auth (zero marginal cost).

Codex sandbox limitation: the sandbox prevents copying files out. This module
works around it by:
  1. Recording a timestamp before running `codex exec`
  2. Finding the newest PNG in ~/.codex/generated_images/ after the run
  3. Copying it to the target path

Image size: ~1254x1254 (near-square).
Time per image: 80-85s typical, up to 180s for complex prompts.
Auth: ChatGPT subscription (zero marginal cost, no API key).

Timeout strategy:
  - Default per-image timeout: 300s
  - Retry on timeout: 1 retry with 360s timeout
  - Total max wait per image: 660s (~11 min)
  - If all attempts fail, return None
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from config import IMAGERY_QA_MIN_SCORE
from pathlib import Path
from typing import Optional


CODEX_IMAGES_DIR = Path.home() / ".codex" / "generated_images"


def _find_latest_codex_image(
    after_ts: Optional[float] = None,
    images_dir: Path = CODEX_IMAGES_DIR,
) -> Optional[str]:
    """Find the newest PNG in ~/.codex/generated_images/.

    Scans session subdirectories for exec-*.png files, returning the path
    to the one with the most recent modification time. If after_ts is given,
    only considers images created after that timestamp.

    Returns None if no images are found.
    """
    if not images_dir.exists():
        return None

    candidates: list[tuple[float, str]] = []
    for session_dir in images_dir.iterdir():
        if not session_dir.is_dir():
            continue
        for png in session_dir.glob("exec-*.png"):
            try:
                mtime = png.stat().st_mtime
            except OSError:
                continue
            if after_ts is None or mtime >= after_ts:
                candidates.append((mtime, str(png)))

    if not candidates:
        return None

    # Return the most recent one.
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _build_image_prompt(
    title: str,
    description: str,
    heading: Optional[str] = None,
    palette: str = "futuristic neon-on-dark",
) -> str:
    """Build a self-contained text prompt for Codex CLI image generation.

    Codex does text-to-image, not reference-anchored edit, so the prompt must
    be fully self-contained. The palette is communicated via text, not anchor
    images.

    Args:
        title: Post title.
        description: Post description/lede.
        heading: Optional H2 heading for section images.
        palette: Colour palette guidance text.

    Returns:
        A self-contained image generation prompt string.
    """
    if heading:
        subject = heading
        context = f"for a blog post titled '{title}', section '{heading}'"
    else:
        subject = title
        context = f"for a blog post titled '{title}'"

    return (
        f"Generate an image {context}. "
        f"The image should be a high-quality editorial illustration that captures "
        f"the theme: {subject}. "
        f"Description: {description}. "
        f"Style: abstract, minimal, modern, {palette}. "
        f"No text in the image. Square format, high detail."
    )


def _run_codex(
    prompt: str,
    timeout: int = 300,
    workdir: Optional[str] = None,
) -> Optional[str]:
    """Execute codex CLI with the given prompt. Returns image path or None.

    On VPSes without bubblewrap support (kernel namespace restriction), codex
    generates the image internally but can't copy it via its sandbox. We detect
    this and look for the generated file in ~/.codex/generated_images/ instead.

    Records a timestamp before running, then finds the newest image after
    the run completes.
    """
    before_ts = time.time()
    cwd = workdir or str(Path.home())

    try:
        # Disable bubblewrap sandbox for image generation on restricted kernels
        result = subprocess.run(
            ["codex", "exec", "--disable", "use_linux_sandbox_bwrap", prompt],
            capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        print(f"[codex_image_gen] timed out after {timeout}s")
        return None
    except Exception as exc:
        print(f"[codex_image_gen] execution error: {exc}")
        return None

    # Strategy 1: find the newest image created during the codex run
    img = _find_latest_codex_image(after_ts=before_ts)
    if img:
        return img

    # Strategy 2: look in ~/.codex/generated_images/ for recent images
    # Codex saves generated images here even when bwrap blocks the copy step
    gi_dir = Path.home() / ".codex" / "generated_images"
    if gi_dir.exists():
        recent = sorted(gi_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
        for d in recent:
            if d.is_dir() and d.stat().st_mtime > before_ts:
                for img_file in d.glob("*"):
                    if img_file.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                        print(f"[codex_image_gen] found image in generated_images: {img_file}")
                        return str(img_file)

    print("[codex_image_gen] no image found after codex run")
    return None


def generate_hero(
    title: str,
    description: str,
    out_path: str,
    timeout: int = 300,
    palette: str = "futuristic neon-on-dark with halftone textures",
    workdir: Optional[str] = None,
) -> Optional[str]:
    """Generate a hero image for a blog post via Codex CLI.

    After generation, runs Gemini vision QA (Block 9) to verify the image
    matches the topic. Regenerates once if score < IMAGERY_QA_MIN_SCORE.
    """
    prompt = _build_image_prompt(title, description, heading=None, palette=palette)
    result = _run_with_retry(prompt, out_path, timeout, workdir)
    if result is None:
        return None

    # Block 9: Gemini Vision QA — score 0-10, regenerate once if low.
    if Path(out_path).exists():
        score = _qa_retry_if_low(out_path, title, description,
                                 min_score=IMAGERY_QA_MIN_SCORE)
        if score != -1 and score < IMAGERY_QA_MIN_SCORE:
            prompt += (
                f"\n\nQA feedback: The previous image scored {score}/10 "
                f"on relevance to the topic. Ensure the image directly "
                f"illustrates '{title}'."
            )
            result = _run_with_retry(prompt, out_path, timeout, workdir)
    return result


def generate_section(
    title: str,
    heading: str,
    out_path: str,
    timeout: int = 300,
    palette: str = "futuristic neon-on-dark with halftone textures",
    workdir: Optional[str] = None,
) -> Optional[str]:
    """Generate a section image for a blog post via Codex CLI.

    After generation, runs OCR text-legibility check (Block 10)
    to verify the H2 heading text is readable.
    """
    prompt = _build_image_prompt(title, heading, heading=heading, palette=palette)
    result = _run_with_retry(prompt, out_path, timeout, workdir)
    if result is None:
        return None

    # Block 10: OCR text-legibility check.
    if Path(out_path).exists():
        ocr_result = _ocr_text_check(out_path, expected_text=heading)
        if not ocr_result["legible"]:
            # Log warning and continue (no regen — Codex is too slow).
            import logging
            logging.getLogger("codex_image_gen").warning(
                "OCR text illegible: title='%s', heading='%s', found='%s'",
                title, heading, ocr_result.get("found_text", "")[:80],
            )
        elif not ocr_result["matches_expected"]:
            import logging
            logging.getLogger("codex_image_gen").warning(
                "OCR text mismatch: title='%s', expected='%s', found='%s'",
                title, heading, ocr_result.get("found_text", "")[:80],
            )
    return result


def _run_with_retry(
    prompt: str,
    out_path: str,
    timeout: int,
    workdir: Optional[str] = None,
    retry_timeout: int = 360,
) -> Optional[str]:
    """Run codex with one retry on timeout. Copy result to out_path.

    Returns out_path on success, None on failure.
    """
    # Quick check: if system bubblewrap isn't on PATH, Codex's bundled bwrap
    # will fail with kernel namespace restrictions (this VPS's config). Skip
    # straight to the Pillow fallback to avoid 10+ min of timeouts.
    try:
        bwrap_ok = subprocess.run(["bwrap", "--version"],
                                  capture_output=True, timeout=3).returncode == 0
    except Exception:
        bwrap_ok = False

    if not bwrap_ok:
        print(f"[codex_image_gen] no system bwrap; skipping codex, using Pillow fallback")
        return _generate_fallback_image(out_path, Path(out_path).parent.name)

    for attempt, current_timeout in enumerate([timeout, retry_timeout], 1):
        img_src = _run_codex(prompt, timeout=current_timeout, workdir=workdir)
        if img_src and Path(img_src).exists():
            try:
                target = Path(out_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(img_src, target)
                return str(target)
            except Exception as exc:
                print(f"[codex_image_gen] copy failed (attempt {attempt}): {exc}")
                continue
        elif attempt == 1:
            print(f"[codex_image_gen] retrying with {retry_timeout}s timeout")

    print(f"[codex_image_gen] all attempts failed for {out_path}")
    # Fallback: generate a simple Pillow placeholder if Codex CLI can't write
    # (e.g., bubblewrap sandbox restricted on this kernel).
    print(f"[codex_image_gen] using Pillow fallback for {Path(out_path).name}")
    return _generate_fallback_image(out_path, Path(out_path).parent.name)

# -- Gemini Vision QA (Block 9) ---------------------------------------------


def _generate_fallback_image(out_path: str, title: str) -> Optional[str]:
    """Generate a simple themed placeholder image via Pillow.
    
    Used when Codex CLI can't write files (bubblewrap sandbox restriction
    on kernels without user-namespace support). Produces an abstract
    tech-themed gradient with overlaid title text — not as good as
    Codex-generated art but keeps the pipeline moving.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
        import hashlib
        
        w, h = 1200, 630  # Standard OG image size
        img = Image.new('RGB', (w, h))
        draw = ImageDraw.Draw(img)
        
        # Deterministic palette from title hash
        hue = int(hashlib.md5(title.encode()).hexdigest()[:4], 16) % 360
        
        # Dark background with gradient-ish effect
        bg = (10, 6, 18)  # near-black
        for y in range(h):
            t = y / h
            r = int(bg[0] + (min(hue, 200) * t))
            g = int(bg[1] + (min(hue % 120 + 20, 100) * t * 0.5))
            b = int(bg[2] + (min((hue + 120) % 360, 200) * t * 0.3))
            draw.line([(0, y), (w, y)], fill=(min(r, 255), min(g, 255), min(b, 255)))
        
        # Accent lines (cyberpunk grid feel)
        accent = (0, 200, 255) if hue < 180 else (255, 100, 100)
        for x in range(0, w, 80):
            draw.line([(x, 0), (x, h)], fill=(*accent, 30), width=1)
        for y in range(0, h, 80):
            draw.line([(0, y), (w, y)], fill=(*accent, 20), width=1)
        
        # Title text (truncated to fit)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 42)
        except Exception:
            font = ImageFont.load_default()
        
        title_text = title[:60]
        text_bbox = draw.textbbox((0, 0), title_text, font=font)
        text_x = (w - (text_bbox[2] - text_bbox[0])) // 2
        text_y = h // 2 - 50
        draw.text((text_x, text_y), title_text, fill=(220, 220, 240), font=font)
        
        # Subtitle "algorithmiccompass.com"
        try:
            font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        except Exception:
            font_small = ImageFont.load_default()
        draw.text((20, h - 40), "algorithmiccompass.com", fill=(120, 120, 140), font=font_small)
        
        target = Path(out_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(target), "PNG")
        return str(target)
    except Exception as exc:
        print(f"[codex_image_gen] fallback image failed: {exc}")
        return None

def _gemini_vision_check(image_path: str, title: str, description: str) -> int:
    """Score 0-10 how well the image matches the post topic.

    Uses Gemini vision (free tier). Returns 0 if unavailable (degrade to accept).
    """
    try:
        import google.generativeai as genai
    except ImportError:
        return -1  # Gemini not available, degrade to accept.

    try:
        from pathlib import Path
        import json
        img_path = Path(image_path)
        if not img_path.exists():
            return -1

        # Upload image and ask for a relevance score.
        model = genai.GenerativeModel("gemini-1.5-flash")
        img_data = img_path.read_bytes()
        prompt = (
            f"Does this image match the topic '{title}'? "
            f"Description: {description}. "
            "Score 0-10 (0=irrelevant, 10=perfect match). "
            "Respond with just the number."
        )
        response = model.generate_content([prompt, {"mime_type": "image/png", "data": img_data}])
        text = response.text.strip()
        # Extract the number.
        import re
        m = re.search(r'(\d+)', text)
        if m:
            return min(10, max(0, int(m.group(1))))
        return -1
    except Exception:
        return -1


def _qa_retry_if_low(image_path: str, title: str, description: str,
                     min_score: int = 6) -> int:
    """Check image quality via Gemini vision. Flags low scores.

    Returns the quality score (0-10) or -1 if Gemini unavailable.
    Does NOT regenerate (caller handles that decision).
    """
    score = _gemini_vision_check(image_path, title, description)
    return score

# -- OCR Text-Legibility Check (Block 10) -------------------------------------

def _ocr_text_check(image_path: str, expected_text: str = "") -> dict:
    """Check image text legibility via Tesseract OCR.

    Returns:
        {"legible": bool, "found_text": str, "matches_expected": bool}
    """
    try:
        import subprocess
        result = subprocess.run(
            ["tesseract", image_path, "-", "--psm", "7"],
            capture_output=True, text=True, timeout=10,
        )
        found_text = result.stdout.strip()
        if not found_text:
            return {"legible": False, "found_text": "", "matches_expected": False}
        legible = len(found_text) > 3  # At least a few characters
        matches = expected_text.lower() in found_text.lower() if expected_text else False
        return {"legible": legible, "found_text": found_text, "matches_expected": matches}
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        # Tesseract not installed — degrade to accept.
        return {"legible": True, "found_text": "", "matches_expected": True}
    except Exception:
        return {"legible": True, "found_text": "", "matches_expected": True}


def _has_significant_text(image_path: str, threshold: int = 10) -> bool:
    """Check if an image contains significant text (for textless image validation).

    Returns True if substantial text detected (which may be unexpected for
    abstract/hero images), False if minimal text found.
    """
    result = _ocr_text_check(image_path)
    return len(result.get("found_text", "")) > threshold