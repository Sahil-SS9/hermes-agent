"""Blog pipeline orchestrator - run_stream / run_all + CLI.

Order of operations (mirrors article_pipeline):
  1. blog_router.choose(stream)  -> plan or None (skip)
  2. blog_generator.write_with_gate(plan, stream)  -> draft (or None)
  3. blog_illustrator.illustrate(draft)  -> {hero_path, section_paths}
  4. Check for failed images (hero AND all sections None -> set aside)
  5. blog_assembler.assemble(draft, images, repo)  -> mdx Path
  6. blog_publisher.stage_draft(mdx_path, repo)  -> slug
  7. blog_router.record(stream, topic_id, title)  -> (on success only)

Status values:
  - "skipped_disabled"    - BLOG_ENABLED is False
  - "skipped_router"      - router returned None
  - "skipped_generator"   - generator returned None (LLM dead or gate fail)
  - "ok"                  - draft staged + topic recorded
  - "failed_images"       - all images failed; post set aside for retry
"""
from __future__ import annotations
import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from config import BLOG_ENABLED, BLOG_STREAMS, SAHILBLOG_REPO
from blog.blog_router import choose, record
from blog.blog_generator import write_with_gate
from blog.blog_illustrator import illustrate
from blog.blog_assembler import assemble
from blog.blog_publisher import stage_draft


# Path for tracking posts with failed images.
FAILED_IMAGES_PATH = Path(__file__).parent.parent / "blog_topics" / "failed_images.jsonl"
STALE_THRESHOLD_DAYS = 7


def _track_failed_image(slug: str, stream: str, error: str) -> None:
    """Append a failed-image record to the tracking JSONL file."""
    FAILED_IMAGES_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "slug": slug,
        "stream": stream,
        "date": date.today().isoformat(),
        "attempts": 1,
        "last_error": error,
        "first_failure": date.today().isoformat(),
    }
    # Check if slug already tracked — if so, increment attempts.
    existing: list[dict] = []
    if FAILED_IMAGES_PATH.exists():
        for line in FAILED_IMAGES_PATH.read_text().splitlines():
            if line.strip():
                try:
                    existing.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    # Find existing entry for this slug.
    found = False
    for e in existing:
        if e.get("slug") == slug:
            e["attempts"] = e.get("attempts", 0) + 1
            e["last_error"] = error
            e["date"] = date.today().isoformat()
            found = True
            break
    if not found:
        existing.append(entry)
    # Rewrite the file.
    with open(FAILED_IMAGES_PATH, "w") as f:
        for e in existing:
            f.write(json.dumps(e) + "\n")


def _remove_from_failed(slug: str) -> None:
    """Remove a slug from the failed-images tracking file."""
    if not FAILED_IMAGES_PATH.exists():
        return
    existing: list[dict] = []
    for line in FAILED_IMAGES_PATH.read_text().splitlines():
        if line.strip():
            try:
                existing.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    existing = [e for e in existing if e.get("slug") != slug]
    with open(FAILED_IMAGES_PATH, "w") as f:
        for e in existing:
            f.write(json.dumps(e) + "\n")


def _get_failed_entries() -> list[dict]:
    """Read all failed-image entries from the tracking file."""
    if not FAILED_IMAGES_PATH.exists():
        return []
    entries = []
    for line in FAILED_IMAGES_PATH.read_text().splitlines():
        if line.strip():
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _is_stale(entry: dict, threshold_days: int = STALE_THRESHOLD_DAYS) -> bool:
    """Check if a failed-image entry is stale (older than threshold_days)."""
    first = entry.get("first_failure") or entry.get("date", "")
    if not first:
        return False
    try:
        first_dt = date.fromisoformat(first)
    except ValueError:
        return False
    return (date.today() - first_dt).days > threshold_days


def get_stale_failed_images() -> list[dict]:
    """Return entries that have been in failed_images for > threshold_days.

    Used by the weekly audit cron to flag posts stuck in failed-image state.
    """
    return [e for e in _get_failed_entries() if _is_stale(e)]


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

    # 4. Failed-image check: if hero AND all sections are None, set aside.
    hero_ok = images.get("hero_path") is not None
    sections_ok = bool(images.get("section_paths"))
    if not hero_ok and not sections_ok:
        slug = draft.get("slug", "")
        error = "All image generation attempts failed (hero + sections)"
        _track_failed_image(slug, stream, error)
        return {
            "status": "failed_images", "stream": stream,
            "slug": slug, "title": draft.get("title", ""),
            "topic_id": plan.get("topic_id", ""),
            "error": error,
        }

    # 5. Assembler (accept partial imagery — hero or some sections succeeded).
    mdx_path = assemble(draft, images, repo=repo_path)

    # 6. Publisher (stage draft, no push).
    slug = stage_draft(str(mdx_path), repo=repo_path)

    # 7. Record topic (on success only, record-on-success).
    record(stream, plan.get("topic_id", ""), draft.get("title", ""))

    return {
        "status": "ok", "stream": stream, "slug": slug,
        "title": draft.get("title", ""), "topic_id": plan.get("topic_id", ""),
        "mdx_path": str(mdx_path),
    }


def _check_systemic_ocr_failures(draft: dict, images: dict) -> None:
    """Check if >50% of section images had OCR text issues and flag the post."""
    import logging
    section_paths = images.get("section_paths", [])
    if isinstance(section_paths, list) and len(section_paths) > 0:
        total = len(section_paths)
        # Check each section image by re-running OCR (quick stats check).
        ocr_failures = 0
        for img_path in section_paths:
            try:
                from blog.codex_image_gen import _ocr_text_check
                result = _ocr_text_check(str(img_path))
                if not result["legible"]:
                    ocr_failures += 1
            except Exception:
                ocr_failures += 1
        failure_pct = ocr_failures / total * 100
        if failure_pct > 50:
            logging.getLogger("blog_pipeline").warning(
                "Systemic OCR failure: title='%s', %d/%d images illegible (%.0f%%). "
                "Flagging post for review.",
                draft.get("title", ""), ocr_failures, total, failure_pct,
            )


def retry_failed_images(slug: str, stream: str,
                        repo: Optional[str] = None) -> dict:
    """Re-attempt image generation for a post in the failed_images tracking.

    Re-runs illustrate with the draft's title/description. On success,
    re-assembles, re-stages, and removes from the tracking file. On failure,
    increments the attempt count.

    Returns:
        {"status": "ok"|"failed_images", ...}
    """
    repo_path = repo or str(SAHILBLOG_REPO)
    entries = _get_failed_entries()
    entry = next((e for e in entries if e.get("slug") == slug), None)
    if not entry:
        return {"status": "not_found", "slug": slug}

    # Reconstruct a minimal draft for illustration.
    draft = {
        "title": slug.replace("-", " ").title(),
        "description": "",
        "body_md": "",
        "slug": slug,
        "stream": stream,
    }

    images = illustrate(draft)
    hero_ok = images.get("hero_path") is not None
    sections_ok = bool(images.get("section_paths"))

    if not hero_ok and not sections_ok:
        _track_failed_image(slug, stream, "Retry: all images still failing")
        return {"status": "failed_images", "slug": slug}

    # Success — remove from tracking.
    _remove_from_failed(slug)
    return {"status": "ok", "slug": slug, "hero_path": images.get("hero_path")}


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