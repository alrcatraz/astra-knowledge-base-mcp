#!/usr/bin/env python3
"""Astra Knowledge Base MCP Server (PostgreSQL).

Provides MCP tools for AI agents to manage and search multi-tenant
knowledge bases backed by PostgreSQL + tsvector full-text search.

Tools:
  Tools               — KB lifecycle (list/create/delete/enable/disable)
  kb_add              — Add text content (auto-chunked)
  kb_search           — Full-text search across KBs
  kb_list_chunks      — Paginated chunk listing
  kb_update           — Edit a chunk (replace or append)
  kb_delete_chunk     — Delete a single chunk
  mgmt_list_tables    — List operational mgmt tables
  mgmt_query          — Query operational data (services/health_log/api_keys)
"""

import sys
import json
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
import mcp.server.stdio

from pg_backend import (
    list_kbs, create_kb, delete_kb, enable_kb, disable_kb,
    add_chunks, search_kbs as pg_search,
    search_kbs_vector, search_kbs_hybrid,
    list_chunks, update_chunk, delete_chunk,
    mgmt_list_tables, mgmt_query,
    search_sag_fast, search_sag_precise, extract_chunks,
)

def _search(query, kb_names=None, limit=10, search_mode="hybrid"):
    if search_mode == "vector":
        return search_kbs_vector(query, kb_names, limit)
    elif search_mode == "fts":
        return pg_search(query, kb_names, limit)
    elif search_mode == "sag_fast":
        return search_sag_fast(query, kb_names, limit)
    elif search_mode == "sag_precise":
        return search_sag_precise(query, kb_names, limit)
    return search_kbs_hybrid(query, kb_names, limit)

