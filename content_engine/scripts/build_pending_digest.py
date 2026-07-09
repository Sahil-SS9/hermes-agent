#!/usr/bin/env python3
"""Build a self-contained pending-approvals digest for #blog-management.

Replaces the LLM-hand-written digest (which only listed slugs and bare
preview filenames that mobile Discord cannot open). This script inlines
each article's rendered preview HTML into ONE self-contained dark-mode
file, so a single tapped MEDIA attachment shows every article's content.

Deterministic: no LLM HTML generation, so no drift or broken path links.

Outputs: ~/.hermes/reports/blog-previews/pending-digest-DD-MM-YY.html
Prints the absolute path on stdout (so the cron can attach it as MEDIA:).
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
TRACKER = ENGINE / "blog_topics" / "pending_approvals.jsonl"
PREVIEW_DIR = Path.home() / ".hermes" / "reports" / "blog-previews"


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _body_inner(html_path: Path) -> str:
    """Extract the inner HTML of <body>…</body> from a preview file."""
    if not html_path.exists():
        return ""
    text = html_path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"<body[^>]*>(.*?)</body>", text, re.S | re.I)
    return m.group(1).strip() if m else ""


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _blog_items() -> list[dict]:
    rows = _read_jsonl(TRACKER)
    items = []
    for e in rows:
        if e.get("status") != "pending":
            continue
        slug = e.get("slug", "")
        preview = e.get("preview_path") or ""
        body = _body_inner(Path(preview)) if preview else ""
        items.append({
            "slug": slug,
            "title": e.get("title", slug),
            "stream": e.get("stream", e.get("tier", "ai")),
            "body": body,
        })
    return items


def _x_items() -> list[dict]:
    items = []
    for p in sorted(PREVIEW_DIR.glob("xarticle-*.html")):
        # derive a readable title from the filename
        stem = p.stem  # xarticle-2026-07-07-how-i-use-hermes
        parts = stem.split("-", 2)
        date_part = parts[1] if len(parts) > 1 else ""
        title_guess = parts[2].replace("-", " ").title() if len(parts) > 2 else stem
        body = _body_inner(p)
        items.append({
            "slug": stem,
            "title": f"{title_guess} ({date_part})",
            "stream": "x",
            "body": body,
        })
    return items


_STREAM_CLASS = {
    "ai": "stream-ai", "builder": "stream-builder", "pm": "stream-pm", "x": "stream-ai",
}


def _article_block(item: dict, idx: int) -> str:
    cls = _STREAM_CLASS.get(str(item.get("stream", "")).lower(), "stream-ai")
    slug = _esc(item.get("slug", ""))
    title = _esc(item.get("title", slug))
    body = item.get("body") or "<p><em>Preview not available — use !preview to generate.</em></p>"
    return f"""<details class="article" open>
  <summary><span class="item-title">{title} <span class="stream-tag {cls}">{_esc(str(item.get('stream','').upper()) or 'AI')}</span></span></summary>
  <div class="item-meta">slug: <code>{slug}</code></div>
  <div class="item-actions"><code>!approve {slug}</code> · <code>!reject {slug}</code></div>
  <div class="preview">{body}</div>
</details>"""


def build() -> str:
    blog = _blog_items()
    x = _x_items()
    today = date.today().strftime("%d/%m/%Y")
    ddmmyy = date.today().strftime("%d-%m-%y")

    html = f"""<!DOCTYPE html>
<html lang="en" data-color-scheme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Pending Approvals — {today}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #11100f; color: #f5f5f4; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; padding: 1.5rem; max-width: 820px; margin: 0 auto; }}
  h1 {{ color: #fbbf24; font-size: 1.5rem; margin-bottom: 0.25rem; }}
  .subtitle {{ color: #a8a29e; font-size: 0.9rem; margin-bottom: 1.5rem; }}
  h2 {{ color: #fbbf24; font-size: 1.1rem; margin: 1.5rem 0 0.75rem; padding-bottom: 0.25rem; border-bottom: 1px solid #34302c; }}
  .article {{ background: #1c1a18; border: 1px solid #34302c; border-radius: 6px; padding: 0.75rem 1rem; margin-bottom: 0.5rem; }}
  .article > summary {{ cursor: pointer; list-style: none; }}
  .article > summary::-webkit-details-marker {{ display: none; }}
  .item-title {{ font-weight: 600; color: #f5f5f4; }}
  .item-meta {{ font-size: 0.8rem; color: #a8a29e; margin: 0.25rem 0; }}
  .item-meta code {{ background: #2c2a28; padding: 1px 4px; border-radius: 3px; font-size: 0.75rem; }}
  .item-actions {{ font-size: 0.85rem; margin-bottom: 0.5rem; }}
  .item-actions code {{ background: #2c2a28; color: #fbbf24; padding: 2px 6px; border-radius: 4px; }}
  .preview {{ border-top: 1px solid #34302c; margin-top: 0.5rem; padding-top: 0.5rem; }}
  .preview img {{ max-width: 100%; height: auto; border-radius: 4px; }}
  .stream-tag {{ display: inline-block; font-size: 0.7rem; padding: 1px 6px; border-radius: 3px; margin-left: 0.5rem; text-transform: uppercase; }}
  .stream-ai {{ background: #3b1f1f; color: #fca5a5; }}
  .stream-builder {{ background: #1f3b2f; color: #86efac; }}
  .stream-pm {{ background: #1f2a3b; color: #93c5fd; }}
  .footer {{ margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #34302c; color: #a8a29e; font-size: 0.8rem; }}
</style>
</head>
<body>
<h1>📝 Pending Approvals</h1>
<p class="subtitle">{today} · {len(blog)} blog posts + {len(x)} X/Twitter articles awaiting review (previews inlined)</p>

<h2>Blog Posts</h2>
{chr(10).join(_article_block(it, i) for i, it in enumerate(blog)) or "<p><em>None pending.</em></p>"}

<h2>X/Twitter Articles</h2>
{chr(10).join(_article_block(it, i) for i, it in enumerate(x)) or "<p><em>None pending.</em></p>"}

<div class="footer">
  Approve: <code>!approve &lt;slug&gt;</code> · Reject: <code>!reject &lt;slug&gt;</code><br>
  Batch: <code>!approve all</code> or <code>!approve 1,2,3,6-10</code>
</div>
</body>
</html>"""

    out_path = PREVIEW_DIR / f"pending-digest-{ddmmyy}.html"
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return str(out_path)


if __name__ == "__main__":
    path = build()
    print(path)
