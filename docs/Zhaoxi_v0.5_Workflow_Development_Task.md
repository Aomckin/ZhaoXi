# Zhaoxi v0.5 · Workflow 开发任务书

> 版本目标：让朝汐把高频、稳定的复杂操作固化为可复用 Workflow，并在参数校验、条件分支、权限确认、暂停恢复、失败重试和执行历史方面形成确定性的运行边界。
>
> 开发基线：v0.4 已具备 Cognitive Router、Agent Runtime、Planner、长期 Memory、统一 Permission Gateway 与审计能力；当前版本号为 `0.4.0`，验证基线为 69 项自动化测试通过。
>
> 首个真实纵向切片：通过独立 `lifehud-tool` 调用 Life HUD 的 Focus API，完成“铁幕开幕 → 查询状态 → 过程控制 → 铁幕落幕”的工作流闭环。Life HUD 是外部事实系统，本仓库不复制其 FocusSession、FocusSegment 或统计逻辑。

---

# 1. 一句话验收目标

```text
用户表达高频复杂意图
→ Cognitive Router 识别为 Workflow 候选
→ Workflow Registry 匹配已注册定义
→ 校验并补齐参数
→ 创建可追踪的 Workflow Run
→ 按步骤调用 ToolExecutor
→ 权限不足时暂停确认
→ 根据结果继续、分支、重试或失败
→ 用户可暂停、恢复或取消
→ 产出结构化结果和执行历史
```

v0.5 完成时至少支持：

- 列出、查看并运行已注册 Workflow；
- 通过自然语言或 CLI 启动 Workflow；
- 参数默认值、必填校验与运行前预览；
- 顺序步骤、条件分支、有限重试和显式跳过；
- 等待用户输入或权限时暂停，并在同一个 Run 上恢复；
- 取消后不再执行后续副作用；
- 每个步骤都经过现有 `ToolExecutor` 与 Permission Gateway；
- Workflow 定义版本与运行快照绑定，执行中修改定义不改变既有 Run；
- 查询执行状态、结果与有界历史；
- 铁幕开幕和落幕两个真实场景可通过 Life HUD Tool 跑通。

---

# 2. 架构边界

## 2.1 Workflow、Planner 与 Agent 的职责

```text
Cognitive Router
├── DIRECT    普通回答
├── TOOL      单次工具调用
├── PLAN      开放式、多步、需动态推理的目标
└── WORKFLOW  已知、稳定、可复用的执行模板
```

- **Planner** 面向开放目标，允许模型动态拆解和 Re-plan；
- **Workflow** 面向已知流程，步骤结构由版本化定义提供，Runtime 确定性推进；
- **Agent** 负责统一入口、上下文与自然语言交互；
- **Tool** 负责真实外部能力；Workflow 不直接访问 HTTP、数据库或文件系统；
- Planner 可以建议或调用一个 Workflow，但不能在 v0.5 中动态生成并永久注册 Workflow。

## 2.2 Workflow 不是第二套权限系统

每个 Tool Step 必须复用 v0.4 的：

```text
WorkflowRuntime
→ ToolExecutor
→ PermissionGateway
→ ToolRegistry
→ Tool.execute()
```

模型和 Workflow 定义都不能直接授予权限。确认应绑定冻结后的 Tool 名称、参数摘要、资源范围和 invocation ID；恢复后消费单次授权。Workflow 级预览可以汇总预计副作用，但不能替代逐调用的确定性权限判断。

## 2.3 Workflow State 不进入 Memory

- 当前步骤、变量、重试次数、暂停原因和输出属于 Workflow Store；
- 用户长期偏好仍属于 Memory；
- Workflow Run 不自动写入长期 Memory；
- 可复用查询结果只保留在有界运行历史，不复制为长期事实。

## 2.4 首版采用受限 DSL，不执行任意代码

Workflow 定义使用 YAML，加载后转为 Pydantic 领域模型。首版只允许：

