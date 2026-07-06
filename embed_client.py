"""Embedding client for Astra Knowledge Base.

Supports two backends:
  - local: llama.cpp server running on localhost:8081
  - siliconflow: API fallback via API key (SILICONFLOW_API_KEY or ASTRA_EMBED_API_KEY)

Config via env:
  ASTRA_EMBED_BACKEND=local|siliconflow  (default: local)
  ASTRA_EMBED_URL=http://127.0.0.3:8081   (local backend)
  ASTRA_EMBED_DIM=1024
  ASTRA_EMBED_API_KEY=sk-...             (siliconflow/API backend, fallback: SILICONFLOW_API_KEY)
  ASTRA_EMBED_API_URL=https://...        (siliconflow/API backend, default: https://api.siliconflow.cn/v1/embeddings)
  ASTRA_EMBED_MODEL=model-name           (siliconflow/API backend, default: Qwen/Qwen3-Embedding-8B)
"""

import json
import os
import sys
import urllib.request
import urllib.error

EMBED_BACKEND = os.environ.get("ASTRA_EMBED_BACKEND", "local")
EMBED_URL = os.environ.get("ASTRA_EMBED_URL", "http://127.0.0.3:8081")
EMBED_DIM = int(os.environ.get("ASTRA_EMBED_DIM", "1024"))
EMBED_API_KEY = os.environ.get("ASTRA_EMBED_API_KEY") or os.environ.get("SILICONFLOW_API_KEY")
EMBED_API_URL = os.environ.get("ASTRA_EMBED_API_URL", "https://api.siliconflow.cn/v1/embeddings")
EMBED_MODEL = os.environ.get("ASTRA_EMBED_MODEL", "Qwen/Qwen3-Embedding-8B")


def embed_text(text: str) -> list[float] | None:
    """Embed a single text string. Returns 1536-dim vector or None on failure."""
    if not text or not text.strip():
        return None

    if EMBED_BACKEND == "siliconflow":
        return _embed_siliconflow(text)
    return _embed_local(text)


def embed_texts(texts: list[str]) -> list[list[float] | None]:
    """Batch embed multiple texts. Returns list of vectors (None for failures)."""
    return [embed_text(t) for t in texts]


# ── Local llama.cpp backend ──────────────────────────────────────


def _embed_local(text: str) -> list[float] | None:
    """Call local llama.cpp embedding server."""
    payload = json.dumps({
        "input": text,
        "model": "default",
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{EMBED_URL}/v1/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result["data"][0]["embedding"]
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, OSError) as e:
        # Log and return None — caller decides fallback
        print(f"[embed] local backend failed: {e}", file=sys.stderr)
        return None


# ── SiliconFlow fallback ─────────────────────────────────────────


def _embed_siliconflow(text: str) -> list[float] | None:
    """Call SiliconFlow embedding API."""
    api_key = EMBED_API_KEY
    if not api_key:
        return None

    payload = json.dumps({
        "model": EMBED_MODEL,
        "input": text,
        "encoding_format": "float",
        "dimensions": EMBED_DIM,
    }).encode("utf-8")

    req = urllib.request.Request(
        EMBED_API_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result["data"][0]["embedding"]
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, OSError) as e:
        print(f"[embed] SiliconFlow backend failed: {e}", file=sys.stderr)
        return None
