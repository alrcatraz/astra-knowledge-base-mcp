"""SQLite connection and schema management for Astra Knowledge Base MCP.

Uses Python's built-in sqlite3 — no external dependencies.
FTS5 full-text search via SQLite's bundled FTS5 extension.
"""

import json
import os
import sqlite3
import threading

# Default path for the SQLite database file
DEFAULT_DB_PATH = os.path.expanduser("~/.astra/knowledge-base.db")

# Resolved from environment
_db_path: str | None = None
_lock = threading.Lock()


def get_db_path() -> str:
    """Get the database path from environment or default."""
    global _db_path
    if _db_path is None:
        _db_path = os.environ.get("ASTRA_KB_PATH", DEFAULT_DB_PATH)
        _ensure_dir(_db_path)
    return _db_path


def _ensure_dir(path: str):
    """Ensure the directory for the database file exists."""
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    """Get a new database connection with WAL mode and FK enforcement."""
    conn = sqlite3.connect(get_db_path())
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


# ── DDL ───────────────────────────────────────────────────────

KB_REGISTRY_DDL = """\
CREATE TABLE IF NOT EXISTS kb_registry (
    name        TEXT PRIMARY KEY,
    description TEXT NOT NULL DEFAULT '',
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

CHUNKS_DDL = """\
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kb_name     TEXT NOT NULL REFERENCES kb_registry(name) ON DELETE CASCADE,
    title       TEXT NOT NULL DEFAULT '',
    content     TEXT NOT NULL,
    source      TEXT,
    tags        TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

FTS_DDL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    title, content, kb_name UNINDEXED,
    content='chunks',
    content_rowid='id',
    tokenize='porter unicode61'
);
"""

# Triggers to keep FTS5 in sync with chunks table
FTS_TRIGGERS = [
    """\
CREATE TRIGGER IF NOT EXISTS chunks_fts_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, title, content, kb_name)
    VALUES (new.id, new.title, new.content, new.kb_name);
END;
""",
    """\
CREATE TRIGGER IF NOT EXISTS chunks_fts_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, title, content, kb_name)
    VALUES ('delete', old.id, old.title, old.content, old.kb_name);
END;
""",
    """\
CREATE TRIGGER IF NOT EXISTS chunks_fts_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, title, content, kb_name)
    VALUES ('delete', old.id, old.title, old.content, old.kb_name);
    INSERT INTO chunks_fts(rowid, title, content, kb_name)
    VALUES (new.id, new.title, new.content, new.kb_name);
END;
""",
]


def init_db():
    """Initialize all tables if they don't exist."""
    with get_connection() as conn:
        conn.execute(KB_REGISTRY_DDL)
        conn.execute(CHUNKS_DDL)
        conn.execute(FTS_DDL)
        for trigger in FTS_TRIGGERS:
            conn.execute(trigger)
        conn.commit()


def drop_kb_data(kb_name: str):
    """Delete all chunks for a knowledge base and unregister it."""
    with get_connection() as conn:
        conn.execute("DELETE FROM chunks WHERE kb_name = ?", (kb_name,))
        conn.execute("DELETE FROM kb_registry WHERE name = ?", (kb_name,))
        conn.commit()
