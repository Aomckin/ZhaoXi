# Zhaoxi v1.3.2 最终收口任务书
## Unified Cognitive Timeline Finalization

> 版本定位：v1.3.2 最终收口补丁。
> 本轮不再新增新的外部信息源、不再扩张功能面，只修复统一时间线在真实使用中暴露出来的 **近期上下文组织、回复错位、当前 Turn 锚定、因果配对与请求隔离** 问题。
> 目标：**让 Experience Stream 真正成为朝汐近期认知上下文的唯一事实来源，并结束 v1.3.2。**

---

# 0. 当前基线

当前 v1.3.2 已完成：

- `cognitive_stream` 一级领域
- `CognitiveEvent`
- `ExperienceStream`
- `CognitiveIngress`
- `AttentionRetriever`
- `SessionProjector`
- `.zhaoxi/experience.db`
- Desktop / CLI / Web 输入输出写入 Stream
- QQ Direct / Ambient / Snapshot 写入 Stream
- Tool Action / Observation 写入 Stream
- Planner / Workflow 高层结果写入 Stream
- Proactive 事件写入 Stream
- Current Cognition 开始读取统一事件源
- Memory 开始读取统一事件源
- Router / Planner / Decision / QQ 上下文可读取 Attention Context
- Interaction Ledger 进入兼容阶段
- Runtime Self State 保持独立

当前已经证明：

```text
QQ 发生过的事情
→ 可以进入统一 Stream
→ Desktop 能在当前上下文直接拿到
→ 不必依赖长期 Memory Retrieval
```

因此 v1.3.2 当前的主要问题已经不再是“认知分身”。

剩余问题集中在：

```text
统一之后，近期上下文该怎么组织才不会乱。
```

---

# 1. 当前剩余问题

## P0-A：Current Turn 锚点不牢

统一时间线已经包含多个来源的最近事件后，模型偶发出现：

- 回答错对象
- 把旧问题当当前问题
- 把别的 Channel 的问句当本轮触发
- 明明在 Desktop，却回答得像当前是在 QQ
- 明明当前问的是“主界面刚才说了什么”，却回到 QQ 群事件

本质问题：

```text
Recent Timeline
与
Current Trigger Event
没有完全分离
```

目标：

```text
CurrentTrigger
```

必须成为当前这一轮唯一、不可歧义的锚点。

---

## P0-B：多来源事件只有时间顺序，没有足够强的问答因果关系

如果 Desktop / QQ / 群聊在短时间内同时发生：

```text
A: QQ Owner 问句
B: Desktop Owner 问句
A': QQ 朝汐回复
B': Desktop 朝汐回复
```

纯时间排序可能成为：

```text
A
B
A'
B'
```

模型可能误把：

```text
B ↔ A'
```

当成一组。

目标：

```text
turn_id
reply_to_event_id
caused_by_event_id
```

必须进入 CognitiveEvent，并在渲染上下文时按“交互单元”组织。

---

## P0-C：共享 Agent 下存在潜在请求级状态串线风险

如果以下信息存在于共享 Agent 可变字段：

```text
current_channel
current_session
current_trigger
current_images
reply_target
privacy_context
current_actor
```

并发请求可能相互覆盖。

目标：

所有单轮请求状态必须封装为：

```text
request-scoped immutable context
```

禁止把本轮状态挂在共享 Agent 实例上。

---

## P1-A：Recent Timeline 仍偏“检索资料包”，而不是自然的近期经历流

当前 Attention 更像：

```text
当前 Session
+
跨频道召回事件
```

目标应当是：

```text
Recent Timeline Context
+
Relevant Recall
```

第一层常驻最近经历，第二层只补更早相关内容。

---

## P1-B：Timeline 事件密度不统一

Raw QQ 群消息、SocialSnapshot、Tool Event、Owner 对话、Assistant Reply 可能同时进入上下文。

容易出现：

