# astra-knowledge-base-mcp — Agent Guide

For AI agents developing and extending this project.
Humans can skip to [README](README.md) or [PLAN](PLAN.md).

---

## Project Overview

MCP (Model Context Protocol) server for managing multi-tenant knowledge bases.
Part of [Astra AI Agent Infrastructure](https://github.com/alrcatraz/astra-aiagent-infra).

**Key architectural choices:**
- **PostgreSQL 16+ with pgvector** is the ONLY backend. SQLite has been removed (dev/prod parity issue).
- **Embedding is provider-agnostic**: config via `ASTRA_EMBED_BASE_URL` + `ASTRA_EMBED_API_KEY` + `ASTRA_EMBED_MODEL`. Any OpenAI-compatible `/v1/embeddings` endpoint works — local llama.cpp, SiliconFlow, OpenAI, DeepSeek, etc.
- **SAG** (SQL-Retrieval Augmented Generation, arxiv 2606.15971, MIT) is the retrieval architecture we are adopting — event-entity indexing + query-time dynamic hyperedges via SQL JOINs.
- **Search strategies are additive** — new paths (sag_fast, sag_precise) coexist with existing ones (fts, vector, hybrid), exposed through a unified `kb_search` interface.
- **Self-implemented, not wrapping zleap-sag** — we implement the SAG algorithm directly on our PG schema. The `zleap-sag` package is a dev dependency for reference/verification only.

---

## Code Map

```
astra-knowledge-base-mcp/
├── server.py                 # MCP server entry — tool definitions & dispatch
├── pg_backend.py             # PostgreSQL backend — KB lifecycle, chunks, search (THE backend)
├── embed_client.py           # Embedding client — provider-agnostic, OpenAI-compatible
├── chunking/
│   ├── __init__.py
│   ├── base.py               # Chunker ABC
│   └── recursive.py          # RecursiveChunker — paragraph/sentence splitting
├── ingestion/
│   ├── __init__.py
│   ├── base.py               # Ingestor ABC
│   └── text.py               # TextIngestor — text/file → chunks
├── search/
│   ├── __init__.py
│   ├── engine.py             # SearchEngine ABC (pluggable interface)
│   └── fts.py                # FTS search implementation
├── sag/                      # [Phase 1] SAG retrieval module (to be created)
│   ├── __init__.py
│   ├── extractor.py          # LLM-based event/entity extraction
│   └── search.py             # SAG retrieval pipeline
├── scripts/
│   └── run.sh                # Startup script
├── AGENTS.md                 # This file
├── PLAN.md                   # Long-term development roadmap (read before starting work)
├── README.md
├── pyproject.toml
└── .venv/                    # Virtual environment (uv-managed)
```

**Data flow (current):**
```
kb_add → TextIngestor → RecursiveChunker → embed_client.embed_text() → pg_backend.add_chunks()
kb_search → search mode dispatch → FTS / Vector / Hybrid → returns ranked chunks
```

**Data flow (Phase 1 target):**
```
kb_add → TextIngestor → RecursiveChunker → embed_batch() → add_chunks()
      └→ [async] extract_event_entity() → events + entities + event_entities tables
kb_search → dispatch:
  hybrid/fts/vector — existing paths (unchanged)
  sag_fast — event vectors → chunks (direct semantic)
  sag_precise — query entities → SQL JOIN seed → hyperedge expansion → merge
```

---

## Development Principles

1. **Additive over replacement.** New search strategies don't break old ones. New storage layers don't require data migration (backfill tools are separate).

2. **Testable at every step.** Each Phase/N in PLAN.md should be independently verifiable — either by existing tool output or a dedicated smoke test.

3. **Schema changes are forward-only.** Never drop columns/tables that existing data depends on. Deprecate, don't delete.

4. **Embedding is infrastructure, not logic.** The `embed_client` module should be thin, cached, retried, and monitored — not coupled to any specific retrieval strategy or provider.

5. **Provider-agnostic.** No hardcoded provider names. All config through env vars: `BASE_URL` + `API_KEY` + `MODEL`. Everything else is derived.

6. **License hygiene.** SAG paper and reference implementation are MIT. Cite in code headers and README when implementing algorithm from a paper. Do not copy code verbatim from GPL/AGPL sources.

7. **British English** for all documentation (-ise/-our/-re/-ence). Code identifiers in US English (standard Python convention).

---

## Getting Started

```bash
git clone https://github.com/alrcatraz/astra-knowledge-base-mcp
cd astra-knowledge-base-mcp
uv sync                       # install dependencies
cp .env.example .env          # configure embed API endpoint
uv run server.py              # start MCP server
```

**Environment variables — see [README](README.md#configuration).**

Minimal setup for SiliconFlow:
```bash
export ASTRA_EMBED_API_KEY=sk-...
export ASTRA_EMBED_MODEL=Qwen/Qwen3-Embedding-8B
uv run server.py
```

---

## Testing

```bash
uv run python -c "import server; print('OK')"
uv run python -c "from embed_client import embed_text; v = embed_text('test'); print(f'vector dims: {len(v) if v else \"failed\"}')"
ASTRA_KB_BACKEND=postgres uv run python -c "from pg_backend import list_kbs; print(list_kbs())"
```

---

## Phase Guidance

### Phase 0 — Vectorization Foundation

Files to modify: `embed_client.py`, `pg_backend.py`, `pyproject.toml`

Key constraints:
- Embedding cache must survive server restarts (SQLite-backed, one `embed_cache.db` file)
- Batch embedding (`embed_batch`) is the default — single-item `embed_text` is a thin wrapper
- All API calls must have exponential backoff retry (429/5xx)
- No hardcoded provider names — only `ASTRA_EMBED_BASE_URL` + `ASTRA_EMBED_API_KEY` + `ASTRA_EMBED_MODEL`
- Do not change search interface signatures in `pg_backend.py` or `server.py`

### Phase 1 — SAG Integration

New files to create:
- `sag/extractor.py` — LLM-based event/entity extraction
- `sag/search.py` — SAG retrieval pipeline

Files to modify: `pg_backend.py`, `server.py`

Key constraints:
- SAG paths are ADDITIONAL — existing search returns identical results before and after
- `kb_extract` is a manual trigger (auto-extract comes in Phase 4)
- LLM prompt for extraction must be versioned (track in `sag/prompts/`)
- Event/entity vectors reuse same embed pipeline as chunks (same `BASE_URL`, same `MODEL`)

### Phase 2+ — See [PLAN.md](PLAN.md)

---

## MCP Tool Reference

| Tool | Purpose | Phase |
|------|---------|-------|
| `kb_list` | List all KBs | Current |
| `kb_create` | Create KB | Current |
| `kb_delete` | Delete KB | Current |
| `kb_enable`/`kb_disable` | Toggle KB visibility | Current |
| `kb_add` | Add text (auto-chunked + embedded) | Current |
| `kb_search` | Search (hybrid/fts/vector) | Current |
| `kb_list_chunks` | Browse chunks | Current |
| `kb_update` | Edit chunk | Current |
| `kb_delete_chunk` | Remove chunk | Current |
| `mgmt_list_tables` | List mgmt tables | Current |
| `mgmt_query` | Query mgmt data | Current |
| `kb_extract` | Extract events/entities from unprocessed chunks | Phase 1 |
| `kb_stats` | KB statistics | Phase 4 |
| `kb_diff` | Chunk change tracking | Phase 4 |

---

## Reference

- **SAG paper**: https://arxiv.org/abs/2606.15971 — retrieval architecture (MIT)
- **Zleap-AI SAG (GitHub)**: https://github.com/Zleap-AI/SAG — reference impl (MIT)
- **PLAN.md**: Long-term development roadmap
- **Hermes Agent**: https://hermes-agent.nousresearch.com/docs — agent framework
