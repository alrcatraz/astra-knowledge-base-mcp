"""Chunking strategy registry and factory.

Supports per-KB chunker configuration with fallback to global default.
"""

from typing import Any, Callable

from .base import Chunker
from .recursive import RecursiveChunker
from .heading import HeadingAnchorChunker
from .semantic import SemanticChunker


# ── Registry ─────────────────────────────────────────────────────

_registry: dict[str, type[Chunker]] = {}


def register(name: str, chunker_cls: type[Chunker]):
    """Register a chunker class by name."""
    _registry[name] = chunker_cls


def list_chunkers() -> list[str]:
    """Return registered chunker names."""
    return list(_registry.keys())


def get_chunker(name: str, **kwargs) -> Chunker:
    """Get a chunker instance by name with optional overrides."""
    cls = _registry.get(name)
    if cls is None:
        raise ValueError(f"Unknown chunker: {name}. Available: {list(_registry.keys())}")
    return cls(**kwargs)


# Register built-in chunkers
register("recursive", RecursiveChunker)
register("heading-anchor", HeadingAnchorChunker)
register("semantic", SemanticChunker)


# ── Per-KB configuration (stored in PG mgmt table) ──────────────

def get_chunker_for_kb(kb_name: str, embed_fn: Callable | None = None) -> Chunker:
    """Resolve chunker for a KB based on its config, with fallback.

    Looks up kb_config.chunker column. Falls back to 'recursive'.
    """
    chunker_name = _load_kb_chunker_config(kb_name)
    kwargs: dict[str, Any] = {}

    if chunker_name == "semantic" and embed_fn is not None:
        kwargs["embed_fn"] = embed_fn
    elif chunker_name == "recursive":
        kwargs = {"chunk_size": 1000, "chunk_overlap": 200}

    return get_chunker(chunker_name, **kwargs)


def set_kb_chunker(kb_name: str, chunker_name: str):
    """Persist chunker choice for a KB in mgmt."""
    from pg_backend import _execute

    if chunker_name not in _registry:
        raise ValueError(f"Unknown chunker: {chunker_name}. Available: {list(_registry.keys())}")

    _execute(
        "UPDATE kb_registry SET chunker = %s, updated_at = now() WHERE name = %s",
        (chunker_name, kb_name),
    )


def _load_kb_chunker_config(kb_name: str) -> str:
    """Load saved chunker name for a KB, or 'recursive' default."""
    try:
        from pg_backend import _fetch_one
        row = _fetch_one(
            "SELECT chunker FROM kb_registry WHERE name = %s",
            (kb_name,),
        )
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return "recursive"


# ── Helper to upgrade kb_registry schema ────────────────────────

def ensure_kb_registry_schema():
    """Add chunker column to kb_registry if missing (idempotent)."""
    try:
        from pg_backend import get_conn
        conn = None
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'kb_registry' AND column_name = 'chunker'
            """)
            if not cur.fetchone():
                cur.execute("""
                    ALTER TABLE kb_registry
                    ADD COLUMN chunker TEXT DEFAULT 'recursive'
                """)
                conn.commit()
    except Exception:
        pass
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass
