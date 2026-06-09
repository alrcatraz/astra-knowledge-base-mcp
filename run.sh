#!/bin/bash
cd /home/alrcatraz/Projects/astra/astra-knowledge-base-mcp
exec uv run server.py "$@"
