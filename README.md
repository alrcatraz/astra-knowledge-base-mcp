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

Astra Knowledge Base MCP provides AI agents with persistent, searchable knowledge bases backed by **SQLite + FTS5** — zero external dependencies, one file per deployment.

Each knowledge base is an isolated namespace with full-text search. Content is auto-chunked on ingestion using recursive text splitting.

## Prerequisites

- **Python 3.11+**
- **uv** — Python package manager (`pip install uv`)

## Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Start

```bash
uv run server.py
```

The database file is created at `~/.astra/knowledge-base.db` by default. Override with the `ASTRA_KB_PATH` environment variable.

## Configuration

| Variable | Default | Description |
|:---------|:--------|:------------|
| `ASTRA_KB_BACKEND` | `sqlite` | Backend: `sqlite` (stdlib) or `postgres` (psycopg2 + pgvector) |
| `ASTRA_KB_PG_DSN` | `dbname=astra_kb user=postgres host=/run/postgresql` | PostgreSQL DSN (only used with `postgres` backend) |
| `ASTRA_KB_PATH` | `~/.astra/knowledge-base.db` | Path to the SQLite database file |
| `ASTRA_EMBED_BACKEND` | `local` | Embedding backend: `local` (llama.cpp) or `siliconflow` (API) |
| `ASTRA_EMBED_URL` | `http://127.0.0.3:8081` | URL for local llama.cpp embedding server |
| `ASTRA_EMBED_DIM` | `1024` | Embedding vector dimension |
| `ASTRA_EMBED_API_KEY` | `SILICONFLOW_API_KEY` fallback | API key for siliconflow/API embedding backend |
| `ASTRA_EMBED_API_URL` | `https://api.siliconflow.cn/v1/embeddings` | API endpoint URL (OpenAI-compatible `/v1/embeddings`) |
| `ASTRA_EMBED_MODEL` | `Qwen/Qwen3-Embedding-8B` | Model name for the API embedding backend |

## Usage

### MCP Tools

| Tool | Description |
|:-----|:------------|
| `kb_list` | List all knowledge bases with enable/disable status |
| `kb_create` | Create a new empty knowledge base |
| `kb_delete` | Permanently delete a knowledge base and all its content |
| `kb_enable` | Enable a knowledge base (include in search results) |
| `kb_disable` | Disable a knowledge base (exclude from search) |
| `kb_add` | Add text content to a knowledge base (auto-chunked) |
| `kb_search` | Search across enabled (or specified) knowledge bases |
| `kb_list_chunks` | List chunks in a knowledge base (paginated) |
| `kb_update` | Update a chunk (replace or append mode) |
| `kb_delete_chunk` | Delete a single chunk by ID |
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

Then restart Hermes Agent. The tools (`kb_list`, `kb_search`, etc.) become available automatically.

## Architecture

```
AI Agent (Hermes)
    │  MCP stdio protocol
    ▼
astra-knowledge-base-mcp (Python, uv run)
    │
    ├── SQLite (stdlib) → ~/.astra/knowledge-base.db
    │   ├── kb_registry    ← KB metadata & status
    │   ├── chunks         ← Content storage
    │   └── chunks_fts     ← FTS5 virtual table
    │
    └── PostgreSQL (psycopg2) → astra_kb
        ├── kb_registry       ← KB metadata & status
        ├── kb_*.chunks       ← Per-KB schema (tsvector FTS)
        └── mgmt              ← Operational data (services, health_log, api_keys)
```

Switch backends via `ASTRA_KB_BACKEND=postgres` or `ASTRA_KB_BACKEND=sqlite` (default).

### Agent Guide

See [AGENTS.md](AGENTS.md) for AI-agent-oriented documentation (entry points, workflows, Hermes integration).

## Related

- [astra-aiagent-infra](https://github.com/alrcatraz/astra-aiagent-infra) — ecosystem portal
- [Hermes Agent](https://hermes-agent.nousresearch.com) — AI agent framework
- [MCP](https://modelcontextprotocol.io) — Model Context Protocol

## Dependencies

This service has no external dependencies. The SQLite database is managed entirely via Python stdlib (`sqlite3`).

## License

MIT — see [LICENSE](LICENSE).

> CI/CD: coming soon — see [astra-aiagent-infra](https://github.com/alrcatraz/astra-aiagent-infra) for ecosystem-wide pipeline plans.

---

## 中文版

### 概述

Astra Knowledge Base MCP 为 AI Agent 提供基于 **SQLite + FTS5** 的持久化、可搜索知识库——零外部依赖，每个部署一个文件。

每个知识库是一个隔离的命名空间，支持全文搜索。内容引入时自动进行递归文本分块。

### 依赖关系

此服务无外部 astra 生态依赖。SQLite 数据库完全通过 Python 标准库 `sqlite3` 管理。

---

&lt;p align=&quot;center&quot;&gt;
  <a href="https://star-history.com/#alrcatraz/astra-knowledge-base-mcp&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=alrcatraz/astra-knowledge-base-mcp&type=Date&theme=dark" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=alrcatraz/astra-knowledge-base-mcp&type=Date" />
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=alrcatraz/astra-knowledge-base-mcp&type=Date" width="600" />
    </picture>
  </a>
</p>
