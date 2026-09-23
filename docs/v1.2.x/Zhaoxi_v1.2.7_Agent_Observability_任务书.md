# Zhaoxi v1.2.7 开发任务书
## 主题：Agent Observability / 行动显式化

> 版本定位：补齐朝汐在“多轮模型调用 + Tool 调用 + 重试 + 回退回复”场景下的可观测性，让用户能看到当前正在做什么，让开发者能准确追踪一次请求的真实执行链，并让最终回复以“最终动作状态”而不是“历史上是否出现过失败”为依据。
>
> 本版本只做可观测性、状态归并、错误归因与前端行动显式化。**暂不进行 Token 阈值、Prompt 长度、上下文裁剪、重试次数等参数调优。**

---

## 1. 背景

目前朝汐在复杂任务中已经会连续经历：

- 读取用户输入 / 图片
- 检索记忆
- 多轮模型调用
- 调用多个 Tool
- Tool 参数校验失败
- 自动重试
- 部分副作用已经成功落地
- 最后一轮模型回复失败
- Web 层输出兜底文案

但前端大多数时候只显示“正在思考”。

一旦发生异常，用户无法判断：

- 朝汐当前卡在哪一步；
- 哪些 Tool 已经成功执行；
- 哪些 Tool 失败后已经被后续调用修复；
- 最终失败发生在 Provider、Token Budget、Tool、Web，还是本地校验层；
- 已经成功产生的副作用是否仍然保留。

近期日志排查还暴露了以下问题：

1. Token 预算超限缺少本次调用与累计用量明细；
2. 回退摘要无法区分“失败后已修复”和“仍失败”；
3. 主日志中的 Tool 执行无法稳定对应具体副作用；
4. 跨层错误关联不完整，且本地预算错误会被展示成“模型服务暂时不可用”；
5. Tool / Provider / Sensor 等错误事件缺少统一的结构化阶段信息。

因此 v1.2.7 不再把“行动显式化”作为单独 UI 小功能，而是建立一套轻量的 Agent Observability 基础设施，前端行动轨迹只是其中一个消费者。

---

# 2. 本版本目标

## 2.1 核心目标

完成以下四项能力：

### A. 一次请求拥有统一 Trace

从用户发送消息开始，到最终回复 / 回退结束，所有关键阶段必须能够通过统一 ID 串起来。

至少包含：

- `trace_id`
- `request_id`
- `step_id`
- `stage`
- `outcome`

Tool 相关事件额外包含：

- `tool_call_id`
- `invocation_id`
- `tool_name`

---

### B. 建立统一的 Action Event / Agent Event

Agent 内部关键动作不再只靠散落日志表达，而是产生结构化事件。

事件至少覆盖：

```text
REQUEST_STARTED

MODEL_STEP_STARTED
MODEL_STEP_FINISHED
MODEL_STEP_FAILED

MEMORY_SEARCH_STARTED
MEMORY_SEARCH_FINISHED
MEMORY_SEARCH_FAILED

TOOL_CALL_STARTED
TOOL_VALIDATION_FAILED
TOOL_CALL_RETRYING
TOOL_CALL_SUCCEEDED
TOOL_CALL_FAILED

TOKEN_BUDGET_WARNING
TOKEN_BUDGET_EXHAUSTED

RESPONSE_GENERATION_STARTED
RESPONSE_GENERATION_SUCCEEDED
RESPONSE_GENERATION_FAILED

TASK_COMPLETED
TASK_PARTIAL
TASK_FAILED
```

事件命名可以根据现有工程规范调整，但语义必须明确。

---

### C. 前端显示“行动轨迹”

用户不再只看到一句：

> 正在思考……

而应根据事件流显示当前任务进展。

示例：

```text
正在理解图片内容…
正在检索相关记忆…
正在新增求职记录…
已新增求职记录 ×2
正在添加日程…
日程参数校验失败，正在修正…
已成功添加日程
正在整理回复…
回复生成失败：本次请求 Token 预算耗尽
已完成的操作均已保留
```

要求：

- 默认展示人类可读、简洁的信息；
- 不直接显示原始参数；
- 不显示 Prompt 正文；
- 不暴露敏感日志；
- 已结束步骤可保留为历史轨迹；
- 当前步骤应有明显的运行中状态；
- 失败、重试、成功需要区分；
- 最终自然语言回复生成失败时，轨迹仍然能够完整结束。

---

### D. 最终结果以“最终动作状态”归并

不能再通过：