- 群聊占掉大量上下文预算
- 同一件事出现 Raw + Snapshot 双重重复
- Tool / Planner 内部事件过多
- 近期真正重要的 Owner 交互被稀释

目标：

```text
L0 Raw Event
完整原始事件，仅存储 / 回溯

L1 Timeline Unit
适合进入近期上下文

L2 Episode / Summary
较旧经历的压缩表示
```

---

## P1-C：抽象后缺乏稳定回溯路径

任何：

```text
Timeline Unit
Snapshot
Episode
```

都必须保留：

```text
parent_refs
source_refs
raw_event_ids
```

原则：

> 抽象可以压缩，但必须能往回摸。

---

## P1-D：来源标签不应直接泄漏进自然回复

曾出现：

```text
[来源: web]
```

直接进入朝汐最终输出。

来源标签应该：

```text
给模型看
不给用户默认看
```

只有当回答本身需要说明来源时才自然表达。

---

# 2. 最终目标架构

```text
World / Channels
      │
      ▼
Cognitive Ingress
      │
      ▼
Experience Stream
      │
      ├── L0 Raw Event
      │
      ├── L1 Timeline Unit
      │
      └── L2 Episode / Summary
      │
      ▼
Timeline Organizer
      │
      ├── Recent Timeline Context
      └── Relevant Recall
      │
      ▼
Current Trigger Event  ← 独立锚定
      │
      ▼
Unified Cognitive Turn
      │
      ▼
Reply / Tool / Planner / Decision
      │
      ▼
Experience Stream
```

---

# 3. Phase 1：Current Trigger Pinning

新增明确的：

```python
class CurrentTriggerContext(BaseModel):
    request_id: str
    turn_id: str
    trigger_event_id: str
    channel: str
    session_id: str | None
    actor_id: str | None
    actor_role: str | None
    privacy_level: str
    reply_target: dict | None
    occurred_at: datetime
```

最终 Prompt 结构建议：

```text
[Recent Timeline]
...
[/Recent Timeline]

[Relevant Earlier Context]
...
[/Relevant Earlier Context]

[Current Turn]
event_id=...
channel=...
actor=...
content=...
[/Current Turn]
```

硬规则：

```text
只回应 Current Turn
```

Recent Timeline 只能用于理解、承接与补充背景。

Current Trigger 不得被 summary、truncate、retrieval replacement 或 timeline compression。

---

# 4. Phase 2：Turn / Reply Causality

扩展 `CognitiveEvent`，新增：

```text
turn_id
reply_to_event_id
caused_by_event_id
```

规则：

- 新输入创建 `turn_id`
- Assistant Reply 使用同一 `turn_id`
- Assistant Reply 的 `reply_to_event_id` 指向当前 Trigger
- Tool Action / Observation 的 `caused_by_event_id` 指向当前 Turn 或对应 Tool Trigger
- Proactive Event 记录自己的生成原因

---

# 5. Phase 3：Timeline Organizer 按交互单元整理

不要再简单：

```text
ORDER BY occurred_at
→ 拼文本
```

而是：

```text
Event
→ group by turn / causal relation
→ render interaction block
```

例如：

```text
11:55 [QQ私聊·Owner]
暗苟：还记得主界面刚才说了啥吗？
朝汐回复：……

11:57 [主界面·Owner]
暗苟：那刚才 QQ 群里说了啥？
朝汐回复：……
```

而不是把 4 个 Event 平铺。

---

# 6. Phase 4：Request-scoped CognitiveTurnContext

新增：

```text
CognitiveTurnContext
```

封装：

```text
request_id
turn_id
trigger_event
channel
session
actor
privacy
reply_target
images
expression_policy
permission_origin
attention_context
```

检查并移除任何类似：

```text
agent.current_channel
agent.current_session
agent.current_trigger
agent.current_images
agent.reply_target
```

的共享 mutable turn state。

Router、Planner、Decision、Tool Executor、Reply Generator、Output Router 必须通过显式参数或 ContextVar 获取当前 Turn。

