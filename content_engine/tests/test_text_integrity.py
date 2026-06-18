"""Tests for text_integrity.py. Generates its own sample images via PIL so no
pre-existing gallery images are needed."""

import pytest
import text_integrity as ti


def _make_test_image(text: str, path: str, width: int = 800, height: int = 120):
    """Create a PNG with white background and black text."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
    except Exception:
        font = ImageFont.load_default()
    draw.text((10, 30), text, fill="black", font=font)
    img.save(path)


def test_correct_text_passes(tmp_path):
    path = str(tmp_path / "good.png")
    _make_test_image("DEBUG A SCHEMA MISMATCH IN 5 MIN buildinpublic", path)
    ok, missing = ti.verify_text(path, ["DEBUG A SCHEMA MISMATCH", "buildinpublic"])
    assert ok, f"missing: {missing}"


def test_misspelled_text_fails(tmp_path):
    path = str(tmp_path / "bad.png")
    _make_test_image("XYBUG X SCHEMA WISPATCH", path)
    ok, missing = ti.verify_text(path, ["DEBUG A SCHEMA MISMATCH"])
    assert not ok
    assert missing


def test_normalisation():
    assert ti._norm("Don't  WATCH.\n") == "dont watch"
    assert ti._norm("Hello   World!!!") == "hello world"
    assert ti._norm("") == ""


def test_textless_image_passes(tmp_path):
    """An image with no text should NOT be flagged as having text."""
    from PIL import Image, ImageDraw
    path = str(tmp_path / "blank.png")
    img = Image.new("RGB", (400, 300), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([50, 50, 350, 250], fill="navy")
    img.save(path)
    assert not ti.has_significant_text(path), "blank image falsely flagged"


def test_textless_image_with_typos_fails(tmp_path):
    """An image WITH text (intended for a textless scene) should be rejected."""
    path = str(tmp_path / "typos.png")
    _make_test_image("DEBUG BUILD PRODUCTION DEPLOY", path)
    assert ti.has_significant_text(path), "text-filled image not flagged"
