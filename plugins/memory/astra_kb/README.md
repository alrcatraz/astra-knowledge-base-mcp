# astra_kb — Hermes memory provider

A [Hermes](https://hermes-agent.nousresearch.com) **memory provider** that sinks
conversation turns into the Astra Knowledge Base (PostgreSQL + pgvector) and
recalls them with semantic vector search — a strictly stronger retrieval path
than the built-in SQLite FTS.

Shipped with the KB repo under `plugins/memory/astra_kb/`. Installed as a
**standalone user plugin** — it is NOT part of the Hermes upstream tree
(Hermes CONTRIBUTING no longer accepts new in-tree `plugins/memory/*`
providers; the discovery system already finds external plugins).

---

## Data access model

The provider imports this repo's `pg_backend` + `embed_client` **directly**
— the same data-access layer the MCP server uses. It does **not** go through
MCP tools: MCP tools are agent-invoked, while the provider runs inside the
Hermes agent loop and must write programmatically.

- **Write (`sync_turn`)** → `pg_backend.add_chunks()` (auto-embeds via
  `embed_client`, reusing `ASTRA_EMBED_*`).
- **Read (`kb_mem_search` tool)** → `pg_backend.search_kbs_vector()` (pgvector
  cosine; falls back to pg_trgm FTS if embedding is unavailable).
- **Backend** → PostgreSQL + pgvector + SAG, same tables as MCP.

## Install

Symlink (or copy) this directory into Hermes' user plugins dir:

```bash
mkdir -p ~/.hermes/plugins
ln -sfn \
  "$PWD/plugins/memory/astra_kb" \
  ~/.hermes/plugins/astra_kb
```

Or ship it via a pip entry point exposing `astra_kb`.

## Configure

Profile-scoped config in `config.yaml`:

```yaml
plugins:
  astra_kb:
    kb_name: astra-mem        # target KB for conversation turns
    project_root: ~/.astra/repos/astra-knowledge-base-mcp
    pg_dsn: ""                # optional override (default: Unix-socket peer auth)
    auto_create_kb: true      # create the KB in initialize() if missing

memory:
  provider: astra_kb          # swap the active memory provider to ours
```

The plugin reads `ASTRA_KB_PG_DSN` / `ASTRA_EMBED_*` from the process
environment exactly like `pg_backend` / `embed_client`.

> ⚠️ **Test isolation.** Never point the plugin at a production KB while
> testing `sync_turn`. Create a disposable KB (e.g. `test_astra_mem`), verify,
> then delete it. See `test_sync.py`.

## Test

`test_sync.py` is an end-to-end smoke test using a dedicated `test_astra_mem`
KB (created at runtime, deleted on success). Run from the repo root:

```bash
ASTRA_EMBED_BASE_URL=http://127.0.0.1:20128/v1 \
ASTRA_EMBED_MODEL=embedding \
ASTRA_EMBED_DIM=1024 \
uv run python3 plugins/memory/astra_kb/test_sync.py
```

Requires the Postgres backend (Unix-socket peer auth to `astra_kb`) and an
OpenAI-compatible embedding endpoint reachable as configured.