---
name: knowledge-base-interop
description: "Two-layer knowledge architecture — curate in LLM Wiki, search in Astra KB. Covers input classification, source-to-wiki ingestion, wiki-to-KB export (batch + realtime), semantic chunking, SAG extraction, health checks, and multi-format export."
version: 2.0.0
author: alrcatraz
platforms: [linux]
tags:
  - knowledge-base
  - llm-wiki
  - kb-interop
  - knowledge-management
  - two-layer
  - wikikb-sync
  - semantic-chunking
  - realtime-sync
triggers:
  - knowledge base interop
  - wiki kb sync
  - wiki to knowledge base
  - knowledge base to wiki
  - two layer knowledge
  - llm wiki and kb
  - export wiki to kb
  - sync wiki to kb
  - kb wiki pipeline
  - mkdocs wiki
  - wiki site generation
  - wiki export
  - kb sync script
  - realtime sync
  - wiki kb watch
  - semantic chunking
  - batch first chunking
  - sag extraction
tools:
  - python3
  - find
  - psql
  - hermes
references:
  - ../../docs/kb-wiki-interop.md
  - ../../scripts/wiki-kb-sync.py
  - ../../scripts/wiki-kb-watch.py
  - ../../chunking/semantic.py
  - ../../pg_backend.py
  - ../../embed_client.py
  - ../../server.py
---

# Knowledge Base — LLM Wiki Interop

Two-layer knowledge architecture: **LLM Wiki** (curation layer, for humans) +
**Astra KB** (search layer, for AI agents).

| Layer | What | For whom | Storage |
|-------|------|----------|---------|
| **Layer 1 — LLM Wiki** | Curated Markdown pages with frontmatter, cross-refs | **Humans** (reading, browsing) | `$WIKI_PATH` — a directory of `.md` files |
| **Layer 2 — Astra KB** | Chunked, embedded text with SAG indexing | **AI agents** (search, retrieval) | PostgreSQL 16 + pgvector + pg_trgm |

---

## Before You Begin

- **LLM Wiki** — ask the user where to create it; do not default to `~/wiki`
- **Astra KB** — MCP server with PostgreSQL backend (`scripts/run.sh`)
- **Embedding API** — `ASTRA_EMBED_BASE_URL` + `ASTRA_EMBED_API_KEY` +
  `ASTRA_EMBED_MODEL` (default: SiliconFlow Qwen/Qwen3-VL-Embedding-8B)
- **MarkItDown MCP** — document conversion
- **watchdog** (`pip install watchdog`) — for realtime file watching

---

## Architecture

```
Input (zip / path / file / URL)
    │
    ├── classify + convert
    │
    ▼ (Markdown)
    ┌──────────┴──────────┐
    ▼                     ▼
┌──────────────┐    ┌──────────────┐
│ Layer 1:     │    │ Layer 2:     │
│ LLM Wiki     │    │ Astra KB     │
│              │    │ (direct)     │
│ sync ────────┤──► │              │
│ watch ───────┤──► │ search       │
└──────────────┘    └──────────────┘
```

### Layer 1: LLM Wiki

```
wiki/
├── AGENTS.md      (project-specific paths, conventions, sync commands)
├── index.md
├── mkdocs.yml     (optional MkDocs config)
├── category_A/
├── category_B/
└── ...
```

Project-specific structure is always documented in `AGENTS.md`.

### Layer 2: Astra KB

One KB per project (e.g. `gliousa`). Each contains:
- `chunks` → `embed_vec` (pgvector) + `pg_trgm` index for CJK ILIKE
- `events`, `entities`, `event_entities` (SAG indexing, arxiv 2606.15971)

Search modes: `hybrid`, `vector`, `fts`, `sag_fast`, `sag_precise`

---

## Pipeline 1: Wiki → KB sync

### Batch import (all changed pages)

```bash
cd /path/to/astra-knowledge-base-mcp
ASTRA_EMBED_BASE_URL=... ASTRA_EMBED_API_KEY=... \
  python3 scripts/wiki-kb-sync.py           # incremental
python3 scripts/wiki-kb-sync.py --full       # full resync
python3 scripts/wiki-kb-sync.py --dry-run    # report only
python3 scripts/wiki-kb-sync.py --file 入门/概述.md  # single file
```

