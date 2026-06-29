"""SQLite database for draft lifecycle -- Content Engine v2.1 schema.

Adds topic_usage_log for recency tracking.
"""
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id                 TEXT PRIMARY KEY,
    brand              TEXT NOT NULL,
    platform           TEXT NOT NULL,
    content_type       TEXT NOT NULL DEFAULT 'text',
    pillar             TEXT NOT NULL,
    topic              TEXT NOT NULL,
    title              TEXT,
    body_text          TEXT NOT NULL,
    visual_description TEXT,
    visual_path        TEXT,
    ai_image_path      TEXT,
    ai_video_path      TEXT,
    image_prompt       TEXT,
    video_prompt       TEXT,
    status             TEXT NOT NULL DEFAULT 'draft',
    created_at         TEXT NOT NULL,
    approved_at        TEXT,
    rejected_at        TEXT,
    published_at       TEXT,
    postiz_id          TEXT,
    ai_enriched_at     TEXT,
    regenerate_count   INTEGER DEFAULT 0,
    slop_score         INTEGER DEFAULT 0,
    slop_issues        TEXT DEFAULT '',
    source_provenance  TEXT,
    editorial_rationale TEXT
);

CREATE INDEX IF NOT EXISTS idx_brand ON drafts(brand);
CREATE INDEX IF NOT EXISTS idx_status ON drafts(status);
CREATE INDEX IF NOT EXISTS idx_created ON drafts(created_at);
CREATE INDEX IF NOT EXISTS idx_content_type ON drafts(content_type);

CREATE TABLE IF NOT EXISTS topic_usage_log (
    topic_id      TEXT PRIMARY KEY,
    brand         TEXT NOT NULL,
    topic_text    TEXT NOT NULL,
    used_at       TEXT NOT NULL,
    platform      TEXT,
    quality_score INTEGER
);

