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
            # ── Chunks table (existing) ──
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

            # ── SAG: events table (Phase 1) ──
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.events (
                    id         SERIAL PRIMARY KEY,
                    chunk_id   INTEGER NOT NULL REFERENCES {schema}.chunks(id) ON DELETE CASCADE,
                    event_text TEXT NOT NULL,
                    embed_vec  vector(1024)
                )
            """)
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{schema}_event_embed ON {schema}.events "
                f"USING hnsw (embed_vec vector_cosine_ops)"
            )

            # ── SAG: entities table (Phase 1) ──
            # 11 types per SAG paper: time, location, person, organization,
            # group, topic, work, product, action, metric, label
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.entities (
                    id          SERIAL PRIMARY KEY,
                    name        TEXT NOT NULL,
                    entity_type TEXT NOT NULL DEFAULT 'label',
                    embed_vec   vector(1024),
                    UNIQUE(name)
                )
            """)
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{schema}_entity_embed ON {schema}.entities "
                f"USING hnsw (embed_vec vector_cosine_ops)"
            )

            # ── SAG: event-entity association (hyperedge) ──
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.event_entities (
                    event_id  INTEGER NOT NULL REFERENCES {schema}.events(id) ON DELETE CASCADE,
                    entity_id INTEGER NOT NULL REFERENCES {schema}.entities(id) ON DELETE CASCADE,
                    PRIMARY KEY (event_id, entity_id)
                )
            """)

            # ── SAG: extraction tracking ──
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.extraction_status (
                    chunk_id   INTEGER PRIMARY KEY REFERENCES {schema}.chunks(id) ON DELETE CASCADE,
                    extracted  BOOLEAN NOT NULL DEFAULT false,
                    extracted_at TIMESTAMPTZ,
                    error      TEXT
                )
            """)

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

    # Batch embed all chunk contents first
    try:
        from embed_client import embed_batch
        texts = [c.get("content", "")[:2048] for c in chunks]
        vectors = embed_batch(texts)
    except Exception:
        vectors = [None] * len(chunks)

    for c, vector in zip(chunks, vectors):
        content = c.get("content", "")
        title = c.get("title", "")

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


# ═══════════════════════════════════════════════════════════════════
# Phase 1 — SAG: Event/Entity Extraction & Retrieval
# ═══════════════════════════════════════════════════════════════════
#
# Reference: SAG paper (arXiv 2606.15971) — Yuchao Wu et al., Zleap AI
# https://arxiv.org/abs/2606.15971  (MIT License)
#

SAG_ENTITY_TYPES = [
    "time", "location", "person", "organization", "group",
    "topic", "work", "product", "action", "metric", "label",
]


def ensure_sag_schema(kb_name: str):
    """Create SAG tables on an existing KB that predates Phase 1.

    Idempotent — safe to run on any KB at any time.
    """
    schema = f"{SCHEMA_PREFIX}{kb_name}"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.events (
                    id         SERIAL PRIMARY KEY,
                    chunk_id   INTEGER NOT NULL REFERENCES {schema}.chunks(id) ON DELETE CASCADE,
                    event_text TEXT NOT NULL,
                    embed_vec  vector(1024)
                )
            """)
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{schema}_event_embed ON {schema}.events "
                f"USING hnsw (embed_vec vector_cosine_ops)"
            )
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.entities (
                    id          SERIAL PRIMARY KEY,
                    name        TEXT NOT NULL,
                    entity_type TEXT NOT NULL DEFAULT 'label',
                    embed_vec   vector(1024),
                    UNIQUE(name)
                )
            """)
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{schema}_entity_embed ON {schema}.entities "
                f"USING hnsw (embed_vec vector_cosine_ops)"
            )
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.event_entities (
                    event_id  INTEGER NOT NULL REFERENCES {schema}.events(id) ON DELETE CASCADE,
                    entity_id INTEGER NOT NULL REFERENCES {schema}.entities(id) ON DELETE CASCADE,
                    PRIMARY KEY (event_id, entity_id)
                )
            """)
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {schema}.extraction_status (
                    chunk_id   INTEGER PRIMARY KEY REFERENCES {schema}.chunks(id) ON DELETE CASCADE,
                    extracted  BOOLEAN NOT NULL DEFAULT false,
                    extracted_at TIMESTAMPTZ,
                    error      TEXT
                )
            """)
        conn.commit()
    finally:
        conn.close()


