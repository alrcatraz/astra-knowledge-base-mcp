"""PostgreSQL connection and schema management for Astra Knowledge Base MCP."""

import os
import psycopg2
import psycopg2.extras

# Connection config from environment (or defaults for local dev)
DB_CONFIG = {
    "host": os.environ.get("ASTRA_DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("ASTRA_DB_PORT", "5432")),
    "dbname": os.environ.get("ASTRA_DB_NAME", "astra_kb"),
    "user": os.environ.get("ASTRA_DB_USER", "astramcp"),
    "password": os.environ.get("ASTRA_DB_PASSWORD", "astra_kb_2026"),
}

# Schema SQL — created once per knowledge base
KB_REGISTRY_DDL = """
CREATE TABLE IF NOT EXISTS public.kb_registry (
    name        TEXT PRIMARY KEY,
    description TEXT,
    enabled     BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
"""

CHUNKS_DDL = """
CREATE SCHEMA IF NOT EXISTS {schema};

CREATE TABLE IF NOT EXISTS {schema}.chunks (
    id          SERIAL PRIMARY KEY,
    title       TEXT,
    content     TEXT NOT NULL,
    source      TEXT,
    tags        TEXT[],
    created_at  TIMESTAMPTZ DEFAULT NOW(),

    search_vec  TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('simple', coalesce(title, '') || ' ' || content)
    ) STORED
);

CREATE INDEX IF NOT EXISTS idx_{schema}_fts
    ON {schema}.chunks USING GIN (search_vec);
"""


def get_connection():
    """Get a new database connection."""
    return psycopg2.connect(**DB_CONFIG)


def init_registry():
    """Ensure the KB registry table exists."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(KB_REGISTRY_DDL)
        conn.commit()


def ensure_kb_schema(kb_name: str):
    """Create the schema and chunks table for a knowledge base if not exists."""
    safe_name = _sanitize(kb_name)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(CHUNKS_DDL.format(schema=f"kb_{safe_name}"))
        conn.commit()


def drop_kb_schema(kb_name: str):
    """Drop a knowledge base schema entirely."""
    safe_name = _sanitize(kb_name)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS kb_{safe_name} CASCADE")
            cur.execute("DELETE FROM public.kb_registry WHERE name = %s", (kb_name,))
        conn.commit()


def _sanitize(name: str) -> str:
    """Sanitize a KB name for use as a PostgreSQL identifier."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name).lower()
