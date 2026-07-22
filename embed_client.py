"""OpenAI-compatible embedding client for Astra Knowledge Base.

Supports any OpenAI-compatible embedding endpoint, local or remote.
Config via environment variables — no hardcoded provider names.

  ASTRA_EMBED_BASE_URL   — OpenAI-compatible base URL (required)
  ASTRA_EMBED_API_KEY    — API key (optional: local models may not require one)
  ASTRA_EMBED_MODEL      — Model name (default: Qwen/Qwen3-VL-Embedding-8B)
  ASTRA_EMBED_DIM        — Embedding dimension (default: 1024)

Cache is stored in PostgreSQL (embed_cache table) — no SQLite dependency.

Supports VL (vision-language) embedding for text + image mixed input.

Examples:
  # Remote API — set base URL, API key, and model:
  ASTRA_EMBED_API_KEY=sk-... ASTRA_EMBED_BASE_URL=https://api.siliconflow.cn/v1 ASTRA_EMBED_MODEL=Qwen/Qwen3-VL-Embedding-8B

  # Local llama.cpp (no API key needed):
  ASTRA_EMBED_BASE_URL=http://127.0.0.3:8081/v1

  # OpenAI:
  ASTRA_EMBED_BASE_URL=https://api.openai.com/v1 ASTRA_EMBED_API_KEY=sk-... ASTRA_EMBED_MODEL=text-embedding-3-small

  # DeepSeek:
  ASTRA_EMBED_BASE_URL=https://api.deepseek.com/v1 ASTRA_EMBED_API_KEY=sk-... ASTRA_EMBED_MODEL=deepseek-embedding
"""

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

# ── Configuration (all from env, no hardcoded provider names) ─────

BASE_URL = os.environ.get("ASTRA_EMBED_BASE_URL", "").rstrip("/")

API_KEY = os.environ.get("ASTRA_EMBED_API_KEY", "")
MODEL = os.environ.get("ASTRA_EMBED_MODEL", "Qwen/Qwen3-VL-Embedding-8B")
DIM = int(os.environ.get("ASTRA_EMBED_DIM", "1024"))

# ── Embedding cache (PostgreSQL-backed, survives restarts) ────────

_PG_DSN = os.environ.get(
    "ASTRA_KB_PG_DSN",
    "dbname=astra_kb user=postgres host=/run/postgresql",
)


def _get_pg_conn():
    """Get a PostgreSQL connection for the embedding cache."""
    import psycopg2

    conn = psycopg2.connect(_PG_DSN)
    with conn.cursor() as cur:
        cur.execute(
            """CREATE TABLE IF NOT EXISTS embed_cache (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                model TEXT NOT NULL,
                dim   INTEGER NOT NULL,
                ts    DOUBLE PRECISION NOT NULL
            )"""
        )
    conn.commit()
    return conn


def _cache_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> list[float] | None:
    """Retrieve cached embedding. Returns None on miss."""
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT value, model, dim FROM embed_cache WHERE key = %s",
                (key,),
            )
            row = cur.fetchone()
        conn.close()
        if row and row[1] == MODEL and row[2] == DIM:
            return json.loads(row[0])
    except Exception:
        pass
    return None


def _cache_set(key: str, vector: list[float]):
    """Store embedding in cache."""
    try:
        conn = _get_pg_conn()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO embed_cache (key, value, model, dim, ts) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (key) DO UPDATE SET "
                "  value = EXCLUDED.value, model = EXCLUDED.model, "
                "  dim = EXCLUDED.dim, ts = EXCLUDED.ts",
                (key, json.dumps(vector), MODEL, DIM, time.time()),
            )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Core embedding API ────────────────────────────────────────────

# Rate limiting: track last call time for simple pacing
_last_call = 0.0


def _pace():
    """Ensure at least 0.1s between API calls."""
    global _last_call
    now = time.time()
    elapsed = now - _last_call
    if elapsed < 0.1:
        time.sleep(0.1 - elapsed)
    _last_call = time.time()


def embed_text(text: str) -> list[float] | None:
    """Embed a single text string. Returns vector or None on failure."""
    if not text or not text.strip():
        return None

    key = _cache_key(text)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    result = _call_api([text])
    if result and len(result) > 0:
        vector = result[0]
        if vector is not None:
            try:
                _cache_set(key, vector)
            except Exception:
                pass
            return vector
    return None


def embed_batch(texts: list[str]) -> list[list[float] | None]:
    """Batch embed multiple texts. Returns list of vectors (None for failures).

    Uses cache + single API batched call for uncached texts.
    """
    if not texts:
        return []

    results: list[list[float] | None] = []
    uncached_keys: list[str] = []
    uncached_texts: list[str] = []

    for text in texts:
        if not text or not text.strip():
            results.append(None)
            continue
        key = _cache_key(text)
        cached = _cache_get(key)
        if cached is not None:
            results.append(cached)
        else:
            results.append(None)
            uncached_keys.append(key)
            uncached_texts.append(text)

    if uncached_texts:
        api_results = _call_api_batch(uncached_texts)

        # Map API results back to result slots
        uncached_idx = 0
        for i in range(len(results)):
            if results[i] is None and uncached_texts:
                if uncached_idx < len(api_results):
                    vec = api_results[uncached_idx]
                    if vec is not None:
                        results[i] = vec
                        try:
                            _cache_set(uncached_keys[uncached_idx], vec)
                        except Exception:
                            pass
                uncached_idx += 1

    return results


# ── API call helpers (with retry + exponential backoff) ────────────


def _call_api(texts: list[str], retries: int = 3) -> list[list[float] | None]:
    """Call the embedding API with retry and exponential backoff.

    Uses OpenAI-compatible /v1/embeddings format.
    """
    for attempt in range(retries):
        try:
            _pace()
            payload = json.dumps({
                "model": MODEL,
                "input": texts,
                "encoding_format": "float",
                "dimensions": DIM,
            }).encode("utf-8")

            url = f"{BASE_URL}/embeddings"
            headers = {"Content-Type": "application/json"}
            if API_KEY:
                headers["Authorization"] = f"Bearer {API_KEY}"

            req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())

            data = result.get("data", [])
            data.sort(key=lambda x: x.get("index", 0))
            return [d["embedding"] for d in data]

        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = 2 ** attempt
                print(f"[embed] rate limited (429), retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"[embed] HTTP {e.code}: {e.reason}", file=sys.stderr)
            return [None] * len(texts)

        except (urllib.error.URLError, json.JSONDecodeError, KeyError, OSError) as e:
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"[embed] error: {e}, retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"[embed] giving up after {retries} attempts: {e}", file=sys.stderr)
            return [None] * len(texts)

    return [None] * len(texts)


def _call_api_batch(texts: list[str]) -> list[list[float] | None]:
    """Batch API call. OpenAI-compatible APIs support batch input natively."""
    if not texts:
        return []
    return _call_api(texts)


# ── Legacy compatibility ──────────────────────────────────────────


def embed_texts(texts: list[str]) -> list[list[float] | None]:
    """Legacy wrapper. Prefer embed_batch()."""
    return embed_batch(texts)
