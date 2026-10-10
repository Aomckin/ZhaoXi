# Zhaoxi v1.4.8.x · Interim Reply Semantic Patch
## “边做边说”中间回复语义修正补丁任务书

> 项目：**Zhaoxi / 朝汐**  
> 类型：**Reliability / Progressive Response / Agent Loop UX Patch**
>
> 核心修正：
>
> > **中间回复不是一个额外动作。**
>
> > **它应该是朝汐决定下一步行动时，同一次模型输出中自然说给暗苟的一句话。**
>
> 简写：
>
> ```text
> Say While Acting
> ```
>
> 而不是：
>
> ```text
> Decide Action
> ↓
> 再调用一个 emit_interim_reply Tool
> ↓
> 再说话
> ```

---

# 0. 背景

v1.4.0 起已经存在 Progressive Response / Interim Reply 能力。

v1.4.8 又继续修补：

```text
工具暴露时机
时长阈值
拒绝原因诊断
真实进展门控
```

但实际 Dogfooding 后发现：

> **当前系统理解错了“中间回复”的本质。**

现有思路更接近：

```text
Agent 已经在行动
↓
达到条件
↓
Runtime 给模型暴露 emit_interim_reply
↓
模型额外决定是否调用
↓
发送一条中间回复
```

这会产生几个问题：

```text
1. 中间回复像系统播报，不像朝汐本人
2. 模型要额外“决定是否说话”
3. 中间回复与下一步行动割裂
4. 门控很多，但真实日用仍极少触发
5. 为了一句等待中的自然交流，造出了独立 Tool 语义
```

---

# 1. 用户真正想要的行为

正确模型：

```text
用户请求
↓
Model Step
├─ 决定下一步要做什么
└─ 同时可顺口说一句给暗苟
↓
执行 Tool
↓
Model Step
├─ 根据新结果决定下一步
└─ 必要时再顺口说一句
↓
……
↓
Final Reply
```

也就是说：

> **一次模型调用同时产出“行动”和“可选可见文本”。**

---

# 2. 核心定义

## Interim Reply

定义为：

> **一个尚未结束本轮任务的 Agent Step 中，由主模型自然产生的用户可见文本。**

它不是：

```text
Tool
后台状态播报
Runtime 固定模板
额外模型调用
最终回复
```

它是：

```text
主模型当前行动步骤的 visible part
```

---

# 3. 最重要的设计句

> **Interim Reply is not an action. It is the visible part of an action step.**

中文：

> **中间回复不是朝汐额外做的一件事，而是她在做下一件事时顺口跟暗苟说的一句话。**

---

# 4. 理想示例

用户：

```text
帮我看看今天下午有什么安排，再判断要不要出去打舞萌。
```

第一次模型调用：

```text
content:
“我先翻下今天的安排哦，看看下午有没有硬事～”

tool_calls:
agenda_list(...)
```

Runtime：

```text
发送 content 作为 interim reply
执行 agenda_list
```

第二次模型调用：

```text
content:
“下午倒是挺空的，我再看看最近项目这边有没有东西卡着。”

tool_calls:
read_current_cognition(...)
```

Runtime：

```text
根据门控决定是否展示这句
执行工具
```

最后一次模型调用：

```text
content:
“去打舞萌吧！下午没硬安排，项目现在也没有非今天不可的节点，出去玩一轮更值。”

tool_calls:
[]
```

Runtime：

```text
按现有 Final Reply 流程提交
结束本轮
```

---

# 5. 目标链路

旧：

```text
Model
↓
Tool Call
↓
执行
↓
……
↓
达到 Interim 条件
↓
暴露 emit_interim_reply
↓
模型调用 Interim Tool
↓
继续执行
```

新：

```text
Model
↓
Response
├─ content
└─ tool_calls

if tool_calls:
    content 可作为 interim
    执行 tool_calls
    continue

if no tool_calls:
    content = final reply
    commit
    finish
```

---

# 6. 最优实现方向

优先检查并复用现有 Provider Response：

```text
response.content
response.tool_calls
```

