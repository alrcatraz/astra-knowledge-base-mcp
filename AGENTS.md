# astra-knowledge-base-mcp — Agent Guide

For AI agents developing and extending this project.
Humans can skip to [README](README.md).

---

## Project Overview

MCP (Model Context Protocol) server for managing multi-tenant knowledge bases.
Part of [Astra AI Agent Infrastructure](https://github.com/alrcatraz/astra-aiagent-infra).

**Key architectural choices:**
- **PostgreSQL 16+ with pgvector** is the single, authoritative backend (keeps dev and prod on identical storage semantics).
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
│   ├── run.sh                # Startup script
│   ├── wiki-kb-sync.sh       # One-click wiki → KB sync script
│   ├── dir-kb-sync.py        # [Phase 3] Whole-directory vectorisation CLI (generalised from wiki-kb-sync)
│   └── classify-input.sh     # Input classification — detect wiki vs doc stack vs single file, handle archives
├── templates/
│   └── kb-wiki-page.md       # KB-optimised wiki page template
├── plugins/
│   └── memory/
│       └── astra_kb/         # [Phase 2] Hermes memory provider (ships standalone)
├── skills/                   # Skills for AI agents (symlinked from ~/)
│   └── knowledge-base-interop/
│       └── SKILL.md          # Two-layer interop skill
├── AGENTS.md                 # This file (tracked, sanitised) — includes evolution roadmap below
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

## LLM Wiki Interop

Astra KB is the **retrieval layer** for AI agents. The **LLM Wiki** is the
curation layer for humans. The two work together via three pipelines
documented in the `knowledge-base-interop` skill.

**When to load:** `skill_view('knowledge-base-interop')`

**Pipeline overview:**

| Pipeline | Direction | When |
|----------|-----------|------|
| Source → Wiki → KB | Layer 1 → Layer 2 | New information needs curation |
| KB → Wiki | Layer 2 → Layer 1 | Valuable search result found |
| Batch sync | Layer 1 → Layer 2 | Wiki had many updates |

**Key files:**

| File | Purpose |
|------|---------|
| `docs/kb-wiki-interop.md` | Detailed reference doc |
| `scripts/wiki-kb-sync.sh` | One-click sync script |
| `templates/kb-wiki-page.md` | Page template with `kb_sync` frontmatter |
| `skills/knowledge-base-interop/SKILL.md` | Skill for agent workflow |

**Selective sync:** Only pages with `kb_sync: true` in frontmatter are
exported to Astra KB. See the `knowledge-base-interop` skill for details.

---

## Development Principles

1. **Additive over replacement.** New search strategies don't break old ones. New storage layers don't require data migration (backfill tools are separate).

2. **Testable at every step.** Each Phase below should be independently verifiable — either by existing tool output or a dedicated smoke test.

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
cp config/embed.example config/embed.conf # configure embed endpoint
uv run server.py              # start MCP server
```

**Environment variables — see [README](README.md#configuration).**
**Minimal setup:**

```bash
export ASTRA_EMBED_BASE_URL=https://api.siliconflow.cn/v1
export ASTRA_EMBED_API_KEY=sk-...
uv run server.py
```

---

## Testing

```bash
uv run python -c "import server; print('OK')"
uv run python -c "from embed_client import embed_text; v = embed_text('test'); print(f'vector dims: {len(v) if v else 'failed'}')"
ASTRA_KB_BACKEND=postgres uv run python -c "from pg_backend import list_kbs; print(list_kbs())"
```

---

## Phase Guidance

### Phase 0 — Vectorization Foundation ✅ (done)

Batch-first semantic chunker, embedding cache, provider-agnostic embed client,
`recursive` + `semantic` chunkers, per-KB chunker registry.

Files to modify as needed: `embed_client.py`, `pg_backend.py`, `pyproject.toml`

Key constraints (Phase 0):
- Embedding cache must survive server restarts (PostgreSQL-backed, shared `embed_cache` table)
- Batch embedding (`embed_batch`) is the default — single-item `embed_text` is a thin wrapper
- All API calls must have exponential backoff retry (429/5xx)
- No hardcoded provider names — only `ASTRA_EMBED_BASE_URL` + `ASTRA_EMBED_API_KEY` + `ASTRA_EMBED_MODEL`
- Do not change search interface signatures in `pg_backend.py` or `server.py`

### Phase 1 — SAG Integration (verified 2026-08-20)

| Item | Status |
|------|--------|
| Event/entity extraction schema | ✅ event tables in `pg_backend` |
| `kb_extract` manual trigger | ✅ |
| `sag_fast` / `sag_precise` search modes | ✅ wired in `kb_search` |
| `sag/extractor.py` + `sag/search.py` | ✅ superseded — logic inlined in `pg_backend` (`extract_chunks` / `search_sag_fast` / `search_sag_precise`); no separate `sag/` module needed |
| Auto-extract on ingest | ⏳ deferred (manual `kb_extract` today) |

Additional files: `sag/extractor.py`, `sag/search.py` (if a standalone module is ever restored).

Key constraints:
- SAG paths are ADDITIONAL — existing search returns identical results before and after
- `kb_extract` is a manual trigger (auto-extract comes in Phase 4)
- LLM prompt for extraction must be versioned (track in `sag/prompts/`)
- Event/entity vectors reuse same embed pipeline as chunks (same `BASE_URL`, same `MODEL`)

### Phase 2 — Memory Provider (done 2026-08-23)

**Goal:** sink useful conversation facts into KB so cross-session recall uses
semantic vector search instead of the weaker built-in SQLite FTS.

**Plugin lives in THIS repo** — `plugins/memory/astra-kb/` — ships as a
**standalone memory plugin** installed into `~/.hermes/plugins/` (or via pip
entry point). It does **not** go into the Hermes upstream repo (coupling and
maintenance decision). Our plugin stays in lockstep with KB version/schema/embed.

**Approach:** implement a Hermes **memory provider** plugin exposing
`sync_turn(user_content, assistant_content, *, session_id)` that writes the
turn into the target KB. Config `memory.provider` switches to it.

**Data access:** the plugin imports this repo's `pg_backend` + `embed_client`
directly (same data-access layer as the MCP server). It does NOT go through
MCP — MCP tools are agent-invoked, while the provider runs inside the Hermes
agent loop and must write programmatically. Backend stays PostgreSQL + pgvector + SAG.

**Why a memory provider, not a context engine:** the context engine *owns* the
session compaction policy; a memory provider only observes turns without
owning anything. Sinking is observation, not compaction — so the provider path
leaves `context.engine: compressor` untouched and always works.

**Acceptance (all verified 2026-08-23):**
- A turn with a reusable fact lands in the configured KB (correct KB) ✅
- `kb_search` over that KB finds it with semantic ranking ✅ (incl. pg8000 ILIKE cast fix)
- `context.engine: compressor` still active (no regression) ✅
- Side effect on embedding API or DB failure is nil (fail-open) ✅

### Phase 3 — Whole-directory vectorisation (done 2026-08-23)

Generalised `scripts/wiki-kb-sync.py` → `scripts/dir-kb-sync.py`.

Any directory + KB name via `--dir`/`--kb`:

| Item | Status |
|------|--------|
| `--dir`/`--kb` required CLI args | ✅ `dir-kb-sync.py` |
| Recursive `os.walk` (md; bracket dirs like `[世界观]` safe) | ✅ |
| Reuse semantic chunker + embed client | ✅ (chunker/embed reused) |
| `--watch` live monitoring | ✅ `dir-kb-sync.py --watch` (watchdog; .md/.txt 增/删/改/改名事件) |
| Path out of hardcoded glob | ✅ (`os.walk`, no glob) |
| Original scripts = thin wrappers (backward-compatible) | ✅ |

**Dev-verified** (2026-08-20 → 2026-08-23):
- **3A**: `--full --dry-run` no longer clears DB (fixed inherited dry-run hole); CLI requires `--dir`+`--kb`; `--file`/`--full`/`--dry-run` semantics preserved; real wiki scanned. Original `wiki-kb-sync.py`/`wiki-kb-watch.py` became thin wrappers.
- **3B**: `.txt` support; `--watch` generalised into `dir-kb-sync.py` (watchdog, dry-run safe).

### Phase 4 — ContextEngine `select_context()` RAG injection (OPTIONAL — deferred)

> Per-request retrieval-augmented context selection.

**Caution (from Hermes doc `context-engine-plugin.md`):**
- A real select hits the prompt-cache prefix — turns that reshape re-write cache instead of reading it. Must return **stable selections when nothing changed**; only reshape when routing actually differs.
- Default must stay `None` (no-op) so non-injecting turns keep cache intact.
- It replaces the per-request message list (request-only; persisted history never mutated). Fail-open on exception.

**Defer** unless weekly evidence shows auto-injection genuinely improves
reasoning quality — highest-risk, lowest-certainty item.

### Phase 5 — Live context sources (Obsidian/Notion bidirectional) (OPTIONAL — deferred)

- Obsidian live REST + Notion API clients as a connected context **source**.
- Reading a live note → on-demand KB add; KB search result → write back to the note as an updated knowledge source.
- Hermes already ships `markitdown` / `pageindex` MCP for Obsidian bidirectional read/write; this phase unifies them into one native surface.

---

## Sequencing recommendation

1. **Phase 2 (memory provider)** — highest value / lowest risk. ❌ DONE 2026-08-23
2. **Phase 3 (dir-kb-sync)** — mostly extraction of existing code. ❌ DONE 2026-08-23
3. **Phase 4 (select_context)** — highest risk. Only if measured benefit. (deferred)
4. **Phase 5 (context sources)** — only if live bidirectional needs exist. (deferred)

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
- **Hermes Context Engine plugins**: https://hermes-agent.nousresearch.com/docs — plugin ABCs & `select_context` contract