---

# 7. Phase 5：Recent Timeline Context

Recent Timeline 是朝汐每轮默认知道的近期经历，不是“问到了才跨频道搜”。

建议第一版：

```text
最近 30~90 分钟
或最近 N 个 L1 Timeline Unit
```

按 token budget 动态裁剪。

优先包含：

```text
Owner 直接交互
朝汐回复
重要 Tool / Workflow 结果
直接指向朝汐的 External Message
高价值 SocialSnapshot
近期 Proactive / Runtime 关键事件
```

普通 Ambient Raw 群聊默认只以 L1 压缩形式进入。

---

# 8. Phase 6：Relevant Recall

只补充：

```text
超出 Recent Timeline 范围
但与 Current Trigger 高度相关
```

的事件。

优先级建议：

```text
明确引用 / reply ref
同 topic
同 actor
同对象
关键词
时间 proximity
```

Relevant Recall 永远只是背景，不能覆盖 Current Trigger。

---

# 9. Phase 7：L0 / L1 / L2 信息密度

## L0 Raw Event

完整保存：

```text
原始文本
图片引用
消息 id
来源
时间
actor
provenance
```

默认不全部进入 Prompt。

## L1 Timeline Unit

近期 Context 使用。

例如：

```text
11:00~11:08 [QQ群·xxx]
群里在讨论今晚聚餐；A 问暗苟是否参加，B 猜测暗苟可能有事。
关于暗苟的描述来自群友，未经 Owner 确认。
```

## L2 Episode / Summary

较旧经历压缩。

v1.3.2 只需建立接口和最小实现，不要求大规模 Episode 系统。

---

# 10. Phase 8：Source Traceability

所有 L1 / L2 必须保存：

```text
source_event_ids
parent_refs
raw_refs
```

建议提供：

```python
resolve_timeline_unit(unit_id)
```

用于回查 Raw Event。

如果 Timeline 只有图片视觉摘要，但用户继续追问具体视觉细节：

```text
→ 回查 raw image event
→ 原图仍存在则重新送视觉模型
```

如果原图已 TTL 过期：

```text
明确只能根据之前的视觉摘要回答
```

不能编造具体细节。

---

# 11. Phase 9：来源标签只服务认知

内部：

```text
[source=desktop]
[source=qq_group]
[source=qq_private]
[source=tool]
```

继续保留。

最终回复默认不得出现：

```text
[来源: web]
[Owner QQ Message]
[External Social Snapshot]
[Recent Self Activity]
```

需要说明来源时，自然表达：

```text
“这个是刚才 QQ 群里看到的。”
“你刚才在主界面说过……”
“刚刚查 LifeHUD 时看到……”
```

---

# 12. Phase 10：External Planner 职责收缩

External Planner 只负责：

```text
是否立即回应
attention priority
是否需要 action
是否需要高优先 Timeline Unit
```

不再负责建立另一套外部认知上下文。

原则：

```text
不回复 != 不进入认知
```

普通群聊即使 `reply=false`，仍然可以进入 Timeline。

---

# 13. Phase 11：Current Cognition 收口

确认 Current Cognition：

```text
只读取统一 Stream / Timeline
```

不再：

```text
直接读取 Desktop Conversation
直接走 QQ Candidate 侧门
```

Owner Desktop / Owner QQ：

```text
同一 actor_role=OWNER
channel 不同
```

均可作为可信证据。

Third Party 不能升级为 Owner 事实。

---

# 14. Phase 12：Memory Organizer 收口

确认长期 Memory：

```text
统一读取 CognitiveEvent / Timeline
```

不再分成：

```text
Desktop AutoMemory
QQ External Memory Candidate
```

Timeline 负责：

```text
最近发生过什么
```

Memory 负责：

```text
什么值得长期留下
```

禁止因为 Timeline 完整就大量写长期 Memory。

---

# 15. Phase 13：Router / Planner / Decision 收口

确认：