如果 Provider 本身已经支持：

```text
content + tool_calls 同时存在
```

则不要新增复杂 Step Schema。

直接让现有 Agent Loop 正确消费二者。

---

# 7. Agent Step 新语义

当前不能再默认：

```text
有 tool_calls
→ content 没用 / 忽略
```

而应改成：

```text
有 tool_calls
+
content 非空
→ content 是本步骤潜在 Interim Reply
```

随后：

```text
Runtime 判断是否值得送达
```

---

# 8. Final Reply 判定

最终回复仍保持非常简单：

```text
response.tool_calls 为空
+
response.content 有效
→ Final Reply
```

最终回复继续走现有：

```text
reply protocol
emoji
decision awareness
commit_reply
Conversation persistence
final delivery
```

不要因为 Interim Patch 重写 Final Reply。

---

# 9. 中间回复来自谁

必须来自：

```text
朝汐主模型
```

并继承：

```text
Persona
当前 Conversation
Current Context
刚得到的 Tool Result
当前行动目的
```

因此它自然可以是：

```text
“我去翻一下今天的日程哦～”
```

而不是：

```text
“正在查询日程。”
```

---

# 10. 删除固定人格文案

当前或旧补丁中如果存在：

```text
固定 interim 文案
Runtime 自动文案
模板化“正在……”
```

应移出正常用户可见链路。

允许：

```text
只用于 Debug / fallback
```

但不能冒充朝汐正常台词。

---

# 11. 不增加模型调用

这是硬要求。

正确：

```text
Model Step
→ content + tool_calls
```

错误：

```text
Model Step
→ tool_calls

额外 Model Call
→ 生成一句 Interim Reply
```

补丁不能因为“更有人格”增加一次模型调用。

---

# 12. 不再把 Interim Reply 设计成 Tool

现有：

```text
emit_interim_reply
```

应逐步退场。

建议迁移：

```text
Phase 1
新旧机制并存，默认优先 Say While Acting

Phase 2
确认稳定后关闭 emit_interim_reply Tool 暴露

Phase 3
删除 Tool 入口及相关 Prompt / Schema
```

---

# 13. 可以保留什么

以下基础设施可以保留：

```text
ActionTrace.emit_interim(...)
interim_reply SSE / Event
前端 transient bubble
first_reply_ms
interim_replies 统计
sequence
request_id / trace_id
```

也就是说：

> **保留“怎么送出去”，改掉“内容怎么产生”。**

---

# 14. Runtime 的职责

主模型负责：

```text
这一步想不想顺口说一句
说什么
```

Runtime 负责：

```text
这句话现在是否值得真正展示
```

职责必须分开。

---

# 15. Runtime Gate

不要求模型每一步都播报。

Runtime 可以继续做轻门控。

建议考虑：

```text
任务已运行多久
是否已经发过 Interim
当前是否有真实新行动 / 新进展
内容是否重复
内容是否过长
是否泄露内部字段
是否错误宣称完成
```

---

# 16. 时长阈值的新定位

旧理解：

```text
超过 10 秒
→ 才允许模型拥有“说话能力”
```

新理解：

```text
模型一直可以产生 Step Visible Text
```

但：

```text
Runtime 可以在任务太快时选择不展示
```

例如：

```text
Step 1 在 800ms 内马上执行完
→ 不必显示

任务已经 8~10 秒
→ 更倾向显示

刚产生有意义的新阶段
→ 可以显示
```

---

# 17. 不要求严格 10 秒

`interim_threshold_seconds` 可以保留为：

```text
展示阈值
```

而不是：

```text
模型工具暴露阈值
```

这能大幅简化语义。

---

# 18. 主模型 Prompt

需要加入一小段明确规则：

```text
当你还需要调用工具或继续行动时，
你可以在同一次回复中同时给出一句简短、自然的可见文本和下一步 Tool Call。

这句话是你顺口告诉暗苟“我现在去做什么 / 我刚知道了什么后准备继续做什么”，
应保持朝汐人格。

不要播报每个内部步骤。
不要说后台术语、step、trace、tool call、JSON。
没有值得说的内容时，content 可以为空，直接调用工具。

如果本轮已经可以最终回答，则不要再调用工具，正常给出最终回复。
```

