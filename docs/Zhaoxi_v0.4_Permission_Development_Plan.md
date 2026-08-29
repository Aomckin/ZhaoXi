# Zhaoxi v0.4 · Permission 开发计划

> 版本目标：为所有 Tool 调用建立统一的权限声明、策略判断、用户确认和安全审计边界，使朝汐在执行写入、删除、外部动作或危险操作前能够可靠地获得授权，并让每次允许、拒绝与执行结果都可追溯。
>
> 历史开发基线：v0.3.2 已具备 Cognitive Router、Agent Runtime、Planner、长期 Memory 与生命周期管理；进入 v0.4 开发时为 55 项自动化测试通过。当前 v0.4 验证基线见 `CODEBASE_STATUS.md`。
>
> 核心原则：**模型可以提出动作，但不能授予权限；Tool 可以声明能力，但不能绕过统一执行门；所有副作用都必须经过确定性代码判断。**

> 实现状态：核心纵向切片已完成。权限等级、统一 ToolExecutor / Permission Gateway、Agent 与 Planner 确认恢复、自然语言允许/拒绝、同类调用批量确认与按编号部分批准、参数摘要绑定、单次授权、撤销、取消失效、JSONL 审计、不可信 ToolResult 标记和 CLI 权限命令均已接入。Pending 回复会在进入 Cognitive Router/LLM 前处理，并为原 `tool_call_id` 补齐 Tool Message；同一响应中连续、同 Tool/同权限的冻结调用只需确认一次，用户也可选择只执行其中若干项。Undo / rollback hook、跨进程 pending/grant 持久化和真实外部 Tool 留待后续增量。

---

# 1. 一句话验收目标

完成以下闭环：

```text
模型提出 Tool Call
→ 解析 Tool 权限与调用上下文
→ Permission Gateway 确定性评估策略
   ├── 自动允许
   ├── 请求用户确认并暂停
   └── 拒绝
→ 获得授权后执行 Tool
→ 记录脱敏审计事件与结果
→ 返回 Agent / Planner 继续推理
```

v0.4 完成时必须支持：

- 每个 Tool 明确声明权限等级与副作用，而不是只靠 `mutates_state`；
- Agent 与 Planner 经过同一个 Permission Gateway，不保留两套权限逻辑；
- READ 可按策略自动许可，WRITE / DELETE / EXTERNAL_ACTION / DANGEROUS 可配置为确认或拒绝；
- 用户确认内容明确包含工具、动作摘要、目标、风险与授权范围；
- 确认后只恢复原始、不可变的待执行调用，不能让模型趁确认过程替换参数；
- 用户拒绝后不执行 Tool，并把结构化拒绝结果交回运行时；
- Planner 等待授权时可以暂停、批准、拒绝或取消，且不会创建重复 Goal；
- 同一调用的重试不会无意义地重复确认，但更换工具、参数或扩大风险必须重新授权；
- 每次策略判断、确认、拒绝、执行与回滚尝试都有脱敏审计记录；
- Tool 输出按不可信数据进入上下文，不能改变系统规则或授权状态。

---

# 2. 当前基线与切入点

当前实现中：

- `Tool` 只有 `mutates_state: bool`，不足以区分写入、删除、外部动作和危险操作；
- `ZhaoxiAgent._execute_tool()` 与 `PlannerRuntime._execute_tool()` 分别调用 `tool.run()`；
- Planner 的“只读任务”通过自然语言标记和 `mutates_state` 拦截，只能作为附加约束，不能代替权限系统；
- Planner Trace 记录目标与步骤状态，但不是跨 Agent/Planner 的安全审计日志；
- Planner 的 `request_user_input` 面向业务信息缺失，不能直接承担不可伪造的授权确认；
- Tool 参数与结果目前可能进入普通 TOOL 日志，v0.4 必须统一脱敏策略；
- 内置 Memory Tools 已同时包含读取、写入、归档、遗忘、固定和整合，适合作为首批权限验收对象。

因此 v0.4 的首要架构动作不是给每个 Tool 加 `if confirm`，而是建立一个被 Agent 和 Planner 共同调用的执行门。

---

# 3. 范围与权限模型

## 3.1 权限等级

定义稳定 Enum：

