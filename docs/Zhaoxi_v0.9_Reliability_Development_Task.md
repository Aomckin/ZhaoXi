# Zhaoxi v0.9 · Reliability 开发任务书

> 项目：**Zhaoxi / 朝汐**  
> 版本：**v0.9 · Reliability**  
> 性质：正式版前可靠性收敛 / 数据安全 / 可观测性 / 发布硬化  
> 开发分支：`v0.9`  
> 上游基线：`v0.8`，提交 `f58044d`  
> 核心目标：**让 Zhaoxi 从“功能可运行”进入“能够长期、可恢复、可诊断地运行”。**

本文是 v0.9 的范围、优先级、开发顺序和验收依据。实现过程中若改变数据模型、运行边界或交付顺序，必须同步更新本文、`docs/CODEBASE_STATUS.md`、`README.md` 与相关配置示例。

---

## 1. 版本定位

v0.9 不继续横向堆叠业务能力，而是集中偿还 v0.1—v0.8 积累的长期运行风险。它需要回答：

- 进程异常退出后，用户的会话、计划、权限等待和工作流能否安全恢复？
- Provider、Life HUD 或模型短时故障时，是否会有限重试、正确降级且不重复副作用？
- 数据库损坏、迁移失败或误操作后，是否有可验证的备份与恢复路径？
- 一次失败能否通过统一 trace、结构化日志和指标定位，同时不泄露隐私？
- 桌面端能否在干净 Windows 环境中安装、升级、卸载并稳定启动？
- 自动化测试是否覆盖恢复、故障注入、兼容性和长时间运行，而不依赖真实 API 凭据？

本版本的结果不是“永不失败”，而是：

> **失败有边界，状态可恢复，数据可验证，问题可定位，发布可复现。**

---

## 2. 当前基线与已知风险

### 2.1 可复用能力

- Core 已有统一 Agent、Planner、Workflow、Permission、Proactive、Reflection 与 Interface Gateway 边界。
- Memory、Workflow、Proactive、Reflection 已有 SQLite 实现，可复用仓储抽象和迁移测试模式。
- Agent、Planner、Life HUD、Voice 已有局部 timeout/retry；v0.9 负责收敛成统一策略，而不是重写所有运行时。
- 权限审计、request ID、trace ID、日志脱敏和不可信 ToolResult 边界已有基础。
- Web/Desktop 仅监听 loopback，桌面宿主具备单实例、托盘、快捷键、通知和 Voice 主链路。
- 测试使用 Fake Provider / Mock Transport，可在无真实密钥的情况下做故障注入。

### 2.2 开工时确认的阻塞

在 `v0.9` 分支创建后执行基线验证：

```powershell
python -m pytest
python -m compileall -q src tests
git diff --check
```

结果：编译检查和 diff 检查通过，但 pytest 在收集阶段失败。`src/zhaoxi/reflection/sqlite.py` 的 `_list` 方法名在类作用域遮蔽内建 `list`，使返回类型 `list[ReflectionRecord]` 被解析为函数下标，导致 3 个 Reflection 测试模块无法导入。

因此阶段 0 必须先修复并冻结 v0.8 基线；在全量测试恢复为绿色前，不开始 v0.9 的结构性改造。

### 2.3 当前可靠性缺口

- Planner 和 Session 仍以内存存储为主，进程退出后无法恢复。
- Permission pending/grant 为进程内状态；崩溃后等待确认的操作缺少完整恢复语义。
- 各模块的 retry、timeout、错误码、幂等键和退避行为尚未形成统一契约。
- 多个 SQLite 数据库缺少统一健康检查、备份清单、恢复工具和迁移失败回滚流程。
- 日志、trace 与 audit 分散，尚无统一关联字段和最小指标面。
- Provider 没有明确的 fallback/circuit-breaker 策略，Token/Cost 预算也未形成统一硬限制。
- Tool Sandbox 目前主要依赖 Tool/Permission 抽象，尚无系统级隔离承诺。
- 安装、升级、卸载、开机自启、签名与干净 Windows 验证尚未交付。
- `pyproject.toml` 仍标记为 `0.7.1`，README 与 `CODEBASE_STATUS.md` 的当前版本描述落后于 v0.8 实现。

