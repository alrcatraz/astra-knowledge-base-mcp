#!/bin/bash
# Start the Astra Knowledge Base MCP server in SSE/HTTP mode (systemd entrypoint).
# Usage: bash scripts/run-sse.sh [extra server.py args]
#
# This is the script referenced by ~/.config/systemd/user/astra-kb-mcp.service.
# It must stay tracked in git on EVERY branch that a deployment checks out —
# an untracked entrypoint silently leaves the unit in a 203/EXEC restart loop.
set -e
cd "$(dirname "$0")/.."
exec bash scripts/run.sh --http --port 3003
