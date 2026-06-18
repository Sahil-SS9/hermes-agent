"""Tests for blog.blog_publisher — git stage/commit (draft) + approval flip + build + push.

Draft posts are staged and committed (not pushed). Publishing = flip
approved:true in the MDX frontmatter, pnpm build, commit, push. Do NOT
auto-publish.
"""
import os
import subprocess
from pathlib import Path

import blog.blog_publisher as bp


_DRAFT = {
    "title": "Token-Maxing at the Edge",
    "slug": "token-maxing-at-the-edge",
}


def _setup_tmp_git_repo(tmp_path):
    """Create a tmp git repo with the SahilBlog skeleton."""
    (tmp_path / "src/content/blog").mkdir(parents=True)
    (tmp_path / "public/blog").mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
    # Create an initial commit so there's a HEAD.
    (tmp_path / "README.md").write_text("# test repo\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)
    return tmp_path


def _write_mdx(repo, slug, approved=False):
    """Write a minimal MDX post into the tmp repo."""
    fm_approved = "true" if approved else "false"
    mdx = f"""---
title: "Test Post"
description: "A test."
pubDate: 2026-06-16
tags: ["ai"]
tier: pm
format: essay
approved: {fm_approved}
source: manual
---

# Test Post

Body text.
"""
    p = repo / "src/content/blog" / f"{slug}.mdx"
    p.write_text(mdx)
    return p


def test_stage_draft_commits_without_push(monkeypatch, tmp_path):
    """stage_draft() git adds + commits the post, does NOT push."""
    repo = _setup_tmp_git_repo(tmp_path)
    mdx = _write_mdx(repo, _DRAFT["slug"])
    # Mock pnpm build as a no-op (the repo has no package.json).
    monkeypatch.setattr(bp, "_run_build", lambda repo: 0)
    slug = bp.stage_draft(str(mdx), repo=str(repo))
    assert slug == _DRAFT["slug"]
    # Verify the file is committed.
    log = subprocess.run(
        ["git", "-C", str(repo), "log", "--oneline"],
        capture_output=True, text=True,
    ).stdout
    assert "draft:" in log
    # No push happened (no remote configured, but no error either).
    # Verify the file is in the commit.
    show = subprocess.run(
        ["git", "-C", str(repo), "show", "--stat", "HEAD"],
        capture_output=True, text=True,
    ).stdout
    assert f"{_DRAFT['slug']}.mdx" in show


def test_stage_draft_stages_images_too(monkeypatch, tmp_path):
    """stage_draft() also stages images in public/blog/<slug>/."""
    repo = _setup_tmp_git_repo(tmp_path)
    mdx = _write_mdx(repo, _DRAFT["slug"])
    # Create a fake image.
    img_dir = repo / "public/blog" / _DRAFT["slug"]
    img_dir.mkdir(parents=True, exist_ok=True)
    (img_dir / "hero.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(bp, "_run_build", lambda repo: 0)
    bp.stage_draft(str(mdx), repo=str(repo))
    show = subprocess.run(
        ["git", "-C", str(repo), "show", "--stat", "HEAD"],
        capture_output=True, text=True,
    ).stdout
    assert "hero.png" in show


def test_approve_flips_approved_flag(monkeypatch, tmp_path):
    """approve() sets approved:true in the MDX frontmatter."""
    repo = _setup_tmp_git_repo(tmp_path)
    _write_mdx(repo, _DRAFT["slug"], approved=False)
    monkeypatch.setattr(bp, "_run_build", lambda repo: 0)
    monkeypatch.setattr(bp, "_git_push", lambda repo: 0)
    bp.approve(_DRAFT["slug"], repo=str(repo))
    mdx = (repo / "src/content/blog" / f"{_DRAFT['slug']}.mdx").read_text()
    assert "approved: true" in mdx


def test_approve_runs_build_before_push(monkeypatch, tmp_path):
    """approve() runs pnpm build and only pushes if build succeeds."""
    repo = _setup_tmp_git_repo(tmp_path)
    _write_mdx(repo, _DRAFT["slug"], approved=False)
    build_calls = []
    push_calls = []
    monkeypatch.setattr(bp, "_run_build", lambda r: build_calls.append(r) or 0)
    monkeypatch.setattr(bp, "_git_push", lambda r: push_calls.append(r) or 0)
    bp.approve(_DRAFT["slug"], repo=str(repo))
    assert len(build_calls) == 1
    assert len(push_calls) == 1


def test_approve_does_not_push_on_build_failure(monkeypatch, tmp_path):
    """When build fails (non-zero exit), approve() does NOT push."""
    repo = _setup_tmp_git_repo(tmp_path)
    _write_mdx(repo, _DRAFT["slug"], approved=False)
    push_calls = []
    monkeypatch.setattr(bp, "_run_build", lambda r: 1)  # build fails
    monkeypatch.setattr(bp, "_git_push", lambda r: push_calls.append(r) or 0)
    result = bp.approve(_DRAFT["slug"], repo=str(repo))
    assert len(push_calls) == 0  # no push on build failure
    assert "build_failed" in result["status"]


def test_approve_commits_after_flip(monkeypatch, tmp_path):
    """approve() commits the approved:true flip with a 'publish:' message."""
    repo = _setup_tmp_git_repo(tmp_path)
    _write_mdx(repo, _DRAFT["slug"], approved=False)
    monkeypatch.setattr(bp, "_run_build", lambda repo: 0)
    monkeypatch.setattr(bp, "_git_push", lambda repo: 0)
    bp.approve(_DRAFT["slug"], repo=str(repo))
    log = subprocess.run(
        ["git", "-C", str(repo), "log", "--oneline"],
        capture_output=True, text=True,
    ).stdout
    assert "publish:" in log


def test_stage_draft_returns_slug(monkeypatch, tmp_path):
    """stage_draft() returns the slug extracted from the mdx path."""
    repo = _setup_tmp_git_repo(tmp_path)
    mdx = _write_mdx(repo, _DRAFT["slug"])
    monkeypatch.setattr(bp, "_run_build", lambda repo: 0)
    slug = bp.stage_draft(str(mdx), repo=str(repo))
    assert slug == _DRAFT["slug"]