保持薄 Prompt。

---

# 19. 不强制每步都有 content

合法：

```text
content = ""
tool_calls = [search_memory]
```

合法：

```text
content = "我再确认一下最近项目的状态哦。"
tool_calls = [read_current_cognition]
```

都可以。

---

# 20. 避免碎碎念

必须避免：

```text
“我先查一下。”
“我再看一下。”
“我继续查一下。”
“我现在再检查一下。”
```

连续刷屏。

建议 Runtime Gate：

```text
相近语义去重
最短展示间隔
最大 Interim 次数
```

---

# 21. Interim 数量

普通 Agent：

```text
默认最多 1~2 条
```

Planner 长任务：

```text
可稍多
```

但不机械按每一步输出。

---

# 22. Interim 长度

保持短。

建议：

```text
1~2 句
大约 10~80 中文字符
```

硬上限可以保留：

```text
180 chars
```

---

# 23. 禁止内容

Interim 不得：

```text
泄露 trace_id
泄露 invocation_id
泄露 token
泄露内部 schema
说“LLM”
说“第 3 步”
展示 JSON
提前宣告任务完成
把未验证结果说成事实
```

---

# 24. 可以说什么

适合：

```text
当前要去查什么
为什么还需要再看一个信息
已经得到一个初步事实，但仍需继续确认
阶段方向发生变化
```

例如：

```text
“下午是空的，我再看看项目这边有没有急事。”
```

---

# 25. 不该说什么

不值得：

```text
“我调用一下 calculator。”
“正在执行 Tool。”
“已经进入 Planner step 2。”
```

---

# 26. Interim 不进入 Conversation

保持原设计：

```text
不作为正式 assistant turn
```

原因：

```text
它只是本轮过程语言
```

最终 Conversation 仍然只记录：

```text
用户请求
最终朝汐回复
```

---

# 27. Interim 不进入 Memory

禁止：

```text
AutoMemory
Long-term Memory
Current Cognition
Decision Journal
Choice History
```

把 Interim 当成新的事实来源。

---

# 28. Interim 不影响 Decision

Decision Awareness 应以：

```text
真实用户输入
最终回复
实际 Tool / Context
```

为准。

不能因为 Interim 说：

```text
“我觉得可能……”
```

就产生 Decision History。

---

# 29. 刷新后的处理

第一版允许：

```text
Interim 是 transient
刷新后不恢复
```

只要 Final Reply 和执行结果正常持久化即可。

后续如果想保留过程时间线，再单独设计。

---

# 30. Final Reply 必须独立完整

即使用户已经看过 Interim：

```text
Final Reply 仍应完整回答原请求
```

不能写：

```text
“所以就按刚才说的。”
```

因为：

```text
Interim 可能未持久化
可能没成功送达
可能刷新丢失
```

---

# 31. Interim 送达失败

如果：

```text
SSE 断开
前端没显示
```

不能影响：

```text
Tool 执行
Final Reply
```

Interim Delivery 永远是：

```text
best effort
```

---

# 32. Tool 失败后的行为

例如：

```text
Interim:
“我去看一下日程哦。”

Tool:
失败
```

下一轮模型拿到失败结果后：

```text
仍然可以继续降级
```

最终：

```text
“日程刚刚没拿到，我先按现在知道的信息说……”
```

不能因为之前 Interim 承诺“去查”而假装查成功。

---

# 33. 用户中途再次发消息

如果当前架构支持前台抢占 / cancel：

```text
Interim 不改变现有取消规则
```

新用户输入到达后：

```text
旧请求按现有策略取消 / 收口
```

不能让旧 Interim 继续发送。

---

# 34. 与 Graceful Degradation 协作

这个补丁应提高：

```text
长任务等待体验
```

但不能降低可靠性。

优先级：

```text
Final Delivery
>
Tool Correctness
>
Interim Reply
```

Interim 永远不能让主链失败。

---

