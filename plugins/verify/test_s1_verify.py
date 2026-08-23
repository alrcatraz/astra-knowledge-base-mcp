"""Phase 1 (SAG) end-to-end verification on a dedicated TEST KB.

Verifies: extract_chunks (LLM event/entity extraction) → search_sag_fast /
search_sag_precise against a disposable KB, then deletes it. Never touches
production KBs (gloriosa_*).

Run from repo root:

    ASTRA_EMBED_BASE_URL=http://127.0.0.1:8080/v1 \
    ASTRA_EMBED_MODEL=embedding \
    ASTRA_EMBED_DIM=1024 \
    ASTRA_LLM_BASE_URL=http://127.0.0.1:8080/v1 \
    ASTRA_LLM_MODEL=auto/best-free \
    uv run python3 tests/test_sag_verify.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_KB = "test_sag_mem"

SAMPLE_CHUNKS = [
    {
        "title": "user-style",
        "content": (
            "用户对深色界面有强烈偏好，并且坚持在动手前先读官方文档。"
            "项目负责人王小明在2026年8月正式决定采用向量检索方案。"
        ),
        "source": "session:test-sag-1",
    },
]


def main() -> int:
    import pg_backend as pg

    names = {r["name"] for r in pg.list_kbs()}
    if TEST_KB in names:
        pg.delete_kb(TEST_KB)
        print("[setup] removed leftover test KB")

    # 1. create + write
    pg.create_kb(TEST_KB, "SAG verification")
    pg.add_chunks(TEST_KB, SAMPLE_CHUNKS)
    print("[1] KB created + chunks written")

    # 2. extract (needs ASTRA_LLM_*)
    res = pg.extract_chunks(TEST_KB)
    print(f"[2] extract_chunks -> {res}")
    assert res.get("success"), "extraction should succeed"

    # 3. verify SAG tables got rows
    from pg_backend import get_conn

    conn = get_conn(); cur = conn.cursor()
    counts = {}
    for tbl in ("events", "entities", "event_entities"):
        cur.execute(f"SELECT count(*) FROM kb_{TEST_KB}.{tbl}")
        counts[tbl] = cur.fetchone()[0]
    conn.close()
    print(f"[3] SAG tables -> {counts}")
    assert counts["entities"] >= 1, "expected at least one extracted entity"

    # 4. SAG retrieval
    r_fast = pg.search_sag_fast("谁决定采用向量检索方案", kb_names=[TEST_KB], limit=3)
    print(f"[4] sag_fast -> {len(r_fast)} hits")
    r_prec = pg.search_sag_precise("深色界面偏好", kb_names=[TEST_KB], limit=3)
    print(f"[4] sag_precise -> {len(r_prec)} hits")

    # 5. cleanup
    pg.delete_kb(TEST_KB)
    assert TEST_KB not in {r["name"] for r in pg.list_kbs()}
    print("[5] test KB cleaned up")
    print("\n✅ Phase 1 SAG verification PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())