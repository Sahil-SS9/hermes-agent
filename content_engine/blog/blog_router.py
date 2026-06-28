"""Blog topic router - per-stream topic selection + cross-run dedup.

Mirrors article_pipeline._recent_article_topic_ids / _record_article_topics
but keys under brand=f"blog_{stream}" so each stream has its own dedup window.

  choose(stream)  -> {topic_id, title_hint, tags, source, signals} or None
  record(stream, topic_id, title)  -> writes back AFTER a successful publish

Candidate gathering:
  - builder: activity_collector.collect_all() signals (gitradar + harness).
  - ai/pm:   manual topic queue file (sources that are not yet wired as
              standalone collectors fall back to the queue; paper_synthesis is
              wired when available). This keeps the router functional today
              without blocking on unbuilt collectors.
"""
from __future__ import annotations
from typing import Optional

import activity_collector as ac
import database as db
from config import BLOG_TOPIC_RECENCY_DAYS
from blog.blog_streams import STREAMS, tags_for


def _recent_used(stream: str) -> list[str]:
    """Topic ids used for this stream within the recency window.

    Read-only and defensive: a DB hiccup must never block today's article.
    """
    try:
        return db.get_recently_used_topics(
            f"blog_{stream}", days=BLOG_TOPIC_RECENCY_DAYS,
        )
    except Exception:
        return []


def _gather_candidates(stream: str) -> list[dict]:
    """Gather candidate topics for a stream.

    Builder stream uses activity_collector (gitradar + harness signals).
    AI/PM streams use a manual topic queue file (forward-compatible: when
    paper_synthesis / pm_frameworks collectors land, they plug in here).
    """
    if stream not in STREAMS:
        return []
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
                "source_override": None,  # use stream config source
                "signals": [sig],
                "priority": sig.get("priority", 0),
            })
        return cands

    # AI / PM: read from the manual topic queue if it exists.
    cands = _read_manual_queue(stream)
    return cands


def _manual_queue_path(stream: str):
    """Path to the manual topic queue for a stream."""
    from pathlib import Path
    return Path(__file__).resolve().parent.parent / "blog_topics" / f"{stream}.jsonl"


def _read_manual_queue(stream: str) -> list[dict]:
    """Read queued topics from blog_topics/<stream>.jsonl (one JSON object per line).

    Each line: {"topic_id", "title_hint", "tags", "priority", "source_override?"}
    Missing file = no candidates (the stream skips that day).
    """
    from pathlib import Path
    import json
    p = _manual_queue_path(stream)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        out.append({
            "topic_id": obj.get("topic_id", ""),
            "title_hint": obj.get("title_hint", ""),
            "tags": obj.get("tags", []),
            # Honest source label: manual queue entries have no live source URL.
            # Explicit source_override may still be set (e.g. "research-paper"
            # for a paper-linked entry), but null defaults to "manual_queue".
            "source_override": obj.get("source_override") or "manual_queue",
            "signals": [{
                "signal_id": obj.get("topic_id", ""),
                "summary": obj.get("title_hint", ""),
                "priority": obj.get("priority", 5),
            }],
            "priority": obj.get("priority", 5),
        })
    return out


def choose(stream: str) -> Optional[dict]:
    """Pick the highest-priority unused topic for a stream.

    Returns a topic dict:
      {topic_id, title_hint, tags, source, signals}
    or None when no candidates remain.
    """
    if stream not in STREAMS:
        return None
    used = set(_recent_used(stream))
    cands = [c for c in _gather_candidates(stream)
             if c.get("topic_id") and c["topic_id"] not in used]
    if not cands:
        return None
    cands.sort(key=lambda c: (-c.get("priority", 0), c.get("topic_id", "")))
    top = cands[0]
    # Source comes from the stream config (the verified contract), not the
    # candidate, unless the candidate explicitly overrides via source_override.
    source = top.get("source_override") or STREAMS[stream]["source"]
    return {
        "topic_id": top["topic_id"],
        "title_hint": top.get("title_hint", ""),
        "tags": tags_for(stream, top.get("tags", [])),
        "source": source,
        "signals": top.get("signals", []),
    }


def record(stream: str, topic_id: str, title: str) -> None:
    """Persist the chosen topic id so future runs cannot re-pick it.

    Called only after a successful publish (record-on-success), mirroring
    the article track. Defensive: a DB hiccup must never crash the pipeline.
    """
    try:
        db.log_topic_usage(
            topic_id=topic_id, brand=f"blog_{stream}",
            topic_text=(title or "")[:200], platform="blog",
        )
    except Exception:
        pass