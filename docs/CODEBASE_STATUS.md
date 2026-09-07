# 朝汐 ZhaoXi 代码现状与交接说明

> **当前开发分支：`v1.1.2`，运行时版本 `1.1.2`，v1.1.1 基线提交 `0b65cfd`**。潮间态、统一时间轴、桌面状态与动态建议已实现；已生成验证 wheel，真实模型、LifeHUD 长时运行、原生桌面图标及锁屏/全屏人工验收待完成。

Life HUD 原始时间字段继续按带时区的 UTC Instant 解析；仅在生成 Tool observation 时转换到配置的展示时区（默认 `Asia/Shanghai`），不回写源数据。

v1.0 采用全新安装策略，不提供早期人工测试数据的 v0.9 原位迁移保证。用户可移走或删除旧 `.zhaoxi` 测试目录后重新配置；安装和卸载脚本不会自动删除用户数据。

v1.0 前置解耦已完成：Life HUD 实现与铁幕 Workflow 位于独立 `tools/lifehud_tool` 包，Core 通过通用 Tool Package discovery 加载；Registry 只暴露一个 `lifehud` Tool，并根据封闭 operation 动态解析 READ/WRITE 权限。Life HUD 项目本体保持只读。

本文是后续开发的首要交接入口。版本、架构、数据结构、测试数量或关键限制发生变化时，应在同一提交中更新本文。

## v1.1.2 当前增量

- 复用 Message.timestamp，持久化主动 delivery_id/background；ContextBuilder 注入消息绝对时间、当前时间和互动状态，正式正文不混入背景。
- Desktop 轻量 Win32 状态采样，ACTIVE / SEMI_ACTIVE / IDLE / AWAY 与变化事件、动态 Gate、Natural Check-in 集成。
- 动态建议复用既有回复/主动决策，额外模型调用为0；时间显示统一，图片按钮和“汐”字应用图标已接入。
- 当前验证：**351项 Python、17项 Node 通过**；compileall、diff检查、验证wheel与隔离安装导入通过。浏览器样例已验收，真实桌面长时场景待人工验证。
- 完整方案、文件清单、API、配置及限制见 [`Zhaoxi_v1.1.2_Release_Notes.md`](Zhaoxi_v1.1.2_Release_Notes.md)。

## v1.1.2 前置清理

- Web Adapter 明确消费 `UnifiedResponse`；CLI 直接使用 Settings 的日志字段，移除为不完整测试替身保留的属性兜底。
- 删除旧 importlib metadata API 兼容分支、重复 capability 声明和 Setup capability catalog 赋值。
- Permission 内存存储补齐 `save_grant`，Gateway 统一通过存储方法写入；保留权限匹配及持久化行为。
- PlanStore 明确提供启动用的同步 `list_sync`，Planner 不再探测私有 `_list`；内存与 SQLite 均验证权限等待恢复。
- 删除已由 Workflow SQLite 行为测试覆盖的单独导入测试。发布验证取消固定版本号限制，继续检查源码、项目与 wheel metadata 一致性及敏感文件排除。
- 发布测试实际验证合法 wheel 的 SHA256 输出，以及源码/metadata 版本错误、缺包、重复包、秘密文件和数据库拒绝；安装/卸载脚本在临时目录运行，pip 与注册表操作由测试替身拦截，验证数据保留和自启动显式启用。
- 前置清理验证：**330 项 Python、17 项 Node 通过**；compileall 与 git diff --check 通过，1 项既有 Starlette/httpx 弃用警告。该清理阶段尚未生成发布包。

## v1.1.1 当前增量

