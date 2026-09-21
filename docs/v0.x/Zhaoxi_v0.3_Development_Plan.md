# Zhaoxi v0.3 · Planner 开发计划

> 版本目标：让朝汐能够把一个目标拆成可检查的多步计划，在执行中依据工具观察结果继续、重试、回退或重新规划，并留下完整执行轨迹。  
> 基线：v0.2 已具备 Agent Runtime、Tool Registry、长期 Memory 与跨 Session Context 注入。  
> 核心原则：Planner 负责任务状态与执行控制；具体能力仍由 Tools 提供，不把业务工具硬编码进 Core。

---

# 1. 一句话验收目标

完成以下真实闭环：

```text
用户提出多步目标
→ Planner 建立 Goal 和 Plan
→ 执行下一步 Action
→ 收集结构化 Observation
→ 根据结果继续 / 重试 / 回退 / Re-plan
→ 必要时等待用户补充信息
→ 可被用户取消
→ 在步数与总超时限制内给出最终结果
→ 返回可检查的 Execution Trace
```

v0.3 完成时必须支持：

- 一个目标连续调用多个工具并汇总结果；
- 工具暂时失败时按策略重试，而不是无限循环；
- 首选工具不可用时选择兼容的 fallback；
- Observation 推翻原计划时生成新修订版计划；
- 信息不足时暂停并向用户提出明确问题，补充后继续；
- 用户可以取消正在执行的任务；
- 最大执行步数、单步超时和总超时都能可靠终止任务；
- 每次规划、行动、观察和状态变化都有可检查的 Trace。

---

# 2. 本版架构决策

## 2.1 Planner 是 Core 能力，不是新 Tool

推荐结构：

```text
ZhaoxiAgent
    ↓
PlannerRuntime
├── Goal
├── Plan / PlanRevision
├── ExecutionState
├── RetryPolicy
└── ExecutionTrace
    ↓
ToolRegistry → Tool.execute() → Observation
```

- `ZhaoxiAgent` 继续作为单轮用户入口；
- `PlannerRuntime` 维护多步任务的生命周期和约束；
- `ToolRegistry` 仍是唯一工具发现与执行入口；
- `ContextBuilder` 负责把当前目标、计划、最近 Observation 和相关 Memory 注入模型；
- Provider 继续只返回厂商无关的内部类型。

禁止在 Planner 中出现 `if calendar`、`if files` 等具体业务分支。

## 2.2 使用线性、可修订计划，不实现 DAG

v0.3 的计划是有序步骤列表：

```text
Plan revision 1
├── Step 1 completed
├── Step 2 running
└── Step 3 pending

Observation 改变前提
→ Plan revision 2（保留 revision 1）
```

第一版不实现计划树、DAG 调度、并行依赖图或通用工作流语言。模型可以在单个 Action 中发出彼此独立的多个 Tool Call，但 Runtime 不负责复杂并行编排。

## 2.3 计划输出必须结构化

扩展 Provider-neutral 类型，让模型输出可以明确表达：

```text
direct_answer
plan
action
replan
request_user_input
final
```

优先复用现有 Tool Calling 协议承载 Action；Goal、Plan 和控制决策使用 Pydantic 模型验证。解析失败作为可恢复的规划错误处理，不让厂商私有响应进入 Core。

## 2.4 任务状态先做进程内持久化边界

定义 `PlanStore` 接口，v0.3 先实现 `InMemoryPlanStore`。任务应能跨多个用户回合暂停和继续，但不承诺进程重启恢复。

长期保存和崩溃恢复属于 v0.9 Reliability；本版只保证接口可替换，并避免把任务状态塞进 Conversation 或 Memory 数据库。

## 2.5 Memory 只提供上下文，不替代 Planner State

- 用户长期偏好和历史事实继续来自 Memory；
- 当前目标、步骤状态、重试次数和 Observation 属于 Planner；
- Execution Trace 不自动写入长期 Memory；
- Planner 故障不得破坏 v0.2 的普通对话与记忆能力。

---

# 3. 领域模型与状态机

## 3.1 核心模型

建议新增 `src/zhaoxi/planner/`：

```text
planner/
├── models.py
├── runtime.py
├── policy.py
├── store.py
└── trace.py
```

至少定义：

```text
Goal
- id
- description
- status
- created_at / updated_at

Plan
- goal_id
- revision
- steps[]
- reason

PlanStep
- id
- description
- status
- attempt_count
- tool_hints[]
- result_summary

Observation
- step_id
- tool_name
- success
- content / data / error
- retryable
- timestamp

ExecutionTrace
- trace_id / request_id / goal_id
- ordered events[]
- started_at / finished_at
- final_status
```