```text
Router
Planner
Decision
```

不再直接把：

```text
agent.conversation
```

当近期世界。

统一使用：

```text
Current Trigger
Recent Timeline
Relevant Recall
Current Cognition
Memory
```

---

# 16. Phase 14：Interaction Ledger 退出认知 Prompt

如果 ExperienceStream 已稳定提供：

```text
最近 Self Events
QQ / Desktop 原始互动
```

则 Interaction Ledger 不应再向正常 Prompt 注入：

```text
“你刚刚在 QQ 做过……”
```

这种摘要。

保留用途仅限：

```text
migration
debug
fallback
```

---

# 17. Phase 15：Context 最终结构

推荐：

```text
System Personality

Runtime Rules

Runtime Self State

Current Cognition

Agenda

Relevant Long-term Memory

[Recent Timeline]
按时间 / 交互单元组织的近期经历
[/Recent Timeline]

[Relevant Earlier Context]
按需召回的更早经历
[/Relevant Earlier Context]

[Current Turn]
唯一当前触发事件
[/Current Turn]
```

---

# 18. Phase 16：Prompt 收口

禁止继续用大量补丁式 Prompt：

```text
“QQ 和 Desktop 是同一个朝汐”
“不要说另一个我”
“这也是你经历的”
```

如果架构和 Context 正确，模型自然应理解为同一条时间线。

仅保留必要的来源、隐私与权限规则。

---

# 19. Phase 17：测试矩阵

## Current Turn Pinning

Recent Timeline 中有多个旧问句时，当前再输入 1 个新问题。

必须只回复最新 Current Trigger。

## Cross-channel Interleave

事件：

```text
QQ A
Desktop B
QQ Reply A'
Desktop Reply B'
```

Timeline Renderer 必须输出：

```text
QQ Turn: A → A'
Desktop Turn: B → B'
```

不能错配。

## Concurrent Requests

让 QQ 与 Desktop 同时发请求。

确认：

```text
response target
actor
privacy
images
channel policy
```

完全隔离。

## 主界面回忆

QQ 问：

```text
“刚才主界面说了啥？”
```

应直接从 Recent Timeline 回答。

## QQ 回忆

Desktop 问：

```text
“刚才 QQ 那边说了啥？”
```

应直接从 Recent Timeline 回答。

## 群聊事件

群里 99+ 消息。

Recent Timeline 只注入 Timeline Unit / Snapshot，不塞 99 条 Raw。

## 第三方错误事实

群友：

```text
“暗苟已经拿 offer 了。”
```

Timeline 可以记录“群友说……”，但 Current Cognition / Memory 不得升级为 Owner 事实。

## 图片摘要回溯

QQ 发图。

Desktop 先问大概，再追问具体视觉细节。

如果 Raw Image 可用则回查原图；否则明确只能依据旧摘要。

## Source Label Leak

最终回复不得出现：

```text
[来源: web]
[External Observation]
[Recent Timeline]
```

## Tool Cross-channel

Desktop 查 LifeHUD，QQ Owner 问：

```text
“刚才查到啥？”
```

应根据统一 Timeline 回答。

## Proactive Continuity

朝汐主动发过一句后，用户换 Channel 问原因，朝汐必须知道自己说过什么。

---

# 20. Phase 18：实机黑盒验收

必须完成：

### A. Desktop → QQ → Desktop

连续三轮跨 Channel。

不能再出现：

```text
分身
毛玻璃
另一个我
机器替我说
事后看到记录才知道
```

### B. QQ → Desktop → QQ

第二次返回 QQ 时，应能承接 Desktop 中间发生的事。

### C. 群聊 Ambient

先让群聊产生 Snapshot，再在 Desktop 问：

```text
“刚才群里大概在聊什么？”
```

要求来源正确，不把群友陈述当 Owner 事实。

### D. Reply Alignment

QQ 和 Desktop 尽量同时提不同问题。

确认两边回复完全对应各自问题。

### E. Image