- `TidalHeartbeat` 与 `DecisionWorker` 分离，由现有 Web lifespan / TaskSupervisor 管理；观察完成唤醒决策任务，模型等待不阻塞下一次观察，退出可取消两者。
- 复用 Scheduler、PolicyState、Inbox、Desktop sink、Proactive SQLite。事件增加 importance / urgency / next_decision_at，JSON 数据兼容旧记录，增加 pending 索引。
- LifeHUD Tool Package 提供可选 `proactive_sensors()`；Core 不导入 LifeHUD 实现。每 2 分钟只读取 focus / tasks，90 分钟 Focus 和任务完成生成变化事件，API 故障保持静默。
- 持久缓冲默认 5 分钟、200 条候选、6 小时 TTL；自然巡检 TTL 1 小时。使用稳定事件 ID、唯一去重键、事件状态和批次关联 ID 防止重启重复。
- 普通消息冷却 45 分钟，聊天后 15 分钟不打扰；Quiet / 夜间推迟普通候选。提醒跳过普通冷却和聚合，只有 URGENT 可绕过 Quiet / 夜间。
- 自然巡检要求 3 小时未交互、电脑最近 5 分钟有输入、无 Focus、来源健康且有今日轻量上下文；本地日期每天最多一个候选。
- 模型每次最多接收 20 个摘要，返回 silent / defer / speak；单次 provider attempt、30 秒超时，失败静默，事件最多两次决策。回复完成后再次检查打扰状态和 Focus 事实。
- Inbox 展示时间与读状态；点击通知 / Inbox 经鉴权 API 和 Gateway 锁，将消息及简短背景补入并持久化当前 Session，不把原始 Event JSON 交给用户。
- diagnostics 提供 `proactive.*` 进程内计数，重启清零；测试 **321 项 Python、17 项 Node 通过**，1 项既有 Starlette/httpx 弃用警告。
- 完整变更、配置与手动步骤见 [`Zhaoxi_v1.1.1_Release_Notes.md`](Zhaoxi_v1.1.1_Release_Notes.md)。

## v1.1 当前增量

- 当前用户 Task Scheduler 登录延迟 8 秒运行 venv pythonw，`--desktop --background` 初始隐藏；不配置自动重启，主动退出后不复活。
- 在创建 Core 前取得单实例所有权；快捷键 `ctrl+alt+numpad0` 显示/隐藏切换，最小化时恢复，冲突保留托盘。
- `scripts/create_desktop_launcher.ps1` 生成本机双击快捷方式；路径随项目定位，生成的 `.lnk` 不提交。
- Web 回复按空行分气泡，代码围栏内空行保留；新回复段间随机 5～10 秒，历史立即呈现。
- 输入防抖 2 秒；当前回合结束后处理排队输入。支持选择/粘贴图片和纯图片发送，图文合并上限 20 张、每张 100 MB。
- Message 新增 images，Provider 转换成 text/image_url 内容块；Session JSON 向后兼容保存图片，旧文字记录无需迁移。图片回合走已有工具循环，文字路由不变。
- 包含用户已有的人格 YAML、context 规则和角色设定文档修改。
- 当前验证：287 项 Python 测试、14 项 Node 前端测试通过；1 项既有 Starlette/httpx 弃用警告。
- 自启动安装/查询/移除/重装已实测；重新登录、快捷键和托盘完整人工验收、真实模型识图未全部完成。
- v1.1 的心跳后续计划已在 v1.1.1 实现，详见上节。

## v0.9 Reliability