所有状态值使用 Enum，所有模型使用 Pydantic 或不可变数据类，禁止散落魔法字符串。

## 3.2 状态

Goal 状态至少包括：

```text
pending
planning
running
waiting_for_user
completed
failed
cancelled
```

Step 状态至少包括：

```text
pending
running
completed
failed
skipped
cancelled
```

终态不可再次执行。每次状态迁移必须通过统一方法校验并写入 Trace。

## 3.3 计划修订

Re-plan 必须：

- 说明触发原因；
- 创建递增 revision，不覆盖旧计划；
- 保留已完成步骤及其 Observation；
- 明确哪些旧步骤被取消、跳过或替换；
- 受 `max_replans` 限制。

---

# 4. Planner Runtime

## 4.1 执行流程

```text
receive goal
→ retrieve relevant memory
→ create validated plan
→ select next pending step
→ ask model for action
→ execute through Tool Registry
→ normalize ToolResult as Observation
→ evaluate progress
   ├── continue
   ├── retry
   ├── fallback
   ├── re-plan
   ├── wait for user
   └── finish
```

Runtime 负责控制流，模型负责语义判断。步数、超时、重试次数、状态合法性和取消检查必须由确定性代码保证，不能只靠 Prompt。

## 4.2 与现有 Agent Loop 的迁移

先把当前 `ZhaoxiAgent._run_loop()` 中这些能力提取成可复用执行原语：

- Provider 调用；
- Tool Call 执行；
- ToolResult → Observation；
- Conversation 回填；
- 最大步数与超时处理。

保持 `ZhaoxiAgent.run()` 公共调用方式兼容。普通聊天和简单单工具请求仍走轻量路径；只有需要显式多步规划的目标才建立 Planner Task。

不要并存两套互相漂移的工具执行逻辑。

## 4.3 Retry Policy

默认策略建议：

```text
max_attempts_per_step = 2
max_replans = 3
```

仅当错误被标记为可重试时重试，例如暂时性 Provider/网络/工具错误。参数校验失败、工具不存在和明确的业务拒绝默认不可原样重试，应修正 Action、选择 fallback 或 Re-plan。

重试必须：

- 记录 attempt；
- 保存每次 Observation；
- 可采用小幅退避；
- 受总超时和取消信号约束。

## 4.4 Tool fallback

fallback 由模型基于 Tool Schema 和失败 Observation 选择，但 Runtime 强制：

- fallback 工具必须已注册；
- 输入必须通过该工具自己的 schema；
- 不允许提升到更高风险操作；
- 同一失败组合不能无限来回切换；
- Trace 记录首选工具、失败原因和替代选择。

v0.3 不提前实现完整 Permission 等级；涉及写入、删除或外部动作的真实工具仍不在本版接入。

## 4.5 用户补充信息

信息不足时返回结构化 `InputRequest`：

```text
goal_id
question
missing_fields[]
resume_token
```

任务进入 `waiting_for_user`。后续用户消息通过 `resume(goal_id, answer)` 继续同一个任务，而不是创建新 Goal。重复恢复、错误 token 或已终止任务返回清晰错误。

## 4.6 Cancellation

提供协作式取消：

- `cancel(goal_id)` 设置取消信号；
- 每次模型调用和 Tool 执行前后检查；
- 正在等待用户时可立即取消；
- 可取消的异步调用传播 `CancelledError`；
- 任务以 `cancelled` 终止并写 Trace；
- 已完成任务取消为幂等操作或明确 no-op。

不承诺强行终止不响应取消的第三方同步代码。

---

# 5. 配置与错误处理

新增配置建议：

```dotenv
ZHAOXI_PLANNER_ENABLED=true
ZHAOXI_PLANNER_MAX_STEPS=12
ZHAOXI_PLANNER_MAX_REPLANS=3
ZHAOXI_PLANNER_MAX_ATTEMPTS_PER_STEP=2
ZHAOXI_PLANNER_STEP_TIMEOUT_SECONDS=30
ZHAOXI_PLANNER_TOTAL_TIMEOUT_SECONDS=180
ZHAOXI_PLANNER_TRACE_MAX_EVENTS=200
```

Pydantic Settings 负责范围校验，且满足：

```text
step timeout <= total timeout
max attempts <= max steps
```

错误类型至少区分：

```text
PlannerError
├── PlanValidationError
├── InvalidStateTransitionError
├── StepExecutionError
├── ReplanLimitError
├── PlannerTimeoutError
├── TaskNotFoundError
└── TaskCancelledError
```