```text
READ
WRITE
DELETE
EXTERNAL_ACTION
DANGEROUS
```

默认语义：

| 等级 | 含义 | 默认策略 |
|---|---|---|
| READ | 读取本地或外部数据，不产生业务副作用 | 自动允许 |
| WRITE | 新增或修改状态 | 每次确认 |
| DELETE | 删除、遗忘或不可见化数据 | 每次确认 |
| EXTERNAL_ACTION | 向外部主体发送、发布、购买、提交等 | 每次确认 |
| DANGEROUS | 系统命令、权限变更或高损失动作 | 默认拒绝 |

权限等级不表示“数值越大即可替代全部规则”。例如发邮件属于 EXTERNAL_ACTION，不应因同时写入草稿而降级成普通 WRITE。

## 3.2 Tool 权限声明

扩展 Tool 合约，建议包含：

```text
permission: PermissionLevel
side_effects: set[SideEffect]
supports_undo: bool
confirmation_description(arguments) -> str
resource_scope(arguments) -> ResourceScope
```

保留 `mutates_state` 一小段兼容期，但其值由权限元数据推导并标记弃用，避免出现两个互相矛盾的事实源。

注册时必须校验：

- Tool 未声明权限时拒绝注册，或只在迁移期开启 fail-closed 默认值；
- READ Tool 不得声明写入副作用；
- `supports_undo=True` 时必须实现 rollback hook；
- 面向用户的确认摘要不得包含密钥、完整 Memory 正文或其他敏感数据。

## 3.3 调用上下文

每次调用构造厂商无关的 `PermissionRequest`：

```text
request_id / invocation_id
tool_name
permission
arguments_digest
resource_scope
action_summary
origin: agent | planner | user_command
goal_id / step_id（可选）
user_intent
created_at / expires_at
```

保存规范化参数的摘要与不可变快照。授权绑定到 `tool + arguments_digest + resource_scope + origin`；任一关键字段变化都使旧授权失效。

---

# 4. Permission 架构

建议新增：

```text
src/zhaoxi/permission/
├── models.py       # Level、Request、Decision、Grant、AuditEvent
├── policy.py       # 策略接口与默认本地策略
├── gateway.py      # 统一授权与执行门
├── store.py        # Pending request / grant store
├── audit.py        # 追加式脱敏审计接口
├── sanitization.py # 参数、结果和日志脱敏
└── injection.py    # Tool 输出的不可信边界处理
```

核心调用链：

```text
Agent / Planner
  → ToolExecutor
  → PermissionGateway.authorize(invocation)
       → PermissionPolicy.evaluate()
       → PendingPermissionStore / GrantStore
       → AuditSink
  → Tool.run()
  → AuditSink
  → normalized ToolResult
```

`ToolExecutor` 负责统一工具发现、参数校验、权限检查、超时和结果规范化。v0.4 应将 Agent 与 Planner 当前重复的工具执行边界收敛到这一处；Planner 仍负责 retry、fallback、Observation 与任务状态，不把规划职责塞进 Gateway。

---

# 5. 策略、授权与确认

## 5.1 策略结果

策略只返回确定性结构：

```text
ALLOW
REQUIRE_CONFIRMATION
DENY
```

每个决定至少包含 `reason_code`、匹配规则、有效范围和过期时间。模型输出不得直接生成 `ALLOW` 或修改策略。

默认本地策略建议：

- READ 自动允许；
- WRITE、DELETE、EXTERNAL_ACTION 每次确认；
- DANGEROUS 默认拒绝；
- 用户明确要求“只读”时，所有非 READ Tool 直接拒绝；
- 未知 Tool、缺失权限声明、无效参数和过期授权全部 fail closed；
- 开发者可通过配置收紧默认策略，但 v0.4 不提供允许任意 Tool 的全局通配开关。

## 5.2 自动许可

可配置自动许可使用结构化规则，而不是自然语言 Prompt：

```text
tool_name
permission
resource_scope
argument_constraints
origin
expires_at
max_uses
```

v0.4 第一版只需支持小范围、可撤销的 session grant，例如“本会话允许更新指定 Memory”。不实现永久账号级授权或复杂策略语言。

## 5.3 Pending Confirmation