- `tool`：调用已注册 Tool；
- `condition`：基于已知变量进行白名单比较；
- `ask`：请求用户补充参数或选择；
- `set`：从常量或已完成步骤输出中提取变量；
- `end`：以成功、失败或取消终止。

禁止 `eval`、任意 Python、Shell、Jinja 任意表达式和动态 import。表达式只支持 `eq/ne/in/exists/and/or/not` 等小型白名单操作符。

---

# 3. 建议模块

```text
src/zhaoxi/workflow/
├── __init__.py
├── models.py          # Definition、Step、Run、Event、状态枚举
├── loader.py          # YAML 加载、schema 校验、版本检查
├── registry.py        # 工作流发现与版本索引
├── runtime.py         # 确定性状态推进
├── expressions.py     # 受限条件求值
├── bindings.py        # 参数与 Tool 输出绑定
├── store.py           # Store 接口及首版实现
└── trace.py           # 结构化、有界事件

src/zhaoxi/tools/integrations/lifehud/
├── __init__.py
├── client.py
├── models.py
└── focus_tools.py

workflows/
└── lifehud/
    ├── iron_curtain_open_v1.yaml
    └── iron_curtain_close_v1.yaml
```

实现时可以按现有代码风格微调路径，但不得把 Life HUD 特判写进 `WorkflowRuntime`、Planner 或 Cognitive Router。

---

# 4. 领域模型与状态机

## 4.1 Workflow Definition

至少包含：

```text
WorkflowDefinition
- id                         稳定标识，如 lifehud.iron_curtain.open
- version                    独立定义版本，如 1
- name / description
- aliases                    自然语言匹配提示，不直接决定执行
- input_schema               参数、类型、默认值、敏感性
- steps[]
- output_schema
- tags
- enabled
```

每个步骤至少包含：

```text
WorkflowStep
- id                         定义内唯一且稳定
- type                       tool | condition | ask | set | end
- input / bindings
- when                       可选受限条件
- retry_policy
- on_success / on_failure
- output_mapping
```

加载时必须拒绝：重复 ID、未知步骤类型、跳转到不存在步骤、不可达终点、循环无上限、未知 Tool 和非法表达式。首版默认禁止任意循环；如需轮询，只允许带确定次数与间隔上限的专用重试策略。

## 4.2 Workflow Run

```text
WorkflowRun
- id
- workflow_id / workflow_version
- definition_snapshot
- status
- current_step_id
- inputs
- variables
- step_runs[]
- pending_reason
- created_at / updated_at / finished_at
- result / error
```

Run 状态至少包括：

```text
pending
running
waiting_for_input
waiting_for_permission
paused
completed
failed
cancelled
```

Step 状态至少包括：

```text
pending
running
waiting
completed
failed
skipped
cancelled
```

要求：

- 所有状态迁移通过统一方法校验；
- 终态不可恢复执行；
- `resume` 必须带 Run ID，并校验当前暂停原因；
- Tool 调用前先持久化冻结的 invocation；
- Tool 完成后先记录结果，再推进下一步；
- 进程内重复恢复不得重复触发已成功副作用。

## 4.3 Store 策略

v0.5 采用两层交付：

1. 先实现 `InMemoryWorkflowStore` 固定接口和状态机；
2. 再实现标准库 `sqlite3` 的 `SQLiteWorkflowStore`，保证进程重启后可查询和恢复未完成 Run。

默认路径建议：

```dotenv
ZHAOXI_WORKFLOW_DB_PATH=.zhaoxi/workflow.db
ZHAOXI_WORKFLOW_HISTORY_LIMIT=100
ZHAOXI_WORKFLOW_MAX_STEPS=50
ZHAOXI_WORKFLOW_MAX_RETRIES=3
ZHAOXI_WORKFLOW_RUN_TIMEOUT_SECONDS=1800
```

SQLite schema 必须版本化并使用临时数据库测试；不得把 Workflow 状态塞进 Memory 数据库表。