用户看到简洁、可操作的信息；Trace 和开发日志保留技术原因，但不记录 API Key、敏感环境变量或不必要的 Memory 全文。

---

# 6. Execution Trace 与可观察性

Trace 使用结构化事件，而不是拼接日志字符串：

```text
goal_created
plan_created
step_started
tool_called
observation_received
step_retried
fallback_selected
plan_revised
input_requested
task_resumed
task_cancelled
task_completed / task_failed
```

每个事件至少包含：

```text
event_id
trace_id
goal_id
plan_revision
step_id
event_type
timestamp
metadata
```

`AgentResponse` 在不破坏现有字段的前提下增加可选的 `goal_id`、`status` 和 `trace`/`trace_id`。默认日志只写 ID、状态、耗时和数量；Tool 参数与结果的敏感内容需脱敏或只在 DEBUG 显示。

CLI 最少增加：

```text
/plan              查看当前任务与计划
/trace [goal_id]   查看精简执行轨迹
/cancel [goal_id]  取消任务
```

---

# 7. 测试计划

测试不得依赖真实 LLM API、真实网络或外部业务系统。扩展 `FakeProvider`，新增确定性的脚本化 Tools。

## 7.1 单元测试

- Goal / Plan / Step 模型校验；
- 合法与非法状态迁移；
- revision 递增和历史保留；
- RetryPolicy 边界；
- Trace 事件顺序与容量限制；
- InMemoryPlanStore CRUD 与终态保护；
- 配置交叉约束；
- Cancellation 幂等性。

## 7.2 集成测试

### A. 正常多步任务

```text
Goal → Plan(3 steps) → Tool A → Tool B → Tool C → Final
```

断言工具顺序、Observation 注入、步骤状态和最终 Trace。

### B. 可重试失败

```text
Tool transient failure → retry → success → continue
```

断言不超过策略限制且两次 Observation 都保留。

### C. fallback

```text
preferred tool unavailable → alternative registered tool → success
```

断言不存在硬编码工具名。

### D. Re-plan

```text
Observation invalidates assumption → revision 2 → replacement steps → Final
```

断言 revision 1 未被覆盖。

### E. 等待用户并恢复

```text
missing information → waiting_for_user → resume(answer) → continue → Final
```

### F. 取消

分别覆盖运行中、重试前和等待用户时取消。

### G. 防无限执行

覆盖最大步数、最大 Re-plan、单步超时和总超时。

### H. 回归

v0.1 的直接回答、单/多 Tool、错误与循环保护，以及 v0.2 的记住、检索、修改、遗忘、跨 Session 注入全部继续通过。

---

# 8. 分阶段实施顺序

## Phase 0：冻结基线

- 运行并记录当前全部测试；
- 固定 `ZhaoxiAgent.run()`、Tool、Provider、Memory Retriever 的现有契约；
- 增加 Planner 关闭时的回归测试。

完成条件：v0.2 行为有测试保护，尚未改变生产逻辑。

## Phase 1：领域模型与状态机

- 建立 `planner/models.py`、状态 Enum 和迁移规则；
- 实现 Plan revision；
- 实现 `PlanStore` 与 `InMemoryPlanStore`；
- 实现结构化 Trace。

完成条件：不调用模型和工具即可完整测试任务生命周期。

## Phase 2：抽取统一执行原语

- 从现有 Agent Loop 提取 Provider/Tool 执行边界；
- 将 ToolResult 标准化为 Observation；
- 保持普通聊天、单 Tool 和 Memory Tool 行为不变。

完成条件：旧测试全部通过，工具执行逻辑只有一套。

## Phase 3：规划与多步执行

- 实现结构化计划生成和校验；
- 将目标、计划和 Observation 接入 ContextBuilder；
- 实现步骤推进和最终汇总；
- 增加最大步骤与双层超时。

完成条件：确定性 Fake Provider 下三步任务闭环通过。

## Phase 4：恢复策略

- 实现 retry 分类与次数限制；
- 实现 fallback 选择约束；
- 实现 Re-plan 与 revision 历史；
- 补充失败终态和错误呈现。

完成条件：失败、fallback 和 Re-plan 集成测试全部通过且无死循环。

## Phase 5：交互控制

- 实现 `waiting_for_user`、InputRequest 和 resume；
- 实现取消信号；
- 增加 `/plan`、`/trace`、`/cancel`；
- 确认多 Session/多 Goal 时目标选择明确。

完成条件：暂停恢复与取消在各边界可靠工作。

