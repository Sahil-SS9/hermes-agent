"""Postiz DB bridge: insert approved drafts into Postiz PostgreSQL."""
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

try:
    import psycopg2
except ImportError:
    psycopg2 = None

POSTGRES_HOST = os.getenv("POSTIZ_DB_HOST", "postiz-postgres")
POSTGRES_PORT = int(os.getenv("POSTIZ_DB_PORT", "5432"))
POSTGRES_USER = os.getenv("POSTIZ_DB_USER", "postiz-user")
POSTGRES_PASS = os.getenv("POSTIZ_DB_PASS", "postiz-password")
POSTGRES_DB = os.getenv("POSTIZ_DB_NAME", "postiz-db-local")

# Organisation ID from the existing Postiz instance
ORG_ID = "2645662d-a479-4a6a-91ca-a50a7d29f607"

# Placeholder integration IDs per brand/platform — must be created when social accounts are linked
# Map: "brand_platform" -> integration_id (to be filled as integrations are added)
INTEGRATION_MAP = {
    "matchdaymaestro_twitter": None,
    "matchdaymaestro_instagram": None,
    "matchdaymaestro_tiktok": None,
    "plenishd_twitter": None,
    "plenishd_instagram": None,
    "plenishd_linkedin": None,
    "sahil_twitter_twitter": None,
    "sahil_linkedin_linkedin": None,
    "coachos_twitter": None,
    "coachos_instagram": None,
    "coachos_linkedin": None,
}


def _conn():
    if psycopg2 is None:
        raise RuntimeError("psycopg2 not installed. Install with: pip install psycopg2-binary")
    return psycopg2.connect(
        host=POSTGRES_HOST,
        port=POSTGRES_PORT,
        user=POSTGRES_USER,
        password=POSTGRES_PASS,
        database=POSTGRES_DB,
    )


def _get_integration_id(brand: str, platform: str) -> Optional[str]:
    key = f"{brand}_{platform}"
    return INTEGRATION_MAP.get(key)


def queue_post(
    body_text: str,
    brand: str,
    platform: str,
    title: Optional[str] = None,
    publish_at: Optional[datetime] = None,
    group: str = "kensei-generated",
) -> Optional[str]:
    """Insert a post directly into Postiz DB. Returns the post ID or None."""
    integration_id = _get_integration_id(brand, platform)
    if not integration_id:
        return None

    post_id = str(uuid.uuid4())
    scheduled = publish_at or (datetime.now(timezone.utc) + timedelta(hours=2))

    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO "Post" (
                id, state, "publishDate", "organizationId", "integrationId",
                content, title, "group", delay, "approvedSubmitForOrder",
                "createdAt", "updatedAt"
            ) VALUES (
                %s, 'QUEUE', %s, %s, %s,
                %s, %s, %s, 0, 'NO',
                NOW(), NOW()
            )
            """,
            (post_id, scheduled, ORG_ID, integration_id, body_text, title or "", group),
        )
        conn.commit()
        cur.close()
        return post_id
    except Exception as e:
        print(f"Postiz insert failed: {e}")
        return None
    finally:
        conn.close()


def list_unpublished(brand: Optional[str] = None, limit: int = 50) -> list:
    conn = _conn()
    cur = conn.cursor()
    integration_ids = [v for v in INTEGRATION_MAP.values() if v]
    if not integration_ids:
        cur.execute(
            """
            SELECT id, content, title, "integrationId", state, "publishDate"
            FROM "Post"
            WHERE state = 'QUEUE'
            ORDER BY "publishDate" ASC
            LIMIT %s
            """,
            (limit,),
        )
    else:
        placeholders = ",".join(["%s"] * len(integration_ids))
        q = f"""
            SELECT id, content, title, "integrationId", state, "publishDate"
            FROM "Post"
            WHERE "integrationId" IN ({placeholders}) AND state = 'QUEUE'
            ORDER BY "publishDate" ASC
            LIMIT %s
        """
        cur.execute(q, integration_ids + [limit])
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [dict(zip(["id", "content", "title", "integration_id", "state", "publish_date"], r)) for r in rows]
