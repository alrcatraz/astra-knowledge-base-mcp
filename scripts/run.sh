#!/bin/bash
# Start the Astra Knowledge Base MCP server.
# Usage: bash scripts/run.sh
set -e
cd "$(dirname "$0")/.."
exec uv run server.py "$@"
