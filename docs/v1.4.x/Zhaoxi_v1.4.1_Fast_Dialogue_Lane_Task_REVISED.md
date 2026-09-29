# Zhaoxi v1.4.1 · Fast Dialogue Lane 开发任务书（基于 v1.4.0 正式修订版）

> 项目：**Zhaoxi / 朝汐**
> 版本：**v1.4.1**
> 主题：**Fast Dialogue Lane & Standard Tool Short-Circuit**
> 定位：v1.4 长周期打磨阶段的第二个小版本
> 前置基线：**v1.4.0 Runtime Observatory & Progressive Response 已完成**
>
> 本版只解决两个核心问题：
>
> 1. **普通聊天必须真正轻量化。**
> 2. **普通单 Tool 任务必须及时收口。**
>
> 不再重复开发 v1.4.0 已完成的 Runtime Observatory、Planner Trace、Memory Inspector、Visibility Contract、Post-turn Maintenance Queue 等能力。

---

# 0. v1.4.0 已完成基线

以下能力视为 v1.4.1 的既有基础，不再重复开发：

```text
Runtime Observatory
Planner Trace → ActionTrace
Memory Retrieval Inspector
Interim Reply 独立事件
Visibility Contract
幽灵回复修复
Final Reply 优先交付
AutoMemory / Current Cognition 后台队列
Tool Discovery 去重
回复分段节奏统一
运行观测中文化
```

v1.4.1 应直接复用现有：

```text
ActionTrace
Runtime Metrics
LLM / Tool duration
Memory candidate snapshot
Post-turn Maintenance Queue
Visibility classification
interim_reply
```

本版不是“再做一套性能观测”，而是：

> **利用 v1.4.0 已经提供的数据，真正减轻前台回复链。**

---

# 1. 当前真实问题

v1.4.0 实机 Trace 已证明：

```text
“小金毛？”
```

这种本应纯聊天的输入，仍可能走成：

```text
Router LLM
↓
Memory Retrieval
↓
Agent LLM #1
↓
Tool
↓
Agent LLM #2
↓
Tool Discovery / inspect_tool_catalog
↓
Agent LLM #3
↓
Agent LLM #4
↓
Final Reply
```

Tool 自身可能只耗：

```text
< 2s
```

真正的耗时主体是：

```text
“再问一次模型下一步干什么” × N
```

因此当前最大的问题不是：

```text
Tool 慢
```

而是：

```text
普通消息默认进入了过重的 Agent Runtime。
```

---

# 2. v1.4.1 的一句话目标

> **让朝汐重新拥有“只是和暗苟说句话”的能力。**

默认：

```text
聊天
```

只有明确需要真实行动时才升级：

```text
Tool / Recall / Decision / Planner
```

---

# 3. Runtime 三档模型

从 v1.4.1 开始，将“运行重量”和“能力类型”分开。

---

## 3.1 FAST

用途：

```text
普通聊天
打招呼
情绪回应
轻量讨论
短社交承接
简单解释
```

硬约束：

```text
Foreground LLM Calls = 1
Router LLM Calls = 0
Long-Term Memory Retrieval = 0
Tool Calls = 0
Tool Discovery = 0
Decision = 0
Planner = 0
Workflow = 0
```

目标：

```text
典型 Final Latency < 10~15s
```

---

## 3.2 STANDARD

用途：

```text
明确 Memory Recall
单 Tool
简单外部查询
简单 Decision
有限动作
```

目标：

```text
Foreground LLM Calls <= 2（通常）
Tool Round <= 1（通常）
```

---

## 3.3 DEEP

用途：

```text
多个步骤
前后依赖
多个 Tool
结果检查
Replan
复杂 Decision
```

允许：

```text
Planner
Workflow
多轮 LLM
Progressive Response
```

---

# 4. P0 · Fast Dialogue Gate 必须位于 Router LLM 前

当前链路：

```text
User
↓
Router LLM
↓
Local Guard
```

修改为：

```text
User
↓
Fast Dialogue Gate
├─ FAST_CHAT
│    ↓
│  run_fast_chat()
│
└─ Not FAST
     ↓
   Existing Cognitive Router
```

Router 从：

```text
每轮必经
```

改为：

```text
有歧义时才调用
```

---

# 5. FAST Gate 的职责

Fast Gate 不负责“理解一切”。

它只判断：

> **当前这句话是否可以安全地只聊天，而不需要真实副作用、长期回忆、外部查询或复杂决策。**

---

# 6. FAST 禁入条件

只要命中以下任一项，就不走 FAST。

---

## 6.1 图片输入

```text
images > 0
→ 非 FAST
```

---