QQ 发图。

Desktop 先问大概，再问具体细节。

验证 L1 摘要与 L0 Raw 回溯。

---

# 21. Phase 19：Diagnostics

新增 / 补全：

```text
Current Trigger
turn_id
reply_to_event_id
caused_by_event_id
Recent Timeline rendered
Relevant Recall rendered
Current Turn rendered
Request Context
Concurrent active turns
Timeline Unit → Raw Event refs
```

Debug Actions：

```text
查看 Current Trigger
查看当前 Recent Timeline
查看 Relevant Recall
按 turn_id 查看事件
按 reply_to 查看问答链
回溯 Timeline Unit 原始事件
模拟并发 Desktop + QQ
```

---

# 22. Phase 20：迁移与兼容

不要求立即删除：

```text
old Conversation
QQ Session
Interaction Ledger
```

但它们不得再作为主认知 Source of Truth。

Session 可以保留用于：

```text
local UI history
reply routing
compatibility
```

禁止 Current Cognition / Memory / Router / Planner / Decision 绕开 Timeline 使用旧 Conversation 作为近期上下文。

---

# 23. 明确不做

本轮不做：

- 新外部 Adapter
- Email / Telegram / 微信
- Timeline UI 大改
- GraphRAG
- 全量向量检索
- 社交关系图谱
- 自动水群
- Episode 大规模自动总结
- 联系人画像
- 多 Agent
- 新 Tool 大功能
- 无限 Raw Event 保存
- 为了“像人”加入无依据心理模拟

---

# 24. 最终验收标准

- [ ] Current Trigger 独立锚定
- [ ] Timeline 不再承担“当前待回复消息”角色
- [ ] CognitiveEvent 有 turn / reply / cause 关系
- [ ] Timeline Renderer 按交互单元组织
- [ ] QQ / Desktop 并发无请求串线
- [ ] Request-scoped CognitiveTurnContext 完成
- [ ] Recent Timeline 成为默认近期经历上下文
- [ ] Relevant Recall 只补更早相关内容
- [ ] Raw / Timeline / Episode 三层边界明确
- [ ] Timeline Unit 可回溯 Raw Event
- [ ] 图片摘要可回查原图
- [ ] 内部来源标签不泄漏进自然回复
- [ ] External Planner 职责收缩
- [ ] Current Cognition 只读统一事件源
- [ ] Memory Organizer 只读统一事件源
- [ ] Router / Planner / Decision 不再直接依赖旧 Conversation
- [ ] Interaction Ledger 退出正常认知 Prompt
- [ ] Third Party 事实边界不退化
- [ ] QQ 多模态不回归
- [ ] QQ 短回复 / 分段发送不回归
- [ ] Ambient Snapshot 不回归
- [ ] Tool / Workflow / Proactive 连续性不回归
- [ ] 自动测试全绿
- [ ] Desktop ↔ QQ 双向实机黑盒通过
- [ ] 并发 Reply Alignment 实机通过

---

# 25. v1.3.2 完成定义

只有当以下现象同时消失：

```text
“另一个我”
“隔着毛玻璃”
“机器替我说话”
“我是看记录才知道”
“刚才那个问题我对不上”
“回复答到另一边去了”
```

并且跨 Channel 实机交互可以自然表现为：

```text
我刚才在 QQ 看到了……
你刚才在主界面说……
群里刚刚有人提到……
刚刚查 LifeHUD 时看到……
```

才算 v1.3.2 正式完成。

---

# 26. 一句话定义

> **v1.3.2 最终要完成的不是“跨频道同步”，而是把所有经历整理成一条有时间、有来源、有因果、有当前焦点、还能回溯细节的近期认知时间线。**

最终：

```text
World Events
    ↓
Experience Stream
    ↓
Timeline Organizer
    ↓
Recent Timeline + Relevant Recall
    ↓
Current Turn
    ↓
Zhaoxi
```

这条链稳定后，v1.3.2 正式收口。
