# Rerank Stage (astra-kb ≥ v1.4.0, opt-in)

## Background & positioning

arXiv:2609.28290 ("Computation Over Geometry"): meaning identity is computed
in a joint forward pass; cosine over frozen independent embeddings reflects
wording neighbourhoods only. Reranking is therefore an operator layer on top
of retrieval — it does not replace embeddings, it certifies identity.

## Configuration (instance-local, never in git)

- File: `config/rerank.conf` (untracked; template in `config/rerank.example`)
- Endpoint: AI Gate `POST {base}/rerank` (Cohere Re-rank v2 contract),
  e.g. base = the local gateway `/v1` root
- **MODEL must be the full `provider/model` form** (e.g.
  `siliconflow-cn/Qwen/Qwen3-VL-Reranker-8B`). The gateway rejects combo short
  names for rerank: `Invalid rerank model … Use format: provider/model`.
- Localhost endpoints need no API key.

## Usage

- MCP `kb_search` accepts `rerank: true` (default false). When enabled the
  coarse pool widens to max(limit*2, 10) across all five search modes.
- Re-scored results carry a `rerank_score` field. Disabled config or an
  unreachable endpoint degrades fail-open to coarse order (stderr log
  `[rerank_client] rerank unavailable`).
- Programmatic entry: `pg_backend.rerank_results(query, results, limit)`.

## Measured discrimination (2026-09-24, throwaway test KB, Chinese paraphrase twins)

hybrid coarse [0.71 / 0.50 / 0.34] → reranked [0.83 / 0.004 / 0.000] — the
irrelevant candidate collapses to ~0, matching the paper's magnitude for the
same model family.

## Pitfalls

- Each rerank call costs input tokens per document (cloud SiliconFlow behind
  the gate). Keep it per-call opt-in; do not flip a global default.
- The AI-Gate MCP bridge (`/api/mcp/servers/astra-kb-mcp/stream`) lists kb_*
  tools fine but fails their `tools/call` with -32602 (bridge-side schema
  relay issue, predates rerank). Direct SSE (:3003) and in-process imports
  work — when debugging "KB broken", first rule out the bridge.