## 6.2 Pending Permission

```text
存在待确认操作
→ Permission Resume
```

---

## 6.3 明确真实动作

例如：

```text
记一下
写进
添加
删除
修改
保存
发送
提醒我
打开
关闭
执行
帮我填
同步
上传
```

如果语义要求真实系统副作用：

```text
→ TOOL / WORKFLOW / Router
```

---

## 6.4 明确长期回忆

例如：

```text
你还记得
之前那个
上次
以前我们
我什么时候
之前说过
回忆一下
```

```text
→ RECALL / STANDARD
```

---

## 6.5 明确决策

例如：

```text
要不要
该不该
选哪个
值不值得
去不去
接不接
怎么选
```

```text
→ Decision
```

---

## 6.6 明确外部 / 实时事实查询

例如：

```text
查一下
搜一下
看看现在
最新
今天有什么
帮我查
```

需要真实外部状态时：

```text
→ STANDARD / TOOL
```

---

# 7. 社交短句默认优先 FAST

以下类型默认视为：

```text
“用户在和朝汐说话”
```

而不是：

```text
“用户要求继续之前的 Agent Task”
```

例如：

```text
小金毛？
在吗
诶
哈哈哈哈
笑死
好家伙
今天好热
我刚吃完
有点烦
可恶
这也太怪了
```

即使 Recent Context 中刚刚存在：

```text
LifeHUD
面试记录
Tool
Planner
```

也不能自动续旧任务。

---

# 8. 只有显式承接词才允许把短句拉回旧任务

候选：

```text
继续
然后呢
接着
刚刚那个
前面那个
那两条呢
剩下的呢
这个再改一下
按刚才的继续
```

原则：

> **Recent Context 可以辅助理解，但不能绑架当前消息。**

---

# 9. P0 · 新增真正独立的 run_fast_chat()

禁止复用：

```python
run_direct()
```

因为旧 DIRECT 仍可能经过：

```text
Memory Retrieval
Tool Context
Agent Loop
```

应新增真正独立的：

```python
run_fast_chat(...)
```

---

# 10. Fast Chat 前台链路

目标：

```text
User Message
↓
Fast Dialogue Gate
↓
FastChat Context
↓
provider.generate(messages, tools=None)
↓
Commit Final Reply
↓
Immediate Delivery
↓
Post-turn Maintenance Queue
```

禁止：

```text
Agent while-loop
Memory Retrieval
Tool Discovery
Tool Catalog
Planner
Workflow
Decision
Router Model
```

---

# 11. Fast Chat Context

FAST 只带：

```text
Persona / Character Prompt
Current Cognition
当前时间
最近 Owner Conversation
当前 User Message
```

建议 Recent Conversation：

```text
最近 4~8 条
总字符约 2000~3000
```

禁止注入：

```text
Long-Term Memory Search Result
完整 Tool Catalog
Tool Schema
Planner State
Workflow Catalog
Decision Rules
Internal Tool-turn
Tool Result
Debug / Trace
无关第三方 Observation
```

---

# 12. FAST 不检索长期 Memory

硬验收：

```text
FAST_CHAT
→ memory_search_count = 0
```

分工：

```text
Current Cognition
→ 最近生活整体状态

Recent Conversation
→ 当前局部连续性

Long-Term Memory
→ 真正需要历史回忆时再查
```

---

# 13. FAST 不得主动寻找“可以做的事”

Fast Prompt 增加明确约束：

```text
当前处于 FAST_CHAT。

你的任务只是自然回应用户当前这句话。

不要主动延续近期未完成任务。
不要因为你知道某个 Tool 存在，就寻找调用理由。
不要声称已经读取、写入、修改、保存、发送、查询任何外部系统。
```

---

# 14. FAST Action Commitment Guard

如果 FAST 输出出现明显真实动作承诺：

```text
我去查一下
我帮你写进去
我现在更新
```

而当前没有 Tool：

```text
Reject FAST Response
↓
最多升级一次
↓
STANDARD / Router
```

禁止：

```text
FAST → Agent → FAST → Agent
```

形成新循环。

---

# 15. P0 · STANDARD Tool Short-Circuit

普通 Tool 任务的标准形态必须收敛成：

```text
LLM #1
↓
Business Tool
↓
Finalization LLM #2
↓
结束
```

目标：

```text
Foreground LLM Calls <= 2
Tool Round <= 1
```

---

# 16. Tool 成功后默认强制 Finalization

如果：

```text
至少一个业务 Tool 成功
AND
无 waiting_for_permission
AND
无失败需要修复
AND
当前 Route != PLAN
AND
没有明确剩余依赖步骤
```