- `src/zhaoxi/reliability/` 提供稳定错误分类、retry/replay 语义、ContextVar 关联上下文和线程安全的进程内指标。
- Interface Gateway 使用外部 `request_id` 作为入口 trace，在异步 Core 调用期间传播 `request_id / session_id`，并记录 started/completed/failed/cache-hit 与耗时聚合。
- `GET /api/diagnostics` 只返回版本、组件可用性和无用户内容的指标快照；Desktop token 边界仍覆盖该 API。
- v0.8 基线导入错误已修复：Reflection SQLite 启用 postponed annotations，避免 `_list` 遮蔽内建 `list` 后破坏返回类型解析。
- Planner、Session 和 Permission 新增独立 SQLite schema；Session 保存有界 user/assistant 文本及 v1.1 图片附件，排除 Tool payload 与 metadata。
- Planner 会从持久 Goal 重建权限等待；临时 Agent 权限等待因缺少完整 Provider transcript，在重启时失败关闭而不重放。
- Provider 对 transient 错误有限重试并支持 fallback 与熔断；认证、校验和安全错误不 fallback；请求有模型调用数与 Token 硬预算。
- Life HUD GET 使用同一 retry primitive；写操作保持不自动重放。任何未声明 `safe_to_replay` 的可重试写失败都会转为 `needs_reconciliation`。
- `BackupManager` 统一管理 Memory、Planner、Session、Permission、Workflow、Proactive、Reflection 和审计数据；SQLite 使用 Online Backup API，恢复前验证并创建 safeguard。
- Tool 参数实施大小、深度、集合和 URL 安全限制；日志与审计可轮转，后台任务通过 supervisor 有界关闭。
- `scripts/` 提供 wheel 构建、当前用户安装、可选自启和保留用户数据的卸载脚本；运维说明见 `docs/Zhaoxi_v1.0_Operations_Runbook.md`。
- v1.0 历史测试基线：**240 项通过**；加速 soak 覆盖 500 次请求，响应缓存和会话均保持上限。

## v1.0 当前切片

- 启动诊断支持 CLI `--doctor`、Web diagnostics 和 Setup Mode；模型配置缺失或可选 Tool Package 加载失败时仍保留可操作界面。
- Core 通过通用 package discovery 组合 Tool、Workflow、routing hints、能力目录与 Reflection source；LifeHUD-Tool 不再由 Core 特判。
- Reflection 已在启动装配中接入 Memory 与 package source，CLI/Web 支持 Daily、Weekly、Monthly、Seasonal 生成和历史查询。
- Reflection Web 输出默认排除原始 Evidence excerpt 与 model metadata，只暴露结论、citation id 和 evidence count。
- Voice Night Mode 使用可注入时钟；用户显式朗读不依赖真实时间，Quiet 仍具最高优先级。

## 当前能力

