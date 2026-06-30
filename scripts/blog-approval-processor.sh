#!/bin/bash
set -euo pipefail
cd /home/kensei/repos/KenseiAgent/content_engine
export PYTHONPATH=.

python3 <<'PY'
from blog.blog_approval import _read_tracker, publish

entries = _read_tracker()
approved = [e for e in entries if e.get("status") == "approved"]
if not approved:
    raise SystemExit(0)

results = []
for entry in approved:
    slug = entry.get("slug", "")
    title = entry.get("title", slug)
    result = publish(slug)
    results.append({
        "slug": slug,
        "title": title,
        "status": result.get("status", "unknown"),
        "detail": result,
    })

published = [r for r in results if r["status"] == "ok"]
failed = [r for r in results if r["status"] != "ok"]

lines = [
    "[Blog Publish]",
    "━━━ **🚀 Publish Status** ━━━",
]

if published:
    lines.append("**Published**")
    for r in published:
        lines.append(f"- `{r['slug']}` — {r['title']}")

if failed:
    if published:
        lines.append("")
    lines.append("**Not published**")
    for r in failed:
        detail = r["detail"]
        extra = detail.get("error") or detail.get("message") or ""
        extra = f" — {extra}" if extra else ""
        lines.append(f"- `{r['slug']}` — {r['title']} (`{r['status']}`{extra})")

print("\n".join(lines))
PY