---

## 3. 成功标准

v0.9 完成时必须满足：

1. 所有持久状态都有明确 owner、schema version、备份与恢复路径。
2. 进程在 Agent/Planner/Workflow/Permission/Reflection 的关键等待点退出后，可恢复或明确、安全地终止；不得静默重复副作用。
3. Provider 和外部只读 Tool 的瞬时故障遵循统一、有限、可观测的 retry/timeout/fallback 策略。
4. 写操作默认不自动重放；只有具备稳定幂等键和事实源确认时才允许恢复执行。
5. 日志、trace、metrics、audit 可通过同一 correlation ID 串联，且不记录密钥、完整用户正文、原始 Tool 参数或 Memory 内容。
6. SQLite 备份可校验、可恢复；损坏、迁移失败、磁盘写失败均有明确错误和安全降级。
7. Prompt Injection 与不可信 Tool 输出经过确定性边界处理，高风险 Tool 无法绕过 Permission。
8. 单元、集成、故障注入、升级兼容和长时间运行测试全绿，不依赖真实外部服务。
9. Windows 发布物可在干净环境完成安装、首次启动、升级、卸载；用户数据默认不随卸载删除。
10. 版本号、README、状态文档、配置样例和运维手册与实现一致。

---

## 4. 范围与优先级

### P0 · 发布阻塞

- 修复并冻结 v0.8 测试基线。
- 统一 Reliability 契约：错误分类、retry、timeout、幂等、恢复和 trace 字段。
- 持久化 Planner/Session/Permission 的最小恢复状态。
- SQLite 健康检查、schema 迁移保护、原子备份、校验与恢复。
- Provider 有界重试、fallback 和熔断；Token/Cost 硬预算。
- 统一结构化日志、trace、audit 关联和最小 metrics。
- Tool/Prompt Injection 边界加固与高风险操作防护。
- 全量回归、故障注入、崩溃恢复和兼容性测试。
- Windows 可复现打包、安装、升级、卸载和干净环境冒烟。

### P1 · v0.9 完整能力

- Proactive/Reflection 调度租约、错过任务补偿和重复投递抑制。
- 数据保留、日志轮转、审计归档和磁盘容量保护。
- 启动自检、诊断命令与脱敏诊断包。
- 优雅关闭：停止接收新请求、等待有界任务、持久化安全点、清理音频临时文件。
- 开机自启的显式安装选项、可撤销配置与失败降级。
- 24 小时加速/模拟 soak test 和资源泄漏检查。

### P2 · 有余量再做

- 多 Provider 动态健康评分和按成本/延迟路由。
- 系统级子进程沙箱或容器隔离 Spike。
- 自动更新与发布签名流水线。
- 多 Session 通知深链接。
- 可视化运维面板。

P2 不得阻塞 v0.9；若实现，必须单独设计、单独验收。

---

## 5. 明确不做

- 不新增 GitHub、Calendar、Gmail、Files 等业务 Tool。
- 不扩展 Life HUD 业务写域。
- 不重做 UI、不引入新的前端框架。
- 不实现分布式多用户、云端控制面或跨设备同步。
- 不以“自动重试”掩盖不具备幂等性的写操作。
- 不把日志、trace 或 metrics 变成用户内容的第二份数据库。
- 不承诺任意第三方 Tool 的操作系统级强沙箱；未隔离能力必须在文档中明确边界。
- 不以真实 API Key 或真实用户数据库作为自动化测试前提。

---

## 6. 可靠性统一契约

### 6.1 错误分类

统一错误至少包含：