- `python main.py --web` 启动只监听本机的 Local Interaction Shell；Web Adapter 复用同一 Agent 实例，提供聊天、Permission Card、Session 清空、Activity 元数据和 Proactive SSE 通道。
- `python main.py --desktop` 启动 Windows 10 主平台 Desktop Host；重复启动通过带随机令牌的 loopback 激活通道呼出已有窗口，不重复创建 Core、Scheduler、端口或托盘。
- Voice 输入默认先录音、转写和人工复核，再以 `InterfaceChannel.VOICE` 进入统一 Gateway；自动发送与自动朗读默认关闭。
- Voice 输出使用 Windows 10 SAPI5，支持显式停止和自然结束复位；Quiet、Night、Permission 等待与录音中状态由确定性策略阻止播报。
- Desktop 使用 pywebview 承载现有 Web Shell，pystray 提供打开、快速输入、状态、Quiet Mode 与退出；默认 Ctrl+Alt+小键盘 0（`ctrl+alt+numpad0`） 使用 Win32 `RegisterHotKey`，冲突时保留托盘降级入口。
- `InterfaceGateway` 统一 Web / Desktop 的消息、响应、Permission View、Session 串行与 request ID 幂等；非 user origin 不得进入用户认知链路。
- Desktop 本地 API 使用每次启动随机令牌；令牌通过 URL fragment 交给内嵌页，再以不记入访问日志的请求头交换为 `HttpOnly`、`SameSite=Strict` Cookie，随后立即清除 fragment；SSE query 和访问日志不包含令牌，服务仍只监听 loopback。
- Proactive Delivery 先持久化 Inbox，再按 Priority 映射到 Windows Toast；INFO 不弹窗，NOTICE / IMPORTANT / URGENT 可显示，点击激活现有桌面窗口。
- Python 3.12+、异步运行时和 OpenAI-compatible Provider；通过环境变量可接入兼容 Chat Completions 的模型服务。
- `Conversation`、`ContextBuilder`、人格提示词和会话管理组成基础对话上下文。
- `CognitiveRouter` 将输入分为 `DIRECT`、`TOOL`、`PLAN`、`WORKFLOW`：稳定流程进入确定性 Workflow Runtime，开放复杂目标仍进入 Planner。
- `ZhaoxiAgent` 支持多轮工具调用；内置 echo、计算器、当前时间和记忆工具，工具由统一 Registry 注册。
- Planner 支持 Goal / Plan / Step、线性执行、重试、fallback、版本化 replan、等待用户、恢复、取消和 trace；当前 Goal/Plan/等待状态保存在 SQLite。
- SQLite 长期记忆支持跨会话检索和上下文注入，以及显式记住、搜索、更新、忘记、归档、再激活、固定和整合。
- `AutoMemory` 在每轮回复后独立判断 `CREATE / UPDATE / MERGE / CONFLICT / REACTIVATE / ARCHIVE / FORGET / CONSOLIDATE / IGNORE`；稳定身份和偏好另有保守的确定性兜底。
- Agent 与 Planner 通过同一 `ToolExecutor` / `PermissionGateway` 执行工具；READ 默认允许，WRITE/DELETE 默认确认，DANGEROUS 默认拒绝。
- 确认绑定原始 invocation、参数摘要和资源范围；Planner 可在 `WAITING_FOR_PERMISSION` 暂停并恢复同一个 Goal。
- 单个 Pending Permission 会在 Cognitive Router 与模型调用前拦截自然语言允许/拒绝；无论批准还是拒绝都会补齐原 `tool_call_id` 的 Tool Message 后再恢复 Agent Loop。
- 同一 assistant 响应中连续、同 Tool/同权限的冻结调用会合并成一次批量确认；确认展示数量与资源范围，不跨 Tool 或跨模型响应合并。
- 合并批次支持按编号部分批准/保留；每个成员独立执行或写入拒绝 Tool Message，原参数与 `tool_call_id` 不变。
- 权限事件写入 `.zhaoxi/audit/permission.jsonl`，审计仅保存摘要、ID、范围和结果，不保存原始参数或正文。
- ToolResult 带不可信来源元数据；后台 Auto Memory 不接受模型自行发起的归档、遗忘和整合。
- 自动记忆不再依赖强制 `tool_choice`，使用一次普通 JSON 响应，避免部分兼容服务因工具参数组合持续返回 HTTP 400。
- 可重新查询的工具结果默认不沉淀为长期记忆；显式记忆、拒绝记忆和忘记请求优先于普通自动判断。
- Workflow Definition 支持 `tool / condition / ask / set / end`，Loader/Registry 会拒绝未知 Tool、非法表达式、错误跳转、重复步骤和循环。
- Workflow Run 支持参数补充、条件分支、有限重试、权限等待、暂停、恢复、取消、有界事件和 SQLite 持久化；重启后可重建冻结的权限请求。
- 单一 `lifehud` Tool 的 READ operations 覆盖 `today / recent / status / focus / tasks / dreams / life / journal / media / growth`；schemaVersion 不匹配时拒绝把响应当事实。
- Agent Context DTO 使用强类型 ISO 时间并允许业务 `null`、空集合和 schema 1 新增未知字段；400 参数错误不重试，GET 网络/5xx 使用有限退避。
- 同一 `lifehud` Tool 的 Focus WRITE operations 提供 `start / complete`；权限按 invocation 解析，写操作不自动重放并继续经过 Permission Gateway。
- 内置 `lifehud.iron_curtain.open@1` 与 `close@1` 在写入前后读取 `/api/agent/context/focus`，避免重复、误结束及仅凭 HTTP 200 宣称成功。
- Workflow 会忽略模型生成的无害未知输入并记录 `unknown_inputs_ignored`；类型错误以自然语言返回，不穿透 CLI。
- 权限恢复后的 WorkflowResult 作为内部 Observation 重新进入模型，普通用户只看到自然语言；模型不可用时使用不含内部字段的确定性回退话术。
- Life HUD/工具检查请求被守卫到 TOOL 路径；运行规则禁止声称检查后不执行。

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

## 已知限制与 P2

