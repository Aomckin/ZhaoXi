# Zhaoxi v1.2.9 收口与瘦身任务书

> 目标：在正式开启 v1.3 Perception System 前，对当前 v1.2.x 主干完成一次完整收口与结构瘦身。
> 原则：**不新增业务语义，不改变用户可见行为，只做版本闭环、历史尾巴清理、装配层拆分与重复结构收敛。**

---

## 0. 背景

当前主干已经接入：

- v1.2.8 Internal Activity
- v1.2.9 Decision Layer

但仍存在以下收口问题：

1. 运行时版本仍停留在 `1.2.7`，与代码实际能力不一致。
2. `build_agent()` 已增长到约 483 行，`cli.py` 已超过 1000 行，后续 v1.3 再接入 Perception / QQ Adapter 会继续放大装配层复杂度。
3. Settings、DataStore、Store、DB path 数量持续增加，接线方式仍偏集中手写。
4. Working Notes、旧 STM 等历史机制已经退出运行时，但部分配置、备份项、兼容路径仍残留。
5. 文档已经形成“旧版本历史 + 当前状态”的体系，但版本号、状态说明、代码行为还需要最后统一。
6. v1.3 将新增新的一级领域，因此 v1.2.9 应作为一个稳定 baseline，而不是带着历史接线债继续往前堆。

本轮目标不是“大重构”，而是：

> **把 v1.2.x 的房间收拾干净，把总配电箱理顺，然后关门挂牌。**

---

# 1. 本轮总目标

完成以下四件事：

### A. 正式完成 v1.2.9 发布闭环

统一：

- `pyproject.toml`
- `src/zhaoxi/__init__.py`
- README
- `docs/current/CURRENT_STATUS.md`
- `docs/current/CODEBASE_STATUS.md`
- v1.2.9 Release / Delivery 文档
- Debug / Health / About 等显示版本的位置

最终所有运行时、文档与包版本均明确显示：

```text
1.2.9
```

不得再出现“代码已到 v1.2.9，但运行时仍是 1.2.7”的状态。

---

### B. 对装配层做一次结构瘦身

当前 `build_agent()` 承担过多依赖构建和运行时接线。

本轮需要在**不改变运行行为**的前提下拆分装配职责，使 `build_agent()` 回归：

> 组合各领域运行时，而不是亲自构建所有领域内部细节。

重点处理：

- Model Provider
- Memory
- Agenda
- Current Cognition
- Archive
- Emoji
- Tool Registry / Tool Packages
- Permission
- Planner
- Workflow
- Proactive
- Decision
- Internal Activity
- Backup / DataStore

---

### C. 清理明确已经退出运行时的历史尾巴

重点检查：

- Working Notes
- legacy Short-Term Memory
- 已删除 Tool
- 已退出的 Emoji 发送 Tool 路径
- 旧 API / 旧兼容入口
- 旧配置字段
- 旧调试字段
- 无引用目录
- 源码目录中的 `__pycache__`
- 已不再使用的 import / helper / compatibility branch

原则：

```text
仍用于读取旧数据 / 恢复 / 迁移
→ 可以保留，但必须明确标为 legacy

已经完全没有用途
→ 删除

是否还需要无法确认
→ 不删除，记录 TODO / Legacy 注释
```

禁止“为了行数好看”删除仍承担兼容职责的代码。

---

### D. 为 v1.3 留出清晰接缝

本轮不实现 Perception System。

但完成后，未来接入应可以自然写成：

```python
agent = assemble_agent(...)

attach_decision_runtime(agent, ...)
attach_proactive_runtime(agent, ...)
attach_internal_activity(agent, ...)
attach_perception_runtime(agent, ...)  # v1.3
```

而不是继续把所有代码塞进 `build_agent()`。

---

# 2. 强约束

本轮必须遵守：

## 2.1 不改变业务行为

不得主动修改：