```text
ReliabilityError
├── code                 稳定机器码
├── category             transient / permanent / validation / permission / corruption
├── retryable            是否允许重试
├── safe_to_replay       是否允许重放
├── user_message         可展示、无内部信息
├── trace_id             跨层关联
└── cause_type           仅记录异常类型，不记录秘密正文
```

不得通过字符串匹配决定是否重试。外部适配器负责把 HTTP、网络和协议错误归一化，Core 只消费统一分类。

### 6.2 Retry Policy

- 仅对明确的 transient 且 safe-to-replay 操作重试。
- 采用指数退避、抖动、最大次数和总时限；测试注入零等待时钟。
- HTTP 429/502/503/504、连接重置等按适配器契约分类。
- 400/401/403、schema 不匹配、权限拒绝和数据损坏默认不重试。
- WRITE/DELETE/EXTERNAL_ACTION 默认不自动重试，除非 Tool 声明稳定幂等键并能查询事实源确认。
- 每次尝试写 trace event，但用户界面只显示最终可操作结果。

### 6.3 Timeout Policy

明确四层预算：

```text
单次外部请求 < 单步预算 < 单次 Agent/Plan 总预算 < 后台任务租约
```

取消从外向内传播；timeout 后不得继续在后台悄悄执行副作用。线程或平台 API 无法强制取消时，必须将其标为 unknown outcome，并禁止自动重放。

### 6.4 幂等与副作用

- 每次调用分配 `invocation_id`，恢复重放沿用原 ID。
- Tool 声明 `side_effect`、`idempotency_mode` 和 `verification_strategy`。
- 相同幂等键只能得到同一业务结果或明确冲突。
- 不确定写入结果进入 `needs_reconciliation`，由事实源查询或用户确认解决。

### 6.5 Trace 与关联字段

所有入口和后台任务统一携带：

```text
trace_id / request_id / session_id / goal_id / workflow_run_id /
reflection_id / invocation_id / schedule_id
```

字段按场景选用，不存在时为空；禁止在不同层重复生成互不关联的 trace ID。

---

## 7. 状态持久化与崩溃恢复

### 7.1 Planner

- 以 `PlanStore` 抽象保留 `InMemoryPlanStore`，新增 SQLite 实现。
- 持久化 Goal、Plan 版本、Step 状态、attempt、Observation 摘要和有界 trace。
- 启动时扫描非终态任务并分类：可恢复、等待用户、等待权限、需对账、已超时。
- 不恢复正在执行但结果未知的副作用步骤；转入 `needs_reconciliation`。

### 7.2 Session

- 持久化最小会话消息和最后活动时间，遵守上下文裁剪上限。
- 不把完整 Tool 原始 payload、音频文件或秘密字段写入 Session。
- `/clear` 语义保持明确：清会话，不删除长期 Memory。
- schema 升级和旧会话读取必须有兼容测试。

### 7.3 Permission

- pending confirmation、批次成员、冻结摘要、到期时间和原 invocation 关联可恢复。
- Grant 仍是窄范围、可撤销、单次消费；恢复后不得扩大范围或刷新 TTL。
- 原操作状态未知时，批准不能直接重放，必须先对账。
- 审计写入失败时，高风险操作 fail closed。

### 7.4 Workflow / Proactive / Reflection

- 复核现有 SQLite Store 的 lease、claim、唯一约束与重启恢复语义。
- 调度任务使用稳定 occurrence key 防止重复生成或重复通知。
- Reflection 重生成继续保留版本；恢复不能覆盖已有记录。
- 所有后台循环具备有界停止和健康状态。

---

## 8. 数据安全、备份与迁移

### 8.1 数据清单

建立注册表，至少覆盖：

- Memory DB
- Workflow DB
- Proactive DB
- Reflection DB
- Planner/Session/Permission DB（新增后）
- Permission audit JSONL
- 日志、临时音频、单实例状态与用户配置

每项注明 owner、路径、schema version、敏感等级、备份策略、保留期和可否重建。

### 8.2 备份