---

# 5. Runtime 执行语义

## 5.1 启动

```text
resolve workflow id/version
→ validate inputs
→ freeze definition snapshot
→ render side-effect preview
→ create Run
→ advance until terminal or waiting state
```

缺少必填参数时进入 `waiting_for_input`，不得让模型猜测高风险参数。对于只影响展示的可选参数，可以使用定义中的默认值。

## 5.2 Tool Step

- 参数绑定只能读取 `inputs`、`variables` 和已完成 `step_outputs`；
- 调用前使用 Tool 自身 Pydantic schema 再校验一次；
- 统一生成 invocation ID 并经 `ToolExecutor` 执行；
- `ToolResult` 保持不可信数据标记和长度限制；
- 输出映射只能提取显式字段，不把整段外部文本当作指令；
- `retryable=false` 时禁止重试；
- WRITE/DELETE/EXTERNAL_ACTION/DANGEROUS 的执行语义完全继承 v0.4。

## 5.3 暂停与恢复

暂停原因分离处理：

- `waiting_for_input`：仅接受与当前问题绑定的用户补充；
- `waiting_for_permission`：沿用现有确认 ID、批准/拒绝和过期逻辑；
- `paused`：用户主动暂停，只有显式恢复才继续；
- 外部 Tool 暂时不可用：按定义重试耗尽后进入 failed，不无限等待。

恢复时不得重新运行已完成 Step。权限拒绝按定义选择失败、跳过或补偿；默认失败并停止，避免静默越过关键动作。

## 5.4 取消与补偿

- 取消立即阻止新 Step 启动，并使待确认授权失效；
- v0.5 不承诺通用事务回滚；
- Workflow 可声明显式 `compensation` Tool Step，但必须单独经过权限判断；
- 已成功的外部副作用必须在结果中明确列出，不能声称“完全取消”；
- 铁幕开幕后取消朝汐 Run，不得自动落幕，除非用户明确批准执行落幕补偿。

## 5.5 幂等与崩溃窗口

- 每个 Tool Step 生成稳定的 `run_id + step_id + attempt` 幂等键；
- integration Tool 在外部 API 支持时传递该键；不支持时至少记录请求指纹；
- 若崩溃发生在“外部成功、结果尚未落库”窗口，恢复时先执行只读核验，再决定是否重试；
- 无法核验的写操作必须进入 `waiting_for_input`，禁止盲目重放。

---

# 6. Cognitive Router、Planner 与 CLI 集成

## 6.1 路由

扩展路由结果为 `WORKFLOW`，至少返回：

```text
route
workflow_id
confidence
reason
extracted_inputs
```

安全规则：

- 低置信度只推荐，不自动执行；
- 有副作用的 Workflow 必须展示即将执行的关键动作；
- 用户明确说“只规划/不要执行”时只返回 Workflow 预览；
- 无匹配 Workflow 时回退 TOOL、PLAN 或 DIRECT，不临时拼接未注册流程。

## 6.2 Planner 协同

Planner 可以把已注册 Workflow 作为一个有边界的执行单元：

```text
开放目标
→ Planner 选择 workflow.run
→ Workflow Runtime 完成稳定子流程
→ 结构化结果成为 Planner Observation
```

首版只允许 Planner 调用已注册、enabled 的 Workflow；不得让 Planner 修改定义或绕过参数与权限校验。

## 6.3 CLI

新增开发者入口：

```text
/workflows
/workflow show <workflow_id>
/workflow run <workflow_id> [JSON 参数]
/workflow status <run_id>
/workflow resume <run_id> [补充内容]
/workflow pause <run_id>
/workflow cancel <run_id>
/workflow history [limit]
```

自然语言入口与 CLI 必须汇入同一个 Runtime，不维护第二套执行逻辑。

---

# 7. Life HUD Tool 边界

## 7.1 集成原则

