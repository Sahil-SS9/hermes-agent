"""Tests for blog.blog_router — per-stream topic selection + dedup.

The router reuses database.get_recently_used_topics / log_topic_usage with
brand=f"blog_{stream}" (mirrors article_pipeline's cross-run dedup). It gathers
candidate topics from the stream's sources, drops recently-used ids, and picks
the highest-priority. record() writes back AFTER a successful publish.
"""
import blog.blog_router as br
from blog.blog_streams import STREAMS


def _fake_topic(tid, priority=5, summary="a topic", tags=None, source=None):
    t = {
        "topic_id": tid,
        "title_hint": summary,
        "tags": tags or [],
        "source_override": source,  # None = use stream config source
        "signals": [{"signal_id": tid, "summary": summary, "priority": priority}],
        "priority": priority,
    }
    return t


def test_choose_returns_topic_dict_or_none(monkeypatch):
    """choose(stream) returns {topic_id, title_hint, tags, source, signals} or None."""
    monkeypatch.setattr(br, "_recent_used", lambda stream: [])
    monkeypatch.setattr(br, "_gather_candidates", lambda stream: [_fake_topic("t1", 7)])
    out = br.choose("builder")
    assert out is not None
    assert out["topic_id"] == "t1"
    assert "title_hint" in out
    assert "tags" in out
    assert "source" in out
    assert "signals" in out


def test_choose_returns_none_when_no_candidates(monkeypatch):
    monkeypatch.setattr(br, "_recent_used", lambda stream: [])
    monkeypatch.setattr(br, "_gather_candidates", lambda stream: [])
    assert br.choose("ai") is None


def test_choose_excludes_recently_used(monkeypatch):
    """Topics within the recency window are excluded."""
    monkeypatch.setattr(br, "_recent_used", lambda stream: ["used1"])
    monkeypatch.setattr(br, "_gather_candidates",
                       lambda stream: [_fake_topic("used1", 9), _fake_topic("fresh1", 5)])
    out = br.choose("pm")
    assert out is not None
    assert out["topic_id"] == "fresh1"


def test_choose_picks_highest_priority(monkeypatch):
    monkeypatch.setattr(br, "_recent_used", lambda stream: [])
    cands = [_fake_topic("low", 3), _fake_topic("high", 9), _fake_topic("mid", 6)]
    monkeypatch.setattr(br, "_gather_candidates", lambda stream: cands)
    out = br.choose("ai")
    assert out["topic_id"] == "high"


def test_choose_uses_stream_source_from_config(monkeypatch):
    """The returned source matches the stream's configured source."""
    monkeypatch.setattr(br, "_recent_used", lambda stream: [])
    monkeypatch.setattr(br, "_gather_candidates", lambda stream: [_fake_topic("t1")])
    out = br.choose("ai")
    assert out["source"] == STREAMS["ai"]["source"]  # research-paper


def test_choose_uses_stream_base_tags(monkeypatch):
    """The returned tags include the stream's base_tags."""
    monkeypatch.setattr(br, "_recent_used", lambda stream: [])
    monkeypatch.setattr(br, "_gather_candidates",
                       lambda stream: [_fake_topic("t1", tags=["extra-tag"])])
    out = br.choose("ai")
    assert "ai" in out["tags"]  # base tag from config
    assert "extra-tag" in out["tags"]  # topic tag merged


def test_record_writes_to_db_with_blog_brand(monkeypatch):
    """record() calls database.log_topic_usage with brand=f'blog_{stream}'."""
    calls = []
    monkeypatch.setattr(br.db, "log_topic_usage",
                        lambda topic_id, brand, topic_text, platform="", **kw: calls.append(
                            (topic_id, brand, topic_text, platform)))
    br.record("builder", "tid1", "title text")
    # quality_score=None is passed as 5th arg.
    assert ("tid1", "blog_builder", "title text", "blog") in calls
    # The call tuple format is (topic_id, brand, topic_text, platform, quality_score)
    # Check that it has the right first 4 even when quality_score is passed.
    match = [c for c in calls if c[0] == "tid1" and c[1] == "blog_builder"]
    assert match, "Expected tid1 call not found"


def test_record_is_defensive_on_db_error(monkeypatch):
    """record() swallows DB exceptions so a failed publish doesn't crash."""
    monkeypatch.setattr(br.db, "log_topic_usage",
                        lambda **kw: (_ for _ in ()).throw(RuntimeError("db down")))
    # Must not raise.
    br.record("ai", "tid1", "title")


def test_recent_used_is_defensive(monkeypatch):
    """_recent_used returns [] on DB error (degrades to in-run-only dedup)."""
    monkeypatch.setattr(br.db, "get_recently_used_topics",
                        lambda brand, days: (_ for _ in ()).throw(RuntimeError("db down")))
    assert br._recent_used("ai") == []


def test_gather_candidates_builder_uses_activity_collector(monkeypatch):
    """Builder stream sources map to activity_collector.collect_all signals."""
    monkeypatch.setattr(br.ac, "collect_all", lambda: {
        "signals": [{"signal_id": "gh1", "summary": "push", "priority": 8,
                     "pillar": "agent_build_notes"}],
    })
    cands = br._gather_candidates("builder")
    # Framework seeds (10) are now injected alongside the signal
    # and come first due to highest priority.
    assert len(cands) == 11, f"Expected 10 framework + 1 signal = 11, got {len(cands)}"
    assert cands[0]["topic_id"].startswith("fw-"), "Framework seeds should be first"
    # The signal should still be present (last, lower priority).
    assert any(c["topic_id"] == "gh1" for c in cands), "Signal should still be present"


def test_gather_candidates_unknown_stream_returns_empty(monkeypatch):
    """An unknown stream name returns [] (no crash)."""
    assert br._gather_candidates("nonexistent") == []