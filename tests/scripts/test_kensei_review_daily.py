"""Regression test for scripts/kensei_review_daily.py.

Verifies the no_agent aggregator:
- finds real source files (or reports [SILENT] when none)
- writes a valid dark-mode HTML review with real content
- prints a MEDIA: tag pointing at the written file
"""
import os
import sys
import tempfile
from pathlib import Path
from html.parser import HTMLParser
import pytest

# Ensure the script dir is importable / runnable
REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "kensei_review_daily.py"
sys.path.insert(0, str(REPO / "scripts"))


class _TagChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.ok = True
        self.li_count = 0

    def handle_starttag(self, tag, attrs):
        if tag not in ("meta", "br", "img", "hr", "link"):
            self.stack.append(tag)
        if tag == "li":
            self.li_count += 1

    def handle_endtag(self, tag):
        if tag in ("meta", "br", "img", "hr", "link"):
            return
        if self.stack and self.stack[-1] == tag:
            self.stack.pop()
        else:
            self.ok = False


def test_script_runs_and_emits_media_tag(capsys):
    import kensei_review_daily as mod

    # Point outputs at a temp dir to avoid clobbering live runbooks
    tmp = Path(tempfile.mkdtemp())
    mod.OUT_DIR = tmp / "kensei-review-daily"
    mod.HERMES = tmp  # not strictly needed but keeps paths isolated

    # We can't easily fake the upstream files without writing them; instead
    # run the real aggregator against today's live data and assert structure.
    rc = os.system(f"{sys.executable} {SCRIPT}")
    assert rc == 0, f"script exited non-zero: {rc}"

    out = capsys.readouterr().out if False else None  # stdout captured below
    # Re-run capturing stdout via subprocess for clean capture
    import subprocess

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True, text=True, cwd=str(REPO),
    )
    assert result.returncode == 0, result.stderr
    assert "MEDIA:" in result.stdout, "no MEDIA tag emitted"
    media_line = [l for l in result.stdout.splitlines() if l.startswith("MEDIA:")][0]
    media_path = media_line.split("MEDIA:", 1)[1].strip()
    assert media_path.endswith("review.html"), media_path

    # Validate the written HTML
    html_text = Path(media_path).read_text()
    checker = _TagChecker()
    checker.feed(html_text)
    assert checker.ok, f"unbalanced HTML tags: {checker.stack}"
    assert "#fbbf24" in html_text, "accent colour missing"
    assert checker.li_count > 0, "no content items in HTML"


def test_script_silent_when_no_sources(monkeypatch, capsys):
    """If all source dirs are empty, it should print [SILENT]."""
    import kensei_review_daily as mod

    tmp = Path(tempfile.mkdtemp())
    mod.DIGEST_DIR = tmp / "digest"
    mod.SYNTH_DIR = tmp / "synth"
    mod.RADAR_DIR = tmp / "radar"
    mod.OUT_DIR = tmp / "out"
    for d in (mod.DIGEST_DIR, mod.SYNTH_DIR, mod.RADAR_DIR):
        d.mkdir(parents=True, exist_ok=True)

    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    with redirect_stdout(buf):
        mod.main()
    assert "[SILENT]" in buf.getvalue(), f"expected [SILENT], got: {buf.getvalue()!r}"
