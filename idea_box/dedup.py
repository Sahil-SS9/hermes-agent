"""Deduplication checker for the Idea Box flow.

Checks a new idea against three sources:
1. Kanban open tasks — title/body similarity
2. session_search — last 30 days of conversation history
3. Mnemosyne recall — semantic memory search

Each source is queried independently.  A match from any source marks
the idea as a duplicate and carries the match details so the idea card
can surface them to Sahil.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from idea_box.models import DedupResult

logger = logging.getLogger("idea_box.dedup")


class DedupSource(str, Enum):
    """Which dedup source produced a match."""

    KANBAN = "kanban"
    SESSION_SEARCH = "session_search"
    MNEMOSYNE = "mnemosyne"


@dataclass
class DedupMatch:
    """A single dedup match from one source."""

    source: DedupSource
    title: str = ""
    summary: str = ""
    ref_id: str = ""           # task id, session id, or memory id
    score: float = 0.0         # 0-1 similarity confidence
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "source": self.source.value,
            "title": self.title,
            "summary": self.summary,
            "ref_id": self.ref_id,
            "score": self.score,
            "extra": self.extra,
        }


# ---------------------------------------------------------------------------
# Similarity helpers
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> set[str]:
    """Lowercase tokenisation for simple overlap similarity."""
    return {w for w in text.lower().split() if len(w) > 2}


def _jaccard_similarity(a: str, b: str) -> float:
    """Jaccard similarity over tokenised strings.

    Simple but effective for short text (idea titles, task summaries).
    Returns 0.0–1.0.
    """
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# Thresholds per source — how similar is "duplicate"?
SIMILARITY_THRESHOLD = 0.35


# ---------------------------------------------------------------------------
# DedupChecker
# ---------------------------------------------------------------------------

class DedupChecker:
    """Run dedup against kanban, session_search, and Mnemosyne.

    Each source is optional and lazily imported so the module works
    in test rigs without all backends present.  Pass mock backends
    via the constructor for testing.
    """

    def __init__(
        self,
        *,
        kanban_conn: Any = None,
        session_search_fn: Any = None,
        mnemosyne_recall_fn: Any = None,
        similarity_threshold: float = SIMILARITY_THRESHOLD,
    ):
        self._kanban_conn = kanban_conn
        self._session_search_fn = session_search_fn
        self._mnemosyne_recall_fn = mnemosyne_recall_fn
        self._threshold = similarity_threshold

    # -- Kanban ----------------------------------------------------------

    def _check_kanban(self, idea_text: str) -> list[DedupMatch]:
        """Query open Kanban tasks for title/body similarity."""
        matches: list[DedupMatch] = []
        if self._kanban_conn is None:
            try:
                from hermes_cli import kanban_db as kb
                _, conn = kb.connect()
            except Exception:
                logger.debug("Kanban unavailable for dedup", exc_info=True)
                return matches
        else:
            conn = self._kanban_conn

        try:
            from hermes_cli import kanban_db as kb

            tasks = kb.list_tasks(conn, include_archived=False)
            for task in tasks:
                # Skip done/archived — only open work matters
                if task.status in ("done", "archived"):
                    continue
                title_sim = _jaccard_similarity(idea_text, task.title or "")
                body_sim = _jaccard_similarity(idea_text, task.body or "")
                best = max(title_sim, body_sim)
                if best >= self._threshold:
                    matches.append(DedupMatch(
                        source=DedupSource.KANBAN,
                        title=task.title or "",
                        summary=(task.body or "")[:200],
                        ref_id=task.id,
                        score=round(best, 3),
                        extra={"status": task.status},
                    ))
        except Exception:
            logger.debug("Kanban dedup query failed", exc_info=True)
        finally:
            if self._kanban_conn is None:
                try:
                    conn.close()
                except Exception:
                    pass

        return matches

    # -- session_search --------------------------------------------------

    def _check_session_search(self, idea_text: str) -> list[DedupMatch]:
        """Query last 30 days of session history for similar ideas."""
        matches: list[DedupMatch] = []
        search_fn = self._session_search_fn

        if search_fn is None:
            try:
                from tools.session_search_tool import session_search
                search_fn = session_search
            except Exception:
                logger.debug("session_search unavailable for dedup", exc_info=True)
                return matches

        try:
            import json
            raw = search_fn(query=idea_text, limit=5)
            data = json.loads(raw) if isinstance(raw, str) else raw
            sessions = data.get("data", data) if isinstance(data, dict) else []
            if not isinstance(sessions, list):
                sessions = sessions.get("sessions", []) if isinstance(sessions, dict) else []

            for sess in sessions:
                snippet = ""
                if isinstance(sess, dict):
                    snippet = sess.get("snippet", sess.get("title", ""))
                    sid = sess.get("session_id", sess.get("id", ""))
                    sim = _jaccard_similarity(idea_text, snippet)
                    if sim >= self._threshold:
                        matches.append(DedupMatch(
                            source=DedupSource.SESSION_SEARCH,
                            title=sess.get("title", ""),
                            summary=snippet[:200],
                            ref_id=str(sid),
                            score=round(sim, 3),
                            extra={"when": sess.get("when", sess.get("created_at", ""))},
                        ))
        except Exception:
            logger.debug("session_search dedup query failed", exc_info=True)

        return matches

    # -- Mnemosyne --------------------------------------------------------

    def _check_mnemosyne(self, idea_text: str) -> list[DedupMatch]:
        """Query Mnemosyne for semantically similar memories."""
        matches: list[DedupMatch] = []
        recall_fn = self._mnemosyne_recall_fn

        if recall_fn is None:
            try:
                # Mnemosyne tools are injected at runtime; use a lazy import
                from hermes_state.memory.mnemosyne_client import recall as mnemosyne_recall
                recall_fn = mnemosyne_recall
            except Exception:
                logger.debug("Mnemosyne unavailable for dedup", exc_info=True)
                return matches

        try:
            results = recall_fn(query=idea_text, limit=5)
            if isinstance(results, str):
                import json
                results = json.loads(results)
            if isinstance(results, dict):
                memories = results.get("memories", results.get("results", []))
            elif isinstance(results, list):
                memories = results
            else:
                memories = []

            for mem in memories:
                if not isinstance(mem, dict):
                    continue
                content = mem.get("content", "")
                sim = _jaccard_similarity(idea_text, content)
                if sim >= self._threshold:
                    matches.append(DedupMatch(
                        source=DedupSource.MNEMOSYNE,
                        title=content[:120],
                        summary=content[:200],
                        ref_id=str(mem.get("id", "")),
                        score=round(sim, 3),
                        extra={"importance": mem.get("importance", 0)},
                    ))
        except Exception:
            logger.debug("Mnemosyne dedup query failed", exc_info=True)

        return matches

    # -- Public API -------------------------------------------------------

    def check(self, idea_text: str) -> DedupResult:
        """Run all three dedup checks and return the combined result."""
        all_matches: list[DedupMatch] = []
        checked: list[str] = []

        kanban_matches = self._check_kanban(idea_text)
        if kanban_matches:
            all_matches.extend(kanban_matches)
        checked.append(DedupSource.KANBAN.value)

        session_matches = self._check_session_search(idea_text)
        if session_matches:
            all_matches.extend(session_matches)
        checked.append(DedupSource.SESSION_SEARCH.value)

        mnemosyne_matches = self._check_mnemosyne(idea_text)
        if mnemosyne_matches:
            all_matches.extend(mnemosyne_matches)
        checked.append(DedupSource.MNEMOSYNE.value)

        is_dup = len(all_matches) > 0
        return DedupResult(
            is_duplicate=is_dup,
            matches=[m.to_dict() for m in all_matches],
            checked_sources=checked,
        )