# astra-knowledge-base-mcp — 开发路线图

> 长期规划文档，指引项目技术演进方向。
> 参考：[SAG: SQL-Retrieval Augmented Generation](https://arxiv.org/abs/2606.15971) (MIT License, Zleap-AI)

---

## 现状 (2026-07)

```
PostgreSQL 16.14 + pgvector 0.8.2
Embedding: 通用 OpenAI 兼容接口（目前通过 SiliconFlow 调用 Qwen3-Embedding-8B，1024d）
检索: FTS (tsvector) + Vector (cosine) 混合搜索，简单 alpha 加权融合
分块: 递归段落/句子分割，固定窗口 1000/200
Ingest: kb_add → TextIngestor → RecursiveChunker → embed → PG chunks
```

**核心弱点：**
- 无跨 chunk 关联推理能力（纯语义相似度，多跳查询几乎不可用）
- 分块策略过于粗糙（无语义边界感知）
- 嵌入 pipeline 无缓存、batch 实现是假的（逐条调用）
- 无重试/退避，API 超时直接返回 None

---

## 架构演进路线

### Phase 0 — 向量化基础设施加固（当前 → 1 周）

**目标：** 把嵌入管道从"能用"变成"可靠、可观、provider-agnostic"。

| # | 任务 | 说明 |
|---|------|------|
| 0.1 | **嵌入缓存** | SQLite-backed content-addressable cache。同段 text 不重复调 API。重启不丢失 |
| 0.2 | **批量嵌入** | `embed_batch` 一次 API 调用处理多条文本（OpenAI-compatible 原生支持） |
| 0.3 | **重试 + 退避** | 指数退避包裹所有 API 调用（429/5xx 恢复，最多 3 次） |
| 0.4 | **Provider-agnostic 设计** | 删掉 `local`/`siliconflow` 硬编码分支。所有 provider 通过 `BASE_URL` + `API_KEY` + `MODEL` 三个环境变量配置。兼容：llama.cpp 本地 / SiliconFlow / OpenAI / DeepSeek / 任何 OpenAI-compatible 端点 |
| 0.5 | **PG backend 嵌入调用适配** | `pg_backend.py` 中使用的新 client 接口适配（`embed_batch` 替换旧 `embed_text`） |

**边界：** 不改变搜索接口，不只加固 embed 层。

---

### Phase 1 — SAG 集成（接 Phase 0 → +1 周）

**目标：** 在现有 chunks 基础上叠加 event/entity 索引，新增 SAG 检索路径。

| # | 任务 | 说明 | 参考（论文 §3） |
|---|------|------|-----------------|
| 1.1 | **PG Schema 扩展** | per-KB: `events`, `entities`, `event_entities` 表 + HNSW 索引 | §3.2 Event-Entity Index |
| 1.2 | **Event/Entity 提取** | `kb_extract` 工具。LLM 对每个 chunk 提取 1 event + N entities（11 种类型） | §3.2 |
| 1.3 | **SAG Fast 检索** | `kb_search(strategy='sag_fast')`：直接 event 向量检索 → 映射回 chunks | §3.3 Path B |
| 1.4 | **SAG Precise 检索** | LLM 提取查询 entity → entity 向量查询 → SQL JOIN 种子召回 → 超边扩展 → 合并去重 | §3.3–3.4 |
| 1.5 | **双路并行** | SAG 路径与现有 FTS/向量/Hybrid 路径共存，`kb_search` 统一接口 | §3.4 Dual-path |

**设计原则：** SAG 是**增量叠加**，不是替代。现有 `hybrid`/`fts`/`vector` 模式继续可用。新增的 `sag_fast`/`sag_precise` 是额外选择。

**许可证：** SAG 论文及参考实现均为 MIT 许可。算法自实现，代码中标注论文引用。

---

### Phase 2 — 分块策略升级（Phase 1 → +3 天）

**目标：** 从固定窗口分块升级到语义感知分块。

| # | 任务 | 说明 |
|---|------|------|
| 2.1 | **语义分块器** | 基于 embedding 相似度检测主题边界（cosine 断点检测） |
| 2.2 | **段落锚定** | Markdown 标题层级感知，按 `#/##/###` 分割 |
| 2.3 | **混合分块策略** | 配置化：recursive / semantic / heading-based，可 per-KB 指定 |
| 2.4 | **重分块** | 已有 chunk 可重新分块并重建向量，保留 source 链接 |

---

### Phase 3 — KB 生态系统（Phase 2 → +1 周）

**目标：** 从"存文本搜文本"扩展到知识管理平台。

| # | 任务 | 说明 |
|---|------|------|
| 3.1 | **多源导入** | 文件（PDF/DOCX/HTML）-> MarkItDown 归一化 -> 入 KB |
| 3.2 | **Source 追踪** | 每个 chunk 记录原始文档/URL/导入时间，支持溯源 |
| 3.3 | **标签体系升级** | 标签继承（source -> chunk）、标签搜索、自动标签（LLM 建议） |
| 3.4 | **Import/Export** | JSONL 格式导入导出，支持跨实例迁移 |
| 3.5 | **搜索可观测性** | 每次搜索记录 query/chunks/得分/策略，用于质量分析 |

---

### Phase 4 — Agent 集成增强（持续）

**目标：** Knowledge Base 成为 Hermes Agent 的"长时记忆层"。

| # | 任务 | 说明 |
|---|------|------|
| 4.1 | **MCP 工具扩展** | `kb_stats`（KB 统计）、`kb_diff`（chunk 变更追踪） |
| 4.2 | **自动提取** | `kb_add` 后自动触发异步 `kb_extract`（不再手动） |
| 4.3 | **增量索引** | SAG 的增量特性——新 chunk 触发局部 event 提取，不重建全局 |
| 4.4 | **Hermes Skill** | 写一个 `astra-kb` skill，指导 Hermes 如何高效使用 KB MCP 工具 |

---

### 远期（探索性）

| # | 项目 | 触发条件 |
|---|------|---------|
| F.1 | 版本化 agent 记忆 / 事件覆盖更新 | SAG 论文列为未来工作。需要 override/过期/历史回溯时 |
| F.2 | 全局社区摘要（GraphRAG 风格） | KB 膨胀到万级文档且有全局问答需求 |
| F.3 | 多模态索引（图片 -> 描述 -> 可检索） | 需要索引图片/音频时 |
| F.4 | Web UI / 图谱可视化 | 需要可视化知识图谱时 |

---

## 架构决策记录

### ADR-1: 后端策略 — PG only

- **结论**: 仅 PostgreSQL 16+ 作为生产后端。SQLite 后端已废弃，不再维护
- **理由**: PG + pgvector 是完整的向量+关系数据库，SQLite 引入的 dev/prod 不一致问题大于其简化价值
- **影响**: 删除 `kb_manager.py`（SQLite backend）和 `db.py`（SQLite 连接管理），保留 SQLite 仅用于嵌入缓存（`embed_cache.db`）

### ADR-2: 嵌入 API — Provider-agnostic

- **结论**: 所有嵌入提供方通过统一环境变量配置，无硬编码 provider 名称
- **接口**: `ASTRA_EMBED_BASE_URL` + `ASTRA_EMBED_API_KEY` + `ASTRA_EMBED_MODEL` + `ASTRA_EMBED_DIM`
- **兼容性**: 任何 OpenAI-compatible `/v1/embeddings` 端点——llama.cpp 本地 / SiliconFlow / OpenAI / DeepSeek / 其他
- **影响**: 删掉 `ASTRA_EMBED_BACKEND=local|siliconflow` 选择器，改为直接 URL 驱动

### ADR-3: 搜索策略 — 自实现 SAG

- **结论**: 自实现 SAG 算法，`zleap-sag` 包仅作参考验证
- **理由**: 算法自实现代码可控、依赖少（对比 zleap-sag 引入 46 个包）、数据流完全自主
- **许可**: 论文及参考实现均为 MIT，代码/文档中标注引用

### ADR-4: 搜索策略——共存

- **结论**: 所有检索路径（fts/vector/hybrid/sag_fast/sag_precise）通过统一 `kb_search(search_mode=...)` 接口暴露
- **理由**: 不同查询适合不同策略，用户/Agent 按需选择。新增路径不破坏现有行为

---

## 技术栈依赖

| 层 | 当前 | 目标 |
|----|------|------|
| 数据库 | PostgreSQL 16.14 + pgvector | PostgreSQL 16.14+ + pgvector |
| 嵌入 | SiliconFlow API (urllib, 无缓存) | 任意 OpenAI-compatible 端点 (urllib+缓存+batch+重试) |
| LLM 调用 | Hermes Agent 上下文 | 内嵌 OpenAI-compatible client 用于 SAG 提取 |
| MCP 框架 | mcp >=1.27.2 | 保持 mcp 最新 |
| Python | >=3.11, uv 管理 | >=3.11, uv 管理 |

---

## 各阶段外部引用

- **SAG 论文**: https://arxiv.org/abs/2606.15971 — 检索架构基础（MIT）
- **Zleap-AI SAG 实现**: https://github.com/Zleap-AI/SAG — 参考实现（MIT）
- **Microsoft MarkItDown**: 文档归一化参考
- **各嵌入提供商**: 通过统一 OpenAI-compatible 接口接入
