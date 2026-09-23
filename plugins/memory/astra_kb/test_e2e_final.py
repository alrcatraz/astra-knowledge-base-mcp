"""Final E2E verification of astra_kb memory provider under a REAL Hermes load
context (system python, no psycopg2 -> pg8000 fallback, project-local config).

Scope: dev astra_kb code + PRODUCTION backend (PG + AI Gate embed). Uses an
isolated test KB, never touches production data.
Requires HERMES_AGENT_DIR (default ~/.hermes/hermes-agent) to locate the Hermes
venv; project root is derived from this file's location. No user-specific
absolute paths live in the tracked tree.

Covers the exact path a real Hermes session exercises:
  load -> initialize(session_id) -> sync_turn (writes) ->
  handle_tool_call('kb_mem_search', ...) -> shutdown.
"""
import os
import sys
import json
from pathlib import Path

HERMES_AGENT = os.getenv(
    "HERMES_AGENT_DIR", str(Path.home() / ".hermes" / "hermes-agent")
)
sys.path.insert(0, HERMES_AGENT)

print("== context ==")
try:
    import psycopg2  # noqa: F401
    print("psycopg2: YES")
except ImportError:
    print("psycopg2: NO (expected under Hermes system python -> pg8000 fallback)")

# --- 1. Load through the Hermes plugin mechanism ---
import plugins.memory as mem

print("\n== discovery ==")
print("astra_kb present:", "astra_kb" in mem.list_memory_provider_names())
prov = mem.load_memory_provider("astra_kb")
print("loaded:", type(prov).__name__, "| available:", prov.is_available)

# --- 2. initialize ---
print("\n== initialize ==")
prov.initialize(session_id="e2e-final-1")
print("initialize ok (no exception)")

# --- 3. sync_turn: write a conversation turn ---
TEST_KB = "test_e2e_final"
print("\n== sync_turn (isolated KB:", TEST_KB, ") ==")
# note: sync_turn fails open (swallowed); MUST verify via DB count below
prov.sync_turn(
    "用户正在基础设施运维，他们偏好使用域名驱动的配置而不硬编码IP地址。",
    "好的，我记得了：用域名而不是硬编码IP。",
    session_id="e2e-final-1",
)
import pg_backend as p  # noqa: E402  (dev repo path added by plugin loader)
in_kb = TEST_KB in [k["name"] for k in p.list_kbs()]
print("KB created:", in_kb)

# --- 4. handle_tool_call('kb_mem_search'): what a real Hermes turn calls ---
print("\n== kb_mem_search (semantic recall via handle_tool_call) ==")
raw = prov.handle_tool_call("kb_mem_search", {"query": "网络配置用什么方式保存", "limit": 3})
try:
    parsed = json.loads(raw)
except Exception:
    parsed = {"results": []}
results = parsed.get("results") or []
print("count:", parsed.get("count"), "| results:", len(results))
for r in results[:3]:
    print("   HIT:", (r.get("content") or "")[:42], "| score:", r.get("score"))
ok = bool(results) and not parsed.get("error")
print("RECALL WORKED" if ok else "RECALL EMPTY/ERROR (FAIL)")

# --- 5. shutdown + cleanup ---
prov.shutdown()
print("\n== shutdown ==")
print("shutdown ok")
try:
    p.delete_kb(TEST_KB)
    print("cleaned:", TEST_KB not in [k["name"] for k in p.list_kbs()])
except Exception as e:
    print("cleanup:", repr(e))

print("\n== E2E PASSED ==" if ok else "\n== E2E FAILED ==")