"""Knowledge base lifecycle management."""

from db import get_connection, init_registry, ensure_kb_schema, drop_kb_schema


def list_kbs():
    """List all knowledge bases with their enable/disable status."""
    init_registry()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name, description, enabled, created_at FROM public.kb_registry ORDER BY name")
            rows = cur.fetchall()
    return [
        {"name": r[0], "description": r[1], "enabled": r[2], "created_at": r[3].isoformat()}
        for r in rows
    ]


def create_kb(name: str, description: str = ""):
    """Create a new knowledge base."""
    init_registry()
    safe_name = name.strip().lower().replace(" ", "_")
    if not safe_name:
        return {"error": "Name cannot be empty"}

    # Check if already exists
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM public.kb_registry WHERE name = %s", (safe_name,))
            if cur.fetchone():
                return {"error": f"Knowledge base '{safe_name}' already exists"}

    ensure_kb_schema(safe_name)

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.kb_registry (name, description) VALUES (%s, %s)",
                (safe_name, description),
            )
        conn.commit()

    return {"success": True, "name": safe_name, "description": description}


def delete_kb(name: str):
    """Delete a knowledge base and all its data."""
    drop_kb_schema(name)
    return {"success": True, "name": name}


def enable_kb(name: str):
    """Enable a knowledge base for search."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE public.kb_registry SET enabled = TRUE, updated_at = NOW() WHERE name = %s",
                (name,),
            )
            if cur.rowcount == 0:
                return {"error": f"Knowledge base '{name}' not found"}
        conn.commit()
    return {"success": True, "name": name, "enabled": True}


def disable_kb(name: str):
    """Disable a knowledge base (excluded from search)."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE public.kb_registry SET enabled = FALSE, updated_at = NOW() WHERE name = %s",
                (name,),
            )
            if cur.rowcount == 0:
                return {"error": f"Knowledge base '{name}' not found"}
        conn.commit()
    return {"success": True, "name": name, "enabled": False}


def get_enabled_kb_names() -> list[str]:
    """Return names of all enabled knowledge bases."""
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM public.kb_registry WHERE enabled = TRUE")
            return [r[0] for r in cur.fetchall()]
