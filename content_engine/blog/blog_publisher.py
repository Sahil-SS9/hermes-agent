"""Blog publisher - git stage/commit (draft) + approval flip + build + push.

Draft posts are written with approved:false (hidden). Publishing = flip to
approved:true in the MDX frontmatter, pnpm build (verify exit 0), commit,
git push. Do NOT auto-publish.

  stage_draft(mdx_path, repo) -> slug (git add + commit "draft: <title>", no push)
  stage_adhoc(mdx_path, stream, repo) -> {status, slug|issues} (adhoc gate + stage)
  approve(slug, repo) -> {status, ...} (flip approved, build, commit, push)
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from config import SAHILBLOG_REPO


def _git(repo: str, *args) -> subprocess.CompletedProcess:
    """Run a git command in the repo dir."""
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True, timeout=60,
    )


def _slug_from_path(mdx_path: str) -> str:
    """Extract the slug from the MDX filename (strip .mdx)."""
    return Path(mdx_path).stem


def _run_build(repo: str) -> int:
    """Run pnpm build in the repo. Returns exit code."""
    result = subprocess.run(
        ["pnpm", "build"], cwd=repo, capture_output=True, text=True, timeout=300,
    )
    return result.returncode


def _git_push(repo: str) -> int:
    """Push to origin main. Returns exit code."""
    result = _git(repo, "push", "origin", "main")
    return result.returncode


def stage_draft(mdx_path: str, repo: Optional[str] = None) -> str:
    """Git add + commit the post and its images. Does NOT push.

    Returns the slug.
    """
    repo_path = str(repo) if repo else str(SAHILBLOG_REPO)
    slug = _slug_from_path(mdx_path)
    # Stage the post + its images.
    _git(repo_path, "add", str(mdx_path))
    # Stage images in public/blog/<slug>/ if they exist.
    img_dir = Path(repo_path) / "public" / "blog" / slug
    if img_dir.exists():
        _git(repo_path, "add", str(img_dir))
    # Commit.
    title = _read_title_from_mdx(mdx_path)
    _git(repo_path, "commit", "-m", f"draft: {title}")
    return slug


def _read_title_from_mdx(mdx_path: str) -> str:
    """Read the title from the MDX frontmatter for the commit message."""
    try:
        text = Path(mdx_path).read_text()
        m = re.search(r'^title:\s+"(.+?)"\s*$', text, re.MULTILINE)
        if m:
            return m.group(1)
    except Exception:
        pass
    return Path(mdx_path).stem


def _flip_approved(mdx_path: Path) -> bool:
    """Flip approved:false to approved:true in the MDX frontmatter."""
    text = mdx_path.read_text()
    new = re.sub(r"^approved:\s*false\s*$", "approved: true", text, flags=re.MULTILINE)
    if new == text:
        return False  # nothing to flip (already approved or no field)
    mdx_path.write_text(new)
    return True


def stage_adhoc(mdx_path: str, stream: str = "ai",
                 repo: Optional[str] = None) -> dict:
    """Run adhoc_check on a manually-written post, then stage if it passes.

    This is the gate for adhoc/manual posts that bypass the pipeline.
    Reads the MDX, parses it into a draft dict, runs blog_gate.adhoc_check,
    and only calls stage_draft if the gate passes.

    Returns:
        {"status": "staged", "slug": slug} on pass
        {"status": "rejected", "issues": [...]} on fail
    """
    from blog.blog_gate import adhoc_check

    repo_path = str(repo) if repo else str(SAHILBLOG_REPO)
    p = Path(mdx_path)
    text = p.read_text(encoding="utf-8", errors="replace")

    # Parse frontmatter into a draft dict.
    fm_match = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not fm_match:
        return {"status": "rejected", "issues": ["Could not parse MDX frontmatter"]}

    fm_text = fm_match.group(1)
    body_md = fm_match.group(2).strip()

    def _extract_fm_value(key: str) -> str:
        m = re.search(rf'^{key}:\s*(.+?)$', fm_text, re.MULTILINE)
        if not m:
            return ""
        val = m.group(1).strip()
        if val.startswith('"') and val.endswith('"'):
            val = val[1:-1]
        return val

    draft = {
        "title": _extract_fm_value("title"),
        "description": _extract_fm_value("description"),
        "body_md": body_md,
        "slug": p.stem,
        "tier": _extract_fm_value("tier") or "pm",
        "format": _extract_fm_value("format") or "essay",
        "source": _extract_fm_value("source") or "manual",
        "stream": stream,
    }

    status, issues = adhoc_check(draft, stream)
    if status != "ok":
        return {"status": "rejected", "issues": issues}

    # Write the (possibly redacted) body back to the MDX.
    if draft["body_md"] != body_md:
        new_text = f"---\n{fm_text}\n---\n\n{draft['body_md']}"
        p.write_text(new_text, encoding="utf-8")

    slug = stage_draft(str(p), repo=repo_path)
    return {"status": "staged", "slug": slug}


def approve(slug: str, repo: Optional[str] = None) -> dict:
    """Flip approved:true, build, commit, push.

    Returns {status: "ok" | "build_failed" | "flip_failed", ...}
    Does NOT auto-publish on build failure.
    """
    repo_path = str(repo) if repo else str(SAHILBLOG_REPO)
    mdx_path = Path(repo_path) / "src/content/blog" / f"{slug}.mdx"
    if not mdx_path.exists():
        return {"status": "not_found", "slug": slug}

    # 1. Flip approved.
    if not _flip_approved(mdx_path):
        return {"status": "flip_failed", "slug": slug}

    # 2. Build.
    build_rc = _run_build(repo_path)
    if build_rc != 0:
        return {"status": "build_failed", "slug": slug, "build_rc": build_rc}

    # 3. Commit.
    _git(repo_path, "add", str(mdx_path))
    title = _read_title_from_mdx(str(mdx_path))
    _git(repo_path, "commit", "-m", f"publish: {title}")

    # 4. Push.
    push_rc = _git_push(repo_path)
    return {"status": "ok", "slug": slug, "push_rc": push_rc}