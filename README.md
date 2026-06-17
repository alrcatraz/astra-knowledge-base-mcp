# astra-knowledge-base-mcp

> MCP (Model Context Protocol) server for managing and searching multi-tenant knowledge bases.
>
> Part of the [Astra AI Agent Infrastructure](https://github.com/alrcatraz/astra-aiagent-infra) ecosystem.

## Overview

Astra Knowledge Base MCP provides AI agents (via [Hermes Agent](https://hermes-agent.nousresearch.com) or any MCP-compatible host) with persistent, searchable knowledge bases backed by PostgreSQL.

Each knowledge base is an isolated schema with full-text search (PostgreSQL `tsvector`). Content is auto-chunked on ingestion.

## Tools

| Tool | Description |
|:-----|:------------|
| `kb_list` | List all knowledge bases with enable/disable status |
| `kb_create` | Create a new empty knowledge base |
| `kb_delete` | Permanently delete a knowledge base and all its content |
| `kb_enable` | Enable a knowledge base (include in search results) |
| `kb_disable` | Disable a knowledge base (exclude from search) |
| `kb_add` | Add text content to a knowledge base (auto-chunked) |
| `kb_search` | Search across enabled knowledge bases |

## Prerequisites

- **PostgreSQL 16+** — with full-text search support (built-in, no extensions required)
- **Python 3.11+**
- **uv** — Python package manager (`pip install uv`)

## Setup

### 1. Database

Create the database:

```bash
createdb astra_kb
```

The server creates required tables automatically on first run.

### 2. Configuration

Configure via environment variables (defaults for local dev):

| Variable | Default | Description |
|:---------|:--------|:------------|
| `ASTRA_DB_HOST` | `127.0.0.1` | PostgreSQL host |
| `ASTRA_DB_PORT` | `5432` | PostgreSQL port |
| `ASTRA_DB_NAME` | `astra_kb` | Database name |
| `ASTRA_DB_USER` | `astramcp` | Database user |
| `ASTRA_DB_PASSWORD` | `astra_kb_2026` | Database password |

### 3. Start

```bash
uv run server.py
```

The server starts in MCP stdio mode, ready to connect to any MCP-compatible host.

## Registering in Hermes Agent

Add to your Hermes `config.yaml`:

```yaml
mcp_servers:
  astra-knowledge-base:
    command: uv
    args:
      - run
      - --directory
      - /path/to/astra-knowledge-base-mcp
      - server.py
```

Then restart Hermes Agent. The tools (`kb_list`, `kb_search`, etc.) become available automatically.

## Architecture

```
AI Agent (Hermes)
    │  MCP stdio protocol
    ▼
astra-knowledge-base-mcp (Python, uv run)
    │  psycopg2
    ▼
PostgreSQL 16 (astra_kb)
    ├── public.kb_registry       ← KB metadata & status
    └── kb_<name>.chunks         ← Per-KB content with FTS index
```

Content is chunked automatically on ingestion using recursive text splitting with configurable chunk size and overlap.

## Related

- [astra-aiagent-infra](https://github.com/alcatraz/astra-aiagent-infra) — ecosystem portal
- [Hermes Agent](https://hermes-agent.nousresearch.com) — AI agent framework
- [MCP](https://modelcontextprotocol.io) — Model Context Protocol

## License

MIT — see [LICENSE](LICENSE).
