# Astra KB rerank stage — operating notes

Mechanism, contract and measured numbers live with the code in `astra-knowledge-base-mcp`
(`rerank_client.py`, `config/rerank.conf`). This file is the operating half only — what to check, and what goes wrong.

## Wiring facts (verified end to end)

- Layering mirrors `embed_client`: env `ASTRA_RERANK_BASE_URL/API_KEY/MODEL/TIMEOUT` → `config/rerank.conf` →
  **disabled**. No shipped endpoint or model defaults.
- Opt-in per call; disabled or unreachable reranker leaves the coarse order untouched (fail-open) — a search never
  breaks because rerank is down.
- The gate's `/v1/rerank` requires the full `provider/model` form; combo short names are rejected
  (`Invalid rerank model … Use format: provider/model`).
- Instance config is untracked: `config/rerank.conf` in the deployed checkout.

## Verification recipe

1. Throwaway `test_*` KB only (never a production KB): one relevant chunk plus two unrelated ones; hybrid search
   with and without rerank.
2. Expect sharp separation after rerank (relevant ≈ 0.8+, irrelevant ≈ 0.00x) against the compressed coarse band
   (0.3–0.7).
3. Negative states must pass through unchanged: unset config → identical order; dead endpoint → identical order
   plus a stderr warning.
4. `kb_delete` the throwaway KB afterwards.

## Pitfalls

- The reranker re-orders what is already in the pool — widen `limit` (pool = `max(limit*2, 10)`) before blaming it
  for recall misses.
- Absence of `rerank_score` means disabled or fail-open, not zero relevance.
- Swapping the rerank model needs no re-embedding — unlike an embedding swap, which needs a full re-index and a
  pgvector column `ALTER`.