def extract_chunks(kb_name: str) -> dict:
    """Extract events and entities from unprocessed chunks in a KB.

    Finds chunks where extraction_status.extracted = false,
    calls LLM to extract 1 event + N entities per chunk,
    and writes results to events/entities/event_entities tables.
    """
    # Ensure SAG schema exists on this KB
    ensure_sag_schema(kb_name)
    schema = f"{SCHEMA_PREFIX}{kb_name}"

    # Find chunks that need extraction
    try:
        rows = _fetch_all(f"""
            SELECT c.id, c.content, c.title
            FROM {schema}.chunks c
            LEFT JOIN {schema}.extraction_status es ON c.id = es.chunk_id
            WHERE es.extracted IS DISTINCT FROM true
            ORDER BY c.id
        """)
    except Exception as e:
        return {"error": f"Cannot query chunks: {e}"}

    if not rows:
        return {"success": True, "extracted": 0, "message": "All chunks already extracted"}

    total = len(rows)
    success_count = 0
    fail_count = 0

    for chunk_id, content, title in rows:
        try:
            result = _extract_single_chunk(chunk_id, content, title or "", schema)
            if result.get("success"):
                success_count += 1
            else:
                fail_count += 1
                _mark_extraction(schema, chunk_id, error=result.get("error", "Unknown"))
        except Exception as e:
            fail_count += 1
            _mark_extraction(schema, chunk_id, error=str(e))

    return {
        "success": True,
        "kb": kb_name,
        "total": total,
        "extracted": success_count,
        "failed": fail_count,
    }


def _extract_single_chunk(chunk_id: int, content: str, title: str,
                          schema: str) -> dict:
    """Extract event + entities from one chunk using LLM, then persist."""
    text = f"{title}\n\n{content}" if title else content
    text = text[:3000]

    extracted = _call_llm_extract(text)
    if extracted is None:
        event_text = text.split(".")[0].strip() or text[:200]
        entities = []
    else:
        event_text = extracted.get("event", text[:200])
        entities = extracted.get("entities", [])

    # Embed event
    event_vector = None
    try:
        from embed_client import embed_text
        event_vector = embed_text(event_text)
    except Exception:
        pass

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            if event_vector is not None:
                cur.execute(
                    f"INSERT INTO {schema}.events (chunk_id, event_text, embed_vec) "
                    f"VALUES (%s, %s, %s::vector) RETURNING id",
                    (chunk_id, event_text, str(event_vector)),
                )
            else:
                cur.execute(
                    f"INSERT INTO {schema}.events (chunk_id, event_text) "
                    f"VALUES (%s, %s) RETURNING id",
                    (chunk_id, event_text),
                )
            event_id = cur.fetchone()[0]

            for ent in entities:
                ent_name = ent.get("name", "").strip()
                ent_type = ent.get("type", "label")
                if not ent_name or ent_type not in SAG_ENTITY_TYPES:
                    ent_type = "label"
                cur.execute(
                    f"INSERT INTO {schema}.entities (name, entity_type) "
                    f"VALUES (%s, %s) ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name "
                    f"RETURNING id",
                    (ent_name, ent_type),
                )
                entity_id = cur.fetchone()[0]
                cur.execute(
                    f"INSERT INTO {schema}.event_entities (event_id, entity_id) "
                    f"VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (event_id, entity_id),
                )

            from datetime import datetime, timezone
            cur.execute(
                f"INSERT INTO {schema}.extraction_status "
                f"(chunk_id, extracted, extracted_at) VALUES (%s, true, %s) "
                f"ON CONFLICT (chunk_id) DO UPDATE SET extracted = true, "
                f"extracted_at = %s, error = NULL",
                (chunk_id, datetime.now(timezone.utc), datetime.now(timezone.utc)),
            )
        conn.commit()
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        conn.close()

    return {"success": True, "event": event_text, "entities": len(entities)}


def _call_llm_extract(text: str) -> dict | None:
    """Call LLM to extract event + entities (SAG paper §3.2)."""
    api_key = os.environ.get("ASTRA_LLM_API_KEY", "")
    base_url = os.environ.get("ASTRA_LLM_BASE_URL", "")
    model = os.environ.get("ASTRA_LLM_MODEL", "THUDM/GLM-Z1-9B-0414")
    if not base_url:
        return None

    truncated = text[:2500]
    prompt = (
        'Extract one event and entities from the following text.\n'
        'Entity types: time, location, person, organization, group, '
        'topic, work, product, action, metric, label.\n'
        'Respond ONLY with this exact JSON format, no other text:\n'
        '{"event": "concise summary of the core content", '
        '"entities": [{"name": "entity name", "type": "entity type"}]}\n'
        'Text:\n' + truncated
    )
    try:
        payload = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": "You extract structured knowledge from text. Output ONLY valid JSON. No explanations, no markdown."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.01,
            "max_tokens": 1024,
        }).encode("utf-8")
        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        import urllib.request as _ur
        req = _ur.Request(url, data=payload, headers=headers, method="POST")
        with _ur.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        raw_content = result["choices"][0]["message"]["content"]
    except Exception:
        return None
    return _parse_extraction_json(raw_content)