权限确认是独立状态，不复用 Planner 的普通业务 `InputRequest`。建议返回：

```text
confirmation_id
question
action_summary
permission
resource_scope
risk_summary
choices: approve_once | deny
expires_at
```

CLI 增加：

```text
/permissions                 查看待确认与本会话授权
/approve <confirmation_id>   单次批准
/deny <confirmation_id>      拒绝
/revoke <grant_id>           撤销尚未消费或仍有效的授权
/audit [limit]               查看脱敏审计摘要
```

批准和拒绝必须是幂等操作；过期、已消费、已撤销或上下文不匹配的确认不能执行。

## 5.4 Agent 与 Planner 恢复

Agent 遇到待确认调用时结束本轮执行并返回确认请求；批准后由保存的 continuation 恢复，不重新让模型生成这次 Tool Call。

Planner 增加 `WAITING_FOR_PERMISSION`（或等价的显式等待原因）：

- 保存 goal_id、step_id、invocation_id 与 confirmation_id；
- 批准后继续原步骤；
- 拒绝后生成 `permission_denied` Observation，由 Planner 决定安全 fallback、replan 或结束；
- fallback 若权限、工具或参数发生变化，必须重新评估；
- 用户取消 Goal 时同时撤销其未消费授权；
- 重试同一参数的同一调用可复用尚有效的单次调用授权，授权在成功执行或明确终止后消费。

---

# 6. 审计与隐私

## 6.1 审计模型

Permission Audit 与 Planner Trace 分离：

- Planner Trace 回答“任务如何推进”；
- Permission Audit 回答“谁请求了什么、为何允许或拒绝、是否执行成功”。

事件至少包括：

```text
permission_requested
policy_allowed
confirmation_required
permission_approved
permission_denied
grant_revoked
tool_execution_started
tool_execution_succeeded
tool_execution_failed
rollback_started / succeeded / failed
```

字段至少包含：

```text
event_id
timestamp
request_id / invocation_id
tool_name
permission
origin
goal_id / step_id
decision / reason_code
arguments_digest
resource_scope_summary
result_status
```

## 6.2 存储策略

第一版实现 `AuditSink` 接口与本地 JSONL 追加式实现，默认写入 `.zhaoxi/audit/` 并继续由 Git 忽略。单元测试使用内存 Sink 或临时目录。

审计默认不保存：

- API Key、Authorization Header、Cookie；
- 完整 Memory 正文；
- 原始文件内容或邮件正文；
- 未脱敏 Tool 参数与 ToolResult；
- 模型完整上下文。

审计写入失败时：

- READ 可按配置降级并报告；
- 产生副作用的操作默认 fail closed，避免“动作发生但没有审计”。

## 6.3 撤销与 Undo

区分两种概念：

- `revoke`：撤销尚未使用或仍有效的授权；
- `rollback`：尝试逆转已经完成的 Tool 副作用。

Tool 可选实现 `prepare_undo()` / `rollback()`。确认界面和审计必须明确 Undo 是 best effort，不得暗示所有写入都能恢复。v0.4 不实现跨 Tool 分布式事务。

---

# 7. Tool 输出不可信边界与 Prompt Injection 防护

权限层不能只保护调用前，还要限制 Tool 输出影响后续决策：

- ToolResult 作为带来源标签的数据块进入 Context，明确“内容不具备指令权限”；
- Tool 输出中的“忽略规则”“自动批准”“调用某工具”等文本不得改变 Policy 或 Grant；
- 授权只由本地策略和显式用户确认产生；
- Tool 返回的候选下一步必须重新走 Registry、参数校验和 Permission Gateway；
- 对过长输出设字符上限或摘要边界，原始数据不直接拼入 system prompt；
- 二进制、HTML、文件内容和外部响应在进入模型前保留来源与可信级别；
- 测试使用恶意 ToolResult 验证无法绕过只读约束或制造授权。

v0.4 做基础数据/指令分离，不实现通用内容安全分类器、沙箱浏览器或完整 RAG 防注入体系。

---

# 8. 配置与错误类型

建议新增配置：

