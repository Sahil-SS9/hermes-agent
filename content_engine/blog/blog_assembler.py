"""Blog assembler - emit MDX with valid frontmatter into SahilBlog.

Writes approved:false draft posts to SAHILBLOG_REPO/src/content/blog/<slug>.mdx
with frontmatter matching the VERIFIED content.config.ts schema. Images are
copied to public/blog/<slug>/ and inline image refs rewritten to /blog/<slug>/NN.png.

Frontmatter rules (from the verified contract):
  - title, description: quoted strings
  - pubDate: UNQUOTED YYYY-MM-DD (Astro z.date() parses this; quoted strings fail)
  - tags: YAML list
  - tier: "pm" | "builder" (the only two valid values)
  - format: "essay" | "note" | "review" | "brief"
  - approved: false (always on generation; flip on approval)
  - source: "research-paper" | "gitradar" | "manual"
  - heroImage: optional, "/blog/<slug>/hero.png"
"""
from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path
from typing import Optional

from config import SAHILBLOG_REPO
from blog.blog_slug import slugify


def _yaml_value(val) -> str:
    """Emit a YAML value: quoted string, unquoted bool, or list."""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, list):
        if not val:
            return "[]"
        inner = ", ".join(_yaml_scalar(v) for v in val)
        return f"[{inner}]"
    return _yaml_scalar(val)


def _yaml_scalar(val) -> str:
    """Emit a quoted YAML scalar."""
    if val is None:
        return '""'
    s = str(val).replace('"', '\\"')
    return f'"{s}"'


def _frontmatter(fm: dict) -> str:
    """Emit YAML frontmatter block (between --- markers)."""
    lines = ["---"]
    # Order matters for readability, not for Astro (it's a map).
    if "title" in fm:
        lines.append(f"title: {_yaml_scalar(fm['title'])}")
    if "description" in fm:
        lines.append(f"description: {_yaml_scalar(fm['description'])}")
    # pubDate: unquoted YYYY-MM-DD (Astro z.date() requires this).
    pub = fm.get("pubDate")
    if pub:
        lines.append(f"pubDate: {pub}")
    if "updatedDate" in fm and fm["updatedDate"]:
        lines.append(f"updatedDate: {fm['updatedDate']}")
    if "heroImage" in fm and fm["heroImage"]:
        lines.append(f'heroImage: "{fm["heroImage"]}"')
    if "tags" in fm:
        lines.append(f"tags: {_yaml_value(fm['tags'])}")
    if "tier" in fm:
        # Enum values: emit unquoted for Astro's z.enum() compatibility.
        lines.append(f"tier: {fm['tier']}")
    if "format" in fm:
        lines.append(f"format: {fm['format']}")
    if "approved" in fm:
        lines.append(f"approved: {_yaml_value(fm['approved'])}")
    if "source" in fm:
        lines.append(f"source: {fm['source']}")
    lines.append("---")
    return "\n".join(lines)


def _insert_section_images(body_md: str, section_paths: dict, slug: str,
                           imgs_dir: Path) -> str:
    """Copy section images and insert inline refs after their H2 headings.

    section_paths is {h2_heading: source_image_path}. Images are copied to
    imgs_dir as NN.png (01, 02, ...) and inline ![alt](/blog/<slug>/NN.png)
    refs are inserted after the matching H2 heading.
    """
    if not section_paths:
        return body_md
    out_lines = []
    idx = 0
    for line in body_md.splitlines():
        out_lines.append(line)
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            heading = m.group(1).strip()
            # Match by heading text (case-insensitive, trimmed).
            for h, src in section_paths.items():
                if h.strip().lower() == heading.lower():
                    idx += 1
                    dst_name = f"{idx:02d}.png"
                    dst = imgs_dir / dst_name
                    try:
                        shutil.copy2(src, dst)
                    except Exception as exc:
                        print(f"[blog_assembler] section image copy failed: {exc}")
                        continue
                    out_lines.append("")
                    out_lines.append(f"![{heading}](/blog/{slug}/{dst_name})")
                    break
    return "\n".join(out_lines)


def _resolve_collision(posts_dir: Path, slug: str) -> Path:
    """If <slug>.mdx exists, append -N until free."""
    base = posts_dir / f"{slug}.mdx"
    if not base.exists():
        return base
    n = 2
    while True:
        candidate = posts_dir / f"{slug}-{n}.mdx"
        if not candidate.exists():
            return candidate
        n += 1


def assemble(draft: dict, images: dict, repo: Optional[str] = None,
             pub_date: Optional[str] = None) -> Path:
    """Write the MDX post into the SahilBlog repo.

    draft: {title, description, body_md, tier, tags, format, source, stream, slug}
    images: {hero_path: str|None, section_paths: {h2_heading: path}}
    repo: path to the SahilBlog repo (defaults to config.SAHILBLOG_REPO).
    pub_date: optional YYYY-MM-DD string; defaults to today.

    Returns the Path to the written MDX file.
    """
    repo_path = Path(repo) if repo else Path(SAHILBLOG_REPO)
    slug = draft.get("slug") or slugify(draft.get("title", "post"))
    posts_dir = repo_path / "src/content/blog"
    imgs_dir = repo_path / "public" / "blog" / slug
    posts_dir.mkdir(parents=True, exist_ok=True)
    imgs_dir.mkdir(parents=True, exist_ok=True)

    fm = {
        "title": draft.get("title", ""),
        "description": draft.get("description", ""),
        "pubDate": pub_date or date.today().isoformat(),
        "tags": draft.get("tags", []),
        "tier": draft.get("tier", "pm"),
        "format": draft.get("format", "essay"),
        "approved": False,
        "source": draft.get("source", "manual"),
    }

    # Hero image.
    hero = images.get("hero_path")
    if hero and Path(hero).exists():
        shutil.copy2(hero, imgs_dir / "hero.png")
        fm["heroImage"] = f"/blog/{slug}/hero.png"

    # Section images + inline refs.
    body = _insert_section_images(
        draft.get("body_md", ""), images.get("section_paths", {}), slug, imgs_dir,
    )

    mdx_path = _resolve_collision(posts_dir, slug)
    mdx_path.write_text(_frontmatter(fm) + "\n\n" + body, encoding="utf-8")
    return mdx_path