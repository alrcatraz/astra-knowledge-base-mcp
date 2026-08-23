---
name: astra-kb
description: "Astra Knowledge Base MCP server — tool reference, search strategy selection, chunking guide, and architecture documentation reference"
metadata:
  hermes:
    tags: [knowledge-base, mcp, kb-search, sag, rag, graphrag, vector-search, chunking]
platforms: [linux]
triggers:
  - astra kb
  - knowledge base search
  - kb add
  - kb search
  - kb stats
  - kb import file
  - sag search
  - sag extraction
  - rag architecture
  - graphrag
  - knowledge base design
  - embedding infrastructure
  - retrieval augmented generation
  - knowledge base planning
  - choose between RAG and GraphRAG
  - chunking strategy
  - document chunking
  - markdown heading splitting
  - postgresql vector search
---

# Astra Knowledge Base — Agent Guide

This skill teaches Hermes how to use the Astra Knowledge Base MCP server
for storing, searching, and managing knowledge.

For **architecture decisions** (RAG vs GraphRAG vs SAG, chunking strategies,
embedding infrastructure, PostgreSQL vector index selection), see the
project's [architecture guide](../docs/architecture-guide.md).

---

## Tools Overview

| Tool | Purpose |
|------|---------|
| `kb_add` | Add text content (auto-chunked + embedded + SAG extracted) |
| `kb_search` | Search across KBs (hybrid/fts/vector/sag_fast/sag_precise) |
| `kb_import_file` | Import PDF/DOCX/PPTX/HTML via MarkItDown |
| `kb_extract` | Manual SAG extraction (auto-extract runs on `kb_add` anyway) |
| `kb_rechunk` | Re-chunk existing content with a new strategy |
| `kb_stats` | Get KB statistics |
| `kb_search_by_tags` | Search by tag overlap |
| `kb_export` / `kb_import_jsonl` | Cross-instance data migration |

---

## Search Strategy Selection

| Strategy | When to use |
|----------|-------------|
| `hybrid` (default) | General purpose — combines FTS + vector |
| `fts` | Exact keyword match, code, config, proper names |
| `vector` | Semantic similarity, paraphrased queries |
| `sag_fast` | Direct event-vector query (fast, SAG-aware) |
| `sag_precise` | Multi-hop / entity-driven retrieval (slower but richer) |

Rule of thumb: use `hybrid` first. If results are too broad, try `sag_precise`.
If you need exact string match, use `fts`.

---

## KB Naming Convention

Knowledge bases are organised by **domain**, not by source type:

| Domain | KB name | Content |
|--------|---------|---------|
| Operations / SRE | `sre_operations` | Postmortems, root cause analysis |
| Agent config | `agent_config` | MCP config, ports, tool quirks |
| Reference | `reference` | Format tables, quick reference |
| Networking | `networking` | Research reports, config notes |
| Service management | `service_management` | Health check logs |
| Linux administration | `linux_admin` | System admin, commands |

**Design principles:**
- **Domain-based, not book-based** — one KB per subject area, not one per source.
- **Tags mark provenance** — use tags to distinguish sources within a domain KB.
- **Search scope precision** — querying `linux_admin` won't return networking results.

---

## Chunking Strategies

| Strategy | Use for |
|----------|---------|
| `recursive` (default) | General text, paragraphs |
| `heading-anchor` | Markdown docs with `#` headings |
| `semantic` | Long text without headings (uses embedding API) |

Pass `chunker='heading-anchor'` to `kb_add` or `kb_import_file` for
structured Markdown content.

See the [architecture guide](../docs/architecture-guide.md) for full
chunking strategy selection logic and implementation details.

---

## Pitfalls

## 生产部署/后端（父 NUC10 PG 模式实战，2026-08-16）

astra-kb MCP 现在是 **PostgreSQL 唯一后端**（SQLite 已移除）；PG 模式**不会自动建表**——这是最易踩的坑。从「认证失败」到「全链路打通」共 4 个独立故障：

### 1. PG 认证（`fe_sendauth: no password supplied`）
- DSN 密码取不到（secret 文件属主错，见下）→ `no password supplied`
- 认证走默认 peer/ident 会失败（进程用户≠postgres）
- **修复**：`CREATE ROLE astra LOGIN PASSWORD '<pw>';` + `GRANT ALL ON DATABASE <db> TO astra;` + pg_hba 顶部 `host <db> astra 127.0.0.1/32 md5` + reload + `GRANT CREATE, USAGE ON SCHEMA public`（PG15+ 非 owner 默认不能在 public 建对象）