- CognitiveRouter 路由语义
- Agent Loop 行为
- Memory 写入规则
- Current Cognition Guard
- Decision Layer 判定规则
- Planner 行为
- Workflow 行为
- Permission 行为
- Proactive / Beat 行为
- Internal Activity 调度语义
- Tool capability 选择逻辑
- Emoji Reply DSL

如果重构后测试行为发生变化，应视为回归，而不是“顺便修”。

---

## 2.2 不开发 v1.3 功能

本轮禁止新增：

- Perception
- Observation
- QQ / NapCat
- External Source
- Trust Model
- Social Snapshot
- External Memory Promotion

只允许为其预留清晰装配边界。

---

## 2.3 不以 LOC 为目标

本轮不要求：

- 总行数必须下降
- 文件数必须减少
- Settings 字段必须减少到某个数字

真正的瘦身目标是：

- 职责集中度下降
- 历史残留减少
- 装配逻辑更清晰
- 新领域接入成本降低
- Debug / Backup / Settings 不再容易漏接

---

# 3. Phase 1：版本与发布状态收口

## 3.1 版本号统一

检查并统一：

```text
pyproject.toml
src/zhaoxi/__init__.py
README
CURRENT_STATUS
CODEBASE_STATUS
Web / Desktop About / Health
CLI 启动信息
测试中写死的版本号
```

统一为：

```text
1.2.9
```

---

## 3.2 README 收口

README 仅维护：

- 当前产品定位
- 当前主要能力
- 安装与启动
- 使用方式
- 当前稳定特性
- 简短 Roadmap 指向

历史版本细节继续沉入：

```text
docs/
```

不得重新把 README 写回版本流水账。

---

## 3.3 CURRENT_STATUS 收口

要求：

- 顶部明确写 v1.2.9 已正式发布。
- v1.2.8 / v1.2.9 不再写“尚未发布”。
- 保留历史状态说明，但明确“历史记录不代表当前运行时”。
- 旧测试数字只作为当时记录。
- 当前行为只以当前状态文档和代码为准。

---

## 3.4 新增正式 Release Notes

建议：

```text
docs/v1.2.x/Zhaoxi_v1.2.9_Release_Notes.md
```

内容至少包括：

- Decision Layer
- Internal Activity 正式并入当前稳定版本
- Current Cognition 当前形态
- Action Trace / Budget / Context Debug
- Agenda / Memory / Tool Discovery 当前基线
- 本轮结构瘦身说明
- 已知限制
- 下一阶段：v1.3 Perception System

---

# 4. Phase 2：拆分 build_agent()

## 4.1 当前问题

`build_agent()` 当前同时负责：

- Provider 构建
- Memory 构建
- Agenda 构建
- Current Cognition 构建
- Archive 构建
- Emoji 构建
- Tool Registry
- Tool Package Discovery
- Reflection
- Permission
- Session
- ContextBuilder
- Planner
- Workflow
- Proactive
- Agent 实例
- Decision
- Beat
- Internal Activity
- BackupManager
- CognitiveCoordinator

职责过多。

---

## 4.2 拆分目标

建议建立：

```text
src/zhaoxi/bootstrap/
├── __init__.py
├── models.py
├── knowledge.py
├── tools.py
├── cognition.py
├── proactive.py
├── storage.py
└── runtime.py
```

名称可根据现有风格调整，不要求机械照搬。

推荐职责：

### `models.py`

负责：

- Primary Provider
- Fallback Provider
- ResilientProvider
- Retry / Budget policy 接线

---

### `knowledge.py`

负责：

- MemoryService
- MemoryRetriever
- AgendaService
- CurrentCognitionService
- ArchiveService
- Reflection 依赖

注意：

这里是“知识/状态域装配”，不修改这些领域本身。

---

### `tools.py`

负责：

- ToolRegistry
- builtin tools
- agenda tools
- emoji tool
- Tool Package discovery
- provider tools
- capability flags
- package records
- routing hints

输出一个结构化结果，例如：

```python
ToolRuntime(
    registry=...,
    packages=...,
    package_records=...,
    capability_flags=...,
    routing_hints=...,
    errors=...,
)
```

