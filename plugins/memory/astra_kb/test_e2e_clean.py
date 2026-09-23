"""Clean isolated E2E: prove sync_turn WRITES a new turn AND that kb_mem_search
recalls THAT SAME content (not stale data). Uses a dedicated KB so it cannot
mask a write failure with leftovers from earlier runs.

Runs under Hermes' own venv python (the real runtime), no psycopg2 -> pg8000.
The astra_kb plugin is located via env HERMES_PLUGINS_DIR_astra_kb or defaulted
to <HERMES_HOME>/plugins/astra_kb; the project root is derived from this file's
location so no user-specific absolute paths live in the tracked tree.
"""
import os
import sys
import json
from pathlib import Path

HERMES_HOME = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # repo root

# AstraKBProvider lives in the Hermes plugin dir.
import importlib.util
_ASTRB_PLUGIN = os.getenv(
    "HERMES_PLUGINS_DIR_astra_kb",
    str(HERMES_HOME / "plugins" / "astra_kb" / "__init__.py"),
)
_spec = importlib.util.spec_from_file_location("astra_kb_plugin", _ASTRB_PLUGIN)
akb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(akb)

# Instantiate directly with an explicit config (mirrors what Hermes would pass).
ISO_KB = "test_e2e_clean"  # underscore (no hyphen) avoids any identifier edge
prov = akb.AstraKBProvider(config={
    "project_root": str(_REPO_ROOT),
    "kb_name": ISO_KB,
})
print("is_available:", prov.is_available())

prov.initialize(session_id="iso-session-1")
assert prov._ready, "provider not ready after initialize"

# 1) write a UNIQUE turn that cannot already be in the KB
UNIQUE = "独角兽饼干在周四下午被绿色飞船送往火星仓库进行量子加速测试。"
prov.sync_turn(
    UNIQUE,
    "助手记录了独角兽饼干运输任务。",
    session_id="iso-session-1",
)

# 2) prove the data landed in THIS kb (direct DB count, not via recall)
import pg_backend as p
kbs = [k["name"] for k in p.list_kbs()]
assert ISO_KB in kbs, f"{ISO_KB} not created: {kbs}"
print("KB created:", ISO_KB)
# count chunks with our unique text
n = 0
for kb in kbs:
    if kb == ISO_KB:
        rows = p._fetch_all("SELECT content FROM kb_test_e2e_clean.chunks WHERE content LIKE %s", (f"%{UNIQUE[:10]}%",)) or []
        n = len(rows)
print("chunks matching unique turn:", n)

# 3) recall the FRESH content by a semantically related query
raw = prov.handle_tool_call("kb_mem_search", {"query": "货船运输饼干到火星", "limit": 5})
parsed = json.loads(raw)
res = parsed.get("results") or []
print("recall count:", parsed.get("count"), "| results:", len(res))
fresh_hit = any(UNIQUE[:16] in (r.get("content") or "") for r in res)
print("FRESH content recalled:", fresh_hit)
for r in res[:5]:
    print("   ", (r.get("content") or "")[:36], "| score:", r.get("score"))

prov.shutdown()
try:
    p.delete_kb(ISO_KB)
    print("cleaned:", ISO_KB not in [k["name"] for k in p.list_kbs()])
except Exception as e:
    print("cleanup:", repr(e))

print("\nCLEAN E2E PASSED" if (fresh_hit and n >= 1) else "\nCLEAN E2E FAILED")