# 朝汐 ZhaoXi 代码现状与交接说明

> **当前开发基线：v0.3.2「Memory Lifecycle」**。项目已经形成“认知路由 → 对话/工具/规划执行 → 自动记忆”的主链路，并在 v0.3.2 为长期记忆加入重要性、相关性、冷热分层、归档、固定、再激活、整合和来源证据。当前仍是本地单用户 CLI Agent；外部数据源、权限审计、持久化计划和图形界面尚未实现。

本文是后续开发的首要交接入口。版本、架构、数据结构、测试数量或关键限制发生变化时，应在同一提交中更新本文。

## 当前能力

- Python 3.11+、异步运行时和 OpenAI-compatible Provider；通过环境变量可接入兼容 Chat Completions 的模型服务。
- `Conversation`、`ContextBuilder`、人格提示词和会话管理组成基础对话上下文。
- `CognitiveRouter` 将输入分为 `DIRECT`、`TOOL`、`PLAN`：直接对话不携带工具 schema，工具任务进入 Agent 循环，复杂任务进入 Planner。
- `ZhaoxiAgent` 支持多轮工具调用；内置 echo、计算器、当前时间和记忆工具，工具由统一 Registry 注册。
- Planner 支持 Goal / Plan / Step、线性执行、重试、fallback、版本化 replan、等待用户、恢复、取消和 trace；当前计划仅保存在进程内。
- SQLite 长期记忆支持跨会话检索和上下文注入，以及显式记住、搜索、更新、忘记、归档、再激活、固定和整合。
- `AutoMemory` 在每轮回复后独立判断 `CREATE / UPDATE / MERGE / CONFLICT / REACTIVATE / ARCHIVE / FORGET / CONSOLIDATE / IGNORE`；稳定身份和偏好另有保守的确定性兜底。
- 自动记忆不再依赖强制 `tool_choice`，使用一次普通 JSON 响应，避免部分兼容服务因工具参数组合持续返回 HTTP 400。
- 可重新查询的工具结果默认不沉淀为长期记忆；显式记忆、拒绝记忆和忘记请求优先于普通自动判断。

## v0.3.2 记忆生命周期

- 数据库 schema 为 v2；旧 v1 数据库启动时通过增量列迁移升级，保留既有记录。
- 记忆元数据包含 `importance`、`relevance`、`pinned`、`access_count`、来源消息/名称/证据、是否可重新查询，以及有效期。
- 生命周期状态包含 `ACTIVE`、`COLD`、`ARCHIVED`、`FORGOTTEN`，并保留冲突处理使用的 `SUPERSEDED`。
- 高重要、低相关记忆进入 `COLD`，不会被自动忘记；低重要、低相关记忆先冷却，达到等待天数后归档。
- 普通相关检索命中 `COLD` 记忆时会将其恢复为 `ACTIVE`，同时提升相关性并累计访问次数。
- 显式历史检索可读取冷却、归档和已替代记忆，但不会触发再激活。
- `pinned` 记忆不会被自动归档，但用户仍可显式忘记。
- 整合会生成一条语义记忆并记录证据引用，旧的非固定细节转为归档。
- 生命周期维护当前由检索过程或 CLI 命令 `/memory maintain` 触发，没有后台定时任务。

## 明确尚未完成

- 尚无 Life HUD、GitHub、日历、文件系统等真实业务工具；来源权威边界只有可扩展接口，没有在线集成。
- Planner Store 是内存实现，进程退出后不能恢复计划、暂停点或 trace。
- 尚未实现 v0.4 Permission Layer：授权、审批、审计、撤销和危险动作防护仍是后续重点。
- 尚无 Workflow、主动唤醒/定时执行、外部 UI、语音、RAG 或向量数据库。
- “忘记”是软状态迁移，不是物理清除；尚无带审计的硬删除流程。
- 自动记忆依赖模型语义判断，确定性兜底只覆盖有限的稳定身份与偏好表达。
- 测试通过 Fake Provider 或 Mock Transport 隔离外部服务；未用真实 API 凭据运行自动化集成测试。

## 技术结构

```text
src/zhaoxi/
  core/          Agent、上下文、对话与消息模型
  cognitive/     认知协调器、路由和自动记忆决策
  memory/        领域模型、SQLite、仓储、检索、服务和生命周期策略
  planner/       Goal/Plan/Step、运行时、Store 和 Trace
  models/        Provider 抽象、OpenAI-compatible 实现和响应类型
  tools/         工具基类、Registry 和内置工具
  config/        环境变量与设置
  personality/   人格提示词
  session/       会话组合
  cli.py         命令行入口
tests/
  cognitive/ config/ core/ integration/ memory/
  models/ planner/ session/ tools/
docs/            版本任务书与本交接文档
```

