# astra-knowledge-base-mcp — Agent Guide

For AI agents consuming this component. Humans can skip to [README](README.md).

## Entry Points

| Action | Command |
|:-------|:--------|
| Start MCP server | `bash scripts/run.sh` or `uv run server.py` |
| List knowledge bases | MCP tool: `kb_list` |
| Create knowledge base | MCP tool: `kb_create(name="...", description="...")` |
| Add content | MCP tool: `kb_add(kb="...", content="...", title="...")` |
| Search | MCP tool: `kb_search(query="...", kb_names=["..."])` |
| Browse chunks | MCP tool: `kb_list_chunks(kb="...", limit=50, offset=0)` |
| Edit chunk | MCP tool: `kb_update(kb="...", chunk_id=..., ...)` |
| Delete chunk | MCP tool: `kb_delete_chunk(kb="...", chunk_id=...)` |
| List mgmt tables | MCP tool: `mgmt_list_tables()` |
| Query mgmt data | MCP tool: `mgmt_query(table="services", ...)` |

## Dependencies

- **Runtime:** Python 3.11+
- **Tooling:** uv (for dependency sync)
- **Database:** PostgreSQL 16+ with pgvector (via psycopg2)
- **Ecosystem:** None — database is `astra_kb` on localhost, no astra ecosystem repos required

## Agent Workflows

### Use Case: Create a Knowledge Base and Seed It

```
1. kb_create("my-kb", "My reference data")
2. kb_add("my-kb", "Content here", title="Doc 1")
3. kb_add("my-kb", "More content", title="Doc 2")
4. kb_search("keywords", kb_names=["my-kb"])
```

### Use Case: Register as MCP in Hermes

In config.yaml:
```yaml
mcp_servers:
  astra-knowledge-base:
    command: /path/to/astra-knowledge-base-mcp/scripts/run.sh
    enabled: true
```
