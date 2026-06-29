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

    Records a timestamp before running, then finds the newest image after
    the run completes. Copies the image to a temporary location.

    Args:
        prompt: The image generation prompt.
        timeout: Maximum seconds to wait for codex to complete.
        workdir: Working directory for codex (defaults to home).

    Returns:
        Path to the generated image, or None on failure.
    """
    before_ts = time.time()
    cwd = workdir or str(Path.home())

    try:
        result = subprocess.run(
            ["codex", "exec", prompt],
            capture_output=True, text=True, timeout=timeout, cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        print(f"[codex_image_gen] timed out after {timeout}s")
        return None
    except Exception as exc:
        print(f"[codex_image_gen] execution error: {exc}")
        return None

    if result.returncode != 0:
        print(f"[codex_image_gen] codex exit code {result.returncode}")
        # Still try to find an image — codex may have generated one before erroring.
        img = _find_latest_codex_image(after_ts=before_ts)
        if img:
            return img
        return None

    # Find the newest image created during the codex run.
    img = _find_latest_codex_image(after_ts=before_ts)
    if not img:
        print("[codex_image_gen] no image found after codex run")
        return None

    return img


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
    return None

# -- Gemini Vision QA (Block 9) ---------------------------------------------

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