#!/usr/bin/env python3
"""Astra Knowledge Base MCP Server.

Provides tools for AI agents to manage and search multi-tenant knowledge bases
backed by PostgreSQL + pgvector FTS.

Tools:
  kb_list       — List all knowledge bases
  kb_create     — Create a new knowledge base
  kb_delete     — Delete a knowledge base
  kb_enable     — Enable a KB (include in search)
  kb_disable    — Disable a KB (exclude from search)
  kb_add        — Add content to a knowledge base
  kb_search     — Search across enabled KBs
"""

import sys
import json
from mcp.server.models import InitializationOptions
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
import mcp.server.stdio

from db import get_connection
from kb_manager import create_kb, delete_kb, enable_kb, disable_kb, list_kbs
from search.fts import FTSEngine
from ingestion.text import TextIngestor

server = Server("astra-knowledge-base")
fts_engine = FTSEngine()
text_ingestor = TextIngestor()


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
            description="Search across enabled (or specified) knowledge bases",
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
                },
                "required": ["query"],
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
            chunks = text_ingestor.ingest(
                arguments["content"],
                title=arguments.get("title", ""),
                source=arguments.get("source"),
                tags=arguments.get("tags", []),
            )
            added = _store_chunks(arguments["kb"], chunks)
            return [types.TextContent(
                type="text",
                text=json.dumps({"success": True, "kb": arguments["kb"], "chunks_added": added}, indent=2, ensure_ascii=False),
            )]

        case "kb_search":
            results = fts_engine.search(
                arguments["query"],
                kb_names=arguments.get("kb_names"),
                limit=arguments.get("limit", 10),
            )
            return [types.TextContent(type="text", text=json.dumps(results, indent=2, ensure_ascii=False))]

        case _:
            raise ValueError(f"Unknown tool: {name}")


def _store_chunks(kb_name: str, chunks: list[dict]) -> int:
    """Insert chunks into a knowledge base. Returns count."""
    from db import _sanitize
    safe = _sanitize(kb_name)
    with get_connection() as conn:
        with conn.cursor() as cur:
            count = 0
            for chunk in chunks:
                cur.execute(
                    f"INSERT INTO kb_{safe}.chunks (title, content, source, tags) VALUES (%s, %s, %s, %s)",
                    (chunk.get("title", ""), chunk["content"], chunk.get("source"), chunk.get("tags", [])),
                )
                count += 1
        conn.commit()
    return count


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