## Phase 6：文档、回归与发布

- 更新 `.env.example`、README、架构图和使用示例；
- 更新版本号为 `0.3.0`；
- 执行完整测试与手工 CLI 验收；
- 检查日志、Trace 和错误信息不泄露敏感内容；
- 形成 v0.3 发布说明。

完成条件：最终验收清单全部通过。

---

# 9. 明确非目标

v0.3 不实现：

- DAG、计划树、通用 Workflow Engine；
- 可复用 Workflow 模板（属于 v0.5）；
- 多 Agent、Agent 团队或任务委派；
- 完整权限等级、审批与审计系统（属于 v0.4）；
- 写入型 Calendar、Gmail、GitHub 等真实外部工具；
- 后台定时任务和 Proactive Agent；
- 进程重启后的 Planner Task 恢复；
- 分布式队列、并行调度器或远程 Worker；
- Planner Trace 自动写入长期 Memory；
- Embedding、向量检索或外部 RAG；
- 为演示“自主性”而移除步数、超时或取消限制。

可以预留小而明确的接口，但不得提前实现后续版本。

---

# 10. 风险与防护

| 风险 | v0.3 防护 |
|---|---|
| Planner 与旧 Agent Loop 形成两套执行逻辑 | 先抽取统一 Provider/Tool 执行原语 |
| 模型产生无效或空计划 | Pydantic 校验、有限修复、失败终态 |
| 失败后无限重试或反复 Re-plan | attempts、replans、steps、total timeout 四重上限 |
| 工具失败被模型误当成功 | 结构化 Observation，success/error 明确分离 |
| Re-plan 丢失历史 | 计划 revision 只追加、不覆盖 |
| 等待用户后创建重复任务 | goal_id + resume token + 状态校验 |
| 取消后仍继续调用工具 | 每个外部边界前后检查取消信号 |
| Planner State 污染长期 Memory | 独立 PlanStore，不自动写 Memory |
| Trace 泄露敏感数据 | 默认记录 ID/状态/摘要，限制参数与全文日志 |
| 提前承担 Permission 职责 | v0.3 只运行当前低风险工具，风险升级留给 v0.4 |

---

# 11. 最终验收清单

- [ ] 当前全部 v0.1 / v0.2 测试保持通过；
- [ ] 普通对话和简单 Tool Call 不被强制规划；
- [ ] 多步 Goal 能形成结构化、可检查的 Plan；
- [ ] 连续多个 Action/Observation 能推进到 Final；
- [ ] 可重试失败严格遵守次数和超时限制；
- [ ] 首选工具失败时可以通过 Registry 使用 fallback；
- [ ] Re-plan 保留旧 revision 与已完成步骤；
- [ ] 信息不足时任务可暂停、补充后可恢复；
- [ ] 运行中和等待中的任务都可取消；
- [ ] max steps、max replans、step timeout、total timeout 全部有效；
- [ ] Execution Trace 能还原规划、行动、观察和状态迁移；
- [ ] Planner 关闭或故障时，普通聊天和 v0.2 Memory 能力可降级使用；
- [ ] 测试不依赖真实模型、网络或外部系统；
- [ ] README、`.env.example`、CLI 帮助和版本号更新为 v0.3；
- [ ] 日志和 Trace 不泄露 API Key 或不必要的敏感内容。

当“多步计划 → 多工具执行 → 失败恢复/Re-plan → 用户补充或取消 → 最终结果与完整 Trace”能够在确定性测试和 CLI 手工验收中稳定跑通，且新增任何具体 Tool 仍无需修改 Planner Runtime 时，v0.3 才算完成。

---

# 12. 推荐首个验收场景

在尚未接入 Calendar、Files、GitHub 等真实系统前，使用三个测试工具模拟“面试准备”：

```text
用户：帮我准备明天下午的面试。

Planner：
1. 获取面试时间与岗位信息
2. 获取公司资料
3. 获取历史面试复盘
4. 汇总准备重点
```

验收至少覆盖：

1. 缺少公司名称时进入 `waiting_for_user`；
2. 用户补充后恢复原 Goal；
3. 首选资料工具暂时失败，重试一次；
4. 仍失败时切换模拟 fallback；
5. 新 Observation 发现面试时间变化，生成 revision 2；
6. 最终给出准备清单；
7. `/trace` 能解释全过程；
8. 任一步均可通过 `/cancel` 停止。

该场景只验证 Core Planner，不接入真实外部服务，从而让底层执行正确性不依赖网络、账号或不可重复的第三方数据。
