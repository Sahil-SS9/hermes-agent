from __future__ import annotations
from pathlib import Path
from typing import Optional
import json

import activity_collector as ac
import database as db
from config import BLOG_TOPIC_RECENCY_DAYS
from blog.blog_streams import STREAMS, tags_for


def _recent_used(stream: str) -> list[str]:
    """Topic ids used for this stream within the recency window."""
    try:
        return db.get_recently_used_topics(
            f"blog_{stream}", days=BLOG_TOPIC_RECENCY_DAYS,
        )
    except Exception:
        return []


def _read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file, skipping blank/comment lines. Returns list of parsed dicts."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append(obj)
    return out


def _gather_framework_candidates() -> list[dict]:
    """Read framework seeds from blog_topics/frameworks.jsonl.

    Framework seeds get priority 8-9 so they're picked ahead of regular topics.
    """
    p = Path(__file__).resolve().parent.parent / "blog_topics" / "frameworks.jsonl"
    objs = _read_jsonl(p)
    cands = []
    for obj in objs:
        priority = obj.get("priority", 8)
        cands.append({
            "topic_id": obj.get("topic_id", ""),
            "title_hint": obj.get("title_hint", ""),
            "tags": obj.get("tags", []),
            "source_override": "manual_queue",
            "signals": [{
                "signal_id": obj.get("topic_id", ""),
                "summary": obj.get("title_hint", ""),
                "priority": priority,
            }],
            "priority": priority,
            "domain": obj.get("domain", ""),
        })
    return cands


def _gather_candidates(stream: str) -> list[dict]:
    """Gather candidate topics for a stream.

    All streams: framework seeds injected at highest priority.
    Builder: also uses activity_collector signals.
    AI/PM: also uses manual topic queue file.
    """
    if stream not in STREAMS:
        return []

    # Framework seeds are injected for ALL streams at highest priority.
    framework_cands = _gather_framework_candidates()

    if stream == "builder":
        try:
            result = ac.collect_all()
            signals = result.get("signals", [])
        except Exception:
            signals = []
        cands = []
        for sig in signals:
            cands.append({
                "topic_id": sig.get("signal_id", ""),
                "title_hint": sig.get("summary", ""),
                "tags": [],
                "source_override": None,
                "signals": [sig],
                "priority": sig.get("priority", 0),
            })
        return framework_cands + cands

    # AI / PM: read from the manual topic queue if it exists.
    cands = _read_manual_queue(stream)
    return framework_cands + cands


def _manual_queue_path(stream: str):
    """Path to the manual topic queue for a stream."""
    return Path(__file__).resolve().parent.parent / "blog_topics" / f"{stream}.jsonl"


def _read_manual_queue(stream: str) -> list[dict]:
    """Read queued topics from blog_topics/<stream>.jsonl (one JSON object per line)."""
    p = _manual_queue_path(stream)
    objs = _read_jsonl(p)
    out = []
    for obj in objs:
        out.append({
            "topic_id": obj.get("topic_id", ""),
            "title_hint": obj.get("title_hint", ""),
            "tags": obj.get("tags", []),
            "source_override": obj.get("source_override") or "manual_queue",
            "signals": [{
                "signal_id": obj.get("topic_id", ""),
                "summary": obj.get("title_hint", ""),
                "priority": obj.get("priority", 5),
            }],
            "priority": obj.get("priority", 5),
        })
    return out


def _get_quality_scores(stream: str) -> dict[str, int]:
    """Fetch historical quality scores for framework topics from DB.

    Returns dict of {topic_id: quality_score}.
    """
    try:
        brand = f"blog_{stream}"
        scores_raw = db.get_quality_scores(brand)
        return {r["topic_id"]: r["quality_score"] for r in scores_raw}
    except Exception:
        return {}


def choose(stream: str) -> Optional[dict]:
    """Pick the highest-priority unused topic for a stream.

    Framework topics (priority 8-9) are chosen first. Within equal priority,
    historical quality_score is used as tiebreaker (higher = preferred).

    Returns a topic dict or None when no candidates remain.
    """
    if stream not in STREAMS:
        return None
    used = set(_recent_used(stream))
    cands = [c for c in _gather_candidates(stream)
             if c.get("topic_id") and c["topic_id"] not in used]
    if not cands:
        return None

    # Fetch quality scores for tiebreaking.
    qs = _get_quality_scores(stream)

    # Sort: descending priority, then descending quality_score, then topic_id.
    cands.sort(key=lambda c: (
        -c.get("priority", 0),
        -(qs.get(c.get("topic_id", "")) or 0),
        c.get("topic_id", ""),
    ))
    top = cands[0]
    source = top.get("source_override") or STREAMS[stream]["source"]
    # Mark framework domain so the writer can route to blueprint format.
    domain = top.get("domain", "")
    return {
        "topic_id": top["topic_id"],
        "title_hint": top.get("title_hint", ""),
        "tags": tags_for(stream, top.get("tags", [])),
        "source": source,
        "signals": top.get("signals", []),
        "domain": domain,
        "format": "blueprint" if domain else "essay",
    }


def record(stream: str, topic_id: str, title: str,
           quality_score: Optional[int] = None) -> None:
    """Persist the chosen topic id so future runs cannot re-pick it.

    Called only after a successful publish (record-on-success).
    Stores quality_score when provided for routing feedback.
    """
    try:
        db.log_topic_usage(
            topic_id=topic_id, brand=f"blog_{stream}",
            topic_text=(title or "")[:200], platform="blog",
            quality_score=quality_score,
        )
    except Exception:
        pass