- Life HUD 项目保持独立，v0.5 不修改其代码和数据文件；
- 朝汐通过可配置 Base URL 的 HTTP Tool 调用公开 REST API；
- Client 隔离 HTTP、超时、状态码、JSON 解析和错误归一化；
- Tool 模型只依赖稳定契约，不 import Life HUD Java 类型；
- Life HUD 仍是 FocusSession、Segment、实际时长和有效时长的唯一事实来源；
- 朝汐只保存 Run 所需的外部 ID 与有界结果快照。

建议配置：

```dotenv
ZHAOXI_LIFEHUD_BASE_URL=http://127.0.0.1:8080
ZHAOXI_LIFEHUD_TIMEOUT_SECONDS=10
```

API Key 等认证配置若后续存在，应走敏感配置与日志脱敏；v0.5 不自创 Life HUD 认证协议。

## 7.2 首批 Focus Tools

| Tool | API | Permission | 用途 |
|---|---|---:|---|
| `lifehud_focus_current` | `GET /api/focus/current` | READ | 查询当前 Focus |
| `lifehud_focus_today` | `GET /api/focus/today` | READ | 查询今日统计 |
| `lifehud_focus_start` | `POST /api/focus/start` | WRITE | 开启铁幕/番茄/自由专注 |
| `lifehud_focus_pause` | `POST /api/focus/{id}/pause` | WRITE | 暂停当前 Focus |
| `lifehud_focus_resume` | `POST /api/focus/{id}/resume` | WRITE | 恢复当前 Focus |
| `lifehud_focus_switch_segment` | `POST /api/focus/{id}/segments/switch` | WRITE | 切换事项、休息或中断 |
| `lifehud_focus_complete` | `POST /api/focus/{id}/complete` | WRITE | 正常落幕 |
| `lifehud_focus_interrupt` | `POST /api/focus/{id}/interrupt` | WRITE | 中断结束 |

首版最低交付为 current/start/complete；pause/resume/switch 可在纵向切片稳定后补齐。所有写 Tool 都必须声明具体资源范围，例如 `lifehud.focus:<session_id>`。

## 7.3 外部状态冲突

必须明确处理：

- Life HUD 未启动或连接超时；
- `/current` 表示当前无 Focus；
- 已有 RUNNING/PAUSED Session 时再次开幕；
- Run 保存的 session ID 与 Life HUD 当前 Session 不一致；
- 目标 Session 已完成或被其他客户端结束；
- 返回未知枚举、缺字段或非 JSON 错误体。

冲突时先返回可理解状态，不覆盖或猜测 Life HUD 数据。

---

# 8. 铁幕 Workflow

## 8.1 “朝汐，开幕”

工作流 ID：`lifehud.iron_curtain.open`

输入：

```text
title               必填；当前主要目标
related_task_ids    可选
```

流程：

```text
查询当前 Focus
├── 已有 RUNNING/PAUSED
│   → 告知现状并询问：继续当前、恢复、还是取消本次开幕
└── 当前为空
    → 预览将创建 IRON_CURTAIN
    → 经 WRITE 权限确认
    → POST /api/focus/start
    → 校验 mode=IRON_CURTAIN 且状态有效
    → 保存 session_id
    → 返回“铁幕已开幕”、目标和开始时间
```

请求体契约按 Life HUD 当前 API：

```json
{
  "mode": "IRON_CURTAIN",
  "title": "开发朝汐 v0.5",
  "taskId": null,
  "plannedMinutes": null,
  "breakMinutes": null,
  "relatedTaskIds": []
}
```

不得在朝汐侧创建假的 Focus ID、计时器或 Segment。

## 8.2 “朝汐，落幕”

工作流 ID：`lifehud.iron_curtain.close`

输入：

```text
note    可选；完成总结
```

流程：