server = Server("astra-knowledge-base")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="kb_list",
            description="List all knowledge bases with their enable/disable status",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="kb_create",
            description="Create a new empty knowledge base",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Knowledge base name (lowercase, underscores)"},
                    "description": {"type": "string", "description": "Optional description"},
                },
                "required": ["name"],
            },
        ),
        types.Tool(
            name="kb_delete",
            description="Permanently delete a knowledge base and all its content",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Knowledge base name"},
                },
                "required": ["name"],
            },
        ),
        types.Tool(
            name="kb_enable",
            description="Enable a knowledge base so it appears in search results",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Knowledge base name"},
                },
                "required": ["name"],
            },
        ),
        types.Tool(
            name="kb_disable",
            description="Disable a knowledge base so it is excluded from search",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Knowledge base name"},
                },
                "required": ["name"],
            },
        ),
        types.Tool(
            name="kb_add",
            description="Add text content to a knowledge base (auto-chunked)",
            inputSchema={
                "type": "object",
                "properties": {
                    "kb": {"type": "string", "description": "Target knowledge base name"},
                    "content": {"type": "string", "description": "Text content to add"},
                    "title": {"type": "string", "description": "Optional title for the content"},
                    "source": {"type": "string", "description": "Optional source URL or path"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"},
                },
                "required": ["kb", "content"],
            },
        ),
        types.Tool(
            name="kb_search",
            description="Search across enabled (or specified) knowledge bases. Default: hybrid (FTS + vector)",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "kb_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional: restrict search to specific KBs",
                    },
                    "limit": {"type": "integer", "description": "Max results (default 10)", "default": 10},
                    "search_mode": {
                        "type": "string",
                        "enum": ["hybrid", "fts", "vector", "sag_fast", "sag_precise"],
                        "description": "Search mode: hybrid (default), fts, vector, sag_fast (event vectors), sag_precise (entity-guided)",
                        "default": "hybrid",
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="kb_list_chunks",
            description="List chunks in a knowledge base (paginated)",
            inputSchema={
                "type": "object",
                "properties": {
                    "kb": {"type": "string", "description": "Knowledge base name"},
                    "limit": {"type": "integer", "description": "Max results (default 50)", "default": 50},
                    "offset": {"type": "integer", "description": "Offset for pagination (default 0)", "default": 0},
                },
                "required": ["kb"],
            },
        ),
        types.Tool(
            name="kb_update",
            description="Update a chunk. Unset fields keep current value. mode='append' appends to content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "kb": {"type": "string", "description": "Knowledge base name"},
                    "chunk_id": {"type": "integer", "description": "Chunk ID to update"},
                    "mode": {
                        "type": "string",
                        "enum": ["replace", "append"],
                        "description": "'replace' (default) or 'append'",
                        "default": "replace",
                    },
                    "title": {"type": "string", "description": "Optional new title"},
                    "content": {"type": "string", "description": "Optional new content"},
                    "source": {"type": "string", "description": "Optional new source"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional new tags"},
                    "media_url": {"type": "string", "description": "Optional media URL"},
                    "media_type": {"type": "string", "description": "Optional media MIME type"},
                },
                "required": ["kb", "chunk_id"],
            },
        ),
        types.Tool(
            name="kb_delete_chunk",
            description="Delete a single chunk by ID",
            inputSchema={
                "type": "object",
                "properties": {
                    "kb": {"type": "string", "description": "Knowledge base name"},
                    "chunk_id": {"type": "integer", "description": "Chunk ID to delete"},
                },
                "required": ["kb", "chunk_id"],
            },
        ),
        types.Tool(
            name="kb_extract",
            description="Extract events and entities from unprocessed chunks (SAG indexing). Reference: arXiv 2606.15971",
            inputSchema={
                "type": "object",
                "properties": {
                    "kb": {"type": "string", "description": "Knowledge base name"},
                },
                "required": ["kb"],
            },
        ),
        types.Tool(
            name="mgmt_list_tables",
            description="List available operational tables (services, health_log, api_keys, ...)",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="mgmt_query",
            description="Query operational data from mgmt schema tables",
            inputSchema={
                "type": "object",
                "properties": {
                    "table": {
                        "type": "string",
                        "enum": ["services", "health_log", "api_keys"],
                        "description": "Table to query",
                    },
                    "filter_col": {
                        "type": "string",
                        "description": "Optional column to filter by (e.g. 'name', 'type', 'provider')",
                    },
                    "filter_val": {
                        "type": "string",
                        "description": "Optional value to filter on",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default 20)",
                        "default": 20,
                    },
                },
                "required": ["table"],
            },
        ),
    ]


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict | None
) -> list[types.TextContent | types.ImageContent | types.EmbeddedResource]:
    if arguments is None:
        arguments = {}

    match name:
        case "kb_list":
            result = list_kbs()
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

        case "kb_create":
            result = create_kb(arguments["name"], arguments.get("description", ""))
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

        case "kb_delete":
            result = delete_kb(arguments["name"])
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

        case "kb_enable":
            result = enable_kb(arguments["name"])
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

        case "kb_disable":
            result = disable_kb(arguments["name"])
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

        case "kb_add":
            from ingestion.text import TextIngestor
            chunks = TextIngestor().ingest(
                arguments["content"],
                title=arguments.get("title", ""),
                source=arguments.get("source"),
                tags=arguments.get("tags", []),
            )
            added = add_chunks(arguments["kb"], chunks)["inserted"]
            return [types.TextContent(
                type="text",
                text=json.dumps({"success": True, "kb": arguments["kb"], "chunks_added": added}, indent=2, ensure_ascii=False),
            )]

        case "kb_search":
            results = _search(
                arguments["query"],
                kb_names=arguments.get("kb_names"),
                limit=arguments.get("limit", 10),
                search_mode=arguments.get("search_mode", "hybrid"),
            )
            return [types.TextContent(type="text", text=json.dumps(results, indent=2, ensure_ascii=False))]

        case "kb_list_chunks":
            result = list_chunks(
                arguments["kb"],
                limit=arguments.get("limit", 50),
                offset=arguments.get("offset", 0),
            )
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

        case "kb_update":
            result = update_chunk(
                arguments["kb"],
                arguments["chunk_id"],
                mode=arguments.get("mode", "replace"),
                title=arguments.get("title"),
                content=arguments.get("content"),
                source=arguments.get("source"),
                tags=arguments.get("tags"),
                media_url=arguments.get("media_url"),
                media_type=arguments.get("media_type"),
            )
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

        case "kb_delete_chunk":
            result = delete_chunk(arguments["kb"], arguments["chunk_id"])
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

        case "kb_extract":
            result = extract_chunks(arguments["kb"])
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

        case "mgmt_list_tables":
            result = mgmt_list_tables()
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

        case "mgmt_query":
            result = mgmt_query(
                arguments["table"],
                filter_col=arguments.get("filter_col"),
                filter_val=arguments.get("filter_val"),
                limit=arguments.get("limit", 20),
            )
            return [types.TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

        case _:
            raise ValueError(f"Unknown tool: {name}")


async def main():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="astra-knowledge-base",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    import anyio
    anyio.run(main)
