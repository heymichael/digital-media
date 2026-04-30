"""Database connection pool and queries."""

import logging
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

logger = logging.getLogger(__name__)

_pool: pool.ThreadedConnectionPool | None = None


def warm_connection_pool() -> None:
    """Initialize the connection pool at startup."""
    global _pool
    if _pool is not None:
        return
    from .config import get_settings
    settings = get_settings()
    dsn = settings.database_url
    if not dsn:
        logger.warning("DATABASE_URL not set; skipping pool initialization")
        return
    _pool = pool.ThreadedConnectionPool(1, 10, dsn)
    logger.info("Connection pool initialized")


def close_pool() -> None:
    """Close all connections in the pool."""
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None


@contextmanager
def get_conn():
    """Context manager for database connections from the pool."""
    if _pool is None:
        raise RuntimeError("Connection pool not initialized")
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


def create_asset(
    org_slug: str,
    gcs_bucket: str,
    gcs_path: str,
    filename: str,
    content_type: str,
    size_bytes: int,
    width: int | None,
    height: int | None,
    uploaded_by: str,
) -> dict:
    """Insert a new asset record and return it."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO assets (
                    org_slug, gcs_bucket, gcs_path, filename, content_type,
                    size_bytes, width, height, uploaded_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (org_slug, gcs_bucket, gcs_path, filename, content_type,
                 size_bytes, width, height, uploaded_by),
            )
            return dict(cur.fetchone())


def get_asset(asset_id: UUID, org_slug: str) -> dict | None:
    """Fetch a single asset by ID, scoped to org."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM assets
                WHERE id = %s AND org_slug = %s AND deleted_at IS NULL
                """,
                (str(asset_id), org_slug),
            )
            row = cur.fetchone()
            return dict(row) if row else None


def list_assets(
    org_slug: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List assets for an org, most recent first."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM assets
                WHERE org_slug = %s AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s
                """,
                (org_slug, limit, offset),
            )
            return [dict(row) for row in cur.fetchall()]


def update_asset(
    asset_id: UUID,
    org_slug: str,
    **updates: Any,
) -> dict | None:
    """Update editable fields on an asset."""
    allowed = {"title", "alt_text", "description", "approved_public"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return get_asset(asset_id, org_slug)

    set_clause = ", ".join(f"{k} = %s" for k in filtered)
    values = list(filtered.values()) + [str(asset_id), org_slug]

    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                f"""
                UPDATE assets
                SET {set_clause}, updated_at = now()
                WHERE id = %s AND org_slug = %s AND deleted_at IS NULL
                RETURNING *
                """,
                values,
            )
            row = cur.fetchone()
            return dict(row) if row else None


def soft_delete_asset(asset_id: UUID, org_slug: str) -> bool:
    """Mark an asset as deleted. Returns True if a row was updated."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE assets SET deleted_at = now()
                WHERE id = %s AND org_slug = %s AND deleted_at IS NULL
                """,
                (str(asset_id), org_slug),
            )
            return cur.rowcount > 0


def count_asset_references(asset_id: UUID) -> int:
    """Count how many references exist for an asset."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM asset_references WHERE asset_id = %s",
                (str(asset_id),),
            )
            return cur.fetchone()[0]


def list_asset_references(asset_id: UUID) -> list[dict]:
    """List all references to an asset."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT * FROM asset_references
                WHERE asset_id = %s
                ORDER BY created_at DESC
                """,
                (str(asset_id),),
            )
            return [dict(row) for row in cur.fetchall()]


def create_reference(
    asset_id: UUID,
    consumer_type: str,
    consumer_id: str,
    consumer_field: str | None,
    org_slug: str,
) -> dict:
    """Register a reference to an asset."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                INSERT INTO asset_references (
                    asset_id, consumer_type, consumer_id, consumer_field, org_slug
                ) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (asset_id, consumer_type, consumer_id, consumer_field)
                DO UPDATE SET created_at = now()
                RETURNING *
                """,
                (str(asset_id), consumer_type, consumer_id, consumer_field, org_slug),
            )
            return dict(cur.fetchone())


def delete_reference(reference_id: UUID) -> bool:
    """Remove a reference. Returns True if a row was deleted."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM asset_references WHERE id = %s",
                (str(reference_id),),
            )
            return cur.rowcount > 0


def search_assets_fulltext(
    org_slug: str,
    query: str,
    limit: int = 20,
) -> list[dict]:
    """Full-text search over assets."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *, ts_rank(search_vector, plainto_tsquery('english', %s)) AS rank
                FROM assets
                WHERE org_slug = %s
                  AND deleted_at IS NULL
                  AND search_vector @@ plainto_tsquery('english', %s)
                ORDER BY rank DESC
                LIMIT %s
                """,
                (query, org_slug, query, limit),
            )
            return [dict(row) for row in cur.fetchall()]


def add_asset_tags(
    asset_id: UUID,
    tags: list[dict],
) -> None:
    """Insert tags for an asset. Each tag dict has 'tag', 'source', and optional 'confidence'."""
    if not tags:
        return
    with get_conn() as conn:
        with conn.cursor() as cur:
            for t in tags:
                cur.execute(
                    """
                    INSERT INTO asset_tags (asset_id, tag, source, confidence)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (asset_id, tag) DO NOTHING
                    """,
                    (str(asset_id), t["tag"], t["source"], t.get("confidence")),
                )


def store_embedding(
    asset_id: UUID,
    embedding: list[float],
    model: str,
) -> None:
    """Store or update the vector embedding for an asset."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO asset_embeddings (asset_id, embedding, model)
                VALUES (%s, %s, %s)
                ON CONFLICT (asset_id)
                DO UPDATE SET embedding = EXCLUDED.embedding, model = EXCLUDED.model, created_at = now()
                """,
                (str(asset_id), embedding, model),
            )


def search_assets_semantic(
    org_slug: str,
    query_embedding: list[float],
    limit: int = 20,
) -> list[dict]:
    """Semantic search using pgvector cosine distance."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT a.*, 1 - (e.embedding <=> %s::vector) AS similarity
                FROM assets a
                JOIN asset_embeddings e ON a.id = e.asset_id
                WHERE a.org_slug = %s AND a.deleted_at IS NULL
                ORDER BY e.embedding <=> %s::vector
                LIMIT %s
                """,
                (query_embedding, org_slug, query_embedding, limit),
            )
            return [dict(row) for row in cur.fetchall()]
