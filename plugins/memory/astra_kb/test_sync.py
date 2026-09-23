"""End-to-end smoke test for the astra-kb memory provider.

Uses a dedicated TEST knowledge base (``test_astra_mem``), never production
KBs (gloriosa_*). Cleans up the test KB when done.

Run from the repo root (so ``import pg_backend`` resolves):

    uv run python3 plugins/memory/astra-kb/test_sync.py

Set embed env to the live endpoint first (same as the running MCP server):

    ASTRA_EMBED_BASE_URL=http://127.0.0.1:8080/v1 \
    ASTRA_EMBED_MODEL=embedding \
    ASTRA_EMBED_DIM=1024 \
    uv run python3 plugins/memory/astra-kb/test_sync.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the KB repo importable regardless of CWD.
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_KB = "test_astra_mem"


def main() -> int:
    import pg_backend

    # 0. Ensure a clean test KB (drop if a stale one exists from a crash).
    names = {r["name"] for r in pg_backend.list_kbs()}
    if TEST_KB in names:
        print("Removing leftover test KB 'test_astra_mem'...")
        pg_backend.delete_kb(TEST_KB)
        names = {r["name"] for r in pg_backend.list_kbs()}

    # 1. Load the provider the way Hermes does (config = memory plugin config).
    from plugins.memory.astra_kb import AstraKBProvider

    provider = AstraKBProvider(
        config={
            "kb_name": TEST_KB,
            "project_root": str(ROOT),
            "auto_create_kb": True,
        }
    )
    assert provider.is_available(), "provider should be available with real root"
    provider.initialize(session_id="test-session-1")

    # 2. Sink a conversation turn.
    provider.sync_turn(
        user_content="用户喜欢深色主题，并偏好先用官方文档再动手。",
        assistant_content="好的，记住了：用户偏好深色主题。",
        session_id="test-session-1",
    )
    print("[OK] sync_turn wrote")

    # 3. Recall via the provider's own tool handler.
    result = provider.handle_tool_call(
        "kb_mem_search", {"query": "用户对颜色主题的偏好是？", "limit": 5}
    )
    print("[OK] kb_mem_search ->", result[:400])

    import json

    payload = json.loads(result)
    results = payload.get("results", [])
    assert payload.get("count", 0) >= 1, "expected at least one hit"
    assert any("深色" in r.get("content", "") for r in results), (
        "expected a semantic hit for the sunk fact"
    )

    # 4. Clean up the test KB so we never leave test data in the reg.
    provider.shutdown()
    pg_backend.delete_kb(TEST_KB)
    names = {r["name"] for r in pg_backend.list_kbs()}
    assert TEST_KB not in names, "test KB should be cleaned up"
    print("[OK] test KB cleaned up")
    print("\n✅ astra-kb memory provider smoke test PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())