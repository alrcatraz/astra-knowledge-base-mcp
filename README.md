# astra-knowledge-base-mcp

> MCP (Model Context Protocol) server for managing and searching multi-tenant knowledge bases.
>
> Part of the [Astra AI Agent Infrastructure](https://github.com/alrcatraz/astra-aiagent-infra) ecosystem.
>
> [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
> [![GitHub stars](https://badgen.net/github/stars/alrcatraz/astra-knowledge-base-mcp)](https://github.com/alrcatraz/astra-knowledge-base-mcp)
> [![GitHub last commit](https://badgen.net/github/last-commit/alrcatraz/astra-knowledge-base-mcp)](https://github.com/alrcatraz/astra-knowledge-base-mcp/commits)

## Overview

Astra Knowledge Base MCP provides AI agents with persistent, searchable knowledge bases backed by **SQLite + FTS5** — zero external dependencies, one file per deployment.

Each knowledge base is an isolated namespace with full-text search. Content is auto-chunked on ingestion using recursive text splitting.

## Tools

| Tool | Description |
|:-----|:------------|
| `kb_list` | List all knowledge bases with enable/disable status |
| `kb_create` | Create a new empty knowledge base |
| `kb_delete` | Permanently delete a knowledge base and all its content |
| `kb_enable` | Enable a knowledge base (include in search results) |
| `kb_disable` | Disable a knowledge base (exclude from search) |
| `kb_add` | Add text content to a knowledge base (auto-chunked) |
| `kb_search` | Search across enabled (or specified) knowledge bases |

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
| `ASTRA_KB_PATH` | `~/.astra/knowledge-base.db` | Path to the SQLite database file |

## Registering in Hermes Agent

Add to your Hermes `config.yaml`:

```yaml
mcp_servers:
  astra-knowledge-base:
    command: /path/to/astra-knowledge-base-mcp/run.sh
    enabled: true
```

Then restart Hermes Agent. The tools (`kb_list`, `kb_search`, etc.) become available automatically.

## Architecture

```
AI Agent (Hermes)
    │  MCP stdio protocol
    ▼
astra-knowledge-base-mcp (Python, uv run)
    │  sqlite3 (stdlib)
    ▼
SQLite (.db file — ~/.astra/knowledge-base.db)
    ├── kb_registry          ← KB metadata & status
    ├── chunks               ← Content storage
    └── chunks_fts           ← FTS5 virtual table (auto-synced)
```

## Related

- [astra-aiagent-infra](https://github.com/alrcatraz/astra-aiagent-infra) — ecosystem portal
- [Hermes Agent](https://hermes-agent.nousresearch.com) — AI agent framework
- [MCP](https://modelcontextprotocol.io) — Model Context Protocol

## License

MIT — see [LICENSE](LICENSE).

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