- Life HUD Agent Context 只读域已接入；写能力仍只覆盖铁幕 start/complete，暂停、恢复、Segment 切换和其他业务写入尚未实现。GitHub、日历和文件系统等真实业务工具仍未实现。
- Planner、Session 与 Permission 已使用 SQLite 持久化；临时 Agent 调用缺少完整模型 transcript 时会在重启后失败关闭。账号体系、OAuth、永久授权策略和操作系统沙箱仍未实现。
- Undo / rollback 仅保留设计边界，当前内置 Tool 尚未实现回滚 hook。
- Voice 的 P0 主链路已实现；独立 Push-to-talk 全局快捷键、音量指示、本地 STT 和多候选转写仍为后续体验项。RAG 与向量数据库尚未实现。
- wheel、当前用户安装、可选开机自启和保留数据卸载脚本已完成；代码签名、自动更新及 Windows 11 实机认证仍未完成。
- Toast / Inbox 已支持 Delivery ID 恢复当前单一桌面 Session 的上下文；跨进程旧 Toast 和多 Session 路由未实现。快捷键冲突仍降级到托盘。
- Workflow 首版不支持 DAG、并行调度、任意循环、图形编辑器或通用跨系统事务回滚。
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
  workflow/      Definition、Loader、Registry、Runtime、SQLite Store 和安全表达式
  permission/    权限模型、策略、确认、Grant、统一执行门和审计
  models/        Provider 抽象、OpenAI-compatible 实现和响应类型
  tools/         工具基类、Registry、内置工具和 Life HUD 集成工具
  config/        环境变量与设置
  personality/   人格提示词
  session/       会话组合
  interfaces/    Web / Desktop 统一消息、响应、权限视图和串行 Gateway
  desktop/       单实例、pywebview、托盘、快捷键和 Windows Toast
  web/           FastAPI、本地 Web Shell、SSE 与 Desktop token 边界
  cli.py         命令行入口
tests/
  cognitive/ config/ core/ desktop/ integration/ interfaces/ memory/
  models/ permission/ planner/ session/ tools/ web/ workflow/
workflows/       版本化内置 Workflow YAML
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
     WORKFLOW: WorkflowRuntime
  -> ToolExecutor / PermissionGateway
     -> ALLOW: Tool.run
        CONFIRM: Pending Permission -> approve / deny -> resume
        DENY: permission_denied ToolResult
  -> 最终回复
  -> AutoMemory.process
  -> MemoryService
  -> SQLiteMemoryRepository
```

工作流：

```text
WorkflowLoader -> WorkflowRegistry
  -> WorkflowRuntime / SQLiteWorkflowStore
  -> ToolExecutor / PermissionGateway
  -> LifeHudClient -> Life HUD REST API
  -> Workflow Run result / event history
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
- `/permissions`：查看待确认权限操作。
- `/approve <confirmation_id>`、`/deny <confirmation_id>`：开发者方式处理待确认操作；单个 pending 也可自然语言允许或拒绝。
- `/revoke <grant_id>`：撤销仍有效的授权。
- `/audit [limit]`：查看脱敏权限审计摘要。
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

模型、日志、上下文、记忆、Planner、Cognitive Router 和 Permission 的常规设置均从环境变量读取。记忆生命周期参数：

```dotenv
ZHAOXI_MEMORY_IMPORTANCE_KEEP_THRESHOLD=0.75
ZHAOXI_MEMORY_RELEVANCE_ACTIVE_THRESHOLD=0.60
ZHAOXI_MEMORY_IMPORTANCE_FORGET_THRESHOLD=0.30
ZHAOXI_MEMORY_RELEVANCE_FORGET_THRESHOLD=0.20
ZHAOXI_MEMORY_RELEVANCE_DECAY_PER_DAY=0.01
ZHAOXI_MEMORY_RELEVANCE_ACCESS_BOOST=0.15
ZHAOXI_MEMORY_COLD_ARCHIVE_AFTER_DAYS=30
```

v0.4 权限参数：