```text
查询当前 Focus
├── 无当前 Session → 返回“当前没有可落幕的铁幕”，不写入
├── mode 不是 IRON_CURTAIN → 明确提示当前模式并请求确认，不误结束
└── 当前为 IRON_CURTAIN
    → 展示 session_id、目标和当前时长
    → 经 WRITE 权限确认
    → POST /api/focus/{id}/complete
    → 校验终态
    → 返回实际时长、有效时长、Segments 与 note 摘要
```

## 8.3 过程控制

在基础开幕/落幕验收后补充：

- “暂停铁幕” → current → 校验 IRON_CURTAIN/RUNNING → pause；
- “继续铁幕” → current → 校验 IRON_CURTAIN/PAUSED → resume；
- “接下来做 Java” → current → switch FOCUS Segment；
- “休息一下” → current → switch BREAK Segment；
- “被电话打断了” → current → switch INTERRUPTION Segment。

这些可以是独立 Workflow，也可以是复用统一 `lifehud.focus.control` 的受限动作参数；优先选择定义更少、边界更清晰的方案。

---

# 9. 开发阶段

## Phase 0：冻结 v0.4 基线

- 在 `v0.5` 分支确认工作区、提交和 69 项测试基线；
- 为 Agent、Planner、Permission Pending 恢复和 ToolExecutor 补关键契约测试；
- 明确 Workflow 与 Planner 的状态、Trace、Store 命名，避免复用同名模型造成语义混乱；
- 记录 Life HUD Focus API 当前契约，仅作为只读参考。

完成条件：无功能改动时 v0.4 全量回归通过。

## Phase 1：定义模型、Loader 与 Registry

- 实现 Definition、Step、Input、Output、RetryPolicy 模型；
- 建立 YAML schema、版本规则和稳定错误信息；
- 实现 Registry 的注册、禁用、按 ID/version 查询；
- 检测重复、无效跳转、非法表达式、未知 Tool 和无界循环；
- 提供最小纯内存测试 Workflow。

完成条件：无 Agent/LLM 参与即可加载、校验和列出 Workflow。

## Phase 2：Runtime 与 InMemory Store

- 实现 Run/Step 状态机和统一迁移；
- 实现 tool/condition/ask/set/end；
- 输入绑定、输出提取、错误归一化和有界 Trace；
- 支持暂停、恢复、取消、有限重试；
- 所有 Tool Step 接入 ToolExecutor；
- Fake Tool 覆盖成功、失败、超时、重试和权限等待。

完成条件：确定性测试可完整跑通分支 Workflow，且权限确认前没有副作用。

## Phase 3：持久化与恢复

- 实现 SQLiteWorkflowStore 和 schema version；
- 原子保存 Run、Step Run、冻结 invocation 和事件；
- 重启后查询、恢复 waiting/paused Run；
- 已完成步骤不重放；
- 处理不确定外部结果的核验/人工确认路径；
- 增加历史上限、清理策略和敏感字段脱敏。

完成条件：进程重启后能恢复等待输入或权限的同一个 Run。

## Phase 4：路由、Planner 与 CLI

- Cognitive Router 增加 WORKFLOW；
- Workflow Registry 摘要以有界方式提供给 Router；
- 低置信度推荐、只预览和显式执行语义；
- Planner 将 Workflow 作为有边界执行单元；
- 完成 `/workflows`、run/status/resume/pause/cancel/history；
- 保持 DIRECT、TOOL、PLAN 和 v0.4 权限命令回归。

完成条件：自然语言与 CLI 启动同一 Workflow，并得到相同状态与审计结果。

## Phase 5：lifehud-tool 最小纵向切片

- 实现 HTTP Client、配置、超时和错误模型；
- 实现 current/start/complete 三个 Focus Tool；
- Tool 参数与返回值使用独立 Pydantic 模型；
- 注册资源范围和 WRITE 权限；
- 用 MockTransport 固化 Life HUD 请求体、状态码和畸形响应；
- 不依赖运行中的真实 Life HUD 完成自动测试。

完成条件：Tool 单测证明不会写错模式、session ID 或 endpoint。