---

### `cognition.py`

负责：

- ContextBuilder
- Planner
- Workflow
- CognitiveCoordinator
- AutoMemory
- DecisionService
- CurrentCognitionMaintainer

---

### `proactive.py`

负责：

- ProactiveRuntime
- Scheduler
- PolicyState
- Heartbeat
- Beat
- DecisionWorker
- Package proactive sensors
- State signal providers
- Internal Activity

注意：

Perception 不在本轮实现。

---

### `storage.py`

负责：

- SessionStore
- PermissionStore
- BackupManager
- DataStoreSpec 聚合
- Legacy datastore 注册

---

### `runtime.py`

作为最终总装：

```python
def build_agent(settings: Settings) -> ZhaoxiAgent:
    ...
```

`cli.py` 不再承载大段运行时装配。

---

## 4.3 build_agent() 验收要求

不强制具体行数，但建议目标：

```text
build_agent() 主体 <= 250 行
```

更重要的是：

- 高层阅读时可以一眼看出各领域装配顺序。
- 不再出现数百行连续的低层构造细节。
- 后续新增一级领域不需要修改多个随机位置。

---

# 5. Phase 3：DataStore 注册收敛

## 5.1 当前问题

BackupManager 的 DataStoreSpec 目前集中手写。

随着 DB 数量增加：

```text
memory
planner
session
permission
workflow
proactive
reflection
agenda
current_cognition
internal_activity
legacy STM
legacy working notes
decision logs
permission audit
...
```

容易出现：

> 新增 Store 但忘记进入 BackupManager。

---

## 5.2 改造目标

新增统一 datastore registry / builder。

例如：

```python
def build_data_store_specs(settings) -> list[DataStoreSpec]:
    ...
```

或者按领域：

```python
specs = [
    *memory_data_stores(settings),
    *agenda_data_stores(settings),
    *decision_data_stores(settings),
    *proactive_data_stores(settings),
    *legacy_data_stores(settings),
]
```

要求：

- 所有需要备份的数据源集中可审计。
- Legacy 数据源显式标记。
- 不改变现有 BackupManager 行为。
- 不改变现有文件路径。

---

# 6. Phase 4：Legacy / Dead Code 清理

## 6.1 Working Notes

检查：

```text
working_notes_db_path
working-notes.db
相关 Store / Tool / UI / Context 路径
```

如果当前仅用于历史备份：

- 运行时不得读取为 Context。
- 不得继续作为业务能力暴露。
- 配置说明明确标记：

```text
Legacy backup only
```

若某字段只为 BackupManager 服务，可考虑迁移到 legacy storage registry，而不是继续表现为活跃业务配置。

---

## 6.2 Short-Term Memory 旧实现

检查：

```text
short_term_memory_db_path
legacy STM 迁移逻辑
旧 SQLite store
旧文档
旧 Debug 字段
```

当前真实短期状态已经由 Current Cognition 取代。

保留迁移所必须的最小代码。

禁止：

- 旧 STM 再次进入 Context。
- 新代码继续依赖 legacy STM。
- Debug 同时把 Current Cognition 和旧 STM 当作两个活跃系统。

---

## 6.3 Emoji 历史链路

确认：

- `send_emoji` 不再作为 Tool 注册。
- 当前唯一发送链路是 Reply DSL。
- `save_emoji` 保留。
- 历史兼容 renderer 保留仅用于旧会话恢复。
- 删除已经无引用的 send_emoji Tool 残余。

---

## 6.4 Tool / Integration 目录

检查：

```text
src/zhaoxi/tools/integrations/
src/zhaoxi/tools/packages/
```

清除：

- `__pycache__`
- 已迁移后的空目录
- 无引用旧文件
- 重复 wrapper
- 已废弃 import

不要删除：

- 仍被 entry point 动态加载的 Tool Package
- 通过反射 / discover 机制引用的模块

---

## 6.5 Compatibility Branch

搜索：