则下一轮强制：

```text
final_only = true
tools = []
tool_catalog = []
discovery_controls = []
```

禁止：

```text
inspect_tool_catalog
request_tool_group
继续寻找额外能力
```

---

# 17. Tool Discovery 在 Finalization 阶段必须关闭

即使之前 Tool Discovery 可用：

```text
Finalization
→ no tools
→ no discovery controls
```

避免：

```text
Tool 已成功
↓
模型又问“我还有什么能力？”
↓
inspect_tool_catalog
↓
再开一轮模型
```

---

# 18. STANDARD Tool Round Budget

建议：

```text
standard_tool_round_limit = 1
standard_model_call_target = 2
```

允许例外：

```text
一次参数校验修复
权限确认恢复
一次明确 transient retry
```

一旦发生额外轮数，Trace 必须写：

```text
extra_round_reason
```

---

# 19. 多步任务不要偷偷膨胀，直接升级 DEEP

如果真实需求是：

```text
查 A
↓
根据 A 决定 B
↓
执行 B
↓
再检查 B
```

这不是 STANDARD。

应明确：

```text
→ PLAN / DEEP
```

不要让普通 Agent Loop 靠连续模型调用“偷偷变成 Planner”。

---

# 20. Existing Tool Discovery 的复用与限制

v1.4.0 已经具备：

```text
规范化查询去重
目录版本去重
无进展循环有界收口
```

v1.4.1 不重做这一套。

只补：

```text
1. STANDARD 成功执行目标 Tool 后禁止再次 Discovery
2. Finalization 禁止 Discovery
3. 同轮相同 inspect 默认最多一次
4. 额外 Discovery 必须有明确原因
```

---

# 21. Router LLM 的新职责

Router 只处理：

```text
Fast Gate 无法判断
Tool / Workflow 有歧义
复杂承接
Plan vs Tool 边界
```

不再处理普通闲聊。

---

# 22. Runtime Route 标记

新增明确：

```text
FAST_CHAT
```

不要继续塞进：

```text
DIRECT
```

建议观测层区分：

```text
FAST_CHAT
DIRECT
TOOL
PLAN
WORKFLOW
```

---

# 23. Runtime Observatory 补充字段

v1.4.0 已有完整 Observatory。

v1.4.1 只新增与路径选择相关的字段：

```text
runtime_lane
route_source

foreground_llm_calls
background_llm_calls

router_llm_calls
agent_llm_calls
planner_llm_calls

memory_search_count
tool_rounds
catalog_inspections

fast_gate_reason
escalation_reason
extra_round_reason
```

不要再造第二套 Debug 页面。

---

# 24. FAST 验收场景

## Case A

```text
小金毛？
```

要求：

```text
runtime_lane = FAST
router_llm_calls = 0
memory_search_count = 0
tool_calls = 0
foreground_llm_calls = 1
planner = false
```

并且不得自动继续近期 LifeHUD 任务。

---

## Case B

```text
今天真热啊
```

要求同 A。

---

## Case C

```text
我刚吃完饭
```

要求：

```text
只聊天
不自动写 LifeHUD
不检索长期 Memory
```

后台是否进入 AutoMemory / Current Cognition：

```text
由 v1.4.0 Post-turn Maintenance 决定
```

---

## Case D

上一轮正在讨论 Tool：

```text
在吗？
```

要求：

```text
FAST_CHAT
```

不得续旧任务。

---

## Case E

上一轮正在讨论 Tool：

```text
刚刚那两条继续
```

要求：

```text
FAST 不命中
→ Router / Tool / Plan
```

---

# 25. STANDARD 验收场景

## Case F

```text
帮我看看今天 LifeHUD 的饮食记录
```

目标：

```text
Agent LLM #1
↓
LifeHUD
↓
Finalization LLM #2
↓
结束
```

禁止无理由出现：

```text
LLM #3
inspect_tool_catalog
LLM #4
```

---

## Case G

```text
把这条饮食记录写进去
```

要求：

```text
业务 Tool 成功
↓
直接 Finalization
```

---

## Case H

```text
先查今天记录，再根据结果补缺失的，再重新核对
```

要求：

```text
升级 PLAN / DEEP
```

---

# 26. 性能目标

## FAST

```text
Foreground LLM Calls = 1
Router Model Calls = 0
Memory Search = 0
Tool Calls = 0
```

目标：

```text
典型 Final Latency < 10~15s
```

如果 Provider 本身慢，不强行保证绝对秒数，但 Runtime 不得再额外增加第二次前台模型。

---

## STANDARD Tool

```text
Foreground LLM Calls <= 2（通常）
Tool Round <= 1（通常）
```

