"""
PostgreSQL backend for Astra Knowledge Base MCP.

Provides the same interface as kb_manager.py + search/fts.py
but targets PG schemas (kb_dynamic_ref, kb_hermes_config, ...)
with to_tsvector full-text search.

Activate by setting env: ASTRA_KB_BACKEND=postgres
"""

import json
import os
import re

# PG DSN: use Unix socket peer auth (postgres user) by default
PG_DSN = os.environ.get(
    "ASTRA_KB_PG_DSN",
    "dbname=astra_kb user=postgres host=/run/postgresql",
)
SCHEMA_PREFIX = "kb_"


# ── Connection ────────────────────────────────────────────────────

def get_conn():
    import psycopg2
    return psycopg2.connect(PG_DSN)


def _fetch_all(sql, params=None):
    """Execute query and return all rows as tuples."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    finally:
        conn.close()


def _fetch_one(sql, params=None):
    """Execute query and return first row or None."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()
    finally:
        conn.close()


def _execute(sql, params=None):
    """Execute statement and return cursor (for rowcount)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            conn.commit()
            return cur
    finally:
        conn.close()


def _execute_many(sql, params_list):
    """Execute executemany."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.executemany(sql, params_list)
            conn.commit()
    finally:
        conn.close()


# ── KB registry ───────────────────────────────────────────────────

def list_kbs():
    rows = _fetch_all(
        "SELECT name, description, enabled, created_at FROM kb_registry ORDER BY name"
    )
    return [
        {
            "name": r[0],
            "description": r[1],
            "enabled": bool(r[2]),
            "created_at": r[3].isoformat() if hasattr(r[3], "isoformat") else str(r[3]),
        }
        for r in rows
    ]