### Realtime watch (automatic, while editing)

```bash
python3 scripts/wiki-kb-watch.py --daemon &

# Log: tail -f /tmp/wiki-kb-watch.log
# Stop: kill $(cat /tmp/wiki-kb-watch.pid)
```

**How it works:** Watchdog monitors all `.md` files. On change:
1. Delete old KB chunks for that source path
2. Re-chunk with configured chunker (semantic recommended)
3. Re-embed and insert

### SAG extraction (after sync)

```
mcp__astra_knowledge_base__kb_extract(kb="<kb_name>")
```

---

## Chunking

Three chunkers in `chunking/`:

| Chunker | How | API calls | Best for |
|---------|-----|-----------|----------|
| **semantic** ✅ | Embed all paragraphs in 1 call, cosine-sim boundaries | **1 per batch** | Structured wiki with distinct topics |
| recursive | Fixed 1000-char windows | 0 | Arbitrary text |
| heading-anchor | Split at `##` | 0 | Clear `##` structure |

**Semantic advantages:** No redundant embedding, R18 auto-separated, threshold-adjustable.

**Configure:**
```sql
UPDATE kb_registry SET chunker = 'semantic' WHERE name = '<kb>';
```

When `server.py`'s `kb_add` runs via the MCP tool, it uses `TextIngestor`
with `RecursiveChunker` (the default).  The chunker registry (`kb_registry`)
is currently consulted only by the sync scripts (`wiki-kb-sync.py` and
`wiki-kb-watch.py`) — they call `get_chunker_for_kb()` to select the KB's
configured chunker and pass `embed_fn` for semantic mode.

---

## Pipeline 2: KB → Wiki (manual)

When a KB search returns something worth keeping:
1. Create a note page in the wiki (no sync needed — manual curation)
2. Not automated; human judgment decides what's worth keeping

---

## Export Formats

| Format | Command | Use |
|--------|---------|-----|
| **Astra KB** | `wiki-kb-sync.py [--full]` | AI search |
| **PDF** | `bash scripts/build-pdf.sh` | Print/offline |
| **MkDocs HTML** | `mkdocs build` | Browse |

### PDF Export

Two components:
- **Generic template**: `scripts/build-pdf.sh` + `preprocess.py` + `header.tex`
  (from this skill's linked files)
- **Project config**: `scripts/build-pdf.sh` in the project wiki directory,
  with `WIKI=`, `OUTPUT=`, `nav_order=` overridden

See project's `AGENTS.md` for exact invocation.

---

## Push to Production

```bash
# Daily sync (cron)
0 6 * * * cd /path && python3 scripts/wiki-kb-sync.py

# Realtime watcher (cron @reboot)
@reboot cd /path && ASTRA_EMBED_BASE_URL=... \
  python3 scripts/wiki-kb-watch.py --daemon

# Weekly SAG extraction (cron)
0 7 * * 1 cd /path && hermes mcp call astra_kb kb_extract --arg kb=<kb>
```

## Health Check

```bash
python3 scripts/wiki-kb-sync.py --dry-run
```

Checks: missing pages, stale pages, chunk count drift.

---

## Pitfalls

1. **Bracket paths** — `[世界观]` breaks shell glob patterns. Python scripts
   (`os.walk()`) handle this correctly.
2. **Semantic chunker needs embed API** — Falls back to paragraph mode if
   `ASTRA_EMBED_BASE_URL` is unset.
3. **SAG is slow** — One LLM call per chunk. Run after sync, not during.
4. **Watchdog memory** — ~30MB RSS. Acceptable for a daemon.
5. **MCP server restart** — Adding a new MCP server needs session restart.

---

## References

- Sync script: `scripts/wiki-kb-sync.py`
- Realtime watcher: `scripts/wiki-kb-watch.py`
- Semantic chunker: `chunking/semantic.py`
- Server dispatch: `server.py` (kb_add → chunker resolution)
- Project config: project `AGENTS.md`
- `knowledge-base-architecture` skill: `skill_view('knowledge-base-architecture')`
