"""SQLite database for draft lifecycle."""
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id          TEXT PRIMARY KEY,
    brand       TEXT NOT NULL,
    platform    TEXT NOT NULL,
    pillar      TEXT NOT NULL,
    topic       TEXT NOT NULL,
    title       TEXT,
    body_text   TEXT NOT NULL,
    visual_path TEXT,
    status      TEXT NOT NULL DEFAULT 'draft',
    created_at  TEXT NOT NULL,
    approved_at TEXT,
    published_at TEXT,
    postiz_id   TEXT
);

CREATE INDEX IF NOT EXISTS idx_brand ON drafts(brand);
CREATE INDEX IF NOT EXISTS idx_status ON drafts(status);
CREATE INDEX IF NOT EXISTS idx_created ON drafts(created_at);
"""


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript(SCHEMA)
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
    visual_path: Optional[str] = None,
) -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute(
        """
        INSERT INTO drafts (id, brand, platform, pillar, topic, title, body_text, visual_path, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            draft_id,
            brand,
            platform,
            pillar,
            topic,
            title,
            body_text,
            visual_path,
            datetime.utcnow().isoformat(),
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
        "UPDATE drafts SET status = 'rejected' WHERE id = ?",
        (draft_id,),
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
