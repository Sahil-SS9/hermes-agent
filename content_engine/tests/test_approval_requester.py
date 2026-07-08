"""Tests for scripts/approval_requester.py — the no-agent batch summary script."""
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

SCRIPT = Path("/home/kensei/repos/KenseiAgent/content_engine/scripts/approval_requester.py")
sys.path.insert(0, str(SCRIPT.parent))
_spec = importlib.util.spec_from_file_location("approval_requester", SCRIPT)
assert _spec is not None and _spec.loader is not None
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)
assert isinstance(mod, ModuleType)


def _entry(slug="s", title="T", preview="/nope.html"):
    return {
        "title": title, "slug": slug, "stream": "ai", "tier": "ai",
        "preview_path": preview, "mdx_path": "/tmp/y.mdx",
    }


def _set_tracker(path: Path) -> None:
    setattr(mod, "TRACKER", path)


def test_load_pending_returns_list():
    pending = mod.load_pending()
    assert isinstance(pending, list)


def test_build_message_includes_media_for_each():
    pending = mod.load_pending()
    if not pending:
        return
    msg = mod.build_message(pending)
    assert msg.count("MEDIA:") == len(pending)


def test_build_message_silent_when_empty(tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    _set_tracker(empty)
    assert mod.build_message(mod.load_pending()) == "[SILENT]"


def test_build_message_handles_missing_preview():
    msg = mod.build_message([_entry(preview="/nonexistent/x.html")])
    assert "(preview missing" in msg
    assert "MEDIA:" not in msg


def test_build_message_handles_oversize_preview(tmp_path):
    big = tmp_path / "big.html"
    big.write_text("x" * (9 * 1024 * 1024))
    msg = mod.build_message([_entry(preview=str(big))])
    assert "(preview too large" in msg
    assert "MEDIA:" not in msg


def test_build_message_includes_valid_media(tmp_path):
    small = tmp_path / "ok.html"
    small.write_text("<h1>OK</h1>")
    msg = mod.build_message([_entry(preview=str(small))])
    assert f"MEDIA:{small}" in msg


def test_pending_previews_all_exist_in_safe_roots():
    pending = mod.load_pending()
    for e in pending:
        p = Path(e["preview_path"])
        assert p.exists(), f"Missing preview: {p}"
        assert "/.hermes/reports/blog-previews/" in str(p), f"Not in safe roots: {p}"


def test_pending_previews_under_8mb():
    pending = mod.load_pending()
    for e in pending:
        size_kb = Path(e["preview_path"]).stat().st_size // 1024
        assert size_kb < 8 * 1024, f"Oversize: {e['preview_path']} ({size_kb}KB)"


def test_build_message_contains_slug_and_title():
    pending = mod.load_pending()
    if not pending:
        return
    msg = mod.build_message(pending)
    for e in pending:
        assert e["title"] in msg
        assert e["slug"] in msg


def test_build_message_contains_reply_instructions():
    pending = mod.load_pending()
    if not pending:
        return
    msg = mod.build_message(pending)
    assert "!approve" in msg
    assert "!reject" in msg
    assert "!amend" in msg