CREATE INDEX IF NOT EXISTS idx_usage_brand ON topic_usage_log(brand);
CREATE INDEX IF NOT EXISTS idx_usage_used_at ON topic_usage_log(used_at);
"""

def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(SCHEMA)
    # Migrate existing DB: add missing columns
    # Add quality_score to topic_usage_log
    usage_cols = {row[1] for row in conn.execute("PRAGMA table_info(topic_usage_log)").fetchall()}
    if "quality_score" not in usage_cols:
        try:
            conn.execute("ALTER TABLE topic_usage_log ADD COLUMN quality_score INTEGER")
        except sqlite3.OperationalError:
            pass
    cols = {row[1] for row in conn.execute("PRAGMA table_info(drafts)").fetchall()}
    for col_name, col_type in [
        ("ai_enriched_at", "TEXT"),
        ("content_type", "TEXT"),
        ("visual_description", "TEXT"),
        ("ai_image_path", "TEXT"),
        ("ai_video_path", "TEXT"),
        ("image_prompt", "TEXT"),
        ("video_prompt", "TEXT"),
        ("rejected_at", "TEXT"),
        ("slop_score", "INTEGER"),
        ("slop_issues", "TEXT"),
        ("source_provenance", "TEXT"),
        ("editorial_rationale", "TEXT"),
    ]:
        if col_name not in cols:
            try:
                conn.execute(f"ALTER TABLE drafts ADD COLUMN {col_name} {col_type}")
            except sqlite3.OperationalError:
                pass
    conn.commit()
    conn.close()

def insert_draft(
    draft_id: str,
    brand: str,
    platform: str,
    pillar: str,
    topic: str,
    title: Optional[str],
    body_text: str,
    content_type: str = "text",
    visual_description: Optional[str] = None,
    visual_path: Optional[str] = None,
    ai_image_path: Optional[str] = None,
    ai_video_path: Optional[str] = None,
    slop_score: int = 0,
    slop_issues: str = "",
    source_provenance: Optional[dict] = None,
    editorial_rationale: str = "",
) -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """
        INSERT INTO drafts (id, brand, platform, content_type, pillar, topic, title, body_text, visual_description, visual_path, ai_image_path, ai_video_path, slop_score, slop_issues, source_provenance, editorial_rationale, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            draft_id, brand, platform, content_type, pillar, topic,
            title, body_text, visual_description, visual_path,
            ai_image_path, ai_video_path, slop_score, slop_issues,
            json.dumps(source_provenance or {}, ensure_ascii=False),
            editorial_rationale or "",
            datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()

# ── Topic usage tracking ──

def log_topic_usage(topic_id: str, brand: str, topic_text: str, platform: str = "",
                     quality_score: Optional[int] = None) -> None:
    """Record that a topic was used for draft generation.

    quality_score (0-10, nullable) stored for routing feedback.
    """
    conn = sqlite3.connect(str(DB_PATH))
    if quality_score is not None:
        conn.execute(
            """
            INSERT OR REPLACE INTO topic_usage_log (topic_id, brand, topic_text, used_at, platform, quality_score)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (topic_id, brand, topic_text, datetime.utcnow().isoformat(), platform, quality_score),
        )
    else:
        conn.execute(
            """
            INSERT OR REPLACE INTO topic_usage_log (topic_id, brand, topic_text, used_at, platform)
            VALUES (?, ?, ?, ?, ?)
            """,
            (topic_id, brand, topic_text, datetime.utcnow().isoformat(), platform),
        )
    conn.commit()
    conn.close()

def get_recently_used_topics(brand: str, days: int = 30) -> List[str]:
    """Return topic_ids used within the last N days."""
    conn = sqlite3.connect(str(DB_PATH))
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        "SELECT topic_id FROM topic_usage_log WHERE brand = ? AND used_at > ?",
        (brand, cutoff),
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_quality_scores(brand: str) -> list[dict]:
    """Return topic_ids and their quality_score for a brand, filtering non-null scores."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT topic_id, quality_score FROM topic_usage_log WHERE brand = ? AND quality_score IS NOT NULL",
        (brand,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def is_topic_recently_used(topic_id: str, days: int = 30) -> bool:
    """Check if a specific topic_id was used within the last N days."""
    conn = sqlite3.connect(str(DB_PATH))
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    row = conn.execute(
        "SELECT 1 FROM topic_usage_log WHERE topic_id = ? AND used_at > ?",
        (topic_id, cutoff),
    ).fetchone()
    conn.close()
    return row is not None

def prune_topic_usage_log(retention_days: int = 90) -> int:
    """Delete old topic usage records. Returns count deleted."""
    conn = sqlite3.connect(str(DB_PATH))
    cutoff = (datetime.utcnow() - timedelta(days=retention_days)).isoformat()
    cur = conn.execute("DELETE FROM topic_usage_log WHERE used_at < ?", (cutoff,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted

# ── Existing draft helpers (unchanged) ──

def list_drafts(status: str = "draft", brand: Optional[str] = None) -> List[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    if brand:
        rows = conn.execute(
            "SELECT * FROM drafts WHERE status = ? AND brand = ? ORDER BY created_at DESC",
            (status, brand),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM drafts WHERE status = ? ORDER BY created_at DESC",
            (status,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def list_recent_drafts(minutes: int = 60, status: str = "draft") -> List[dict]:
    """Return recent drafts for the current approval packet."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT * FROM drafts
        WHERE status = ?
          AND created_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)
        ORDER BY created_at ASC
        """,
        (status, f"-{minutes} minutes"),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def approve_draft(draft_id: str) -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "UPDATE drafts SET status = 'approved', approved_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), draft_id),
    )
    conn.commit()
    conn.close()

def reject_draft(draft_id: str) -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "UPDATE drafts SET status = 'rejected', rejected_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), draft_id),
    )
    conn.commit()
    conn.close()

def mark_published(draft_id: str, postiz_id: Optional[str] = None) -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "UPDATE drafts SET status = 'published', published_at = ?, postiz_id = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), postiz_id, draft_id),
    )
    conn.commit()
    conn.close()

def mark_enriched(draft_id: str) -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "UPDATE drafts SET ai_enriched_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), draft_id),
    )
    conn.commit()
    conn.close()

def list_approved_pending_enrichment() -> List[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM drafts "
        "WHERE status = 'approved' AND ai_enriched_at IS NULL "
        "ORDER BY approved_at ASC, created_at ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_draft(draft_id: str) -> Optional[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def update_draft_visual_path(draft_id: str, visual_path: str) -> None:
    """Attach a free/static visual preview path to a draft."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "UPDATE drafts SET visual_path = ? WHERE id = ?",
        (visual_path, draft_id),
    )
    conn.commit()
    conn.close()

def update_draft_ai_image_path(draft_id: str, ai_image_path: str) -> None:
    """Persist the generated image path (FAL/pollinations) to a draft."""
    # `with` on a sqlite connection commits on success, rolls back on error.
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute(
            "UPDATE drafts SET ai_image_path = ? WHERE id = ?",
            (ai_image_path, draft_id),
        )

def update_draft_ai_video_path(draft_id: str, ai_video_path: str) -> None:
    """Persist the generated video path to a draft (Stage 2 / on approval)."""
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute(
            "UPDATE drafts SET ai_video_path = ? WHERE id = ?",
            (ai_video_path, draft_id),
        )

def update_draft_image_prompt(draft_id: str, image_prompt: str) -> None:
    """Persist the prompt fed to the image model, so the dashboard can show it."""
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute(
            "UPDATE drafts SET image_prompt = ? WHERE id = ?",
            (image_prompt, draft_id),
        )

# Note: the default video path is a free ffmpeg slideshow with no model prompt,
# so nothing writes video_prompt yet. The column is kept as forward schema for a
# future paid AI-video model; the dashboard renders the null case honestly.

def truncate_drafts() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DELETE FROM drafts")
    conn.commit()
    conn.close()

def purge_stale_drafts(retention_hours: int = 48, brand: Optional[str] = None) -> int:
    conn = sqlite3.connect(str(DB_PATH))
    if brand:
        cur = conn.execute(
            "DELETE FROM drafts WHERE created_at < strftime('%Y-%m-%dT%H:%M:%S', 'now', ?) AND brand = ?",
            (f"-{retention_hours} hours", brand),
        )
    else:
        cur = conn.execute(
            "DELETE FROM drafts WHERE created_at < strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)",
            (f"-{retention_hours} hours",),
        )
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted

def count_drafts_older_than(retention_hours: int = 48, brand: Optional[str] = None) -> int:
    conn = sqlite3.connect(str(DB_PATH))
    if brand:
        row = conn.execute(
            "SELECT COUNT(*) FROM drafts WHERE created_at < strftime('%Y-%m-%dT%H:%M:%S', 'now', ?) AND brand = ?",
            (f"-{retention_hours} hours", brand),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) FROM drafts WHERE created_at < strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)",
            (f"-{retention_hours} hours",),
        ).fetchone()
    conn.close()
    return row[0] if row else 0

def list_drafts_by_content_type(content_type: str) -> List[dict]:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM drafts WHERE content_type = ? AND status = 'draft' ORDER BY created_at DESC",
        (content_type,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