```text
历史 Tool 结果里出现过 success=false
```

直接判断“部分操作未完成”。

需要建立目标 / 动作级最终状态。

例如：

```text
agenda_add #1 -> validation_failed
agenda_add #2 -> success
```

如果第二次调用明确是第一次的修复，则最终状态应为：

```text
添加日程 -> completed
```

而不是：

```text
添加日程 -> partial
```

建议最小状态集合：

```text
completed
failed
unknown
superseded
```

其中：

- `completed`：最终确认完成；
- `failed`：最终仍失败；
- `unknown`：无法确认是否产生副作用；
- `superseded`：旧调用已被后续调用替代。

---

# 3. 数据模型设计

## 3.1 AgentEvent

建议建立统一事件结构，例如：

```python
AgentEvent(
    event_type="tool_call_succeeded",
    trace_id="...",
    request_id="...",
    step_id=4,
    stage="tool_execution",
    outcome="success",

    tool_name="agenda_add",
    tool_call_id="...",
    invocation_id="...",

    display_message="已添加日程",
    metadata={
        "result_code": "created",
        "record_id": "...",
    },
    timestamp="..."
)
```

`metadata` 中只允许放安全、脱敏、可观测性所需字段。

禁止默认写入：

- 用户完整输入；
- Prompt 正文；
- Tool 原始参数；
- 图片内容；
- API Key / Cookie；
- 私密数据正文。

---

## 3.2 Action State

在一次 Agent 请求内部维护动作状态表。

示例：

```text
action_id: agenda_add:job_interview_xxx
intent: add_agenda
status: completed

attempts:
  - invocation A
    outcome: validation_failed
    superseded_by: invocation B

  - invocation B
    outcome: success
```

不强制一开始建立复杂持久化数据库。

v1.2.7 可以优先采用：

```text
单请求内存状态 + 日志输出 + 前端事件推送
```

先解决真实问题。

---

# 4. 后端开发任务

## 4.1 统一 Trace 上下文

检查并整理：

- Agent 请求入口；
- Web chat / regenerate；
- 模型调用；
- Tool Executor；
- Permission Executor；
- Recovery；
- Token Budget；
- Memory Search。

确保同一请求的 `trace_id / request_id` 不会跨层丢失。

Web 层不能再出现本应可关联但实际为：

```text
trace=-
request=-
```

的情况。

---

## 4.2 Tool 调用生命周期事件化

每次 Tool 调用至少产生：

```text
START
VALIDATION_FAILED / EXECUTION_FAILED / SUCCESS
```

若发生重试：

```text
FAILED
RETRYING
SUCCESS
```

必须可以知道：

- 第几步；
- 调用了哪个 Tool；
- 对应哪个 `tool_call_id`；
- 对应哪个 `invocation_id`；
- 最终结果；
- 是否被后续调用替代。

写操作成功后，若 Tool 本身能返回记录 ID，可记录脱敏后的：

```text
result_code
created_record_id
updated_record_id
```

避免仅有：

```text
tool=add_job success=true
```

这种无法区分具体副作用的日志。

---

## 4.3 Tool 参数校验事件增强

当前已有字段级校验日志。

本版本补充安全元数据：

```text
expected_type
allowed_enum
supplied_keys
schema_version 或 schema_hash
step_id
tool_call_id
```

仍然禁止记录原始参数值。

例如：

```text
tool=agenda_add
field=type
issue=missing
supplied_keys=[kind, notes, time]
schema_hash=...
step=4
```

---

## 4.4 Token Budget 可观测性

这里只补“看得见”，不调参数。

当接近或超过预算时记录：

```text
used_before
call_input_tokens
call_output_tokens
call_total
used_after
limit
step
provider
model
```

如果 Provider 只返回 total，不支持 input / output 拆分，则允许为空，但字段结构保持一致。

必须以**真实最终发送给 Provider 的 payload**为统计基准，避免诊断路径与真实请求路径不同。

### 本版本明确不做

- 调整 `100000` 等预算值；
- 自动裁剪历史；
- 自动摘要 Tool Result；
- 减少记忆召回数量；
- 修改 Prompt；
- 调整最大 Tool 轮数。

这些留待后续参数 / 上下文调优。

---

## 4.5 错误码与错误归因

不要再把所有 AgentLoop / Provider 相关失败都映射成：

> 模型服务暂时不可用

至少区分：

```text
provider_http_error
provider_timeout
provider_protocol_error
token_budget_exhausted
tool_validation_error
tool_execution_error
agent_loop_error
response_generation_error
```

