"""SQLite database for draft lifecycle — Content Engine v2 schema."""
import sqlite3
from datetime import datetime
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
    status             TEXT NOT NULL DEFAULT 'draft',
    created_at         TEXT NOT NULL,
    approved_at        TEXT,
    rejected_at        TEXT,
    published_at       TEXT,
    postiz_id          TEXT,
    ai_enriched_at     TEXT,
    regenerate_count   INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_brand ON drafts(brand);
CREATE INDEX IF NOT EXISTS idx_status ON drafts(status);
CREATE INDEX IF NOT EXISTS idx_created ON drafts(created_at);
CREATE INDEX IF NOT EXISTS idx_content_type ON drafts(content_type);
"""

def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(SCHEMA)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(drafts)").fetchall()}
    for col_name, col_type in [
        ("ai_enriched_at", "TEXT"),
        ("content_type", "TEXT"),
        ("visual_description", "TEXT"),
        ("ai_image_path", "TEXT"),
        ("ai_video_path", "TEXT"),
        ("rejected_at", "TEXT"),
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
) -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """
        INSERT INTO drafts (id, brand, platform, content_type, pillar, topic, title, body_text, visual_description, visual_path, ai_image_path, ai_video_path, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            draft_id, brand, platform, content_type, pillar, topic,
            title, body_text, visual_description, visual_path,
            ai_image_path, ai_video_path, datetime.utcnow().isoformat(),
        ),
    )
    conn.commit()
    conn.close()

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
    """Mark Stage 2 completed so re-running is idempotent."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        "UPDATE drafts SET ai_enriched_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), draft_id),
    )
    conn.commit()
    conn.close()

def list_approved_pending_enrichment() -> List[dict]:
    """Approved drafts not yet enriched (Stage 2)."""
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
    """Fetch one draft by id (any status)."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def truncate_drafts() -> None:
    """Delete all drafts. Dangerous — use for reset only."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DELETE FROM drafts")
    conn.commit()
    conn.close()


def purge_stale_drafts(retention_hours: int = 48, brand: Optional[str] = None) -> int:
    """Delete drafts older than retention_hours. Respects brand filter if given.

    Returns count of deleted rows.
    """
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
    """Preview how many drafts would be purged (dry-run)."""
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
    """List drafts by content type."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM drafts WHERE content_type = ? AND status = 'draft' ORDER BY created_at DESC",
        (content_type,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