# 35. 与 Tool Call Protocol 协作

需要重点检查 Provider：

```text
content + tool_calls
```

是否在当前所有 Provider 适配器中都被完整保留。

如果某 Provider：

```text
Tool Call 时无法可靠产出 content
```

则：

```text
该 Provider 可以没有 Interim
```

不能为统一外观增加第二次模型调用。

---

# 36. Provider Capability

建议增加能力诊断：

```text
supports_content_with_tool_calls
```

如果无需新增正式 capability 字段，也至少在测试中验证各 Provider 行为。

---

# 37. 如果当前 Reply Protocol 与 Tool Call 冲突

若现有结构要求：

```text
content 必须是特殊 JSON / reply protocol
```

不要强行把 Interim 挤进最终回复 Schema。

更合理的是：

```text
Tool Step 的 response.content
只作为 plain persona text
```

Final Step：

```text
继续走完整 reply protocol
```

具体以现有 Provider / Reply parser 最小修改实现。

---

# 38. Agent Loop 处理顺序

建议：

```python
response = await provider.generate(...)

if response.tool_calls:
    maybe_emit_step_text(response.content)
    execute_tools(response.tool_calls)
    continue

final = response.content
commit_final(final)
return
```

只是语义示意，不要求照抄。

---

# 39. Tool Call 前发送还是后发送

原则：

```text
如果 content 描述“我现在去做什么”
→ Tool 前发送
```

例如：

```text
“我先看看今天的日程。”
```

然后执行。

如果 content 描述：

```text
“刚才看到 A，我还要继续确认 B。”
```

它也是在下一次 Tool 前发送。

因此统一：

> **Step content 与该 Step tool_calls 同时产生，content 在 Tool 执行前送达。**

---

# 40. 不让模型伪造已执行结果

Prompt 明确：

```text
本轮 Tool Call 尚未执行时，
visible content 只能表达“准备去做 / 接下来要确认”。

不能表达：
“我已经查到……”
```

除非这个事实来自：

```text
上一轮 Tool Result
```

---

# 41. Planner

Planner 也采用同一理念：

> **Planner 的中间回复应来自正在决定下一步 Planner Action 的同一次模型调用。**

不是：

```text
额外 emit_interim_reply Tool
```

---

# 42. Planner 的特殊点

Planner 可以有更多阶段，因此可允许：

```text
更多 Interim
```

但仍要求：

```text
有新进展
才说
```

---

# 43. Planner 不要输出计划流水账

禁止：

```text
“步骤1完成，步骤2开始。”
```

除非这本身对用户有意义。

更自然：

```text
“岗位信息已经确认了，我再核一下你之前对这类制度的底线。”
```

---

# 44. Workflow

第一版可以不改 Workflow。

如果 Workflow 已有独立状态机：

```text
保持现状
```

后续如需要，再让 Workflow Step 拥有类似 visible_text。

不要把补丁范围继续扩大。

---

# 45. FAST

FAST 一般不需要 Interim。

原因：

```text
本来就应该快
```

如果 FAST 升级 STANDARD：

```text
进入 STANDARD 后再使用新机制
```

---

# 46. UI 展示

前端继续显示：

```text
普通朝汐气泡
```

但视觉上可以：

```text
稍轻
不显示为最终完成态
```

不要显示：

```text
系统通知卡
后台日志条
```

它是朝汐本人说的话。

---

# 47. UI 标记

内部 metadata：

```text
type = interim_reply
terminates_turn = false
request_id
sequence
```

用户界面不必写：

```text
“中间回复”
```

---

# 48. Final Reply 到达

最终回复到达后：

```text
Interim 气泡保留在当前页面
Final Reply 正常追加
```

不要：

```text
用 Final 覆盖 Interim
```

当前页形成：

```text
朝汐：我先看看日程哦～
朝汐：下午挺空的，我再看一下项目状态。
朝汐：去打舞萌吧……
```

---

# 49. 历史刷新

若 Interim 不持久化：

刷新后可以只剩：

```text
用户请求
最终回复
```

这是第一版可接受行为。

---

