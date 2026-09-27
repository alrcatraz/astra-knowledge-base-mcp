"""astra-kb — Hermes memory provider backed by the Astra Knowledge Base.

Registers as a MemoryProvider plugin so conversation turns sink into a
pgvector knowledge base (PostgreSQL) and can be recalled with semantic search
-- a strictly stronger retrieval path than the built-in SQLite FTS.

This repo ships the plugin at ``plugins/memory/astra-kb/`` (mirrors the
in-tree layout) but it is installed as a **standalone user plugin** into
``$HERMES_HOME/plugins/astra-kb/`` or ``~/.hermes/plugins/astra-kb/``. It is
part of the KB project, NOT the Hermes upstream tree (Hermes CONTRIBUTING no
longer accepts new in-tree memory providers).

Config (profile-scoped, ``config.yaml``):

.. code-block:: yaml

   plugins:
     astra-kb:
       kb_name: astra_mem      # target KB for conversation turns
       project_root: ~/.astra/repos/astra-knowledge-base-mcp
       pg_dsn: ""              # optional override of ASTRA_KB_PG_DSN
       auto_create_kb: true    # create KB in initialize() if missing
       skip_email: true        # strip image/email noise from synced text

HG data access: the plugin imports this repo's ``pg_backend`` + ``embed_client``
directly (same data-access layer as the MCP server) -- it does not go through
MCP tools, because MCP tools are agent-invoked while the provider runs inside
the Hermes agent loop and must write programmatically.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

try:  # in-tree / normal Hermes runtime
    from agent.memory_provider import MemoryProvider
except ImportError:  # standalone test harness without Hermes core installed
    class MemoryProvider:  # type: ignore[no-redef]
        pass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_DEFAULTS = {
    "kb_name": "astra-kb",
    "project_root": "",
    "pg_dsn": "",
    "auto_create_kb": True,
}


def _load_plugin_config() -> dict:
    """Canonical plugin config read, honouring managed-scope overlay + ${VAR}."""
    cfg: dict = dict(_DEFAULTS)
    try:
        from hermes_cli.config import load_config_readonly, cfg_get

        all_config = load_config_readonly()
        user = cfg_get(all_config, "plugins", "astra-kb", default={}) or {}
        cfg.update(user)
    except Exception:
        pass
    # Expand $HOME / ${VAR} in path fields
    home = str(Path.home())
    for key in ("project_root", "pg_dsn"):
        val = cfg.get(key) or ""
        if isinstance(val, str):
            cfg[key] = val.replace("$HOME", home).replace("${HOME}", home)
    return cfg


def _resolve_project_root(cfg: dict) -> Path | None:
    """Find this repo's root so we can import pg_backend/embed_client."""
    # 1. explicit project_root config
    if cfg.get("project_root"):
        p = Path(cfg["project_root"]).expanduser()
        if (p / "pg_backend.py").exists():
            return p
    # 2. this file's own location: <root>/plugins/memory/astra-kb/__
    here = Path(__file__).resolve()
    for cand in (here.parents[3], here.parents[4]):
        if (cand / "pg_backend.py").exists():
            return cand
    return None


# ---------------------------------------------------------------------------
# MemoryProvider implementation
# ---------------------------------------------------------------------------

