# Zhaoxi v1.4.0 · Runtime Observatory & Progressive Response 开发任务书

> 项目：**Zhaoxi / 朝汐**
> 版本：**v1.4.0**
> 主题：**Runtime Observatory & Progressive Response**
> 定位：v1.4 长周期打磨阶段的第一版
> 核心目标：**先看清运行时，再优化；允许复杂任务先回复，再继续行动。**
> 实施状态（2026-09-29）：代码和自动回归已完成，真实模型桌面端验收待重启后进行。实施中按试用反馈取消“超过固定阈值自动发气泡”，仅保留 Agent / Planner 基于真实进展主动发送；AutoMemory 与 Current Cognition 已按补丁任务书后置到持久化维护队列；Final 分段节奏只服从用户设置。

---

## 1. 背景

目前朝汐已经具备 Cognitive Router、Memory Retrieval、主 Agent Loop、Tool、Planner、Workflow、Decision、AutoMemory、Current Cognition 与 ActionTrace。

真实使用中现在有两个非常明显的问题：

1. **运行链路越来越黑箱。**
   很难直接回答“这一轮为什么慢”“Router 花了多久”“Memory 检索到底用了多少时间”“Planner 有没有介入”“AutoMemory 是否阻塞主回复”等问题。

2. **长任务期间完全沉默。**
   即使内部一直在检索、规划和执行工具，用户也可能连续 20~30 秒看不到任何角色回复，最后才一次性收到结果。

v1.4.0 同时解决这两件事：

```text
Runtime Observatory
→ 看清朝汐内部现在正在发生什么

Progressive Response
→ 让朝汐可以先回应一句，再继续执行当前任务
```

---

## 2. 本版核心原则

```text
先看清，再优化。
先反馈，再继续行动。
用户可见进度 ≠ Debug 日志。
中间回复 ≠ 最终回复。
中间回复不能污染 Conversation / Memory / Current Cognition。
```

v1.4.0 **不追求一次性把延迟全部优化掉**。

先建立可信 baseline，后续 v1.4.x 再根据真实数据动 Router、AutoMemory、Planner 等关键路径。

---

## 3. Runtime Observatory

### 3.1 Request 级运行指标

每轮请求至少记录：

```text
request_id
trace_id
started_at
finished_at
total_ms
```

阶段耗时：

```text
routing_ms
memory_retrieval_ms
decision_ms
planner_ms
workflow_ms
tool_ms_total
response_generation_ms
auto_memory_ms
current_cognition_ms
other_ms
```

模型调用：

```text
llm_call_count
llm_calls[]
```

每次 LLM Call：

```text
index
owner
stage
started_at
finished_at
duration_ms
prompt_tokens
output_tokens
total_tokens
tool_call_count
finish_reason
```

owner 至少能区分：

```text
router
agent
planner
decision
decision_expression
auto_memory
current_cognition
workflow_finalization
```

### 3.2 Tool 调用指标

每次 Tool 记录：

```text
tool_name
step_id
invocation_id
duration_ms
success
retry_count
waiting_for_permission
```

能复用现有 ActionTrace 的地方不要再另造一套观测系统。

### 3.3 Debug 总览

应能直接看到类似：

```text
Total: 26.8s

Routing              3.2s
Memory Retrieval     0.08s
Main LLM #1          7.6s
Tool: search_jobs    1.1s
Main LLM #2          5.4s
AutoMemory           6.7s
Finalize             0.3s
Other                2.42s

LLM Calls: 4
Tool Calls: 1
Memory Hits: 4
Planner Used: false
Decision Used: false
```

目标：

> 以后再觉得“朝汐怎么这么慢”，不用猜，直接看数据。

---

## 4. ActionTrace 收口

当前 ActionTrace 已经覆盖：

```text
request
routing
memory_search
model
tool_execution
response_generation
memory
task
```

v1.4.0 建议补充：

```text
runtime
planner
interim_response
metrics
```

建议事件：

```text
runtime_started
runtime_finished

routing_started
routing_finished

memory_search_started
memory_search_finished

llm_call_started
llm_call_finished

planner_started
planner_finished

interim_response_emitted

auto_memory_started
auto_memory_finished

runtime_metrics_finalized
```

---

## 5. 三层信息展示原则

### 第一层：小桌边 / 输入框上方

只显示抽象状态：

```text
理解 · 正在想怎么处理……
检索 · 顺着线索找找看……
行动 · 正在处理……
规划 · 把事情排一下……
整理 · 快弄好啦……
```

禁止显示：

```text
第 2 轮
Token 预算
tool_call_id
invocation_id
goal_id
step_id
LLM #3
```

### 第二层：中间回复

由朝汐自己说：

