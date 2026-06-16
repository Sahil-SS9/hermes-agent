"""Blog pipeline orchestrator — run_stream / run_all + CLI.

Order of operations (mirrors article_pipeline):
  1. blog_router.choose(stream)  -> plan or None (skip)
  2. blog_generator.write_with_gate(plan, stream)  -> draft (or None)
  3. blog_illustrator.illustrate(draft)  -> {hero_path, section_paths}
  4. blog_assembler.assemble(draft, images, repo)  -> mdx Path
  5. blog_publisher.stage_draft(mdx_path, repo)  -> slug
  6. blog_router.record(stream, topic_id, title)  -> (on success only)

Status values:
  - "skipped_disabled" — BLOG_ENABLED is False
  - "skipped_router"   — router returned None
  - "skipped_generator" — generator returned None (LLM dead or gate fail)
  - "ok"               — draft staged + topic recorded
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from typing import Optional

from config import BLOG_ENABLED, BLOG_STREAMS, SAHILBLOG_REPO
from blog.blog_router import choose, record
from blog.blog_generator import write_with_gate
from blog.blog_illustrator import illustrate
from blog.blog_assembler import assemble
from blog.blog_publisher import stage_draft


def run_stream(stream: str, repo: Optional[str] = None) -> dict:
    """Drive one blog post through the pipeline for a single stream."""
    if not BLOG_ENABLED:
        return {"status": "skipped_disabled", "stream": stream}

    repo_path = repo or str(SAHILBLOG_REPO)

    # 1. Router.
    plan = choose(stream)
    if not plan:
        return {"status": "skipped_router", "stream": stream}

    # 2. Generator (with gate + retry).
    draft = write_with_gate(plan, stream=stream)
    if not draft:
        return {"status": "skipped_generator", "stream": stream,
                "topic_id": plan.get("topic_id")}

    # 3. Illustrator.
    images = illustrate(draft)

    # 4. Assembler.
    mdx_path = assemble(draft, images, repo=repo_path)

    # 5. Publisher (stage draft, no push).
    slug = stage_draft(str(mdx_path), repo=repo_path)

    # 6. Record topic (on success only, record-on-success).
    record(stream, plan.get("topic_id", ""), draft.get("title", ""))

    return {
        "status": "ok", "stream": stream, "slug": slug,
        "title": draft.get("title", ""), "topic_id": plan.get("topic_id", ""),
        "mdx_path": str(mdx_path),
    }


def run_all(streams: tuple = BLOG_STREAMS, repo: Optional[str] = None) -> dict:
    """Run each configured stream and return per-stream results."""
    results = {}
    for stream in streams:
        try:
            results[stream] = run_stream(stream, repo=repo)
        except Exception as exc:
            results[stream] = {"status": "error", "stream": stream, "error": str(exc)}
    any_ok = any(r.get("status") == "ok" for r in results.values())
    return {
        "status": "ok" if any_ok else "skipped_all",
        "results": results,
    }


def _cli():
    """CLI entry point: python -m blog.blog_pipeline --stream ai|pm|builder|all"""
    parser = argparse.ArgumentParser(description="SahilBlog content pipeline")
    parser.add_argument("--stream", default="all",
                        choices=["ai", "pm", "builder", "all"],
                        help="Stream to run (default: all)")
    parser.add_argument("--repo", default=None,
                        help="Path to SahilBlog repo (default: config.SAHILBLOG_REPO)")
    args = parser.parse_args()

    if args.stream == "all":
        result = run_all(repo=args.repo)
        print(f"run_all: {result['status']}")
        for stream, r in result.get("results", {}).items():
            print(f"  {stream}: {r.get('status')} {r.get('slug', '')}")
        return 0 if result["status"] == "ok" else 1
    else:
        result = run_stream(args.stream, repo=args.repo)
        print(f"run_stream({args.stream}): {result['status']}")
        if result.get("slug"):
            print(f"  slug: {result['slug']}")
            print(f"  mdx:  {result.get('mdx_path', '')}")
        return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(_cli())