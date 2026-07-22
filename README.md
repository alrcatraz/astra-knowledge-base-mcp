# astra-knowledge-base-mcp

<div align="center">

> MCP (Model Context Protocol) server for managing and searching multi-tenant knowledge bases.
>
> Part of [Astra AI Agent Infrastructure](https://github.com/alrcatraz/astra-aiagent-infra)

[![License](https://badgen.net/github/license/alrcatraz/astra-knowledge-base-mcp)](LICENSE)
[![GitHub stars](https://badgen.net/github/stars/alrcatraz/astra-knowledge-base-mcp)](https://github.com/alrcatraz/astra-knowledge-base-mcp)
[![GitHub last commit](https://badgen.net/github/last-commit/alrcatraz/astra-knowledge-base-mcp)](https://github.com/alrcatraz/astra-knowledge-base-mcp/commits)
[![Sponsor](https://img.shields.io/github/sponsors/alrcatraz?label=Sponsor&logo=github&color=ea4aaa&logoColor=white)](https://github.com/sponsors/alrcatraz)

</div>

## Overview

Astra Knowledge Base MCP provides AI agents with persistent, searchable knowledge bases backed by **PostgreSQL 16+ with pgvector** — hybrid full-text and vector search, plus SAG (SQL-Retrieval Augmented Generation) for relational reasoning across chunks.

Each knowledge base is an isolated namespace. Content is auto-chunked on ingestion (recursive, heading-anchor, or semantic splitting), embedded via any OpenAI-compatible endpoint, and indexed for three complimentary retrieval paths.

## Prerequisites

- **Python 3.11+**
- **uv** — Python package manager (`pip install uv`)
- **PostgreSQL 16+ with pgvector** — installation guide: [pgvector.org](https://github.com/pgvector/pgvector)

## Setup

### 1. Configure PostgreSQL

Create the database and enable pgvector:

```sql
CREATE DATABASE astra_kb;
\c astra_kb
CREATE EXTENSION IF NOT EXISTS vector;
```

### 2. Install dependencies

```bash
uv sync
```

### 3. Configure environment

```bash
# Embedding endpoint (any OpenAI-compatible API)
export ASTRA_EMBED_BASE_URL=https://api.siliconflow.cn/v1
export ASTRA_EMBED_API_KEY=sk-...
export ASTRA_EMBED_MODEL=Qwen/Qwen3-VL-Embedding-8B
export ASTRA_EMBED_DIM=1024

# Optional: LLM endpoint for SAG extraction
export ASTRA_LLM_BASE_URL=https://api.siliconflow.cn/v1
export ASTRA_LLM_API_KEY=sk-...
export ASTRA_LLM_MODEL=THUDM/GLM-Z1-9B-0414

# PostgreSQL connection
export ASTRA_KB_PG_DSN=dbname=astra_kb user=postgres host=/run/postgresql
```

### 4. Start

```bash
uv run server.py
```

## Configuration

| Variable | Default | Description |
|:---------|:--------|:------------|
| `ASTRA_KB_BACKEND` | `postgres` | Backend — PostgreSQL only |
| `ASTRA_KB_PG_DSN` | `dbname=astra_kb user=postgres host=/run/postgresql` | PostgreSQL connection string |
| `ASTRA_EMBED_BASE_URL` | — (required) | OpenAI-compatible embedding endpoint |
| `ASTRA_EMBED_API_KEY` | — | Embedding API key (optional for local models) |
| `ASTRA_EMBED_MODEL` | `Qwen/Qwen3-VL-Embedding-8B` | Embedding model (supports VL for text+image) |
| `ASTRA_EMBED_DIM` | `1024` | Embedding vector dimension |
| `ASTRA_LLM_BASE_URL` | — (required for SAG) | LLM endpoint for event/entity extraction |
| `ASTRA_LLM_API_KEY` | — | LLM API key |
| `ASTRA_LLM_MODEL` | `THUDM/GLM-Z1-9B-0414` | LLM model for extraction |

> **No hardcoded provider defaults.** `ASTRA_EMBED_BASE_URL` and `ASTRA_LLM_BASE_URL`
> must be set explicitly. The old `SILICONFLOW_API_KEY` fallback has been removed —
> use `ASTRA_EMBED_API_KEY` or `ASTRA_LLM_API_KEY` instead.

## Usage

### MCP Tools

| Tool | Description |
|:-----|:------------|
| `kb_list` | List all knowledge bases with enable/disable status |
| `kb_create` | Create a new empty knowledge base |
| `kb_delete` | Permanently delete a knowledge base and all its content |
| `kb_enable` / `kb_disable` | Toggle KB visibility in search |
| `kb_add` | Add text content (auto-chunked + embedded) |
| `kb_update` | Update a chunk (replace or append mode) |
| `kb_delete_chunk` | Delete a single chunk by ID |
| `kb_list_chunks` | List chunks in a knowledge base (paginated) |
| `kb_search` | Search across KBs — modes: `hybrid` (default), `fts`, `vector`, `sag_fast`, `sag_precise` |
| `kb_extract` | Extract events and entities from unprocessed chunks (SAG indexing) |
| `kb_import_file` | Import a file (PDF, DOCX, PPTX, TXT, MD) via MarkItDown |
| `kb_import_jsonl` | Import chunks from a JSONL file |
| `kb_export_jsonl` | Export all chunks to JSONL |
| `kb_stats` | Knowledge base statistics and overview |
| `kb_diff` | Track chunk changes over time |
| `mgmt_list_tables` | List mgmt schema tables (services, health_log, api_keys) |
| `mgmt_query` | Query operational data from mgmt tables |

### Registering in Hermes Agent

Add to your Hermes `config.yaml`:

```yaml
mcp_servers:
  astra-knowledge-base:
    command: /path/to/astra-knowledge-base-mcp/scripts/run.sh
    enabled: true
```

Then restart Hermes Agent. The tools become available automatically.

## Architecture

```
AI Agent (Hermes)
    │  MCP stdio protocol
    ▼
astra-knowledge-base-mcp (Python, uv run)
    │
    ├── PostgreSQL (psycopg2 + pgvector) → astra_kb
    │   ├── kb_registry         ← KB metadata & status
    │   ├── kb_*.chunks         ← Per-KB schema (tsvector FTS + vector(1024))
    │   ├── kb_*.events         ← SAG event index (vector(1024))
    │   ├── kb_*.entities       ← SAG entity index (vector(1024))
    │   └── mgmt                ← Operational data (services, health_log, api_keys)
    │
    └── Embedding cache (PostgreSQL) → embed_cache table
```

Three complimentary retrieval paths:

- **FTS** — keyword search via PostgreSQL `tsvector` / `ts_rank`
- **Vector** — semantic search via cosine similarity on `pgvector` indexes
- **SAG** — SQL-Retrieval Augmented Generation: event-entity extraction + query-time hyperedge expansion for multi-hop reasoning across chunks

### Agent Guide

See [AGENTS.md](AGENTS.md) for AI-agent-oriented documentation (entry points, workflows, Hermes integration).

## Related

- [astra-aiagent-infra](https://github.com/alrcatraz/astra-aiagent-infra) — ecosystem portal
- [Hermes Agent](https://hermes-agent.nousresearch.com) — AI agent framework
- [MCP](https://modelcontextprotocol.io) — Model Context Protocol

## Dependencies

- **PostgreSQL 16+** with **pgvector** — primary data store
- **psycopg2-binary** — PostgreSQL driver
- **MarkItDown** — file import (PDF, DOCX, PPTX)

## Retrieval Strategy

We implement **SAG (SQL-Retrieval Augmented Generation)** — an original retrieval architecture that replaces both traditional RAG and GraphRAG. SAG uses event-entity indexing and query-time dynamic hyperedges to deliver both semantic retrieval and relational reasoning in a single pipeline.

**Reference:**
- SAG paper: [arxiv 2606.15971](https://arxiv.org/abs/2606.15971) — Yuchao Wu et al., Zleap AI (MIT)
- Reference implementation: [github.com/Zleap-AI/SAG](https://github.com/Zleap-AI/SAG) — MIT License

Our implementation follows the SAG algorithm directly on our PostgreSQL/pgvector infrastructure, without wrapping the reference package.

## License

MIT — see [LICENSE](LICENSE).

---

## 中文版

### 概述

Astra Knowledge Base MCP 为 AI Agent 提供基于 **PostgreSQL 16+ + pgvector** 的持久化、可搜索知识库——支持混合全文/向量检索和 SAG（SQL 检索增强生成）关联推理。

每个知识库是隔离的命名空间，内容引入时自动分块（递归、heading-anchor 或语义切分），通过任意 OpenAI 兼容的端点进行向量化，并建立三种互补的检索路径。

**Minimal setup:**

```bash
export ASTRA_EMBED_BASE_URL=https://api.siliconflow.cn/v1
export ASTRA_EMBED_API_KEY=sk-...
uv run server.py
```

---

<p align="center">
  <a href="https://star-history.com/#alrcatraz/astra-knowledge-base-mcp&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=alrcatraz/astra-knowledge-base-mcp&type=Date&theme=dark" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=alrcatraz/astra-knowledge-base-mcp&type=Date" />
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=alrcatraz/astra-knowledge-base-mcp&type=Date" width="600" />
    </picture>
  </a>
</p>