## 主要调用链

普通对话：

```text
User
  -> CognitiveCoordinator / CognitiveRouter
  -> DIRECT: run_direct
     TOOL: ZhaoxiAgent.run
     PLAN: PlannerRuntime
  -> 最终回复
  -> AutoMemory.process
  -> MemoryService
  -> SQLiteMemoryRepository
```

记忆检索与注入：

```text
ContextBuilder / MemoryRetriever
  -> MemoryService.search
  -> 检索 ACTIVE + COLD 候选
  -> 衰减、必要时再激活、更新访问元数据
  -> 相关记忆注入模型上下文
```

生命周期维护与整合：

```text
/memory maintain
  -> MemoryService.maintain
  -> MemoryLifecyclePolicy.decay / classify
  -> 保存状态与相关性

相关记忆 ID
  -> MemoryService.consolidate
  -> 新语义记忆 + evidence references
  -> 旧的非 pinned 细节转为 ARCHIVED
```

## CLI 与记忆操作

- `/plan <目标>`：创建并执行规划任务。
- `/tools`：查看当前注册工具。
- `/memory maintain`：执行一次生命周期维护。
- `/memory history <query>`：检索历史状态记忆且不自动再激活。
- `/clear`：清空当前会话；不会物理删除长期记忆。
- `/exit`：退出 CLI。

代码侧记忆工具包括 `remember_memory`、`search_memory`、`update_memory`、`forget_memory`、`archive_memory`、`reactivate_memory`、`pin_memory` 和 `consolidate_memories`。

## 数据与兼容性

- 默认数据库为 `.zhaoxi/memory.db`，目录已由 Git 忽略；不要将真实用户记忆提交进仓库。
- schema 版本记录在数据库中，v1 → v2 使用 `ALTER TABLE` 增量迁移；新增字段必须继续提供兼容默认值和迁移测试。
- 正常忘记、归档、替代均保留记录；查询时必须明确需要包含的状态，避免把历史数据误注入普通上下文。
- 测试必须使用临时数据库，不得覆盖工作目录中的真实 `.zhaoxi` 数据。
- `.env` 已忽略；任何日志、文档、测试快照和提交中都不得出现真实 API Key。

## 关键配置

模型、日志、上下文、记忆、Planner 和 Cognitive Router 的常规设置均从环境变量读取。v0.3.2 新增生命周期参数：

```dotenv
ZHAOXI_MEMORY_IMPORTANCE_KEEP_THRESHOLD=0.75
ZHAOXI_MEMORY_RELEVANCE_ACTIVE_THRESHOLD=0.60
ZHAOXI_MEMORY_IMPORTANCE_FORGET_THRESHOLD=0.30
ZHAOXI_MEMORY_RELEVANCE_FORGET_THRESHOLD=0.20
ZHAOXI_MEMORY_RELEVANCE_DECAY_PER_DAY=0.01
ZHAOXI_MEMORY_RELEVANCE_ACCESS_BOOST=0.15
ZHAOXI_MEMORY_COLD_ARCHIVE_AFTER_DAYS=30
```

默认值和类型以 `src/zhaoxi/config/settings.py` 为准；新增配置时同步更新 `.env.example` 和配置测试。

## 启动与验证

```powershell
python main.py
\.venv\Scripts\python.exe -m pytest
\.venv\Scripts\python.exe -m compileall -q src tests
git diff --check
```

当前自动化测试基线：**55 项通过**。开发时至少运行与改动相关的测试；提交版本切片前运行全量测试、编译检查和 `git diff --check`。

## 接手建议

1. 先阅读本文件、当前版本任务书和最新 Git 提交，再执行 `git status --short --branch` 确认用户工作区状态。
2. 修改记忆状态机时同时检查普通检索、历史检索、上下文注入和 SQLite 迁移，避免归档数据被意外激活或注入。
3. Provider 兼容问题优先用 Mock Transport 固化请求体与错误响应，不要用真实凭据作为回归测试前提。
4. 工具返回的数据先判断是否可重新查询；可重新查询事实默认不进入长期记忆。
5. 每个版本提交都同步更新本文顶部基线、已完成能力、明确限制、验证数量和提交信息。

## Git 基线

- 当前开发分支：`v0.3.2`
- v0.3.1 基线：`9f4424c feat: integrate v0.3.1 cognitive routing and memory`
- v0.3 Planner：`613859d feat: implement v0.3 planner`
- v0.2 Memory：`b1d0bcc feat: implement v0.2 persistent memory`
- 初始版本：`889f9d5 chore: initialize Zhaoxi project`

本节的“当前开发分支”和提交基线应在后续版本交接时更新。