```text
legacy
deprecated
compat
migration
fallback
TODO
working_notes
short_term_memory
send_emoji
```

对每处做分类：

```text
A. 仍有迁移价值 → 保留并注释退出条件
B. 仍有历史读取价值 → 保留为 read-only compatibility
C. 已完全失效 → 删除
D. 无法确认 → 不动，写明原因
```

---

# 7. Phase 5：Settings 瘦身

本轮不进行 Settings 大重构。

只做：

### 7.1 删除明确无用字段

前提：

- 全仓库确认无引用。
- 不影响旧 `.env` 启动。
- 不影响 Backup / migration。

---

### 7.2 标注 Legacy

历史字段统一在 `.env.example` 和 Settings 中写清楚。

例如：

```python
working_notes_db_path = ...
# Legacy backup only; not runtime context.
```

---

### 7.3 配置区域重新排序

按领域整理：

```text
Model
Reliability
Memory
Agenda
Current Cognition
Decision
Tools
Permission
Planner
Workflow
Reflection
Proactive
Internal Activity
Interface
Desktop
Voice
Legacy
```

不修改环境变量名称。

---

### 7.4 不做嵌套 Settings

暂不改成：

```python
settings.memory.xxx
settings.proactive.xxx
```

避免牵动：

- `.env`
- Web Debug
- 测试
- Tool Package config
- 用户现有配置

---

# 8. Phase 6：cli.py 瘦身

目标：

> `cli.py` 只负责 CLI 交互，不再兼任 Composition Root。

将运行时构建迁移到 bootstrap / runtime。

CLI 保留：

- interactive loop
- `/memory`
- `/plan`
- `/workflow`
- `/permissions`
- `/reflection`
- `/backup`
- `/diagnostics`
- `/capabilities`

如果命令 handler 已明显膨胀，可移动到：

```text
src/zhaoxi/cli_commands/
```

但本轮不是强制要求。

优先级：

```text
build_agent 拆出 cli.py
>
handler 文件拆分
```

---

# 9. Phase 7：测试

## 9.1 必须全量跑现有测试

要求：

```text
现有测试全部通过
```

不能接受：

- “只是重构所以没跑”
- “大部分通过”
- “行为看起来一样”

---

## 9.2 新增结构回归测试

至少覆盖：

### build_agent smoke

验证：

- Agent 能成功构建。
- 核心属性存在。
- Registry 初始化成功。
- Decision / Internal Activity 正确挂载。
- Cognitive Coordinator 正确挂载。

### version consistency

验证：

```text
pyproject version == zhaoxi.__version__
```

### datastore registry

验证关键 Store 均存在：

- memory
- session
- permission
- agenda
- current cognition
- internal activity
- decision logs
- proactive
- workflow
- reflection

Legacy Store 是否存在按当前兼容策略断言。

### no legacy context regression

验证：

- Working Notes 不进入 Context。
- Legacy STM 不进入 Context。
- Current Cognition 仍是唯一近期认知状态来源。

### emoji path

验证：

- `send_emoji` 不在 Tool Registry。
- Reply DSL 仍工作。
- `save_emoji` 仍可用。

---

# 10. Phase 8：人工冒烟测试

至少完成：

### 普通聊天

```text
“今晚有点累。”
```

要求：

- 正常回复。
- Current Cognition / Memory 行为与收口前一致。

---

### Tool 请求

```text
“看看我现在 Life HUD 里有什么。”
```

要求：

- Router / Tool Discovery 不退化。
- Action Trace 正常。

---

### Decision

输入一个明确决策问题。

要求：

- L0 / L1 verdict 仍由 Decision Layer 固定。
- 主回复链不能改写方向。
- Debug 重算可用。

---

### Agenda

新增 / 查询一条日程。

要求：

- Agenda Context 正常。

---

### Permission

执行一个需要确认的写操作。

要求：

- pending confirmation 正常。
- approve / deny 正常。

---

### Proactive / Beat

确认：

- Heartbeat 正常启动。
- Internal Activity 正常 tick。
- 不新增异常主动消息。