def _parse_extraction_json(content: str) -> dict | None:
    """Parse LLM JSON output with json_repair + field normalisation.

    Handles: malformed JSON, wrong field names (value/label/entity → name),
    missing fields, truncation, extra text before/after JSON.
    """
    try:
        from json_repair import repair_json
        parsed = json.loads(repair_json(content))
    except Exception:
        try:
            import re as _re
            brace = _re.search(r"\{.*\}", content, _re.DOTALL)
            if brace:
                parsed = json.loads(brace.group())
            else:
                return None
        except Exception:
            return None
    if not isinstance(parsed, dict):
        return None
    # Normalise entities key
    if "entities" not in parsed and "entity" in parsed:
        parsed["entities"] = parsed.pop("entity")
    # Normalise entity field names
    entities = parsed.get("entities", [])
    if isinstance(entities, list):
        normalised = []
        for ent in entities:
            if not isinstance(ent, dict):
                if isinstance(ent, str):
                    normalised.append({"name": ent, "type": "label"})
                continue
            if "name" not in ent:
                for alt in ("value", "label", "entity", "keyword", "content", "text"):
                    if alt in ent:
                        ent["name"] = ent.pop(alt)
                        break
            if "name" in ent:
                normalised.append(ent)
        parsed["entities"] = normalised
    elif isinstance(entities, str):
        parsed["entities"] = [{"name": entities, "type": "label"}]
    return parsed if parsed.get("event") else None


def _mark_extraction(schema: str, chunk_id: int, error: str | None = None):
    """Mark a chunk's extraction status."""
    from datetime import datetime, timezone
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO {schema}.extraction_status "
                f"(chunk_id, extracted, extracted_at, error) "
                f"VALUES (%s, %s, %s, %s) ON CONFLICT (chunk_id) DO UPDATE "
                f"SET extracted = EXCLUDED.extracted, error = EXCLUDED.error",
                (chunk_id, bool(error), datetime.now(timezone.utc) if not error else None, error),
            )
        conn.commit()
    finally:
        conn.close()


# ── SAG Retrieval ────────────────────────────────────────────────


def search_sag_fast(query: str, kb_names: list[str] | None = None,
                    limit: int = 10) -> list[dict]:
    """SAG Fast mode: event vector search -> chunks (§3.3 Path B)."""
    try:
        from embed_client import embed_text
        query_vector = embed_text(query)
    except Exception:
        query_vector = None

    if query_vector is None:
        return search_kbs_hybrid(query, kb_names, limit)

    targets = kb_names or get_enabled_kb_names()
    if not targets:
        return []

    parts = []
    for kb in targets:
        schema = f"{SCHEMA_PREFIX}{kb}"
        parts.append(f"""
            SELECT c.id AS chunk_id, '{kb}' AS kb_name, c.title, c.content,
                   c.source, c.tags::text AS tags,
                   1 - (e.embed_vec <=> %s::vector) AS score
            FROM {schema}.events e
            JOIN {schema}.chunks c ON c.id = e.chunk_id
            WHERE e.embed_vec IS NOT NULL
        """)

    if not parts:
        return []

    vec_str = str(query_vector)
    union_sql = " UNION ALL ".join(parts)
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
        return search_kbs_hybrid(query, kb_names, limit)

    results = []
    for row in rows:
        results.append({
            "chunk_id": row[0],
            "kb": row[1],
            "title": row[2],
            "content": row[3],
            "score": round(float(row[6]), 4),
            "source": row[4],
            "tags": _parse_tags(row[5]),
        })
    return results


