#!/bin/bash
# Start the Astra Knowledge Base MCP server in SSE/HTTP mode (systemd entrypoint).
# Usage: bash scripts/run-sse.sh
# This is the script referenced by ~/.config/systemd/user/astra-kb-mcp.service.
set -e
cd "$(dirname "$0")/.."
exec bash scripts/run.sh --http --port 3003