UI 文案可以友好，但底层错误码必须准确。

例如：

```text
token_budget_exhausted
```

应显示：

> 本次任务累计 Token 已达到预算上限，最终回复未能继续生成。

而不是：

> 模型服务暂时不可用。

---

## 4.6 Recovery 重构

重点检查：

```text
src/zhaoxi/core/agent.py
_recoverable_turn_content()
```

Recovery 不再扫描历史结果简单判断：

```text
出现过失败 -> partial
```

而应该读取最终 Action State。

输出至少分成：

```text
已完成
仍失败
结果未知
```

示例：

```text
已完成：
- 新增求职记录 ×2
- 添加日程

仍失败：
- 无

结果未知：
- 无
```

如果只有最终自然语言生成失败：

```text
任务状态 = completed
response_generation = failed
```

不可把任务整体标成 partial。

---

# 5. 前端行动显式化

## 5.1 默认展示

当前“正在思考”替换为动态行动区域。

建议采用：

```text
┌ 朝汐正在处理
│ ✓ 已读取图片
│ ✓ 已检索相关记忆
│ ✓ 已新增求职记录 ×2
│ ↻ 正在添加日程…
└
```

完成后可折叠为：

```text
本次任务 · 7 个步骤 · 1 个警告
```

用户可点击展开。

---

## 5.2 状态类型

至少支持：

```text
running
success
warning
retrying
failed
info
```

视觉表现保持轻量，不需要大面积报错红框。

---

## 5.3 Debug 展开

普通模式：

```text
正在添加日程…
参数有误，正在修正…
日程已添加
```

Debug 模式：

```text
13:21:04 agenda_add START
step=4
tool_call_id=xxx

13:21:04 VALIDATION_FAILED
field=type
issue=missing
supplied_keys=[kind, notes]

13:21:05 RETRY
new_tool_call_id=yyy

13:21:05 SUCCESS
invocation_id=zzz
result_code=created
```

Debug UI 仍然不展示敏感原始参数。

---

# 6. 事件传输

根据现有 Web 架构选择最小侵入方案。

优先级：

1. 如果当前已经存在 SSE / WebSocket / 流式回复通道，复用；
2. 如果有统一 chat stream，加入新的 event 类型；
3. 不为了 v1.2.7 单独引入重量级实时通信框架。

示例：

```json
{
  "type": "agent_event",
  "event": {
    "event_type": "tool_call_started",
    "stage": "tool_execution",
    "display_message": "正在添加日程…"
  }
}
```

最终文本 Token 流与 Action Event 可以走同一连接，但前端逻辑必须分开。

---

# 7. 日志改造

主日志建议统一使用结构化关键字段：

```text
trace=
request=
step=
stage=
event=
tool=
tool_call_id=
invocation_id=
outcome=
error_code=
```

继续保留：

- 时间戳；
- 日志等级；
- 模块名；
- 当前已有脱敏策略。

不要复制 permission audit 中已有的敏感参数摘要。

重点是**建立关联关系，而不是把所有信息重复写一遍。**

---

# 8. Sensor / Heartbeat 可观测性补丁

本版本顺手补齐近期发现的静默异常问题。

LifeHudSensor 失败时记录：

```text
stage
elapsed_ms
timeout_ms
error_type
failure_count
next_poll_at
```

`heartbeat.run()` 顶层：

```python
except Exception:
```

不能只增加计数。

至少写一条脱敏错误日志：

```text
error_type
error_code
stage
trace/request（若存在）
```

本版本不调整 Heartbeat / Sensor 的轮询参数。

---

# 9. 非目标

v1.2.7 不处理以下内容：

### 不做 Token / Prompt 参数调优
包括但不限于：

- Token Budget 大小；
- Prompt 长度；
- Memory 数量；
- Tool Schema 注入方式；
- Tool Result 压缩；
- 图片上下文压缩；
- 最大循环次数。

### 不重写 Agent 主循环

以“小步加入可观测层”为原则。

不要为了 Action Trace 把整个 Agent Runtime 推倒重建。

### 不引入完整分布式链路系统

暂不需要 OpenTelemetry / Jaeger 等重型方案。

当前目标是单机生活 Agent 的可观测性，而不是云原生微服务监控。

### 不记录敏感正文

不能因为 Debug 方便就重新把 Prompt、用户消息、完整 Tool 参数写进日志。

---

# 10. 推荐实现顺序

