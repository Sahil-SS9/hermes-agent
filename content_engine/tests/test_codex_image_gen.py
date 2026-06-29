"""Tests for blog.codex_image_gen — Codex CLI image generation module.

Covers:
  - _find_latest_codex_image: timestamp filtering, empty dir, missing dir
  - _build_image_prompt: hero vs section, palette inclusion
  - _run_codex: timeout, exit code, image discovery
  - generate_hero / generate_section: public API with retry
  - _run_with_retry: copy on success, retry on timeout, all-fail
"""
import shutil
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import blog.codex_image_gen as cig


def _make_fake_png(path):
    """Create a real 1x1 PNG at the given path so Path.exists() passes."""
    import struct, zlib
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IHHBBBB", 1, 1, 8, 0, 0, 0, 0)
    ihdr_chunk = b"IHDR" + ihdr
    ihdr_crc = struct.pack(">I", zlib.crc32(ihdr_chunk) & 0xFFFFFFFF)
    ihdr_full = struct.pack(">I", len(ihdr)) + ihdr_chunk + ihdr_crc
    raw = b"\x00\xff\xff\xff"
    comp = zlib.compress(raw)
    idat_chunk = b"IDAT" + comp
    idat_crc = struct.pack(">I", zlib.crc32(idat_chunk) & 0xFFFFFFFF)
    idat_full = struct.pack(">I", len(comp)) + idat_chunk + idat_crc
    iend = b"IEND"
    iend_crc = struct.pack(">I", zlib.crc32(iend) & 0xFFFFFFFF)
    iend_full = struct.pack(">I", 0) + iend + iend_crc
    path.write_bytes(sig + ihdr_full + idat_full + iend_full)
    return str(path)


# -- _find_latest_codex_image tests -----------------------------------------

def test_find_latest_returns_none_for_missing_dir(tmp_path):
    """Returns None when the images directory does not exist."""
    result = cig._find_latest_codex_image(images_dir=tmp_path / "nonexistent")
    assert result is None


def test_find_latest_returns_none_for_empty_dir(tmp_path):
    """Returns None when no PNG files exist."""
    (tmp_path / "session1").mkdir()
    result = cig._find_latest_codex_image(images_dir=tmp_path)
    assert result is None


def test_find_latest_returns_newest_png(tmp_path):
    """Returns the path to the newest PNG in session subdirectories."""
    session = tmp_path / "session-abc"
    session.mkdir()
    old_png = session / "exec-old.png"
    new_png = session / "exec-new.png"
    old_png.write_bytes(b"\x89PNG\r\n\x1a\n")
    new_png.write_bytes(b"\x89PNG\r\n\x1a\n")
    import os
    old_ts = time.time() - 10
    new_ts = time.time() - 1
    os.utime(old_png, (old_ts, old_ts))
    os.utime(new_png, (new_ts, new_ts))

    result = cig._find_latest_codex_image(images_dir=tmp_path)
    assert result is not None
    assert "exec-new.png" in result


def test_find_latest_filters_by_after_ts(tmp_path):
    """Only returns images created after the given timestamp."""
    session = tmp_path / "session-abc"
    session.mkdir()
    old_png = session / "exec-old.png"
    new_png = session / "exec-new.png"
    old_png.write_bytes(b"\x89PNG\r\n\x1a\n")
    new_png.write_bytes(b"\x89PNG\r\n\x1a\n")
    base_ts = time.time()
    import os
    os.utime(old_png, (base_ts - 20, base_ts - 20))
    os.utime(new_png, (base_ts - 5, base_ts - 5))

    result = cig._find_latest_codex_image(after_ts=base_ts - 10, images_dir=tmp_path)
    assert result is not None
    assert "exec-new.png" in result
    assert "exec-old.png" not in result


# -- _build_image_prompt tests -----------------------------------------------

def test_build_image_prompt_hero():
    """Hero prompt includes title, description, and palette."""
    prompt = cig._build_image_prompt("Token-Maxing", "A claim about edges")
    assert "Token-Maxing" in prompt
    assert "A claim about edges" in prompt
    assert "neon-on-dark" in prompt