```dotenv
ZHAOXI_PERMISSION_READ_POLICY=allow
ZHAOXI_PERMISSION_WRITE_POLICY=confirm
ZHAOXI_PERMISSION_DELETE_POLICY=confirm
ZHAOXI_PERMISSION_EXTERNAL_ACTION_POLICY=confirm
ZHAOXI_PERMISSION_DANGEROUS_POLICY=deny
ZHAOXI_PERMISSION_CONFIRMATION_TTL_SECONDS=300
ZHAOXI_PERMISSION_AUDIT_PATH=.zhaoxi/audit/permission.jsonl
ZHAOXI_PERMISSION_MAX_TOOL_OUTPUT_CHARS=12000
```

Workflow 与独立 LifeHUD-Tool 参数：

```dotenv
ZHAOXI_WORKFLOW_ENABLED=true
ZHAOXI_WORKFLOW_DIRECTORY=workflows
ZHAOXI_WORKFLOW_DB_PATH=.zhaoxi/workflow.db
ZHAOXI_WORKFLOW_HISTORY_LIMIT=100
ZHAOXI_WORKFLOW_MAX_STEPS=50
ZHAOXI_WORKFLOW_MAX_EVENTS=200
ZHAOXI_TOOL_LIFEHUD_BASE_URL=http://127.0.0.1:8025
ZHAOXI_TOOL_LIFEHUD_CONTEXT_PATH=/api/agent/context
ZHAOXI_TOOL_LIFEHUD_SCHEMA_VERSION=1
ZHAOXI_TOOL_LIFEHUD_TIMEOUT_SECONDS=10
ZHAOXI_TOOL_LIFEHUD_MAX_RETRIES=2
```

默认值和类型以 `src/zhaoxi/config/settings.py` 为准；新增配置时同步更新 `.env.example` 和配置测试。
LifeHUD-Tool 的具体配置校验归独立 Tool 包所有；旧 `ZHAOXI_LIFEHUD_*` 名称仅保留一个兼容周期。

## 启动与验证

```powershell
python main.py
\.venv\Scripts\python.exe -m pytest
\.venv\Scripts\python.exe -m compileall -q src tests
git diff --check
```

当前自动化测试基线：**351 项 Python、17 项 Node 通过**。开发时至少运行与改动相关的测试；提交版本切片前运行全量测试、编译检查和 `git diff --check`。

## 接手建议

1. 先阅读本文件、当前版本任务书和最新 Git 提交，再执行 `git status --short --branch` 确认用户工作区状态。
2. 修改记忆状态机时同时检查普通检索、历史检索、上下文注入和 SQLite 迁移，避免归档数据被意外激活或注入。
3. Provider 兼容问题优先用 Mock Transport 固化请求体与错误响应，不要用真实凭据作为回归测试前提。
4. 工具返回的数据先判断是否可重新查询；可重新查询事实默认不进入长期记忆。
5. 每个版本提交都同步更新本文顶部基线、已完成能力、明确限制、验证数量和提交信息。

## Git 基线

- 当前开发分支：`v1.1.2`
- v1.1.1 基线：`0b65cfd feat(v1.1.1): add tidal heartbeat and proactive inbox continuation`
- v1.1.2：本次潮间态实现、前置清理与验收文档在同一提交中归档。
- v1.0 起点：`87eb9c6 feat: complete v0.9 reliability hardening`
- v1.0 正式版：`51cf34b docs(v1.0): record release evidence`（功能 RC：`2e4db8f`）
- v0.5.1.2 工作区基线：基于 `3f3f13a` 与未提交的 v0.5/v0.5.1/v0.5.1.1 纵向切片继续修补
- v0.3.1 基线：`9f4424c feat: integrate v0.3.1 cognitive routing and memory`
- v0.3 Planner：`613859d feat: implement v0.3 planner`
- v0.2 Memory：`b1d0bcc feat: implement v0.2 persistent memory`
- 初始版本：`889f9d5 chore: initialize Zhaoxi project`

本节的“当前开发分支”和提交基线应在后续版本交接时更新。