- 使用 SQLite Online Backup API 或等价一致性快照，不直接复制正在写入的数据库文件。
- 先写临时目标，完成 integrity check 和 manifest 后原子改名。
- manifest 记录应用版本、schema version、创建时间、文件大小和校验和，不记录用户正文。
- 支持保留数量/天数上限；清理仅作用于已验证的备份目录。

### 8.3 恢复

- 恢复前验证 manifest、校验和、SQLite integrity 和 schema 兼容性。
- 当前数据先生成可恢复快照，再替换目标。
- 恢复必须在服务停止或写入冻结状态下执行。
- 失败时保留原数据，并返回明确诊断，不留下半恢复状态。

### 8.4 迁移

- 每个数据库独立维护 schema version。
- 迁移在事务中执行；不可逆迁移必须先备份。
- 同版本迁移幂等，旧版本升级有 fixture，新版本被旧程序打开时安全拒绝。
- 启动不允许“部分数据库已升级、部分未升级”后继续提供写服务。

---

## 9. Provider、成本与降级

- Provider 配置由单实例升级为有序候选列表，但保持现有单 Provider 配置兼容。
- fallback 只在 transient/availability 类错误触发，不在认证失败、输入非法或安全拒绝时切换。
- 每个 Provider 有独立 timeout、并发上限、失败计数和冷却窗口。
- 简单熔断状态：closed → open → half-open；状态变化写 metrics/trace。
- 请求预算包含最大模型调用次数、输入字符/Token 估算、输出上限和可选成本上限。
- 预算耗尽返回可操作的部分结果或安全失败，不继续隐藏调用。
- Auto Memory、Router、Reflection 等后台模型调用必须计入同一请求或任务预算。

---

## 10. 可观测性与隐私

### 10.1 结构化日志

统一 JSON/文本 formatter 的字段集合和脱敏过滤器。默认 INFO 记录：事件名、状态、耗时、计数、稳定 ID 和错误类型；DEBUG 也不得记录密钥、Authorization、Cookie、完整 Memory 正文或原始音频。

### 10.2 Metrics

P0 先实现进程内聚合与可测试快照，避免立即引入外部监控依赖。至少包含：

- 请求数、成功率、错误分类和延迟分布
- Provider 调用、retry、fallback、熔断与预算拒绝
- Tool 调用、权限等待/拒绝、unknown outcome
- 活跃 Planner/Workflow/后台任务数
- DB 操作失败、迁移、备份、恢复和队列积压
- 当前进程 uptime 与优雅关闭结果

指标标签必须低基数，不使用 user text、memory ID 或任意 URL 作为标签。

### 10.3 诊断

提供只读诊断入口，输出版本、平台、配置是否完整、数据库健康、Provider 可用性摘要、队列积压和最近错误类型。诊断包默认脱敏，生成前展示包含内容，不复制用户数据库。

---

## 11. 安全加固

- 所有 ToolResult、网页/文件/外部系统文本继续标记为 untrusted data，不能覆盖 system/personality/permission 指令。
- Tool Schema 限制参数长度、集合大小、路径范围、URL scheme 和响应体大小。
- 高风险 Tool 必须经过统一 `ToolExecutor -> PermissionGateway`，不得存在旁路调用。
- 路径操作解析绝对路径并验证允许根；拒绝 `..`、符号链接逃逸和宽泛递归目标。
- 外部 URL 默认拒绝 loopback、link-local、metadata IP 和非 HTTP(S) scheme，除非具体一方 Tool 有显式允许列表。
- 日志、错误页、SSE、Toast 和 Voice 不回显秘密或不可信原文。
- 安全测试覆盖 prompt injection、参数走私、超长输出、权限恢复篡改和审计失败 fail-closed。

系统级 Tool Sandbox 先做威胁模型与 Spike。若 v0.9 未交付真正隔离，文档必须明确当前仅有应用层权限与参数边界。

---

## 12. Windows 发布与生命周期