# 50. Observability

保留以下指标：

```text
interim_replies
first_reply_ms
interim_response_emitted
```

新增建议：

```text
interim_candidate_generated
interim_candidate_suppressed
```

---

# 51. Suppress Reason

建议诊断原因：

```text
too_fast
duplicate
too_long
no_progress
max_count
unsafe_content
terminal_claim
delivery_unavailable
```

方便以后 Dogfooding。

---

# 52. 不把 Suppress 当失败

没有发 Interim：

```text
不是失败
```

Final Reply 成功即可。

---

# 53. 测试：最基本 Say + Act

模型响应：

```text
content = “我先查一下今天的安排哦。”
tool_calls = [agenda_list]
```

预期：

```text
先产生 interim_reply event
再执行 agenda_list
最终仍继续模型循环
```

---

# 54. 测试：无话可说

```text
content = ""
tool_calls = [search_memory]
```

预期：

```text
不发 Interim
正常执行 Tool
```

---

# 55. 测试：快速任务

模型有：

```text
content + tool_calls
```

但整轮刚开始。

预期可按当前策略：

```text
抑制 Interim
```

并继续执行。

---

# 56. 测试：长任务

运行已超过阈值：

```text
content + tool_calls
```

预期：

```text
发送 Interim
```

---

# 57. 测试：重复内容

连续：

```text
“我再查一下。”
“我再查一下。”
```

第二条应被 suppress。

---

# 58. 测试：人格

确认 Interim 来自主模型原生 content。

不能：

```text
被 Runtime 换成固定模板
```

---

# 59. 测试：提前完成宣称

Tool 尚未执行：

```text
“已经帮你查完了。”
+ tool_call
```

预期：

```text
Interim 不发送
```

工具继续执行。

---

# 60. 测试：Tool 失败

先成功发：

```text
“我去看日程。”
```

Tool 失败。

最终：

```text
明确说明没拿到日程
```

不能假成功。

---

# 61. 测试：Final 独立完整

即使 Interim 已送达：

```text
Final Reply 单独看也能完整理解
```

---

# 62. 测试：SSE 失败

Interim sink 报错 / 断连：

```text
主 Agent Loop 不失败
Tool 正常执行
Final 正常交付
```

---

# 63. 测试：不污染 Conversation

执行后检查：

```text
正式 Conversation
```

只有：

```text
User
Final Assistant
```

没有 Interim Assistant。

---

# 64. 测试：不污染 Memory / Cognition

Interim 不参与：

```text
AutoMemory
Current Cognition
Decision Learning
```

---

# 65. 测试：多 Provider

至少覆盖当前实际使用 Provider：

```text
content only
tool_calls only
content + tool_calls
```

行为都不出错。

---

# 66. 测试：Planner

Planner：

```text
说一句 + 下一步行动
```

应能自然送达。

---

# 67. 回归：Final Reply

确保：

```text
普通聊天
图片聊天
Tool
Decision
Memory
emoji
regenerate
permission
timeout
```

最终回复逻辑不被破坏。

---

# 68. 迁移 emit_interim_reply

建议第一阶段：

```text
保留旧实现代码
默认不开给 Agent / Planner
```

可通过 Debug flag 临时回滚。

---

# 69. 最终删除条件

Dogfooding 确认：

```text
新机制可以稳定出现自然中间回复
不会明显刷屏
不增加模型调用
Final Reply 稳定
```

以后再删旧 Tool。

---

# 70. 验收场景 A

用户：

```text
“帮我查一下今天日程，再看看下午干嘛。”
```

理想：

```text
朝汐：
“我先翻下今天的安排哦～”

[内部执行 Agenda]

朝汐：
“下午没硬安排，我再看看最近项目有没有急事。”

[内部读取状态]

朝汐最终：
“下午去打舞萌吧……”
```

---

# 71. 验收场景 B

用户：

```text
“帮我把这个订单记到物簿。”
```

如果一步工具足够快：

```text
可以完全没有 Interim
```

直接：

```text
Final Reply
```

不要为了展示功能强行插一句。

---