---

### 重启恢复

完整退出 Core 后重新启动。

确认：

- Session
- Memory
- Agenda
- Current Cognition
- Permission
- Decision logs
- Internal Activity state

均没有结构性回归。

---

# 11. Phase 9：Debug / Diagnostics 收口

检查维护抽屉和 diagnostics。

确保：

- 版本号正确。
- 不再展示已经退出运行时的 Working Notes。
- “Current Cognition” 命名一致。
- Internal Activity 状态正常。
- Decision Debug 正常。
- Tool Debug 正常。
- Budget / Context Debug 正常。
- Legacy datastore 不误显示为活跃能力。

如有必要增加一个轻量：

```text
Runtime Components
```

仅展示：

```text
Memory: ready
Agenda: ready
Current Cognition: ready
Decision: ready
Proactive: ready
Internal Activity: ready
```

不是必做 UI 功能，不要扩大范围。

---

# 12. 文档更新

完成后更新：

```text
README.md
docs/current/CURRENT_STATUS.md
docs/current/CODEBASE_STATUS.md
docs/v1.2.x/Zhaoxi_v1.2.9_Release_Notes.md
```

Release Notes 增加：

## Structural Cleanup

说明：

- `build_agent()` 已拆分。
- Composition Root 已从 CLI 解耦。
- DataStore 注册集中。
- Legacy runtime paths 已清理。
- Settings 仅做轻量整理，无环境变量破坏性变更。
- 用户可见行为不变。

---

# 13. 明确不做

本轮不做：

- Perception System
- Observation 模型
- QQ
- NapCat
- WebSocket
- Social Snapshot
- 外部事实可信度
- External Memory
- Memory Trust 重构
- Current Cognition 外部证据
- 新 Tool
- 新 UI 大功能
- Planner 重构
- CognitiveRouter 重写
- Memory 大重构
- 数据库合并
- Settings 嵌套化
- 为降低 LOC 而压缩代码

---

# 14. 最终验收标准

满足以下条件才算 v1.2.9 正式收口：

- [ ] 运行时版本正式为 `1.2.9`
- [ ] README / STATUS / package version 一致
- [ ] v1.2.8 / v1.2.9 不再标记“尚未发布”
- [ ] `build_agent()` 已显著拆分
- [ ] `cli.py` 不再承担主要 Composition Root
- [ ] DataStore 注册集中可审计
- [ ] Working Notes 不再具有任何活跃运行时职责
- [ ] legacy STM 不再进入 Context
- [ ] Emoji 发送链只保留 Reply DSL
- [ ] 明确 dead code / `__pycache__` 已清理
- [ ] Settings 中 legacy 字段边界明确
- [ ] 现有自动测试全绿
- [ ] 新增结构回归测试通过
- [ ] 普通聊天 / Tool / Decision / Agenda / Permission / Proactive 冒烟通过
- [ ] 重启恢复正常
- [ ] 无用户可见行为改变
- [ ] 无 v1.3 Perception 功能提前混入
- [ ] 最终形成可直接供 v1.3 使用的稳定 baseline

---

# 15. 收口后的预期骨架

```text
Zhaoxi
│
├── bootstrap/
│   ├── models
│   ├── knowledge
│   ├── tools
│   ├── cognition
│   ├── proactive
│   ├── storage
│   └── runtime
│
├── core/
├── cognitive/
├── memory/
├── agenda/
├── current_cognition/
├── decision/
├── proactive/
├── internal_activity/
├── planner/
├── workflow/
├── permission/
├── tools/
├── interfaces/
├── web/
└── desktop/
```

未来 v1.3 可以自然新增：

```text
perception/
adapters/
```

而不再继续膨胀现有 Agent / CLI。

---

# 16. 一句话任务定义

> **把 v1.2.x 从“功能已经做完”收束到“结构也足够干净，可以放心长出下一层”。**

完成本任务后，再正式开启：

```text
Zhaoxi v1.3
Perception System
```