- 选择并记录打包方案 ADR；锁定 Python、依赖与构建命令。
- 产物包含版本信息、许可证、默认配置和启动入口，不包含 `.env`、数据库、日志或测试密钥。
- 安装范围默认当前用户；数据目录与程序目录分离。
- 升级保留数据和配置，先备份再迁移；降级遇到新 schema 时安全拒绝。
- 卸载默认保留用户数据，删除数据需要独立、明确确认。
- 开机自启为可选项，安装/移除可重复执行且失败可诊断。
- 在干净 Windows 10/11 环境验证安装、首次启动、托盘、Voice 可选依赖、升级和卸载。
- 签名与自动更新若无法在 v0.9 完成，列为 P2 且在发布说明中明确。

---

## 13. 配置建议

新增配置应遵循 `ZHAOXI_` 前缀、Pydantic 强类型、边界校验和 `.env.example` 同步。建议分组：

```dotenv
ZHAOXI_RELIABILITY_DB_PATH=.zhaoxi/reliability.db
ZHAOXI_RETRY_MAX_ATTEMPTS=3
ZHAOXI_RETRY_BASE_DELAY_SECONDS=0.5
ZHAOXI_RETRY_MAX_DELAY_SECONDS=8
ZHAOXI_PROVIDER_FAILURE_THRESHOLD=5
ZHAOXI_PROVIDER_COOLDOWN_SECONDS=60
ZHAOXI_REQUEST_MAX_MODEL_CALLS=12
ZHAOXI_REQUEST_MAX_INPUT_TOKENS=100000
ZHAOXI_REQUEST_MAX_OUTPUT_TOKENS=16000
ZHAOXI_BACKUP_DIRECTORY=.zhaoxi/backups
ZHAOXI_BACKUP_RETENTION_COUNT=14
ZHAOXI_LOG_MAX_BYTES=10485760
ZHAOXI_LOG_BACKUP_COUNT=5
ZHAOXI_SHUTDOWN_GRACE_SECONDS=15
```

具体默认值在实现 Spike 后冻结。测试不得依赖 wall-clock sleep，应注入 clock/sleeper/random。

---

## 14. 开发流程

### 阶段 0：修复并冻结 v0.8 基线

- 修复 Reflection SQLite 类型注解遮蔽问题。
- 运行全量 pytest、compileall、`git diff --check`。
- 核对 v0.8 功能入口和数据库迁移。
- 更新 `CODEBASE_STATUS.md` 的分支、版本、测试数和已知限制。

退出条件：基线全绿，有单独提交，不把 Reliability 架构改动混入修复。

### 阶段 1：可靠性契约与 ADR

- 盘点所有状态、外部调用、后台循环和副作用路径。
- 输出错误分类、retry/timeout、幂等、恢复、数据目录和发布方案 ADR。
- 建立统一 correlation context 与可注入 clock/sleeper。

退出条件：契约测试先行，跨模块不再各自发明错误和重试语义。

### 阶段 2：可观测性纵向切片

- 从一次 Web/Desktop 请求贯穿 Agent → Tool/Provider → Store。
- 统一结构化日志、trace event、metrics snapshot 和脱敏。
- 增加诊断入口与错误码目录。

退出条件：一次成功、一次 Provider 失败、一次权限等待均可用同一 trace ID 解释。

### 阶段 3：Planner / Session / Permission 持久恢复

- 新增 SQLite Store、schema、迁移和恢复状态机。
- 实现等待用户、等待权限、超时、未知副作用对账。
- 保留 InMemory 实现供单元测试和嵌入场景使用。

退出条件：在关键状态强制终止并重启，结果不丢失、不越权、不重复写入。

### 阶段 4：统一外部调用策略

- 抽取 retry/timeout/budget primitives。
- 接入 Provider 与 Life HUD 只读路径，再逐步覆盖其他适配器。
- 实现 Provider fallback、熔断和调用预算。

