# astra-knowledge-base-mcp — Agent Guide

For AI agents consuming this component. Humans can skip to [README](README.md).

## Entry Points

| Action | Command |
|:-------|:--------|
| Start MCP server | `bash run.sh` or `uv run server.py` |
| List knowledge bases | MCP tool: `kb_list` |
| Create knowledge base | MCP tool: `kb_create(name="...", description="...")` |
| Add content | MCP tool: `kb_add(kb="...", content="...", title="...")` |
| Search | MCP tool: `kb_search(query="...", kb_names=["..."])` |

## Dependencies

- Python 3.11+
- uv (for dependency sync)
- No external services — database is local SQLite via `$ASTRA_KB_PATH`

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
    command: /path/to/astra-knowledge-base-mcp/run.sh
    enabled: true
```