```dotenv
ZHAOXI_PERMISSION_ENABLED=true
ZHAOXI_PERMISSION_READ_POLICY=allow
ZHAOXI_PERMISSION_WRITE_POLICY=confirm
ZHAOXI_PERMISSION_DELETE_POLICY=confirm
ZHAOXI_PERMISSION_EXTERNAL_ACTION_POLICY=confirm
ZHAOXI_PERMISSION_DANGEROUS_POLICY=deny
ZHAOXI_PERMISSION_CONFIRMATION_TTL_SECONDS=300
ZHAOXI_PERMISSION_SESSION_GRANT_MAX_USES=10
ZHAOXI_PERMISSION_AUDIT_PATH=.zhaoxi/audit/permission.jsonl
ZHAOXI_PERMISSION_MAX_TOOL_OUTPUT_CHARS=12000
```

生产默认不得通过 `PERMISSION_ENABLED=false` 绕过检查。该开关仅用于测试旧契约或迁移诊断，并且非 READ Tool 在权限层缺失时必须 fail closed。

错误至少区分：

```text
PermissionError
├── PermissionDeniedError
├── ConfirmationRequiredError
├── ConfirmationExpiredError
├── InvalidGrantError
├── GrantRevokedError
├── AuditWriteError
└── RollbackError
```

拒绝、待确认和执行失败是不同结果；不要把它们都伪装成普通 Tool Error。

---

# 9. 分阶段开发流程

## Phase 0：冻结基线与威胁模型

- 固定 55 项测试通过的 v0.3.2 基线；
- 列出所有内置 Tool 的权限、资源范围、是否可撤销和敏感字段；
- 为 Agent、Planner、Cognitive Router、Memory Tool 建立权限关闭/缺失时的回归测试；
- 写出最小威胁清单：模型越权、恶意 Tool 输出、参数替换、重复批准、审计泄密、Planner 重试绕过。

完成条件：旧行为和安全边界有测试保护，尚未改变执行路径。

## Phase 1：权限领域模型与 Tool 元数据

- 实现 PermissionLevel、SideEffect、PermissionRequest、Decision、Grant、PendingConfirmation；
- 扩展 Tool 合约并迁移全部内置 Tool；
- Registry 注册时执行元数据一致性校验；
- 为确认摘要和参数摘要建立稳定、可测试的规范化规则。

完成条件：所有 Tool 都有明确权限，缺失或矛盾声明会 fail closed。

## Phase 2：统一 ToolExecutor 与 Permission Gateway

- 抽取 Agent / Planner 共用 ToolExecutor；
- 实现默认 PermissionPolicy 与 Gateway；
- 保留 Planner 自己的超时、retry、fallback 和 Observation；
- 保留只读用户意图作为 Gateway 的强制约束；
- 阻止任何直接 `tool.run()` 的生产调用绕开 Gateway。

完成条件：Agent 和 Planner 通过同一执行门，旧测试继续通过。

## Phase 3：确认、恢复与授权生命周期

- 实现 PendingPermissionStore 与 session grant；
- Agent 支持返回确认并从原始调用恢复；
- Planner 支持等待权限、批准、拒绝、取消和继续；
- 实现 TTL、单次消费、幂等、撤销与参数摘要绑定；
- 增加 CLI 权限命令。

完成条件：WRITE 调用在确认前绝不执行，批准后只执行一次，拒绝和过期均不可执行。

## Phase 4：审计、脱敏与 Undo Hook

- 实现 AuditSink、内存测试实现与本地 JSONL 实现；
- 对策略、确认、执行、失败与撤销记录结构化事件；
- 统一 TOOL 日志和审计的敏感字段脱敏；
- 为支持的 Tool 接入可选 rollback hook；
- 明确审计故障的 fail-closed 行为。

完成条件：副作用调用可由审计记录还原决策链，日志中无敏感正文或凭据。

## Phase 5：不可信输出与注入防护

- 给 ToolResult 增加来源/信任元数据；
- ContextBuilder 使用稳定的数据边界注入 Tool 内容；
- 对输出长度、嵌套内容和候选动作重新验证；
- 增加恶意 Tool 输出、伪造批准文本和风险升级测试。

完成条件：任何 Tool 文本都不能产生 Grant、改变 Policy 或跳过下一次权限检查。

## Phase 6：文档、回归与发布