class AstraKBProvider(MemoryProvider):
    """Memory provider that sinks turns into an Astra Knowledge Base.

    Subclasses ``agent.memory_provider.MemoryProvider`` so every optional
    lifecycle hook (``on_session_end``, ``on_session_switch``, ...) keeps the
    ABC's no-op default instead of raising AttributeError when MemoryManager
    fires it.
    """

    def __init__(self, config: dict | None = None):
        self._config = config or _load_plugin_config()
        self._root: Path | None = None
        self._pg_backend = None
        self._kb_name = self._config.get("kb_name", "astra-kb")
        self._session_id = ""
        self._ready = False
        # Turn buffers sink at the session boundary (on_session_end), not per
        # turn — sync_turn only appends here. Kept per session so a switch or
        # reset can't leak one conversation's transcript into another's sink.
        self._pending: List[Dict[str, Any]] = []

    @property
    def name(self) -> str:
        # Must equal the directory name (astra_kb) so it round-trips through
        # discover_memory_providers() / load_memory_provider(name) — Hermes
        # resolves providers by directory name, not the plugin.yaml label.
        return "astra_kb"

    def is_available(self) -> bool:
        """True if the KB repo is present and a target KB is configured."""
        if not self._config.get("kb_name"):
            return False
        root = _resolve_project_root(self._config)
        if root is None:
            return False
        self._root = root
        return True

    def unavailable_reason(self) -> str:
        root = _resolve_project_root(self._config)
        if root is None:
            return (
                "astra-knowledge-base-mcp project root not found. Set "
                "plugins.astra-kb.project_root in config.yaml."
            )
        return ""

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id
        root = _resolve_project_root(self._config)
        if root is None:
            logger.warning("astra-kb: project root not found; provider inactive")
            self._ready = False
            return
        self._root = root
        # Bring the KB repo's modules onto the import path, then load the
        # backend lazily so a missing/corrupt config is non-fatal at startup.
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            import pg_backend  # noqa: F401
            import embed_client  # noqa: F401

            self._pg_backend = pg_backend
        except Exception as e:
            logger.warning("astra-kb: could not import backend modules: %s", e)
            self._ready = False
            return

        # Fail CLOSED on a dead database path: without a reachable PG driver +
        # KB there is nothing to sink into, and pretending otherwise makes
        # every sync_turn swallow errors in silence (the pre-0.2.0 bug: no
        # psycopg2/pg8000 in the Hermes venv -> _ready=True -> silent no-op).
        if self._config.get("auto_create_kb", True):
            try:
                names = {r["name"] for r in pg_backend.list_kbs()}
                if self._kb_name not in names:
                    pg_backend.create_kb(self._kb_name, "Astra-KB memory sink")
                    logger.info("astra-kb: created KB '%s'", self._kb_name)
            except Exception as e:
                logger.warning(
                    "astra-kb: KB ensure failed (%s); provider inactive — "
                    "install a PG driver (pg8000 or psycopg2-binary) in the "
                    "Hermes environment and check ASTRA_KB_PG_DSN.", e,
                )
                self._pg_backend = None
                self._ready = False
                return
        self._ready = True

    def system_prompt_block(self) -> str:
        if not self._config.get("kb_name"):
            return ""
        return (
            "# Astra KB Memory\n"
            f"Active. Conversation turns sink into KB '{self._config['kb_name']}' "
            "with semantic vector search. Use kb_mem_search to recall prior facts."
        )

    def sync_turn(
        self,
        user_content: str,
        assistant_content: str,
        *,
        session_id: str = "",
        messages: List[Dict[str, Any]] | None = None,
    ) -> None:
        """Buffer a completed turn; the KB write happens at the session boundary.

        Sinking per-turn meant one embedding + insert round-trip inside every
        agent turn (and one failure swallowed per turn). Buffering lets
        ``on_session_end`` do a single batched ``add_chunks`` — the ABC's
        intended shape ("on_session_end: end-of-session extraction; fires only
        at real session boundaries, never per-turn").
        """
        if not self._ready or not user_content:
            return
        self._pending.append({
            "user": user_content,
            "assistant": assistant_content or "",
            "session": session_id or self._session_id,
        })

    def _sink(self, turns: List[Dict[str, Any]]) -> None:
        """Batch-write buffered turns into the KB. Fail-open: never break the
        agent loop on an embedding/DB error."""
        if not turns or not self._ready or not self._pg_backend:
            return
        chunks = []
        for t in turns:
            src = f"session:{t['session']}"
            chunks.append({"title": "conversation", "content": t["user"], "source": src})
            if t["assistant"]:
                chunks.append({"title": "assistant", "content": t["assistant"], "source": src})
        try:
            self._pg_backend.add_chunks(self._kb_name, chunks)
        except Exception as e:
            # fail-open: swallowing here must never break the agent turn.
            logger.warning("astra-kb sink failed (%d turns dropped): %s", len(turns), e)

    def on_session_end(self, messages: List[Dict[str, Any]]) -> None:
        """Flush the buffered turns of the ending session into the KB."""
        pending, self._pending = self._pending, []
        self._sink(pending)

    def on_session_switch(
        self, new_session_id: str, *, parent_session_id: str = "",
        reset: bool = False, rewound: bool = False, **kwargs,
    ) -> None:
        """Rebind session state mid-process (/new, /reset, compression).

        Flush first so a reset can't drop the old conversation's buffer into
        the new session id, then rebind.
        """
        pending, self._pending = self._pending, []
        self._sink(pending)
        self._session_id = new_session_id

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "kb_mem_search",
                "description": "Search the Astra KB memory store with semantic ranking. "
                "Use for cross-session recall over previously sunk conversation turns.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "limit": {"type": "integer", "description": "Max results (default 5)"},
                    },
                    "required": ["query"],
                },
            }
        ]

    def handle_tool_call(self, tool_name: str, args: Dict[str, Any], **kwargs) -> str:
        if tool_name != "kb_mem_search":
            raise NotImplementedError(
                f"Provider {self.name} does not handle tool {tool_name}"
            )
        if not self._pg_backend:
            return json.dumps({"error": "kb backend not loaded", "results": []})
        try:
            # Semantic recall — vector cosine over the KB; falls back to
            # pg_trgm FTS inside search_kbs_vector if embedding is unavailable.
            results = self._pg_backend.search_kbs_vector(
                args.get("query", ""),
                kb_names=[self._kb_name],
                limit=int(args.get("limit", 5)),
            )
        except Exception as e:
            return json.dumps({"error": str(e), "results": []})
        return json.dumps({"results": results, "count": len(results)})

    def shutdown(self) -> None:
        # Flush whatever the final session buffered before dropping the backend.
        pending, self._pending = self._pending, []
        self._sink(pending)
        self._pg_backend = None
        self._ready = False


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    """Hermes plugin entry: register the astra-kb memory provider."""
    provider = AstraKBProvider(config=_load_plugin_config())
    ctx.register_memory_provider(provider)