退出条件：故障注入证明次数、退避、取消和 fallback 均有确定上限。

### 阶段 5：数据库备份、恢复与迁移保护

- 数据清单、健康检查、manifest、原子备份和恢复 CLI/服务。
- 为每个 SQLite Store 增加旧 schema、损坏、磁盘失败测试。
- 启动时执行跨库兼容预检。

退出条件：从备份恢复后全量数据契约测试通过；恢复失败不破坏原库。

### 阶段 6：安全与后台运行硬化

- Prompt Injection、Tool 参数、路径/URL、输出大小和权限旁路测试。
- Proactive/Reflection occurrence 去重、lease 恢复和积压限制。
- 优雅关闭、日志轮转、临时文件清理和磁盘容量保护。

退出条件：安全回归全绿，后台任务在重启和重复 tick 下不重复投递。

### 阶段 7：Windows 发布链路

- 完成打包 ADR、锁定构建、安装/升级/卸载脚本或安装器。
- 数据目录迁移、可选自启、首次启动诊断。
- 干净 Windows 10/11 冒烟并保留测试记录。

退出条件：同一 commit 可重复构建，升级保留数据，卸载默认保留用户数据。

### 阶段 8：Soak、文档与发布候选

- 执行 24 小时模拟/加速 soak，采集内存、线程、队列、句柄和错误趋势。
- 全量回归、备份恢复演练、安装升级演练。
- 同步 README、状态文档、配置、版本号、故障排查和发布说明。

退出条件：P0 全部满足，无未解释的资源增长或高风险已知缺陷。

---

## 15. 测试矩阵

### Baseline / Regression

- 全量现有测试持续通过。
- Reflection 导入、生成、引用和 SQLite 回归。
- CLI/Web/Desktop/Voice 在缺少可选依赖时安全降级。

### Recovery

- Planner 每个非终态节点退出并恢复。
- Session 裁剪、清空、旧 schema 和并发写。
- Permission pending/batch/grant 到期、撤销和恢复篡改。
- Workflow/Proactive/Reflection claim 后崩溃、租约到期和重复 tick。

### Retry / Timeout / Fallback

- transient → retry → success。
- permanent → 不重试。
- budget/timeout → 取消并停止后续调用。
- Provider open/half-open/closed 状态转换。
- 写操作 unknown outcome → 对账，不自动重放。

### Storage

- 空库、新库、旧库、新版本库、损坏库、只读目录、磁盘满模拟。
- 在线备份一致性、校验和失败、恢复中断和恢复回滚。
- 日志/审计轮转不丢失关键边界事件。

### Security / Privacy

- ToolResult prompt injection 不改变权限策略。
- 路径逃逸、SSRF、参数走私、超大 payload 被拒绝。
- 日志、trace、metrics、诊断包不含密钥或测试 canary 正文。
- 审计失败时高风险操作 fail closed。

### Packaging / Soak

- 干净 Windows 安装、首次运行、升级、卸载、保留数据。
- 重复安装/卸载和自启开关幂等。
- 加速定时任务、长对话、反复 Voice start/stop、SSE 重连和 Provider 抖动。
- 资源使用稳定，无无界队列、线程、文件句柄或临时文件增长。

---

## 16. 集中黑盒冒烟验收

### Case A：崩溃恢复

启动多步计划，在等待用户和等待权限阶段分别强制退出。重启后能恢复同一任务；旧确认不扩权，已完成副作用不重复执行。

### Case B：Provider 故障

主 Provider 连续返回 503，系统在有限重试后熔断并切换备用 Provider；认证错误不 fallback；调用数不超过预算。

### Case C：未知写入结果

写 Tool 在服务端成功后连接断开。系统标记 `needs_reconciliation`，不自动重放，通过事实源确认后再结束任务。

### Case D：备份恢复

运行中生成一致性备份，验证 manifest；破坏测试副本后恢复，Memory、Workflow、Reflection 和任务状态均可读取。