## Phase 6：铁幕 Workflow

- 编写并注册 open/close v1 定义；
- 覆盖已有 Focus、非铁幕 Focus、PAUSED、完成冲突和无当前 Focus；
- 权限拒绝、过期、取消与恢复均不重复调用；
- 最终回复使用 Life HUD 返回的真实 startedAt、actual/effective 和 Segments；
- 视稳定性补 pause/resume/switch 过程控制。

完成条件：“开幕 → 查询 → 落幕”在 Mock 集成和本地手工 smoke test 中均成功。

## Phase 7：收尾与发布

- 更新版本号至 `0.5.0`；
- 更新 README 架构、能力、CLI、配置和安全边界；
- 更新 `CODEBASE_STATUS.md` 的分支、测试数、限制和提交基线；
- 增加 Workflow 定义编写说明和最小示例；
- 全量 pytest、compileall、`git diff --check`；
- 检查 `.zhaoxi` 数据库、审计、凭据和 Life HUD 用户数据未被提交。

---

# 10. 测试矩阵

## Definition / Loader

- 合法 YAML、Unicode 和版本选择；
- 重复 Workflow/Step ID；
- 未知 Tool、未知字段和非法绑定；
- 跳转不存在、不可达 end、循环无上限；
- 条件表达式不能执行代码或读取环境变量；
- 定义更新不改变已创建 Run 的 snapshot。

## Runtime

- 顺序执行、条件分支、skip 和 end；
- 必填参数缺失后 ask/resume；
- ToolResult 输出提取与缺字段错误；
- retryable 与 non-retryable；
- 最大步骤、最大重试、总超时；
- pause/resume/cancel；
- 终态不可重启；
- Trace 顺序、长度和敏感信息脱敏。

## Permission

- READ 自动允许；
- WRITE 等待确认后执行一次；
- 拒绝、过期、撤销和取消；
- 参数变化不能复用授权；
- 恢复后原 invocation ID 与 Tool Call 绑定；
- 补偿动作再次独立确认。

## Persistence

- schema 首次创建和重复 migration；
- waiting_for_input / waiting_for_permission / paused 重启恢复；
- completed Step 不重复执行；
- 外部成功但本地状态不确定时不盲目重放；
- 中文参数、JSON、UTC 时间 round-trip；
- 测试只使用临时数据库。

## Life HUD Integration

- Base URL、路径拼接和超时；
- current 无内容、RUNNING、PAUSED；
- start 请求固定使用 `IRON_CURTAIN`；
- complete 使用 current 返回的 session ID；
- 409、404、500、非 JSON、缺字段和未知枚举；
- 日志不输出凭据或完整私密 note。

## 真实验收场景

### A. 开幕

```text
用户：“朝汐，开幕，今天做 v0.5 Workflow。”
→ current 无 Focus
→ 展示将创建铁幕
→ 用户允许
→ start 成功
→ 返回真实 session ID、目标和开始时间
```

### B. 已有铁幕

```text
用户再次说“开幕”
→ current 已有 RUNNING 铁幕
→ 不重复创建
→ 返回当前目标和时长
```

### C. 落幕

```text
用户：“落幕，Workflow 骨架完成。”
→ current 为 IRON_CURTAIN
→ 用户允许
→ complete 成功
→ 返回 actual/effective、Segments 与总结
```

### D. 冲突

```text
current 为 POMODORO
→ 不直接 complete
→ 明确当前模式并等待用户决定
```

### E. 重启恢复

```text
start 等待 WRITE 权限
→ 退出并重启朝汐
→ Run 仍可查询
→ 批准后只执行一次 start
```

### F. 回归

DIRECT、单 Tool、Planner、Memory 生命周期、Permission 批量/部分批准及全部 v0.4 测试继续通过。

---

# 11. 明确非目标

v0.5 不实现：