def search_sag_precise(query: str, kb_names: list[str] | None = None,
                       limit: int = 10) -> list[dict]:
    """SAG Precise mode: entity-guided + SQL JOIN expansion (§3.3-3.4).

    Steps:
      1. LLM extracts key entities from query
      2. Entity vector similarity -> related entities
      3. SQL JOIN: entities -> event_entities -> events -> chunks
      4. Merge with direct event vector results (sag_fast)
      5. Sort by score, dedup, return top K
    """
    targets = kb_names or get_enabled_kb_names()
    if not targets:
        return []

    try:
        from embed_client import embed_text
        query_vector = embed_text(query)
    except Exception:
        query_vector = None

    query_entities = _extract_query_entities(query)

    seed_chunks: dict[int, dict] = {}
    if query_entities and query_vector is not None:
        for ent in query_entities:
            ent_name = ent.get("name", "").strip()
            if not ent_name:
                continue
            ent_vector = embed_text(ent_name)
            if ent_vector is None:
                continue

            for kb in targets:
                schema = f"{SCHEMA_PREFIX}{kb}"
                try:
                    entity_rows = _fetch_all(f"""
                        SELECT e.id, e.name,
                               1 - (e.embed_vec <=> %s::vector) AS score
                        FROM {schema}.entities e
                        WHERE e.embed_vec IS NOT NULL
                          AND 1 - (e.embed_vec <=> %s::vector) > 0.85
                        ORDER BY score DESC
                        LIMIT 10
                    """, (str(ent_vector), str(ent_vector)))
                except Exception:
                    continue

                for erow in entity_rows:
                    eid = erow[0]
                    try:
                        chunk_rows = _fetch_all(f"""
                            SELECT DISTINCT c.id, c.title, c.content, c.source, c.tags::text,
                                   1 - (ev.embed_vec <=> %s::vector) AS score
                            FROM {schema}.event_entities ee
                            JOIN {schema}.events ev ON ev.id = ee.event_id
                            JOIN {schema}.chunks c ON c.id = ev.chunk_id
                            WHERE ee.entity_id = %s
                              AND ev.embed_vec IS NOT NULL
                            ORDER BY score DESC
                            LIMIT 5
                        """, (str(query_vector), eid))
                    except Exception:
                        continue

                    for cr in chunk_rows:
                        if cr[0] not in seed_chunks:
                            seed_chunks[cr[0]] = {
                                "chunk_id": cr[0],
                                "kb": kb,
                                "title": cr[1],
                                "content": cr[2],
                                "score": round(float(cr[5]), 4),
                                "source": cr[3],
                                "tags": _parse_tags(cr[4]),
                            }

    # Merge with fast path
    fast_results = search_sag_fast(query, kb_names, limit)
    for r in fast_results:
        cid = r["chunk_id"]
        if cid in seed_chunks:
            seed_chunks[cid]["score"] = max(seed_chunks[cid]["score"], r["score"])
        else:
            seed_chunks[cid] = r

    sorted_results = sorted(
        seed_chunks.values(),
        key=lambda x: x.get("score", 0),
        reverse=True,
    )[:limit]
    return sorted_results


def _extract_query_entities(query: str) -> list[dict]:
    """Extract key entities from a search query (online LLM call, §3.3).

    Falls back to heuristic if LLM unavailable.
    """
    api_key = os.environ.get("ASTRA_LLM_API_KEY", "")
    base_url = os.environ.get("ASTRA_LLM_BASE_URL", "")
    model = os.environ.get("ASTRA_LLM_MODEL", "THUDM/GLM-Z1-9B-0414")

    if base_url:
        prompt = f"""Extract key entities from this search query.

Entity types: time, location, person, organization, group, topic, work, product, action, metric, label

Output JSON only:
{{"entities": [{{"name": "...", "type": "..."}}]}}

Query: {query}
"""
        try:
            payload = json.dumps({
                "model": model,
                "messages": [
                    {"role": "system", "content": "You extract query entities. Output ONLY valid JSON. No explanations."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.01,
                "max_tokens": 512,
            }).encode("utf-8")

            url = f"{base_url.rstrip('/')}/chat/completions"
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}

            import urllib.request as _ur
            req = _ur.Request(url, data=payload, headers=headers, method="POST")
            with _ur.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())

            raw_content = result["choices"][0]["message"]["content"]

            # Reuse the same parsing logic
            from json_repair import repair_json
            import re as _re

            parsed = None
            try:
                repaired = repair_json(raw_content)
                parsed = json.loads(repaired)
            except Exception:
                brace = _re.search(r"\{.*\}", raw_content, _re.DOTALL)
                if brace:
                    try:
                        parsed = json.loads(brace.group())
                    except Exception:
                        pass

            if isinstance(parsed, dict):
                if "entities" not in parsed and "entity" in parsed:
                    parsed["entities"] = parsed.pop("entity")
                entities = parsed.get("entities", [])
                if isinstance(entities, list):
                    normalised = []
                    for ent in entities:
                        if not isinstance(ent, dict):
                            if isinstance(ent, str):
                                normalised.append({"name": ent, "type": "label"})
                            continue
                        if "name" not in ent:
                            for alt in ("value", "label", "entity", "keyword", "content", "text"):
                                if alt in ent:
                                    ent["name"] = ent.pop(alt)
                                    break
                        if "name" in ent:
                            normalised.append(ent)
                    return normalised
                elif isinstance(entities, str):
                    return [{"name": entities, "type": "label"}]
            return []
        except Exception:
            pass

    return [{"name": query, "type": "topic"}]
