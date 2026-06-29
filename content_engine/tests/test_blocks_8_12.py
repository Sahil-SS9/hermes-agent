"""Tests for Blocks 8-12: QC hardening, image QA, OCR, source audit, normalisation.

Block 8: Retry reviewer threshold + QC hardening
Block 9: Gemini Vision QA on Codex images
Block 10: OCR text-legibility check
Block 11: Source-label audit
Block 12: Format consistency normalisation
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

import pytest

# Ensure content_engine root is on sys.path so tools.* is importable.
sys.path.insert(0, str(Path(__file__).parent.parent))

import blog.codex_image_gen as cig
from blog.blog_generator import _framework_prompt_builder  # Block 7 smoke
from tools.audit_source_labels import audit_post, audit_all
from tools.normalise_frontmatter import _normalise_field, normalise_file, normalise_all


# -- Block 8: Retry threshold tests -------------------------------------------

def test_block8_retry_score_check_imports():
    """Block 8: blog_generator imports logging for score threshold check."""
    import inspect
    from blog import blog_generator as bg
    src = inspect.getsource(bg)
    assert "retry_score" in src
    assert "logging" in src


def test_block8_strict_mode_rejects_low_score(monkeypatch):
    """Block 8: strict_review=True returns None when retry score < 6."""
    import blog.blog_generator as bg

    # Build a minimal chain that passes the gate but gets low review score.
    plan = {"topic_id": "t1", "title_hint": "t", "tags": [],
            "signals": [{"signal_id": "s1", "summary": "s"}]}
    draft = {"title": "Test", "description": "Desc", "body_md": "# Test\n\nBody.",
             "slug": "test", "tier": "ai", "tags": ["ai"], "format": "essay",
             "source": "manual", "stream": "ai", "signals": plan["signals"],
             "context": "", "kb_snippets": []}

    monkeypatch.setattr(bg, "write", lambda p, **kw: draft)
    monkeypatch.setattr(bg, "gate_check", lambda d: ("ok", []))

    # First review fails (triggers retry), second review passes gate but score=4.
    def fake_review_first(d, s):
        return {"passed": False, "issues": ["bad structure"], "score": 3,
                "degraded": False, "claims_to_verify": []}
    def fake_review_second(d, s):
        return {"passed": False, "issues": [], "score": 4,
                "degraded": False, "claims_to_verify": []}

    import blog.blog_reviewer as _br
    # Use a function wrapper that calls the right fake based on call count.
    _call_count = {"n": 0}
    def _review_side_effect(d, s):
        _call_count["n"] += 1
        if _call_count["n"] == 1:
            return fake_review_first(d, s)
        return fake_review_second(d, s)
    monkeypatch.setattr(_br, "review", _review_side_effect)
    monkeypatch.setattr(bg, "_verify_claims", lambda c: [])
    monkeypatch.setattr(bg, "_redact_draft", lambda d: None)
    monkeypatch.setattr(bg, "ground_post",
                        lambda d, stream: {"body_md": d.get("body_md", ""),
                                           "grounds": 0, "dead_links": [],
                                           "references_found": []})
    monkeypatch.setattr(bg, "_case_study_check",
                        lambda body, stream: ("ok", []))

    result = bg.write_with_gate(plan, stream="ai", strict_review=True)
    # Strict mode should reject on low score (4 < 6).
    assert result is None


# -- Block 9: Gemini Vision QA tests -----------------------------------------

def test_block9_gemini_vision_check_returns_score():
    """Block 9: _gemini_vision_check returns 0-10 score when Gemini available."""
    # The function degrades to -1 when google.generativeai is not installed.
    score = cig._gemini_vision_check("/tmp/nonexistent.png", "Title", "Desc")
    assert score == -1  # Degraded (no Gemini or file missing).


def test_block9_qa_retry_if_low_returns_score():
    """Block 9: _qa_retry_if_low returns a score or -1."""
    score = cig._qa_retry_if_low("/tmp/nonexistent.png", "Title", "Desc")
    assert score == -1  # Degraded.


def test_block9_gemini_functions_exist():
    """Block 9: Gemini Vision QA functions are defined in codex_image_gen."""
    assert hasattr(cig, "_gemini_vision_check")
    assert hasattr(cig, "_qa_retry_if_low")


# -- Block 10: OCR text-legibility tests -------------------------------------

def test_block10_ocr_functions_exist():
    """Block 10: OCR text check functions are defined in codex_image_gen."""
    assert hasattr(cig, "_ocr_text_check")
    assert hasattr(cig, "_has_significant_text")


def test_block10_ocr_text_check_degrades_when_no_tesseract():
    """Block 10: _ocr_text_check degrades gracefully when Tesseract missing."""
    with patch("subprocess.run", side_effect=FileNotFoundError("tesseract")):
        result = cig._ocr_text_check("/tmp/fake.png", "expected text")
    # Degrades to accept (legible=True).
    assert result["legible"] is True


def test_block10_ocr_text_check_finds_text():
    """Block 10: _ocr_text_check returns found text when Tesseract succeeds."""
    mock_result = MagicMock()
    mock_result.stdout = "MMLU Benchmark Results"
    with patch("subprocess.run", return_value=mock_result):
        result = cig._ocr_text_check("/tmp/fake.png", "MMLU")
    assert result["legible"] is True
    assert "MMLU" in result["found_text"]
    assert result["matches_expected"] is True


def test_block10_has_significant_text_threshold():
    """Block 10: _has_significant_text returns False for short text."""
    mock_result = MagicMock()
    mock_result.stdout = "ab"  # Very short text
    with patch("subprocess.run", return_value=mock_result):
        result = cig._has_significant_text("/tmp/fake.png", threshold=10)
    assert result is False


# -- Block 11: Source-label audit tests ---------------------------------------

def test_block11_audit_post_ok_for_research_paper_with_link(tmp_path):
    """Block 11: research-paper source with arXiv link is OK."""
    mdx = tmp_path / "test.mdx"
    mdx.write_text('---\ntitle: "Test"\nsource: research-paper\n---\n\nSee [paper](https://arxiv.org/abs/2303.08774).\n')
    result = audit_post(mdx)
    assert result["status"] == "ok"


def test_block11_audit_post_mismatch_no_link(tmp_path):
    """Block 11: research-paper without links is a mismatch."""
    mdx = tmp_path / "test.mdx"
    mdx.write_text('---\ntitle: "Test"\nsource: research-paper\n---\n\nJust text about AI.\n')
    result = audit_post(mdx)
    assert result["status"] == "mismatch"


def test_block11_audit_post_upgrade_manual_with_paper(tmp_path):
    """Block 11: manual source with paper reference is upgrade candidate."""
    mdx = tmp_path / "test.mdx"
    mdx.write_text('---\nsource: manual\ntitle: "Test"\n---\n\nSee arxiv.org/abs/2303.08774.\n')
    result = audit_post(mdx)
    assert result["status"] == "upgrade"


def test_block11_audit_all_returns_summary(tmp_path):
    """Block 11: audit_all returns a summary dict with counts."""
    for i in range(3):
        (tmp_path / f"post{i}.mdx").write_text(
            f'---\nsource: manual\ntitle: "Post{i}"\n---\n\nBody.\n'
        )
    report = audit_all(tmp_path)
    assert report["total"] == 3
    assert report["ok"] == 3
    assert "posts" in report


# -- Block 12: Frontmatter normalisation tests --------------------------------

def test_block12_normalise_unquotes_enum_fields():
    """Block 12: enum values like format: "essay" → format: essay."""
    assert _normalise_field("format", '"essay"') == "essay"
    assert _normalise_field("tier", '"pm"') == "pm"
    assert _normalise_field("source", '"research-paper"') == "research-paper"


def test_block12_normalise_quotes_string_fields():
    """Block 12: string values like title: Value → title: "Value"."""
    result = _normalise_field("title", "My Post Title")
    assert result.startswith('"')
    assert result.endswith('"')


def test_block12_normalise_unquotes_date_fields():
    """Block 12: date values unquoted."""
    assert _normalise_field("pubDate", '"2026-06-29"') == "2026-06-29"


def test_block12_normalise_file_dry_run(tmp_path):
    """Block 12: dry-run shows changes without writing."""
    mdx = tmp_path / "test.mdx"
    original = '---\ntitle: Test\nformat: "essay"\n---\n\nBody.\n'
    mdx.write_text(original)

    changes = normalise_file(mdx, dry_run=True)
    assert len(changes) > 0
    # File unchanged.
    assert mdx.read_text() == original


def test_block12_normalise_file_live(tmp_path):
    """Block 12: live run writes changes."""
    mdx = tmp_path / "test.mdx"
    mdx.write_text('---\ntitle: Test\nformat: "essay"\n---\n\nBody.\n')

    changes = normalise_file(mdx, dry_run=False)
    assert len(changes) > 0
    written = mdx.read_text()
    assert 'format: essay' in written
    assert '"Test"' in written


def test_block12_normalise_all(tmp_path):
    """Block 12: normalise_all processes all MDX files."""
    (tmp_path / "a.mdx").write_text('---\ntitle: A\nformat: "essay"\n---\n\n')
    (tmp_path / "b.mdx").write_text('---\ntitle: B\nformat: essay\n---\n\n')

    report = normalise_all(tmp_path, dry_run=True)
    assert report["total"] == 2
    # At least one needs changes (a.mdx has quoted format).
    assert report["changed"] >= 1