```text
我先把前几天的记录翻一下，顺便看看有没有漏掉的地方～
```

这是角色输出，不是 Debug 状态。

### 第三层：Dashboard / Debug

显示完整运行细节：

```text
Routing 3.2s
Memory hits: 4
Planner Plan v2
Step 2 / 4
Tool: lifehud
LLM calls: 5
AutoMemory 6.7s
```

---

## 6. Progressive Response / 中间回复

### 6.1 定义

中间回复是一种：

> **用户可见，但不结束当前 turn 的角色输出。**

生命周期：

```text
用户请求
↓
模型判断任务明显仍需继续
↓
emit_interim_reply
↓
用户立即看到一段话
↓
Runtime 继续执行
↓
最终回复
↓
当前 turn 正式结束
```

示例：

```text
用户：
帮我看看今天秋招相关的东西，再顺便整理一下 LifeHUD

朝汐：
我先把今天留下来的记录对一下，顺便看看有没有漏掉的地方～

↓ 继续执行 Memory / Planner / Tool

朝汐最终回复：
今天主要有三件……
```

---

## 7. 中间回复必须是独立 Runtime 类型

**禁止**直接：

```text
conversation.add_assistant(...)
```

保存中间回复。

否则会产生：

- Conversation History 把过程话当正式回答；
- AutoMemory 可能记住“我先去查一下”；
- Current Cognition 可能把过程状态当事实；
- 外部适配器可能误判 turn 已结束；
- 后续模型上下文出现重复自述；
- Resume / Retry 逻辑变复杂。

因此新增独立语义：

```text
InterimResponseEvent
```

或内部事件名：

```text
interim_reply
```

推荐属性：

```text
visible_to_user = true
terminates_turn = false

persist_to_conversation = false
eligible_for_auto_memory = false
eligible_for_current_cognition = false
eligible_for_long_term_memory = false
is_fact_source = false
```

可记录：

```text
request_id
trace_id
sequence
content
emitted_at
reason
```

---

## 8. 中间回复控制能力

建议给 Agent / Planner 提供控制能力：

```text
emit_interim_reply
```

输入：

```json
{
  "content": "我先把之前几条记录对一下，再继续看后面的～"
}
```

Runtime：

```text
校验是否允许
↓
发送给前端
↓
ActionTrace 记录 interim_response_emitted
↓
不结束 turn
↓
继续当前模型 / Tool / Planner loop
```

---

## 9. 中间回复使用规则

### 9.1 简单聊天禁止使用

例如：

```text
“在吗”
“这个是什么”
“解释一下 JVM”
```

不需要先说一句“我看看”。

### 9.2 快任务禁止使用

如果预计几秒即可完成，不要为了“显得活着”硬发中间消息。

初版可将触发阈值配置为：

```text
8~12 秒
```

### 9.3 默认最多一次

普通 Agent：

```text
max_interim_replies = 1
```

长 Planner：

```text
max_interim_replies = 2
```

### 9.4 第二次必须包含新进展

禁止：

```text
稍等一下～
↓
还在处理～
```

允许：

```text
前面的记录已经核对完了，现在只剩 LifeHUD 那边两项要补，我继续弄一下～
```

### 9.5 禁止提前宣布结果

尚未得到 Tool / Planner 结果时禁止：

```text
“我查到了……”
“已经更新好了……”
“问题解决了……”
```

允许：

```text
“我先去查一下……”
“我先把这几条对上……”
```

### 9.6 Persona 正常生效

中间回复必须仍然是“朝汐说的话”。

但要求：

- 短；
- 自然；
- 不要客服腔；
- 不要固定模板；
- 不要机械重复；
- 不要过度舞台描写；
- 不要泄露内部实现。

---

## 10. 中间回复触发建议

初版可以采用规则 + Agent 主动调用：

```text
进入 Planner

OR

首次 Tool 调用后仍然明确存在多个后续步骤

OR

已经执行 >= 1 个 Tool 且仍需继续推理 / 执行

OR

累计运行时间超过阈值且任务未完成
```

不要为了追求“每轮都有回应”而强制触发。

---

## 11. TTFR 指标

新增：

```text
TTFR
Time To First Reply
```

定义：

```text
从收到用户输入
到第一次用户可见角色输出
```

第一次输出可以是：

```text
interim reply
```

也可以直接是：

```text
final reply
```

同时记录：

```text
ttfr_ms
final_response_ms
total_ms
```

示例：

```text
TTFR            5.8s
Final Response 24.3s
Total Runtime  25.1s
```

这样最终任务即使依旧需要 25 秒，体验也不再是 25 秒完全沉默。

---

## 12. 前端行为

### 12.1 收到 Interim Reply

立即显示：