def create_kb(name: str, description: str = ""):
    safe_name = name.strip().lower().replace(" ", "_")
    if not safe_name:
        return {"error": "Name cannot be empty"}

    schema = f"{SCHEMA_PREFIX}{safe_name}"

    existing = _fetch_one(
        "SELECT 1 FROM kb_registry WHERE name = %s", (safe_name,)
    )
    if existing:
        return {"error": f"Knowledge base '{safe_name}' already exists"}

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.chunks (
                    id         SERIAL PRIMARY KEY,
                    title      TEXT NOT NULL DEFAULT '',
                    content    TEXT NOT NULL,
                    source     TEXT,
                    tags       TEXT[] DEFAULT '{{}}',
                    media_url  TEXT,
                    media_type TEXT,
                    embed_vec vector(1024),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    search_vec TSVECTOR GENERATED ALWAYS AS (
                        to_tsvector('simple', coalesce(title,'') || ' ' || content)
                    ) STORED
                )
            """)
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{schema}_fts ON {schema}.chunks USING gin(search_vec)"
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{schema}_embed ON {schema}.chunks "
                f"USING hnsw (embed_vec vector_cosine_ops)"
            )
            cur.execute(
                "INSERT INTO kb_registry (name, description) VALUES (%s, %s)",
                (safe_name, description),
            )
        conn.commit()
    finally:
        conn.close()

    return {"success": True, "name": safe_name, "description": description}


def delete_kb(name: str):
    schema = f"{SCHEMA_PREFIX}{name}"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            cur.execute("DELETE FROM kb_registry WHERE name = %s", (name,))
        conn.commit()
    finally:
        conn.close()
    return {"success": True, "name": name}


def enable_kb(name: str):
    cur = _execute(
        "UPDATE kb_registry SET enabled = true, updated_at = now() WHERE name = %s",
        (name,),
    )
    if cur.rowcount == 0:
        return {"error": f"Knowledge base '{name}' not found"}
    return {"success": True, "name": name, "enabled": True}


def disable_kb(name: str):
    cur = _execute(
        "UPDATE kb_registry SET enabled = false, updated_at = now() WHERE name = %s",
        (name,),
    )
    if cur.rowcount == 0:
        return {"error": f"Knowledge base '{name}' not found"}
    return {"success": True, "name": name, "enabled": False}


def get_enabled_kb_names() -> list[str]:
    rows = _fetch_all("SELECT name FROM kb_registry WHERE enabled = true")
    return [r[0] for r in rows]


# ── Chunks ─────────────────────────────────────────────────────────

def add_chunks(kb_name: str, chunks: list[dict]) -> dict:
    """Add chunks with optional auto-embedding."""
    schema = f"{SCHEMA_PREFIX}{kb_name}"

    for c in chunks:
        content = c.get("content", "")
        title = c.get("title", "")

        # Embed the chunk content
        vector = None
        embed_text_for_store = content[:2048]  # clip to avoid over-long input
        try:
            from embed_client import embed_text
            vector = embed_text(embed_text_for_store)
        except Exception:
            vector = None

        # Insert with embed_vec if available
        if vector is not None:
            _execute(
                f"""INSERT INTO {schema}.chunks (title, content, source, tags, media_url, media_type, embed_vec)
                    VALUES (%s, %s, %s, %s, %s, %s, %s::vector)""",
                (
                    title,
                    content,
                    c.get("source"),
                    c.get("tags", []),
                    c.get("media_url"),
                    c.get("media_type"),
                    str(vector),
                ),
            )
        else:
            _execute(
                f"INSERT INTO {schema}.chunks (title, content, source, tags, media_url, media_type) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    title,
                    content,
                    c.get("source"),
                    c.get("tags", []),
                    c.get("media_url"),
                    c.get("media_type"),
                ),
            )

    return {"inserted": len(chunks)}


# ── Search ─────────────────────────────────────────────────────────

def search_kbs(query: str, kb_names: list[str] | None = None, limit: int = 10) -> list[dict]:
    """Full-text search across knowledge bases using PG tsvector."""
    targets = kb_names or get_enabled_kb_names()
    if not targets or not query.strip():
        return []

    # Build a UNION ALL query across targeted KBs
    parts = []
    for kb in targets:
        schema = f"{SCHEMA_PREFIX}{kb}"
        parts.append(f"""
            SELECT c.id AS chunk_id, '{kb}' AS kb_name, c.title, c.content,
                   c.source, c.tags::text AS tags, c.media_url, c.media_type,
                   ts_rank(c.search_vec, plainto_tsquery('simple', %s)) AS score
            FROM {schema}.chunks c
            WHERE c.search_vec @@ plainto_tsquery('simple', %s)
        """)

    if not parts:
        return []

    union_sql = " UNION ALL ".join(parts)
    full_sql = f"""
        SELECT * FROM ({union_sql}) AS combined
        WHERE combined.score > 0
        ORDER BY combined.score DESC
        LIMIT %s
    """

    # Parameters: for each part, (query, query); final LIMIT
    params = []
    for _ in targets:
        params.extend([query, query])
    params.append(limit)

    rows = _fetch_all(full_sql, params)

    results = []
    for row in rows:
        tags = _parse_tags(row[5])
        result = {
            "chunk_id": row[0],
            "kb": row[1],
            "title": row[2],
            "content": row[3],
            "score": round(float(row[8]), 4),
            "source": row[4],
            "tags": tags,
        }
        if row[6]:  # media_url
            result["media_url"] = row[6]
        if row[7]:  # media_type
            result["media_type"] = row[7]
        results.append(result)

    return results


def search_kbs_vector(query: str, kb_names: list[str] | None = None,
                      limit: int = 10) -> list[dict]:
    """Vector-only search using embedding + pgvector cosine distance.

    Falls back to FTS if embedding is unavailable or returns no results.
    """
    # Embed query
    try:
        from embed_client import embed_text
        vector = embed_text(query)
    except Exception:
        vector = None

    if vector is None:
        # Fallback to FTS
        return search_kbs(query, kb_names, limit)

    targets = kb_names or get_enabled_kb_names()
    if not targets:
        return []

    # Build UNION ALL with cosine distance
    parts = []
    for kb in targets:
        schema = f"{SCHEMA_PREFIX}{kb}"
        parts.append(f"""
            SELECT c.id AS chunk_id, '{kb}' AS kb_name, c.title, c.content,
                   c.source, c.tags::text AS tags, c.media_url, c.media_type,
                   1 - (c.embed_vec <=> %s::vector) AS score
            FROM {schema}.chunks c
            WHERE c.embed_vec IS NOT NULL
        """)

    if not parts:
        return search_kbs(query, kb_names, limit)

    union_sql = " UNION ALL ".join(parts)
    vec_str = str(vector)
    full_sql = f"""
        SELECT * FROM ({union_sql}) AS combined
        WHERE combined.score IS NOT NULL
        ORDER BY combined.score DESC
        LIMIT %s
    """

    params = [vec_str] * len(targets) + [limit]
    try:
        rows = _fetch_all(full_sql, params)
    except Exception:
        return search_kbs(query, kb_names, limit)

    results = []
    for row in rows:
        tags = _parse_tags(row[5])
        result = {
            "chunk_id": row[0],
            "kb": row[1],
            "title": row[2],
            "content": row[3],
            "score": round(float(row[8]), 4),
            "source": row[4],
            "tags": tags,
        }
        if row[6]:
            result["media_url"] = row[6]
        if row[7]:
            result["media_type"] = row[7]
        results.append(result)

    return results


def search_kbs_hybrid(query: str, kb_names: list[str] | None = None,
                      limit: int = 10, alpha: float = 0.5) -> list[dict]:
    """Hybrid search combining FTS and vector scores.

    alpha: weight for FTS (1-alpha for vector). Default 0.5 = equal weight.
    """
    fts_results = search_kbs(query, kb_names, limit=limit * 2)
    vec_results = search_kbs_vector(query, kb_names, limit=limit * 2)

    # Merge by chunk_id
    merged: dict[int, dict] = {}
    for r in fts_results:
        cid = r["chunk_id"]
        merged[cid] = r
        merged[cid]["_score"] = r["score"] * alpha

    for r in vec_results:
        cid = r["chunk_id"]
        if cid in merged:
            merged[cid]["_score"] = (merged[cid]["_score"] +
                                     r["score"] * (1 - alpha))
        else:
            merged[cid] = r
            merged[cid]["_score"] = r["score"] * (1 - alpha)

    # Sort by combined score, then add rank_boost for exact FTS matches
    sorted_results = sorted(
        merged.values(),
        key=lambda x: x.get("_score", 0),
        reverse=True,
    )

    # Remove internal _score, return top limit
    for r in sorted_results:
        r.pop("_score", None)

    return sorted_results[:limit]


def list_chunks(kb_name: str, limit: int = 50, offset: int = 0):
    """List chunks in a knowledge base, ordered by created_at desc."""
    schema = f"{SCHEMA_PREFIX}{kb_name}"
    try:
        rows = _fetch_all(
            f"""SELECT id, title, LEFT(content, 200) AS content_preview,
                       source, tags::text AS tags,
                       media_url, media_type, created_at
                FROM {schema}.chunks
                ORDER BY created_at DESC
                LIMIT %s OFFSET %s""",
            (limit, offset),
        )
    except Exception as e:
        return {"error": f"KB '{kb_name}' not found: {e}"}

    return [
        {
            "chunk_id": r[0],
            "title": r[1],
            "content_preview": r[2],
            "source": r[3],
            "tags": _parse_tags(r[4]),
            "media_url": r[5],
            "media_type": r[6],
            "created_at": r[7].isoformat() if hasattr(r[7], "isoformat") else str(r[7]),
        }
        for r in rows
    ]


def update_chunk(kb_name: str, chunk_id: int, mode: str = "replace",
                 title: str | None = None, content: str | None = None,
                 source: str | None = None, tags: list[str] | None = None,
                 media_url: str | None = None, media_type: str | None = None) -> dict:
    """Update a chunk. Unset fields keep their current value.

    mode="replace": overwrite content entirely.
    mode="append":   append new content after a newline.
    """
    schema = f"{SCHEMA_PREFIX}{kb_name}"
    sets = []
    params = []

    if title is not None:
        sets.append("title = %s")
        params.append(title)
    if source is not None:
        sets.append("source = %s")
        params.append(source)
    if tags is not None:
        sets.append("tags = %s")
        params.append(tags)
    if media_url is not None:
        sets.append("media_url = %s")
        params.append(media_url)
    if media_type is not None:
        sets.append("media_type = %s")
        params.append(media_type)

    if content is not None:
        if mode == "append":
            sets.append("content = content || %s")
            params.append("\n" + content)
        else:
            sets.append("content = %s")
            params.append(content)

    if not sets:
        return {"error": "No fields to update"}

    params.append(chunk_id)
    try:
        cur = _execute(
            f"UPDATE {schema}.chunks SET {', '.join(sets)} WHERE id = %s",
            params,
        )
    except Exception as e:
        return {"error": f"Update failed: {e}"}

    if cur.rowcount == 0:
        return {"error": f"Chunk {chunk_id} not found in KB '{kb_name}'"}

    # Return the updated chunk
    updated = _fetch_one(
        f"""SELECT id, title, content, source, tags::text AS tags,
                   media_url, media_type, created_at
            FROM {schema}.chunks WHERE id = %s""",
        (chunk_id,),
    )
    if not updated:
        return {"error": "Chunk deleted during update"}

    return {
        "success": True,
        "chunk": {
            "chunk_id": updated[0],
            "title": updated[1],
            "content": updated[2],
            "source": updated[3],
            "tags": _parse_tags(updated[4]),
            "media_url": updated[5],
            "media_type": updated[6],
            "created_at": updated[7].isoformat() if hasattr(updated[7], "isoformat") else str(updated[7]),
        },
    }


def delete_chunk(kb_name: str, chunk_id: int) -> dict:
    """Delete a single chunk by id."""
    schema = f"{SCHEMA_PREFIX}{kb_name}"
    try:
        cur = _execute(
            f"DELETE FROM {schema}.chunks WHERE id = %s",
            (chunk_id,),
        )
    except Exception as e:
        return {"error": f"Delete failed: {e}"}

    if cur.rowcount == 0:
        return {"error": f"Chunk {chunk_id} not found in KB '{kb_name}'"}
    return {"success": True, "deleted": chunk_id}


def mgmt_list_tables() -> list[dict]:
    """List tables in the mgmt schema."""
    rows = _fetch_all(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'mgmt' ORDER BY tablename"
    )
    return [{"table": r[0]} for r in rows]


def mgmt_query(table: str, filter_col: str | None = None,
               filter_val: str | None = None, limit: int = 20) -> dict:
    """Query a table in the mgmt schema.

    If filter_col and filter_val are provided, WHERE filter_col = filter_val.
    """
    allowed = {"services", "health_log", "api_keys"}
    if table not in allowed:
        return {"error": f"Unknown mgmt table '{table}'. Allowed: {sorted(allowed)}"}

    if filter_col and filter_val:
        # Validate column name to prevent injection
        safe_col = filter_col.replace('"', "").replace(";", "")
        sql = f'SELECT * FROM mgmt.{table} WHERE "{safe_col}" = %s LIMIT %s'
        params = (filter_val, limit)
    else:
        sql = f"SELECT * FROM mgmt.{table} LIMIT %s"
        params = (limit,)

    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
        conn.close()
    except Exception as e:
        return {"error": str(e)}

    results = []
    for row in rows:
        d = dict(zip(cols, row))
        # Convert datetime/date to isoformat
        for k, v in d.items():
            if hasattr(v, "isoformat"):
                d[k] = v.isoformat()
        results.append(d)

    return {"table": table, "rows": len(results), "data": results}


def _parse_tags(tags_val) -> list[str]:
    """Parse tags from PG text[] format or list."""
    if tags_val is None:
        return []
    if isinstance(tags_val, list):
        return tags_val
    if isinstance(tags_val, str):
        # PG array literal: {tag1,tag2} or {"tag with space"}
        if tags_val.startswith("{"):
            matches = re.findall(r'"([^"]*)"|(\w+(?:[-\w]*\w)*)', tags_val)
            flat = [g[0] or g[1] for g in matches]
            return [t for t in flat if t]
        try:
            return json.loads(tags_val)
        except (json.JSONDecodeError, TypeError):
            return []
    return []