- 通用 BPMN、DAG、并行调度器或分布式队列；
- 任意代码、Shell 或模板表达式执行；
- 图形化 Workflow 编辑器；
- 模型自动生成并永久安装 Workflow；
- 后台定时触发、事件总线和主动打扰（属于 v0.6）；
- 多用户、云同步和跨设备锁；
- 通用 ACID 跨系统事务或自动回滚保证；
- 把 Life HUD 数据复制进 Zhaoxi Memory；
- 修改 Life HUD 项目、数据库或 Focus 业务逻辑；
- 一次性覆盖 Life HUD 全部业务 API；
- Desktop、Voice、QQ 等新入口。

---

# 12. 风险与防护

| 风险 | v0.5 防护 |
|---|---|
| Workflow 变成第二个 Planner | 定义固定、Runtime 确定性；开放任务仍交给 Planner |
| DSL 演变成远程代码执行 | 白名单步骤与表达式，禁止 eval/import/shell |
| 权限被批量流程绕过 | 每个 Tool Step 强制经 ToolExecutor/Permission Gateway |
| 恢复时重复写入 | 冻结 invocation、步骤落库、幂等键与只读核验 |
| 定义升级破坏运行中任务 | Run 绑定完整 definition snapshot |
| 外部状态与本地 Run 漂移 | 执行前 current 查询、session ID 校验、冲突暂停 |
| Core 硬编码 Life HUD | 独立 Tool/Client，Workflow 只引用 Tool 名称 |
| 私密参数进入日志 | 字段敏感性、摘要、截断与审计脱敏 |
| Run 历史无限增长 | 数量/字符上限、分页和明确清理策略 |
| 自动匹配误触发副作用 | 低置信度只推荐，副作用执行前预览与权限确认 |

---

# 13. Definition of Done

- [ ] `v0.5` 分支以 v0.4 为干净基线；
- [ ] Workflow Definition、Registry、Runtime、Store 和 Trace 职责清晰；
- [ ] YAML 定义可校验、版本化且不能执行任意代码；
- [ ] Workflow 支持参数、条件、Tool Step、暂停、恢复、取消和有限重试；
- [ ] SQLite 可恢复未完成 Run，已完成副作用不被正常路径重复执行；
- [ ] 每个 Tool Step 经过 v0.4 Permission Gateway 并写入审计；
- [ ] Router 能区分 DIRECT / TOOL / PLAN / WORKFLOW；
- [ ] CLI 可以检查和控制 Run；
- [ ] lifehud-tool 不依赖 Life HUD 源码，只通过 HTTP 契约交互；
- [ ] “开幕”和“落幕”Workflow 真实闭环可用；
- [ ] 已有非铁幕 Focus 时不会误创建或误结束；
- [ ] 自动测试不依赖真实 API、真实凭据或真实 Life HUD 数据；
- [ ] v0.4 全量能力无回归；
- [ ] README、配置、版本号和 `CODEBASE_STATUS.md` 更新为 v0.5；
- [ ] Life HUD 项目在本轮保持零修改。

当“朝汐，开幕”不再需要模型每次临时发明步骤，而能通过同一份版本化流程完成状态查询、参数补全、权限确认、真实调用、冲突处理和可恢复执行，并且“落幕”能安全地以 Life HUD 的真实结果收尾时，v0.5 才算完成。

---

# 14. 推荐实施顺序

```text
保护 v0.4 契约
→ 固定 Workflow 领域模型与安全 DSL
→ 完成确定性 Runtime 和 InMemory Store
→ 接入 ToolExecutor 与 Permission Pending
→ 增加 SQLite Run 持久化和恢复
→ 接入 Router、Planner 与 CLI
→ 实现 lifehud-tool 的 current/start/complete
→ 跑通铁幕开幕/落幕纵向切片
→ 补过程控制、文档与全量回归
```

这条顺序先解决 Workflow 自身的状态、权限与恢复风险，再引入真实外部系统；既避免把 Life HUD 特判焊进 Core，也避免在不稳定 Runtime 上堆业务流程。