```text
朝汐：
我先把前面的记录翻一下～
```

但：

```text
请求仍处于 running
```

不能关闭：

- loading；
- 当前行动状态；
- ActionTrace；
- Planner 运行状态。

### 12.2 最终回复

收到 final reply 后才：

- 结束当前 turn；
- 关闭 running；
- ActionTrace 标记完成；
- 允许 AutoMemory / 后处理进入收尾状态。

### 12.3 页面刷新

第一版中间回复可以：

```text
不永久保留
```

刷新后消失可接受。

未来如果要保留，应单独作为：

```text
runtime history
```

而不是普通 Conversation。

---

## 13. Planner 联动

Planner 是中间回复最有价值的场景。

示例：

```text
用户：
帮我检查今天求职相关记录，再看看 LifeHUD 有没有漏填

朝汐：
我先把今天留下来的东西对一下，看看哪些已经处理、哪些还挂着～

↓ Planner

Plan v1
1. 收集求职记录
2. 检查遗漏
3. 更新 LifeHUD
4. 汇总

↓ 执行

朝汐：
前面的记录已经核对完了，现在只剩 LifeHUD 那边要补，我继续弄一下～

↓ Tool

最终回复：
今天主要有三件……
```

---

## 14. Planner Trace 桥接准备

当前：

```text
Planner TraceRecorder
```

与：

```text
ActionTrace
```

仍然是两套体系。

v1.4.0 不要求完成完整 Planner UI，但至少建立 Adapter 边界：

```text
PlannerTraceEvent
↓
PlannerActionTraceAdapter
↓
AgentEvent
```

至少映射：

```text
goal_created
→ planner_started

plan_created
→ planner_plan_created

step_started
→ planner_step_started

step_completed
→ planner_step_completed

plan_revised
→ planner_replanned

task_completed
→ planner_finished
```

完整 Planner 侧栏 UI 留到后续 v1.4.x。

---

## 15. Memory Retrieval Inspector

利用现有：

```text
MemoryService.inspect_retrieval()
```

在 Debug 增加：

```text
查询输入
↓
候选列表
```

每条至少展示：

```text
content
final_score
contextual_relevance
text_score
semantic_score
graph_score
time_score
activation_score
importance_score
status
why_selected
```

初版只要求“看得见”，不在本版修改召回算法。

---

## 16. Runtime Debug 页面

建议增加三个区块。

### Request Summary

```text
Request ID
Trace ID
Route
Total Time
TTFR
LLM Calls
Tool Calls
Memory Hits
Planner Used
Decision Used
Interim Replies
```

### Timeline

```text
00.0s Request
03.1s Routing done
03.2s Memory done
10.8s LLM #1 done
11.0s Interim Reply
12.2s Tool done
18.6s LLM #2 done
24.9s AutoMemory done
25.1s Finished
```

### Raw Detail

保留：

```text
event metadata
internal ids
token usage
error code
```

但默认折叠。

---

## 17. 本版先不要做的性能优化

v1.4.0 第一原则：

> **先建立可信 baseline。**

暂时不要直接：

- 删除 Router；
- 大规模改 Router Fast Path；
- 彻底异步化 AutoMemory；
- 替换 Embedding；
- 重写 Planner；
- 调 Memory 权重；
- 删除 Decision；
- 一口气重构整套 ActionTrace。

可以预留接口，但不要在“还没测清楚”时同时大改行为。

---

## 18. 配置建议

新增：

```text
RUNTIME_METRICS_ENABLED=true

INTERIM_REPLY_ENABLED=true
INTERIM_REPLY_THRESHOLD_SECONDS=10
INTERIM_REPLY_MAX_COUNT=1
PLANNER_INTERIM_REPLY_MAX_COUNT=2

MEMORY_RETRIEVAL_DEBUG_ENABLED=true
```

Debug 相关功能默认仅本地 Web 开启即可。

---

## 19. 错误与超时处理

如果已经发出：

```text
我先去查一下～
```

之后 Tool 失败：

```text
最终回复必须说明失败。
```

禁止停在中间回复后无下文。

如果：

```text
Interim Reply 已发送
↓
Runtime 超时 / Provider 失败
```

必须补最终失败收尾，例如：

```text
刚才那一步没能顺利跑完，这次没有拿到可靠结果。
```

不能让用户永远停在：

```text
“我去看看～”
```

---

## 20. 安全与语义边界

中间回复不能：

- 伪造 Tool 结果；
- 提前声称任务完成；
- 泄露 Prompt；
- 泄露 goal_id / trace_id / invocation_id；
- 泄露 Token 预算；
- 原样暴露 Planner state；
- 把 Debug 日志伪装成角色说话；
- 作为 Memory / Current Cognition 的事实来源。

