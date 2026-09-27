# Astra KB — Hermes 记忆插件（memory provider）

`plugins/memory/astra_kb/`（本仓库内，部署为 `~/.hermes/plugins/astra_kb/`，
生产副本经 symlink 指向 `~/.astra/repos/...` 的即生效）。

## 生命周期契约（v0.2.0 起）

- **必须继承 `agent.memory_provider.MemoryProvider` ABC**。Hermes MemoryManager
  会无条件调用可选 hook（`on_session_end`、`on_session_switch`…），ABC 提供空默认
  实现；鸭子类型子类会在每个会话边界刷 AttributeError。import 失败时以空类兜底
  （standalone 测试环境无 Hermes core）。
- **sink 时机 = 会话边界，不是每 turn**。`sync_turn` 只把 turn 追加进 `self._pending`
  缓冲；`on_session_end` / `on_session_switch`（先 flush 再 rebind session_id）/
  `shutdown` 各调一次 `_sink()` → 单次批量 `add_chunks`。避免每 turn 一次嵌入 API
  往返 + 每 turn 静默吞错。
- **`initialize()` 对死库 fail-closed**：PG 驱动缺失或 KB ensure 失败 →
  `_ready=False` + WARNING 日志点名修复路径。绝不「假就绪」——那会让每个 turn
  静默失败而系统提示声称 active（曾实际发生：venv 无任何 PG 驱动，sink 全链路
  空转一个多月无人察觉）。
- 配置键在 `config.yaml` `plugins.astra-kb:`（kb_name/project_root/auto_create_kb）；
  provider 名必须等于目录名 `astra_kb`（Hermes 按目录名解析）。

## Python 依赖走 PM 轨道（勿手动 pip）

- 驱动声明在插件 `plugin.yaml` 的 `python_dependencies:`（如
  `"pg8000>=1.30,<2"`）。PM 在 enable/更新时把 core+extras+全部启用插件的并集
  解析进新 environment generation，原子发布；失败保留旧选择。
- 触发准备：`hermes plugins enable <name>`，或对 memory provider 直接
  `prepare_memory_provider_dependencies('astra_kb')`（`hermes_cli.memory_setup`，
  桌面端/CLI 设置向导走的同一函数）。返回 `restart_required` 属正常——激活发生在
  进程启动时，重启 gateway/serve 后生效。
- **坑：打包 install 树缺 `pm/uv.lock`** → `hermes pm doctor` / PM 任何入口抛
  `FileNotFoundError: .../workspace/pm/uv.lock`（`pm/runtime.py::_inputs` 要读它）。
  上游 zip payload 漏了这个文件；从源码树复制同一份即可（内容逐字节相同）：
  `cp ~/.hermes/hermes-agent/pm/uv.lock <install>/environments/*/workspace/pm/`。
  每次 `hermes update` 后若 PM 报缺 lock，优先怀疑此文件又没带上。
- 验证生成环境含驱动：facts.json（install state dir）→ `packages.venv.environment`
  → `<env>/lib/python*/site-packages/pg8000`。

## 端到端验收（改完必做，勿只看代码）

在新选中的 generation workspace + venv 下：
`load_memory_provider('astra_kb')` → `initialize(sid)` 断言 `_ready` →
`sync_turn(marker,…)` → `on_session_end([])` → `handle_tool_call('kb_mem_search',…)`
命中 marker → 删测试行（`kb_<schema>.chunks WHERE source='session:<sid>'`）。
注意测试脚本 cwd 别落在 KB repo 上，否则 `plugins.memory` 会被本地同名包遮蔽
（ImportError: load_memory_provider）。

## 已知缺陷：symlinked skill 对 skill_manage 不可见

本技能目录是指向 KB repo 开发副本的 symlink。Hermes `_find_skill()` 用不带
follow-symlinks 的 `rglob("SKILL.md")` 枚举，Python ≥3.13 默认不跟随 symlink 目录——
于是 `astra-kb`、`knowledge-base-interop` 等 symlinked skill 在 `skills_list` 里可见
（扫描器会解析），但 `skill_manage(patch)` 报 "not found in active profile"。
绕过：直接对真实路径用 `patch` 工具编辑（改动仍落在 git 仓库内，照常 commit）。
