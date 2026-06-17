"""Knowledge base lifecycle management."""

import json
import sqlite3

from db import get_connection, init_db, drop_kb_data


def list_kbs():
    """List all knowledge bases with their enable/disable status."""
    init_db()
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT name, description, enabled, created_at FROM kb_registry ORDER BY name"
        )
        rows = cur.fetchall()
    return [
        {
            "name": r["name"],
            "description": r["description"],
            "enabled": bool(r["enabled"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def create_kb(name: str, description: str = ""):
    """Create a new knowledge base."""
    init_db()
    safe_name = name.strip().lower().replace(" ", "_")
    if not safe_name:
        return {"error": "Name cannot be empty"}

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT 1 FROM kb_registry WHERE name = ?", (safe_name,)
        ).fetchone()
        if existing:
            return {"error": f"Knowledge base '{safe_name}' already exists"}

        conn.execute(
            "INSERT INTO kb_registry (name, description) VALUES (?, ?)",
            (safe_name, description),
        )
        conn.commit()

    return {"success": True, "name": safe_name, "description": description}


def delete_kb(name: str):
    """Delete a knowledge base and all its data."""
    drop_kb_data(name)
    return {"success": True, "name": name}


def enable_kb(name: str):
    """Enable a knowledge base for search."""
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE kb_registry SET enabled = 1, updated_at = datetime('now') WHERE name = ?",
            (name,),
        )
        if cur.rowcount == 0:
            return {"error": f"Knowledge base '{name}' not found"}
        conn.commit()
    return {"success": True, "name": name, "enabled": True}


def disable_kb(name: str):
    """Disable a knowledge base (excluded from search)."""
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE kb_registry SET enabled = 0, updated_at = datetime('now') WHERE name = ?",
            (name,),
        )
        if cur.rowcount == 0:
            return {"error": f"Knowledge base '{name}' not found"}
        conn.commit()
    return {"success": True, "name": name, "enabled": False}


def get_enabled_kb_names() -> list[str]:
    """Return names of all enabled knowledge bases."""
    with get_connection() as conn:
        cur = conn.execute("SELECT name FROM kb_registry WHERE enabled = 1")
        return [r["name"] for r in cur.fetchall()]


def add_chunks(kb_name: str, chunks: list[dict]):
    """Insert chunks into a knowledge base.

    Each chunk dict should have:
      - title: str
      - content: str
      - source: str | None
      - tags: list[str]
    """
    with get_connection() as conn:
        conn.executemany(
            """INSERT INTO chunks (kb_name, title, content, source, tags)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (
                    kb_name,
                    c.get("title", ""),
                    c.get("content", ""),
                    c.get("source"),
                    json.dumps(c.get("tags", [])),
                )
                for c in chunks
            ],
        )
        conn.commit()
    return {"inserted": len(chunks)}
