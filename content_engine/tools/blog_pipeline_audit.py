#!/usr/bin/env python3
"""Audit SahilBlog pipeline state without mutating it.

Problem-only report for cron/manual checks:
- dirty worktrees
- pending approvals with missing files/previews
- approved:false drafts without pending approval
- duplicate draft title clusters
- failed image entries
- protected approved posts are not treated as image defects
"""
from __future__ import annotations

import json
import re
import subprocess
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
BLOG = Path.home() / "repos" / "SahilBlog"
TRACKER = ENGINE / "blog_topics" / "pending_approvals.jsonl"
FAILED_IMAGES = ENGINE / "blog_topics" / "failed_images.jsonl"
POSTS = BLOG / "src/content/blog"


def _git_dirty(repo: Path) -> int:
    r = subprocess.run(["git", "status", "--short"], cwd=repo, text=True, capture_output=True, timeout=30)
    if r.returncode != 0:
        return -1
    return len([ln for ln in r.stdout.splitlines() if ln.strip()])


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"_invalid_json": line[:120]})
    return rows


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9\s]", "", title.lower()).strip()


def audit() -> list[str]:
    issues: list[str] = []

    kd = _git_dirty(ENGINE.parent)
    bd = _git_dirty(BLOG)
    if kd:
        issues.append(f"KenseiAgent worktree dirty: {kd} changed/untracked paths")
    if bd:
        issues.append(f"SahilBlog worktree dirty: {bd} changed/untracked paths")

    approvals = _read_jsonl(TRACKER)
    pending = [e for e in approvals if e.get("status") == "pending"]
    tracked_slugs = {e.get("slug") for e in approvals if e.get("slug")}
    for e in approvals:
        if e.get("_invalid_json"):
            issues.append("pending_approvals contains invalid JSON line")
            continue
        slug = e.get("slug", "")
        if slug in {"ai", "slug"} or slug.startswith("test-approval-"):
            issues.append(f"pending_approvals contains junk/test slug: {slug}")
        if e.get("status") == "pending":
            mdx = Path(e.get("mdx_path") or "")
            if not e.get("mdx_path") or not mdx.exists():
                issues.append(f"pending approval missing real mdx_path: {slug}")
            preview = Path(e.get("preview_path") or "")
            if not e.get("preview_path") or not preview.exists():
                issues.append(f"pending approval missing preview_path: {slug}")

    false_posts = []
    title_rows = []
    for p in POSTS.glob("*.md*"):
        fm = _frontmatter(p)
        approved = fm.get("approved", "").lower()
        title = fm.get("title", p.stem)
        if approved == "false":
            false_posts.append(p.stem)
            title_rows.append((p.stem, title))
    for slug in false_posts:
        if slug not in tracked_slugs:
            issues.append(f"approved:false draft has no approval-tracker entry: {slug}")

    for i, (slug_a, title_a) in enumerate(title_rows):
        for slug_b, title_b in title_rows[i+1:]:
            ratio = SequenceMatcher(None, _norm_title(title_a), _norm_title(title_b)).ratio()
            if ratio >= 0.82:
                issues.append(f"possible duplicate draft titles ({ratio:.2f}): {slug_a} / {slug_b}")

    failed = _read_jsonl(FAILED_IMAGES)
    for e in failed:
        if e.get("slug"):
            issues.append(f"failed image tracked: {e.get('slug')} attempts={e.get('attempts')} error={e.get('last_error')}")

    return issues


if __name__ == "__main__":
    problems = audit()
    if not problems:
        print("[SILENT]")
    else:
        print("[Blog Pipeline Audit]")
        for item in problems:
            print(f"- {item}")