## Phase 1：统一事件模型

完成：

```text
AgentEvent
TraceContext
ActionState
```

先不接 UI。

确保现有逻辑可以稳定产生事件。

---

## Phase 2：Tool 生命周期

接入：

- tool start
- validation fail
- execution fail
- retry
- success
- superseded

完成 Action State 最终归并。

---

## Phase 3：错误归因 + Recovery

完成：

- error_code；
- Token Budget 明细；
- Provider / Budget / Tool 错误区分；
- `_recoverable_turn_content()` 改为读取最终状态。

---

## Phase 4：前端 Action Trace

将事件流接入 Web UI：

- 当前动作；
- 已完成动作；
- warning；
- retry；
- failed；
- 折叠历史；
- Debug 展开。

---

## Phase 5：Sensor / Heartbeat 补洞

最后处理不影响主 Agent 流程的 P2 可观测性问题。

---

# 11. 验收场景

必须至少完成以下黑盒测试。

## Case 1：单 Tool 成功

用户：

```text
帮我加一个明天下午两点的日程
```

预期：

```text
正在添加日程…
已添加日程
```

最终自然语言回复正常。

---

## Case 2：Tool 参数失败后修复成功

第一次：

```text
agenda_add -> validation_failed
```

第二次：

```text
agenda_add -> success
```

前端：

```text
正在添加日程…
参数校验失败，正在修正…
已添加日程
```

最终任务状态：

```text
completed
```

不得显示：

```text
部分操作未完成
```

---

## Case 3：多个同名写 Tool

连续：

```text
add_job
add_job
```

日志与 Action State 必须能明确区分：

```text
invocation A
invocation B
```

并能确认两个写操作各自的最终状态。

---

## Case 4：Tool 已成功，但最终回复 Token Budget 超限

预期 UI：

```text
已新增求职记录 ×2
已添加日程
正在整理回复…
本次请求 Token 预算已耗尽
已完成的操作均已保留
```

最终任务状态：

```text
completed
```

最终回复状态：

```text
failed
```

不得显示：

```text
模型服务暂时不可用
```

---

## Case 5：Provider HTTP 失败

预期：

- error_code 为 `provider_http_error`；
- Action Trace 明确显示模型请求失败；
- 不伪装成 Tool 失败；
- trace / request 可以从 Web 一直追到 Provider 层。

---

## Case 6：Tool 最终失败

例如：

```text
validation_failed
retry
execution_failed
```

最终：

```text
failed
```

Recovery 必须明确列入：

```text
仍失败
```

不能因为曾经执行过重试就标 completed。

---

## Case 7：Heartbeat 顶层异常

模拟抛出异常。

必须：

- failure counter 正常增加；
- 主日志出现结构化失败记录；
- 不再静默吞掉。

---

# 12. 完成标准

v1.2.7 完成时应满足：

- [ ] 一次 Chat 请求拥有完整 Trace
- [ ] Model / Memory / Tool / Recovery 关键阶段可产生事件
- [ ] Tool 调用拥有 `tool_call_id + invocation_id`
- [ ] Tool 重试可以关联前一次失败
- [ ] 最终动作状态支持 completed / failed / unknown / superseded
- [ ] Recovery 基于最终状态生成
- [ ] Token Budget 超限日志包含完整数值上下文
- [ ] Budget 错误不再被误报成 Provider 不可用
- [ ] Web UI 能实时展示行动轨迹
- [ ] Action Trace 在最终回复失败时仍能结束
- [ ] Debug 展开可以查看安全的结构化执行详情
- [ ] 主日志不新增用户正文 / Tool 原始参数泄露
- [ ] Heartbeat 顶层异常不再静默
- [ ] 上述 7 个黑盒场景通过

---

# 13. 版本完成后的预期体验

修改前：

```text
正在思考……

（数分钟）

模型服务暂时不可用。
部分操作可能未完成。
```

修改后：

```text
正在理解图片…
已新增求职记录 ×2
正在添加日程…
参数校验失败，正在修正…
已添加日程
正在整理回复…
⚠ 本次请求 Token 预算已耗尽
✓ 已完成的操作均已保留
```

v1.2.7 的目标不是让朝汐“更少出错”。

而是：

> **无论成功、失败、重试还是只完成了一部分，朝汐都应该知道自己做到了哪一步，并把真实状态准确地告诉用户。**

参数调优、Prompt 缩减、上下文压缩与 Token 策略，留到 v1.2.7 完成后单独处理。