### 2. secret 文件属主
secret 在 sudo 上下文创建 → 属主 root → 运行用户 `$(cat)` 静默失败（空）→ DSN 无密码。
- **修复**：`sudo chown <user>:<user> <file>` + `chmod 600`

### 3. PG 模式不自动建表（`relation "kb_registry" does not exist`）
`db.py` 建表**仅 sqlite 模式**；pg_backend 假设表已存在。
- **手动建全局 `kb_registry`**（name text PK / description text / enabled bool NOT NULL DEFAULT false / created_at / updated_at timestamptz DEFAULT now()）+ GRANT
- **pgvector 已内置**（PG18 无需装）：`CREATE EXTENSION IF NOT EXISTS vector` 报已存在 = 正常
- 每 KB 独立 schema `kb_<name>` + chunks 表由 `kb_create` **自动**建（GIN FTS + HNSW vector 索引）

### 4. API 语义（易误判为 bug）
- **`kb_add` 参数名是 `kb`**（非 `kb_name`）——错则 `'kb' is a required property`
- **新 KB 默认 `enabled=false`**，`kb_search` 只搜 enabled=true → 新建后必先 `kb_enable` 才搜得到
- 测试数据用完 `kb_delete` 清理

### e2e 最小闭环（实测有效）
`kb_create(test_kb)` → `kb_add(kb=...)` → `kb_list`（confirm enabled=false）→ `kb_enable(test_kb)` → `kb_search(q)`（命中返回 score）→ `kb_delete(test_kb)`

### astra_kb memory provider 接入 Hermes 的三个坑（2026-08-23 实测）
用 `plugins/memory/astra_kb` 作 Hermes memory provider，`sync_turn` 写库 + `kb_mem_search` 语义召回要同时满足 3 个条件：

1. **psycopg2 缺失 → `No module named 'psycopg2'`**。Hermes 系统 python 通常没有 psycopg2，而 `pg_backend.get_conn()` 默认 `import psycopg2`。修复：`get_conn()` 做 **psycopg2 → pg8000 双驱动 fallback**（pg8000 纯 Python、TCP-only，`host=/run/postgresql` socket DSN 要转 `127.0.0.1`）。pg_backend 用标准 DB-API 元组行访问，pg8000 兼容。

2. **KB 名含连字符 → `42601 syntax error at or near "-"`**。`schema = f"kb_{name}"` 直接拼；`astra-kb` 默认 kb_name 带连字符就炸。修复：新增 `_schema_for(name)` 单点净化（`re.sub(r"[^a-z0-9_]+","_",name.lower())`），**create/add/search/delete 全部走它**，别只修 create。psycopg2 版同样会有此 bug（只是从没经默认名建库踩到）。

3. **embed env 缺失 → sink 无向量、召回空**。`embed_client` 顶层读 `ASTRA_EMBED_BASE_URL/MODEL/DIM/API_KEY`；Hermes 进程无这些 → `embed_batch` 静默失败 → chunk.embed_vec 全 NULL → vector 召回 0。**修复（2026-08-23）**：`embed_client` 加了<repo>/config/embed.conf 加载层（env 未设时回退读它），ASTRA_EMBED_BASE_URL/MODEL/DIM 写进该文件即可，**Hermes 进程无需注入 env**。优先级 env > embed.conf > 默认。**MODEL 用 AI Gate combo 名 `embedding`，不是底层具体模型**（siliconflow-cn/Qwen/...）。同理 `pg_backend` 的 SAG LLM → <repo>/config/llm.conf，MODEL 用 combo `auto/best-free`（内置 auto 路由里"最佳免费"，实测稳定路由到 mistral-large-latest，适合需 JSON 一致性的 SAG 抽取）；不用单写 `auto`/`main`（main 不是 free）/`cheap`（动态轮换不稳定）/`free`（不存在）。

**验证顺序**：先 `create_kb` 建 `kb_<safe>` → 查 chunks 有向量 → 再 `search_kbs_vector` 回 1+ 条。缺向量=embed env 问题；SQL 报错=identifier 问题。



1. **`kb_add` content is auto-SAG-extracted** — no need to call `kb_extract` separately.
2. **`kb_rechunk` is destructive** — replaces ALL chunks in the KB. Back up with `kb_export` first.
3. **Tags are text[] arrays** — use `kb_search_by_tags` for tag queries, not `kb_search`.
4. **SAG requires extraction first** — `kb_extract` or `kb_add` (auto-extract). New KBs are empty until content is added.
5. **For architecture decisions**, load the [architecture guide](../docs/architecture-guide.md) — it covers RAG/GraphRAG/SAG comparison, embedding infrastructure design, PG vector index selection, and more.