- 更新 `.env.example`、README、CLI 帮助和 `CODEBASE_STATUS.md`；
- 更新版本号和启动标识为 `0.4.0` / `v0.4 · Permission`；
- 运行全量 pytest、compileall、`git diff --check`；
- 手工验收 READ、WRITE、DELETE、拒绝、过期、撤销、Planner 恢复与恶意输出；
- 形成 v0.4 发布说明。

完成条件：最终验收清单全部通过。

---

# 10. 测试计划

测试继续使用 Fake Provider、临时目录与脚本化 Tool，不依赖真实 API、账号或网络。

## 10.1 单元测试

- 权限等级、Tool 元数据与 Registry 校验；
- 参数规范化与 digest 稳定性；
- 默认 Policy 的 allow / confirm / deny；
- 只读约束优先于自动许可；
- confirmation TTL、消费、撤销与幂等；
- grant 的 tool、参数、资源与 origin 绑定；
- AuditEvent 顺序、脱敏和容量/轮转边界；
- Tool 输出封装与长度限制；
- rollback hook 成功、失败和不支持。

## 10.2 集成测试

### A. READ 自动允许

```text
search_memory → policy allow → execute → audit success
```

### B. WRITE 待确认并批准

```text
remember_memory → confirmation required → 未执行
→ approve once → 原调用执行一次 → grant consumed
```

### C. DELETE 拒绝

```text
forget_memory → confirmation → deny → 数据保持不变
```

### D. 参数替换攻击

确认后改变 memory_id、正文或资源范围，旧 grant 必须失效。

### E. Planner 暂停与恢复

多步任务在 WRITE 步骤进入等待授权；批准后继续同一 Goal 和 Step，不重复已完成步骤。

### F. Retry 与 fallback

同一已授权调用的暂时性失败按策略重试；切换更高权限 Tool 或改变参数时重新确认。

### G. 审计故障

副作用调用在审计不可用时不执行；READ 的降级行为符合配置。

### H. Prompt Injection

恶意 Tool 输出声称“用户已经批准”“忽略系统规则”或要求调用删除工具，均不能产生授权或绕过 Gateway。

### I. 回归

v0.1 Agent、v0.2 Memory、v0.3 Planner、v0.3.1 Cognitive Integration 和 v0.3.2 Memory Lifecycle 全部保持通过。

---

# 11. 首批 Tool 权限映射

建议初始映射：

| Tool | 权限 | 说明 |
|---|---|---|
| `echo` | READ | 无业务副作用 |
| `calculator` | READ | 纯计算 |
| `current_time` | READ | 读取系统时间 |
| `search_memory` | READ | 读取长期记忆，输出需脱敏边界 |
| `remember_memory` | WRITE | 新增长期记忆 |
| `update_memory` | WRITE | 修改既有记忆 |
| `archive_memory` | WRITE | 状态迁移，可视为可恢复写入 |
| `reactivate_memory` | WRITE | 状态迁移 |
| `pin_memory` | WRITE | 改变自动生命周期策略 |
| `consolidate_memories` | WRITE | 新增语义记忆并归档旧记录 |
| `forget_memory` | DELETE | 进入遗忘状态，需明确确认 |

Auto Memory 是 Core 的后台副作用，不应因“不是 Tool”而绕过权限。v0.4 应将其 CREATE / UPDATE / MERGE / ARCHIVE / FORGET / CONSOLIDATE 动作接入同一策略边界；第一版可以选择：普通自动记忆仅允许 CREATE/UPDATE 的受限 session policy，高风险生命周期动作仍要求显式用户意图或直接拒绝后台执行。

---

# 12. 明确非目标

v0.4 不实现：

- 操作系统级沙箱、容器隔离或命令执行器；
- OAuth、账号连接、企业 RBAC、多用户与多租户权限；
- 永久云端授权同步和跨设备 Grant；
- 通用策略语言、ABAC 引擎或复杂角色继承；
- 跨多个 Tool 的原子事务与分布式回滚；
- Calendar、Gmail、GitHub、Life HUD 等真实外部 Tool；
- Workflow Engine、主动唤醒、定时任务与 GUI；
- 依赖模型判断危险等级或批准授权；
- 承诺所有动作可撤销；
- 完整的内容安全、网页隔离或 RAG 注入防护平台。