# 72. 验收场景 C

复杂多步请求运行 30 秒：

至少应有机会出现：

```text
一条自然、有人格、有实际意义的 Interim
```

不是：

```text
固定等待文案
```

---

# 73. 验收场景 D

单个 Provider 调用自己阻塞 30 秒。

因为模型没有返回：

```text
本机制无法凭空生成 Interim
```

这是明确边界，不算 Bug。

如果未来要解决：

```text
需要流式 reasoning / 独立心跳机制
```

属于另一问题。

---

# 74. 本补丁明确不解决

```text
单次模型调用自身长时间阻塞
网络完全断开时的即时自然语言
Provider 没有任何输出时自动编造人格台词
复杂 Workflow Progressive Response
持久化 Interim 历史
```

---

# 75. 性能目标

补丁必须满足：

```text
额外模型调用 = 0
```

同时：

```text
Tool Call 数量不增加
Memory Retrieval 不增加
Router 不增加
```

---

# 76. 用户体验目标

最终感觉应该是：

```text
朝汐正在和我一起做事
```

而不是：

```text
我向后台提交了一项任务
后台偶尔发状态通知
```

---

# 77. 与 v1.4.x Reliability 的关系

这不是单纯“角色味修复”。

它直接解决：

```text
长任务等待的不确定感
中间回复触发率过低
固定文案割裂人格
额外 Interim Tool 复杂度
```

同时不能损害：

```text
98%+ 最终回复稳定性目标
```

因此：

> **Final Reply 永远优先于 Interim Reply。**

---

# 78. 开发建议顺序

## Phase 1

确认当前各 Provider 是否保留：

```text
content + tool_calls
```

## Phase 2

修改 Agent Loop：

```text
Tool Step content
→ Interim Candidate
```

## Phase 3

复用 ActionTrace：

```text
emit_interim
```

但去掉：

```text
“必须由 emit_interim_reply Tool 触发”
```

## Phase 4

薄 Prompt 调整：

```text
允许边说边行动
```

## Phase 5

迁移旧 `emit_interim_reply` Tool：

```text
默认关闭
保留回滚
```

## Phase 6

Planner 同语义迁移。

## Phase 7

真实 Dogfooding。

重点看：

```text
有没有自然出现
会不会太频繁
会不会说得像系统
有没有提前吹牛说完成
最终回复是否仍稳定
```

---

# 79. 代码 Review 必问

> **这里是不是为了说一句中间话，多跑了一次模型？**

如果：

```text
是
```

设计错了。

---

# 80. 第二个 Review 问题

> **这句话是朝汐在“做下一件事时说的”，还是 Runtime 自己生成的状态广播？**

后者不应进入正常人格聊天。

---

# 81. 第三个 Review 问题

> **如果删掉所有 Interim，最终任务是否仍能完整成功？**

必须：

```text
能
```

否则 Interim 侵入主链过深。

---

# 82. 完成标准

补丁完成后：

```text
[ ] 主模型一次调用可同时产生 visible text + tool calls
[ ] Tool Step 的 visible text 可成为 Interim Candidate
[ ] 不新增任何模型调用
[ ] Runtime 只负责展示门控，不负责生成人格台词
[ ] 普通快速 Tool 请求可以没有 Interim
[ ] 长任务有真实进展时可自然出现 Interim
[ ] Interim 保持朝汐人格
[ ] Interim 不写入正式 Conversation
[ ] Interim 不进入 Memory / Cognition / Decision Learning
[ ] Interim delivery 失败不影响主链
[ ] Final Reply 保持原有完整流程
[ ] Final Reply 单独看仍完整
[ ] 旧 emit_interim_reply Tool 可回滚但默认退场
[ ] Agent 与 Planner 至少完成核心路径验证
```

---

# 83. 一句话收尾

> **朝汐不是做事做到一半以后，停下来按一个“中间回复按钮”。**
>
> **她应该是在决定“我接下来去做这个”的同时，自然地抬头跟暗苟说一句：**
>
> **“我先去看看这个哦～”**
>
> **然后继续做事。**