---

## DEEP

不设死调用次数，但必须继续使用：

```text
Progressive Response
Planner Trace
Runtime Observatory
```

---

# 27. Post-turn Maintenance 直接复用 v1.4.0

v1.4.1 不再改造：

```text
AutoMemory 后台队列
Current Cognition 后台队列
Visibility Contract
Final Delivery
```

只要求：

```text
FAST Final Reply
↓
立即交付
↓
继续进入既有 Post-turn Maintenance Queue
```

---

# 28. FAST 不等于削弱“广记”

FAST：

```text
不查长期 Memory
```

但仍可以：

```text
ExperienceStream 记录
AutoMemory 后台判断
Current Cognition 后台维护
```

区别：

> **记录可以后台慢慢做，聊天不能等它做完。**

---

# 29. 外部渠道

第一版优先：

```text
Desktop / Web Owner
```

验证稳定后复用到：

```text
Owner QQ Direct
```

第三方 / 群聊继续遵守现有 Perception 和隐私边界。

---

# 30. 失败与降级

FAST 模型失败：

```text
按现有 Provider Retry Policy
```

不要默认 fallback 到完整 Agent Loop。

STANDARD 超预算：

```text
真的多步
→ DEEP / Planner

只是模型漂移
→ 强制 Finalization
```

---

# 31. 建议代码结构

候选：

```text
src/zhaoxi/cognitive/fast_gate.py
src/zhaoxi/core/fast_chat.py
```

建议：

```python
FastDialogueDecision(
    eligible: bool,
    reason: str,
    continuation_detected: bool,
)
```

Coordinator：

```text
Pending Permission
↓
Image / Override 等硬路径
↓
FastDialogueGate
├─ hit → run_fast_chat()
└─ miss → CognitiveRouter
```

---

# 32. 推荐开发顺序

## Phase 1 · Fast Gate

- [ ] FAST eligibility
- [ ] 社交短句优先
- [ ] continuation markers
- [ ] action / recall / decision / query exclusions
- [ ] fast_gate_reason

## Phase 2 · run_fast_chat()

- [ ] 单次 Provider 调用
- [ ] 无 Tool Schema
- [ ] 无 Memory Retrieval
- [ ] 精简 Context
- [ ] Final Reply 正常持久化
- [ ] 接既有 Post-turn Maintenance

## Phase 3 · Action Commitment Guard

- [ ] 禁止虚假 Tool 承诺
- [ ] 最多升级一次
- [ ] 禁止循环

## Phase 4 · Standard Tool Short-Circuit

- [ ] Tool Round Budget
- [ ] Tool 成功后 final_only
- [ ] Finalization 禁止 Tool Discovery
- [ ] extra_round_reason

## Phase 5 · Observatory 字段补充

- [ ] runtime_lane
- [ ] route_source
- [ ] foreground/background LLM calls
- [ ] tool_rounds
- [ ] catalog_inspections
- [ ] escalation_reason

## Phase 6 · 实机验收

至少：

```text
10 条普通闲聊
5 条短社交承接
5 条单 Tool
3 条明确 Memory Recall
3 条 Decision
3 条多步 Planner
```

记录：

```text
平均前台 LLM Calls
P50 / P95 Final Latency
误升级率
误 FAST 率
Tool 后额外轮数
```

---

# 33. 本版明确不做

以下全部后移：

```text
Current Cognition 内容重构
Memory Lifecycle 收口
真实 Embedding
Dashboard 全面改版
Presence 2.0
向日葵视觉统一
Planner 完整 UI
手机端
```

v1.4.1 只处理：

> **什么时候该只是聊天，以及普通做事什么时候该停。**

---

# 34. 完成标准

```text
1. “小金毛？”只发生 1 次前台模型调用。

2. 普通聊天不再固定调用 Router LLM。

3. 普通聊天不再固定检索长期 Memory。

4. 普通聊天不再携带 Tool Catalog / Schema。

5. Recent Context 不会把所有短句吸回旧任务。

6. 单 Tool 任务通常只需要：
   模型 → Tool → Finalization。

7. Tool 成功后不会继续无意义 inspect_tool_catalog。

8. 真正多步任务会显式升级 DEEP / Planner。

9. v1.4.0 的 Final 优先交付、后台维护和 Visibility Contract 保持不变。

10. Runtime Observatory 能清楚显示 FAST / STANDARD / DEEP 路径。
```

---

# 35. 一句话定义

> **v1.4.1 不是让朝汐少会一点，而是让她学会：有时候暗苟只是叫了她一声，不需要先把整个工具箱、记忆库和 Planner 都搬出来。**