---

## 21. 验收场景

### Case A：普通闲聊

输入：

```text
今天真热啊
```

要求：

```text
有 Runtime Metrics
无 Planner
无 Interim Reply
LLM 调用统计准确
总耗时准确
```

### Case B：单 Tool

输入：

```text
帮我看看今天 LifeHUD 的状态
```

要求：

```text
Router / Memory / Main LLM / Tool / Finalization 耗时可见
Tool duration 可见
没有必要时不发 Interim Reply
```

### Case C：复杂 Planner

输入：

```text
帮我检查今天求职相关记录，再看看 LifeHUD 有没有漏填
```

要求：

```text
Planner Used = true
Plan / Step 进入统一 Trace
允许一次 Interim Reply
最终回复正常
```

### Case D：长任务

运行时间超过 threshold。

要求：

```text
最终回复前可收到一次自然中间回复
任务不中断
后续 Tool / Planner 正常继续
```

### Case E：中间回复后失败

要求：

```text
Interim Reply 已显示
后续 Tool 失败
最终回复明确失败
ActionTrace 完整
```

### Case F：不污染 Conversation

中间回复：

```text
我先去翻一下记录～
```

要求：

```text
Conversation History 中不存在这条普通 Assistant Message
```

### Case G：不污染 AutoMemory

要求：

```text
AutoMemory evidence 不包含 Interim Reply
```

### Case H：不污染 Current Cognition

要求：

```text
Current Cognition Maintainer 输入不包含 Interim Reply
```

### Case I：次数限制

要求：

```text
普通 Agent <= 1
Planner <= 2
```

第二次必须存在真实新进展。

---

## 22. 建议开发顺序

### Phase 1 · Metrics 基础

- [x] Request timer
- [x] Stage timer
- [x] LLM call timer
- [x] Tool timer
- [x] total_ms
- [x] ttfr_ms
- [x] Debug 输出

### Phase 2 · ActionTrace 收口

- [x] 增加 runtime metrics event
- [x] LLM owner / stage metadata
- [x] 统一 request timeline
- [x] Planner Adapter 接口

### Phase 3 · Memory Inspector

- [x] 接 `inspect_retrieval()`
- [x] 展示 candidate scores
- [x] 展示 why_selected
- [x] 展示 status / importance / activation

### Phase 4 · Interim Reply Runtime

- [x] 定义 `InterimResponseEvent`
- [x] 增加 `emit_interim_reply`
- [x] 次数限制
- [x] 不结束 turn
- [x] 不写 Conversation
- [x] 不进入 Memory
- [x] 不进入 Current Cognition

### Phase 5 · 前端支持

- [x] Web 收到 interim event 后立即显示
- [x] 保持 running
- [x] Final Reply 后再结束请求
- [x] ActionTrace 记录 `interim_response_emitted`

### Phase 6 · Planner 联动

- [x] Planner 可发 Interim Reply
- [x] 第二次必须有新进展
- [x] Planner Trace Adapter 初步接通

---

## 23. 本版本不做

暂不做：

- Current Cognition 重构；
- Router Fast Path；
- AutoMemory 后台化；
- Planner 完整侧栏 UI；
- Dashboard 全面改版；
- Presence 2.0；
- 向日葵花海视觉；
- 真实 Embedding；
- Memory FTS / ANN 重构；
- v1.4 全局性能优化。

这些留给后续 v1.4.x。

---

## 24. 完成标准

v1.4.0 完成后：

```text
1. 每一轮到底慢在哪里，可以直接看到。

2. 每次 LLM / Tool 调用的归属与耗时可以追踪。

3. Memory 为什么召回某条记录，可以 Debug 查看。

4. Planner 主要事件开始进入统一观测体系。

5. 长任务允许朝汐先回应一句，再继续行动。

6. Interim Reply 不污染 Conversation / Memory / Current Cognition。

7. Interim Reply 后即使失败，也会有明确最终收尾。

8. 小桌边状态、角色中间回复、Debug 三层职责明确。

9. 为 v1.4 后续性能优化建立可信 baseline。
```

---

## 25. 版本意义

v1.4.0 不负责让朝汐突然拥有更多能力。

它负责的是：

> **让已经存在的能力第一次真正变得“看得见”。**

并且让复杂任务从：

```text
沉默
沉默
沉默
最终回复
```

变成：

```text
先回应
↓
继续做事
↓
让过程可见
↓
最终回来
```

这是整个 v1.4 长周期打磨阶段的第一块地基。

后续：

```text
性能优化
Planner 显式化
Memory 收口
Current Cognition 重构
Dashboard
Presence
视觉统一
```

都可以建立在这一版产生的真实运行数据之上。