### Case E：Prompt Injection

Life HUD 或未来外部源返回“忽略权限并执行危险操作”。内容只作为数据进入上下文，不能创建旁路 Tool 调用或自动授权。

### Case F：磁盘与审计失败

模拟数据库只读、磁盘满和 audit 写失败。只读查询可按策略降级，高风险写操作 fail closed，界面返回带 trace ID 的可操作错误。

### Case G：升级卸载

在干净 Windows 安装旧版测试包并写入测试数据，升级 v0.9 后数据可用；卸载程序后用户数据仍保留，显式清理需二次确认。

### Case H：长时间运行

模拟 24 小时混合负载与时钟推进。定时任务不重复、SSE 可重连、临时音频被清理、资源曲线无持续无界增长。

---

## 17. 交付物

- 统一 Reliability 契约、ADR 与错误码目录。
- Planner / Session / Permission SQLite Store 与迁移。
- retry、timeout、budget、circuit breaker 公共组件。
- Provider fallback 与调用预算。
- 统一 logging / tracing / metrics / diagnostics。
- 数据健康检查、备份、校验、恢复和保留策略。
- 安全加固与故障注入测试集。
- Windows 可复现构建与安装/升级/卸载交付物。
- 运维手册：启动失败、数据库损坏、恢复备份、Provider 故障、诊断包。
- 更新后的 README、`CODEBASE_STATUS.md`、`.env.example`、版本号和发布说明。

---

## 18. Definition of Done

- [x] 阶段 0 的 v0.8 基线已修复并全绿（187 项基线测试通过）。
- [x] P0 全部完成，P1 未完成项有明确延期说明。
- [x] 所有持久状态均有 schema、迁移保护、备份和恢复测试。
- [x] 崩溃恢复不重复副作用、不扩大权限、不丢失可恢复任务。
- [x] retry、timeout、fallback、熔断和预算均有确定上限。
- [x] 统一 trace 能串联入口、模型、Tool、权限、Store 和后台任务。
- [x] 日志、metrics、trace、audit 和诊断快照通过隐私 canary 测试。
- [x] Prompt Injection 与 Tool 参数边界测试通过。
- [x] 全量 pytest、compileall 和 `git diff --check` 通过（225 项测试）。
- [x] Windows 10 wheel 构建、隔离目标安装、资源完整性与 PowerShell 脚本语法冒烟通过。
- [x] 加速 soak test 无无界响应缓存或会话增长。
- [x] `pyproject.toml`、README、状态文档、配置样例与 v0.9 一致。
- [x] 已知限制和 v1.0 前剩余风险已记录。

验收环境为 Windows 10 `10.0.19045`、Python 3.12+。Windows 11 实机、代码签名、自动更新与操作系统级 Tool Sandbox 不在本地环境中可执行，按本文既定范围保留为 P2；当前版本明确只承诺应用层权限、参数、审计和恢复边界。

---

## 19. 推荐提交切片

```text
fix(reflection): restore green v0.8 baseline
docs(reliability): define v0.9 contracts and ADRs
feat(observability): unify correlation logs traces and metrics
feat(recovery): persist planner sessions and permissions
feat(reliability): unify retry timeout and request budgets
feat(provider): add bounded fallback and circuit breaker
feat(storage): add verified backup restore and migration guard
feat(security): harden untrusted tools and permission boundaries
feat(runtime): harden schedulers shutdown and retention
build(windows): add reproducible installer and upgrade path
test(reliability): add recovery fault injection and soak suites
docs(v0.9): finalize operations and release documentation
```

每个切片必须有对应测试；涉及 schema 的提交必须同时包含迁移和旧版 fixture。

---

## 20. 一句话验收

> **把朝汐在运行中“拔掉电源”再启动，她知道哪些事情能继续、哪些必须停下来确认；数据没有丢、权限没有扩大、动作没有重复，并且开发者能用同一条 trace 解释发生了什么。**