可以留下小而明确的接口，但不得提前实现 v0.5 之后的业务能力。

---

# 13. 风险与防护

| 风险 | v0.4 防护 |
|---|---|
| Agent 与 Planner 权限逻辑漂移 | 统一 ToolExecutor + Permission Gateway |
| 模型自行宣称用户已授权 | Grant 只由本地策略或显式确认产生 |
| 用户确认后参数被替换 | 不可变调用快照 + arguments digest + scope 绑定 |
| Planner retry 重复执行副作用 | invocation id、单次消费与幂等状态 |
| fallback 升级权限 | 每个新 Tool/参数重新评估 |
| “只读”只靠提示词 | Gateway 确定性拒绝非 READ Tool |
| 审计记录泄露隐私 | 摘要、digest、资源范围与统一脱敏 |
| 动作已执行但审计丢失 | 副作用操作在审计不可用时 fail closed |
| Tool 输出进行 Prompt Injection | 数据/指令分离，输出不能创建 Grant |
| Undo 造成虚假安全感 | 显式 capability，best-effort 状态与失败审计 |
| Auto Memory 绕过 Tool 权限 | 后台认知动作接入同一策略边界 |
| 关闭权限配置造成裸奔 | 非 READ 在 Gateway 缺失时 fail closed |

---

# 14. 最终验收清单

- [x] 55 项历史基线及当前 69 项自动化测试全部通过；
- [x] 每个 Tool 都有明确权限、资源范围与副作用声明；
- [ ] Agent、Planner 和 Auto Memory 的副作用经过统一策略边界；
- [x] READ 可按默认策略自动执行；
- [x] WRITE / DELETE / EXTERNAL_ACTION 在需要时可靠暂停并确认；
- [x] DANGEROUS 默认拒绝；
- [x] “只读”请求无法调用任何产生副作用的 Tool；
- [x] 批准绑定到原 Tool、原参数摘要和原资源范围；
- [x] 批准、拒绝、过期、消费和撤销均幂等且可测试；
- [x] Planner 可在同一 Goal 上等待授权并恢复；
- [ ] retry 不重复消费副作用，fallback 不越权；
- [x] 审计能还原请求、策略、确认和执行结果，但不保存敏感正文；
- [x] 审计故障时副作用操作 fail closed；
- [ ] 支持 Undo 的 Tool 可记录回滚成功或失败，不支持的 Tool 不虚假承诺；
- [ ] 恶意 Tool 输出不能改变 Policy、伪造 Grant 或绕过下一次检查；
- [x] `.env.example`、README、CLI、版本号和 `CODEBASE_STATUS.md` 更新为 v0.4；
- [x] 测试不依赖真实模型、网络、账号或真实用户 Memory 数据。

当“模型提出副作用动作 → 本地策略判定 → 用户明确确认 → 原调用仅执行一次 → 全链路脱敏审计 → Planner/Agent 安全继续”在确定性测试和 CLI 手工验收中稳定成立，并且新增 Tool 只需声明权限而无需修改 Core 分支逻辑时，v0.4 才算完成。

---

# 15. 推荐首个端到端验收场景

使用现有 Memory Tools 完成，不接入外部系统：

```text
用户：检查重复记忆，只整理确实重复的内容，不要忘掉任何东西。
```

验收流程：

1. `search_memory` 作为 READ 自动执行；
2. Planner 提出 `consolidate_memories`，进入 WRITE 确认；
3. 确认界面展示目标记忆 ID、动作摘要和可能归档旧记录的风险；
4. 未批准前数据库不变；
5. 批准后恢复同一 Goal，仅执行原调用一次；
6. Planner 若尝试 `forget_memory`，因用户只读/不遗忘约束而拒绝；
7. 恶意模拟 ToolResult 中的“自动批准删除”文本不能产生 Grant；
8. `/audit` 可看到 READ 自动许可、WRITE 确认、批准、执行成功和 DELETE 拒绝；
9. `/trace` 仍能独立解释 Planner 的步骤推进；
10. 任一等待状态均可取消，取消后 pending grant 失效。

这个场景同时覆盖权限声明、确认恢复、Planner 协作、用户约束、审计和 Tool 输出不可信边界，是 v0.4 最适合的第一条纵向切片。