def test_build_image_prompt_section():
    """Section prompt includes heading and title context."""
    prompt = cig._build_image_prompt(
        "Token-Maxing", "A claim", heading="The mechanism",
    )
    assert "The mechanism" in prompt
    assert "Token-Maxing" in prompt


def test_build_image_prompt_custom_palette():
    """Custom palette is included in the prompt."""
    prompt = cig._build_image_prompt(
        "T", "D", palette="warm monochrome",
    )
    assert "warm monochrome" in prompt


# -- _run_codex tests ---------------------------------------------------------

@patch("blog.codex_image_gen.subprocess.run")
@patch("blog.codex_image_gen._find_latest_codex_image")
def test_run_codex_success(mock_find, mock_run):
    """_run_codex returns image path on successful codex execution."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    mock_find.return_value = "/fake/path/image.png"
    result = cig._run_codex("test prompt", timeout=10)
    assert result == "/fake/path/image.png"
    mock_run.assert_called_once()


@patch("blog.codex_image_gen.subprocess.run")
def test_run_codex_timeout(mock_run):
    """_run_codex returns None on timeout."""
    import subprocess
    mock_run.side_effect = subprocess.TimeoutExpired("codex", 10)
    result = cig._run_codex("test prompt", timeout=10)
    assert result is None


@patch("blog.codex_image_gen.subprocess.run")
@patch("blog.codex_image_gen._find_latest_codex_image")
def test_run_codex_finds_image_even_on_nonzero_exit(mock_find, mock_run):
    """Codex may generate an image before returning non-zero; still find it."""
    mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
    mock_find.return_value = "/fake/path/image.png"
    result = cig._run_codex("test prompt", timeout=10)
    assert result == "/fake/path/image.png"


# -- _run_with_retry tests ----------------------------------------------------

@patch("blog.codex_image_gen._run_codex")
def test_run_with_retry_success_first_attempt(mock_run, tmp_path):
    """_run_with_retry copies and returns out_path on first success."""
    src = _make_fake_png(tmp_path / "codex_src.png")
    mock_run.return_value = src
    out = str(tmp_path / "out.png")
    result = cig._run_with_retry("prompt", out, timeout=10)
    assert result == out
    assert Path(out).exists()


@patch("blog.codex_image_gen._run_codex")
def test_run_with_retry_retries_on_failure(mock_run, tmp_path):
    """_run_with_retry retries when the first attempt fails."""
    src = _make_fake_png(tmp_path / "codex_src.png")
    mock_run.side_effect = [None, src]
    out = str(tmp_path / "out.png")
    result = cig._run_with_retry("prompt", out, timeout=10)
    assert result == out
    assert mock_run.call_count == 2


@patch("blog.codex_image_gen._run_codex")
def test_run_with_retry_all_fail(mock_run):
    """_run_with_retry returns None when all attempts fail."""
    mock_run.return_value = None
    result = cig._run_with_retry("prompt", "/tmp/out.png", timeout=10)
    assert result is None
    assert mock_run.call_count == 2


@patch("blog.codex_image_gen._run_codex")
def test_generate_hero_calls_run_with_retry(mock_run, tmp_path):
    """generate_hero passes through to _run_with_retry with hero prompt."""
    src = _make_fake_png(tmp_path / "codex_src.png")
    mock_run.return_value = src
    out = str(tmp_path / "hero.png")
    result = cig.generate_hero("Title", "Desc", out, timeout=10)
    assert result == out


@patch("blog.codex_image_gen._run_codex")
def test_generate_section_calls_run_with_retry(mock_run, tmp_path):
    """generate_section passes through to _run_with_retry with section prompt."""
    src = _make_fake_png(tmp_path / "codex_src.png")
    mock_run.return_value = src
    out = str(tmp_path / "sec.png")
    result = cig.generate_section("Title", "Heading", out, timeout=10)
    assert result == out