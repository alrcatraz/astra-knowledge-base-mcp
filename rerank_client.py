"""Cohere-compatible rerank client for Astra Knowledge Base.

Optional precision re-ranking stage: coarse retrieval (FTS/vector/hybrid/SAG)
proposes candidates, then a cross-encoder joint pass over (query, document)
re-scores them.  This exists because meaning identity is *computed* in a
joint forward pass and is not recoverable from independently-encoded vectors
(see arXiv:2609.28290, "Computation Over Geometry").

Config via environment variables — no hardcoded provider names, no shipped
endpoint or model defaults.  Mirrors the ``embed_client`` layering: env →
``config/rerank.conf`` → (nothing; unset means disabled).

  ASTRA_RERANK_BASE_URL  — Cohere-compatible base URL (required to enable)
  ASTRA_RERANK_API_KEY   — API key (optional: local gateways may skip auth)
  ASTRA_RERANK_MODEL     — Model name sent to the endpoint (required to enable)
  ASTRA_RERANK_TIMEOUT   — Per-call timeout seconds (default 10)

Reranking is OPT-IN: when BASE_URL or MODEL is unset, ``is_enabled()`` returns
False and callers keep coarse-retrieval order untouched.  Any transport or
parse failure also degrades to the input order (fail-open), so a search never
breaks because the reranker is down.

Endpoint contract (Cohere Re-rank v2 compatible):

    POST {BASE_URL}/rerank
    {"model": ..., "query": ..., "documents": [...], "top_n": ...}
    -> {"results": [{"index": i, "relevance_score": s}, ...]}
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# ── Configuration (env → config/rerank.conf → nothing) ────────────────


def _load_rerank_conf() -> dict:
    """Load ``config/rerank.conf`` as a fallback for missing env vars."""
    conf = Path(__file__).resolve().parent / "config" / "rerank.conf"
    if not conf.exists():
        return {}
    out = {}
    for line in conf.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip()
    return out


_RERANK_CONF = _load_rerank_conf()


def _rerank_env(name: str, default: str = "") -> str:
    if name in os.environ:
        return os.environ[name]
    if name in _RERANK_CONF:
        return _RERANK_CONF[name]
    return default


BASE_URL = _rerank_env("ASTRA_RERANK_BASE_URL", "").rstrip("/")
API_KEY = _rerank_env("ASTRA_RERANK_API_KEY", "")
MODEL = _rerank_env("ASTRA_RERANK_MODEL", "")
TIMEOUT = float(_rerank_env("ASTRA_RERANK_TIMEOUT", "10"))


def is_enabled() -> bool:
    """True when a rerank endpoint and model are configured."""
    return bool(BASE_URL and MODEL)


def rerank(query: str, documents: list[str], top_n: int | None = None,
           max_retries: int = 2) -> list[dict] | None:
    """Score ``documents`` against ``query`` with a joint-pass reranker.

    Returns a list of ``{"index": int, "relevance_score": float}`` sorted by
    descending score (truncated to ``top_n`` when given), or ``None`` when
    disabled or when every attempt failed — callers treat ``None`` as
    "keep your own order".
    """
    if not is_enabled() or not documents:
        return None

    payload_dict = {"model": MODEL, "query": query, "documents": documents}
    if top_n:
        payload_dict["top_n"] = top_n
    payload = json.dumps(payload_dict).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    url = f"{BASE_URL}/rerank"
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                body = json.loads(resp.read())
            results = body.get("results")
            if not isinstance(results, list) or not results:
                return None
            out = []
            for r in results:
                if (isinstance(r, dict) and isinstance(r.get("index"), int)
                        and isinstance(r.get("relevance_score"), (int, float))):
                    out.append({"index": r["index"],
                                "relevance_score": float(r["relevance_score"])})
            out.sort(key=lambda x: x["relevance_score"], reverse=True)
            return out[:top_n] if top_n else out
        except (urllib.error.URLError, TimeoutError, OSError,
                json.JSONDecodeError, ValueError) as e:
            last_err = e
            if attempt < max_retries:
                time.sleep(0.5 * (2 ** attempt))  # exponential backoff

    print(f"[rerank_client] rerank unavailable, keeping coarse order: {last_err}",
          file=sys.stderr)
    return None
