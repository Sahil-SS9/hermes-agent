"""Regression tests for blog pipeline fixes (issues A/B/C).

A: digest builder inlines previews (no broken file:// links)
B: audit escalates at attempts>=3, reports retry status
C: audit skips approved:false slugs in published_exempt.jsonl
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, "/home/kensei/repos/KenseiAgent/content_engine")

from tools.blog_pipeline_audit import audit, _read_exempt  # noqa: E402
from scripts.build_pending_digest import build  # noqa: E402


def test_exempt_slug_skips_false_flag(tmp_path, monkeypatch):
    """FIX C: a manually-published slug must not be flagged."""
    exempt = tmp_path / "published_exempt.jsonl"
    exempt.write_text(json.dumps({"slug": "already-live-post"}) + "\n")
    monkeypatch.setattr(
        "tools.blog_pipeline_audit.EXEMPT", exempt
    )
    posts = tmp_path / "SahilBlog" / "src" / "content" / "blog"
    posts.mkdir(parents=True)
    (posts / "already-live-post.md").write_text(
        "---\ntitle: Live\napproved: false\n---\nbody\n"
    )
    monkeypatch.setattr(
        "tools.blog_pipeline_audit.POSTS", posts
    )
    monkeypatch.setattr(
        "tools.blog_pipeline_audit.BLOG", tmp_path / "SahilBlog"
    )
    # no tracker entry for this slug -> would normally flag, but exempt skips it
    issues = audit()
    assert not any("already-live-post" in i for i in issues), issues


def test_escalate_at_attempts_threshold(tmp_path, monkeypatch):
    """FIX B: attempts>=3 -> escalated (single report), not repeated 'failed'."""
    failed = tmp_path / "failed_images.jsonl"
    failed.write_text(json.dumps({
        "slug": "hard-fail-post", "stream": "ai", "date": "2026-07-06",
        "attempts": 3, "last_error": "boom", "first_failure": "2026-07-04"
    }) + "\n")
    monkeypatch.setattr("tools.blog_pipeline_audit.FAILED_IMAGES", failed)
    monkeypatch.setattr("tools.blog_pipeline_audit.POSTS", tmp_path / "noposts")
    issues = audit()
    esc = [i for i in issues if "escalated" in i]
    tracked = [i for i in issues if "failed image tracked" in i and "hard-fail-post" in i]
    assert len(esc) == 1, issues
    assert not tracked, "should not double-report escalated post as 'tracked'"


def test_retry_status_reported(tmp_path, monkeypatch):
    """FIX B: audit surfaces last retry outcome from status JSON."""
    status = tmp_path / "blog-failed-retry-status.json"
    status.write_text(json.dumps({
        "rc": 0, "finished_at": "2026-07-09T08:15:00",
        "recovered": ["a"], "still_failed": ["b"], "idle": False,
    }))
    monkeypatch.setattr("tools.blog_pipeline_audit.RETRY_STATUS", status)
    monkeypatch.setattr("tools.blog_pipeline_audit.POSTS", tmp_path / "noposts")
    issues = audit()
    assert any("image-retry" in i and "recovered 1" in i and "still_failed 1" in i for i in issues), issues


def test_digest_inlines_no_broken_links(tmp_path, monkeypatch):
    """FIX A: digest inlines article bodies, no file:// links, images stripped.

    Images MUST be stripped — otherwise 26 inlined previews with base64
    heroes blew the digest to 13.6 MB and Discord rejected the attachment
    (>8 MB bot cap). Regression guard: assert no data:image and a sane size.
    """
    tracker = tmp_path / "pending_approvals.jsonl"
    tracker.write_text(json.dumps({
        "slug": "my-post", "title": "My Post", "stream": "ai", "tier": "ai",
        "status": "pending", "preview_path": str(tmp_path / "my-post.html"),
    }) + "\n")
    preview = tmp_path / "my-post.html"
    preview.write_text(
        "<html><body><h1>My Post</h1><p>body content here</p>"
        "<img src='data:image/jpeg;base64,AAAA'></body></html>"
    )
    monkeypatch.setattr("tools.blog_pipeline_audit.TRACKER", tracker)
    # point digest builder at tmp dirs
    monkeypatch.setattr(
        "scripts.build_pending_digest.TRACKER", tracker
    )
    monkeypatch.setattr(
        "scripts.build_pending_digest.PREVIEW_DIR", tmp_path / "previews"
    )
    out = build()
    html = Path(out).read_text()
    assert "file://" not in html, "digest must not contain broken file:// links"
    assert "body content here" in html, "article body must be inlined"
    assert "data:image" not in html, "base64 images must be stripped (Discord 8MB cap)"
    assert "<details" in html, "articles should be collapsible blocks"
    assert Path(out).stat().st_size < 8 * 1024 * 1024, "digest must stay under Discord's 8MB bot cap"
