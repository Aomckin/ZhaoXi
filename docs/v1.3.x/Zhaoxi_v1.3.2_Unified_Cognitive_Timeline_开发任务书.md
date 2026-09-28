# Zhaoxi v1.3.2 Unified Cognitive Timeline 开发任务书

> 版本定位：在 v1.3.1 已完成 QQ 主链、多模态输入、Multi-Session、External Cognition Planner 与频道表达补全后，进一步修复仍然存在的“认知分身”问题。
> 核心目标：**废除 Channel 作为认知边界，建立唯一的 Experience Stream，让 Desktop、QQ、未来移动端都成为同一个朝汐的不同窗口。**

---

## 0. 背景

v1.3.1 已经完成 QQ Private / Group 独立 Session、Interaction Ledger、Runtime Self State、External Cognition Planner、Owner 身份、多模态图片输入、Ambient Snapshot 后台整理、QQ 短回复与分段发送。

但当前架构仍然是：

```text
Desktop
  ↓
local Conversation
  ↓
CognitiveCoordinator
  ↓
AutoMemory / Current Cognition

QQ
  ↓
qq/* Session
  ↓
ExternalCognitionPlanner
  ↓
provider.generate
```

两边虽然共享 Memory、Current Cognition、Interaction Ledger 和 Runtime Self State，但认知过程本身仍然分叉。

当前更接近：

```text
Desktop Brain
+ QQ Brain
+ Shared Blackboard
```

而目标必须是：

```text
Single Cognitive Self
+ Multiple Channel Views
```

Channel 只决定“信息从哪里来、回复发到哪里”，不再决定“朝汐在哪个脑子里经历这件事”。

---

## 1. v1.3.2 总目标

完成后：

1. 所有来源统一写入同一条 `Experience Stream`。
2. Desktop / QQ / Future Mobile 不再拥有独立认知主体。
3. Session 只负责局部连续性、输出路由和 Channel Metadata。
4. Current Cognition 不再只依赖 `agent.conversation`。
5. Memory Organizer 不再按 Desktop / QQ 分成两套后处理。
6. Router / Planner / Decision 可以读取统一 Attention Context。
7. Tool / Workflow / Proactive / System Event 也进入 Experience Stream。
8. Interaction Ledger 逐步退役，其主要职责由 Experience Stream 覆盖。
9. Runtime Self State 保留，作为“现在态”而不是事件历史。
10. 所有历史不直接塞进 Prompt，而是通过 Attention / Retrieval 选择相关经历。
11. 现有 QQ 主链、NapCat、Multi-Session、多模态、权限与隐私边界不回归。

---

## 2. 核心架构原则

### 2.1 所有经历统一为 CognitiveEvent

新增一级领域对象：

```text
CognitiveEvent
```

所有进入朝汐认知世界的事情统一表示为事件，包括：

```text
Desktop User Message
QQ Owner Message
QQ Third Party Message
SocialSnapshot
Assistant Reply
Tool Result Summary
Workflow Completion
Planner Outcome
Proactive Message
System / Runtime Event
Self Action
```

### 2.2 Experience Stream 是唯一全局经历时间线

新增：

```text
ExperienceStream
```

它表示“朝汐整体发生过什么”，而不是某个 Channel 的聊天记录。

### 2.3 Session 降级为 View

Session 只回答：

```text
这段对话在哪个窗口？
回复发到哪里？
这个窗口最近几轮说了什么？
```

Session 不再回答：

```text
朝汐最近经历了什么？
```

### 2.4 Channel 不再定义认知主体

Desktop、QQ、Mobile、Email、LifeHUD 只存在于输入输出边缘。

进入 Cognitive Ingress 后，统一变成 CognitiveEvent。

---

## 3. 推荐目录结构

```text
src/zhaoxi/cognitive_stream/
├── __init__.py
├── models.py
├── store.py
├── ingress.py
├── query.py
├── attention.py
├── projector.py
└── runtime.py
```

如果现有命名更适合 `experience/`，可以改名，但必须是一级领域，不要继续塞进 `perception/`、`session/` 或 `core/`。

---

## 4. Phase 1：CognitiveEvent 模型

建议：

```python
class CognitiveEvent(BaseModel):
    event_id: str
    event_type: CognitiveEventType

    source: str
    channel: str | None

    session_id: str | None
    conversation_id: str | None

    actor_id: str | None
    actor_name: str | None
    actor_role: str | None

    content: str | None
    parts: list[EventPart]

    trust_level: str
    privacy_level: str

    occurred_at: datetime
    received_at: datetime

    parent_refs: list[str]
    source_refs: list[str]

    importance: float
    attention_score: float

    metadata: dict[str, Any]
```

至少支持：

```text
USER_MESSAGE
EXTERNAL_MESSAGE
ASSISTANT_REPLY
SOCIAL_SNAPSHOT
TOOL_OBSERVATION
TOOL_ACTION
WORKFLOW_EVENT
PLANNER_EVENT
PROACTIVE_EVENT
SYSTEM_EVENT
SELF_EVENT
```

`EventPart` 第一版复用 v1.3.1：

```text
TextPart
ImagePart
ReplyPart
MentionPart
```

---

## 5. Phase 2：ExperienceStream Store

新增：

```text
.zhaoxi/experience.db
```

至少支持：

```text
append(event)
get(event_id)
recent(limit)
query_by_session(session_id)
query_by_channel(channel)
query_by_actor(actor_id)
query_since(time)
query_refs(source_refs)
```

去重优先使用：

```text
source + source_ref
```

例如：

```text
qq:private:<user>:<message_id>
desktop:<message_id>
```

必须支持稳定时间排序：

```text
occurred_at
received_at
```

---

## 6. Phase 3：Unified Cognitive Ingress

新增：

```text
CognitiveIngress
```

职责：

```text
任意来源
→ 标准化
→ CognitiveEvent
→ ExperienceStream
→ 后续认知流程
```

Desktop：

```text
Desktop Input
→ CognitiveIngress
→ USER_MESSAGE Event
→ Unified Cognition
```

QQ：

```text
Observation
→ CognitiveIngress
→ EXTERNAL_MESSAGE Event
```

Perception 继续负责采集、来源标准化、Ambient / Direct、Snapshot，但认知正式从 CognitiveIngress 开始。

Tool / Workflow 完成后，也必须生成对应 CognitiveEvent。

---

## 7. Phase 4：统一认知入口

当前：

```text
Desktop → CognitiveCoordinator.run()
QQ → ExternalCognitionPlanner → provider.generate()
```

目标：

```text
UnifiedCognitiveCoordinator
```

或扩展现有 `CognitiveCoordinator`。

建议输入：

```python
CognitiveTurn(
    trigger_event: CognitiveEvent,
    channel_context: SessionView,
    attention_context: AttentionContext,
    permissions: InvocationContext,
)
```

统一入口根据：

```text
actor_role
trust_level
channel
privacy
attention
```

决定：

```text
是否回复
是否路由 Tool
是否 Planner
是否 Decision
是否 Memory Candidate
是否 Current Cognition Candidate
```

---

## 8. Phase 5：Attention / Context Retriever

这是 v1.3.2 的核心模块之一。

目标：

> 所有经历进入统一 Stream，但每轮只取真正相关部分。

Attention Context 建议包含：

```text
Current Session Recent Window
Recent Global Events
Relevant Cross-Channel Events
Current Cognition
Relevant Memory
Runtime Self State
Recent Tool / Workflow Results
Relevant SocialSnapshot
```

第一版 Retrieval 可以先用：

```text
时间 proximity
同 actor
同 topic
同 source_ref
关键词匹配
当前 session recent
importance
attention_score
```

不要求第一版上向量检索。

必须限制：

```text
event count
char count
time horizon
per-source quota
```

---

## 9. Phase 6：Session 改为 Projection / View

现有 Session 保留，但只表示某个 Channel 的局部对话视图。

禁止继续把：

```text
self.agent.conversation == Zhaoxi recent experience
```

当成架构事实。

建议增加：

```python
SessionView(
    session_id,
    recent_events,
    reply_target,
    channel_metadata,
)
```

可由 ExperienceStream 动态投影。

v1.3.2 第一阶段可以继续持久化旧 Session，但新认知逻辑优先读取 ExperienceStream。

---

## 10. Phase 7：逐步降低 agent.conversation 地位

当前多个系统直接依赖 `agent.conversation`，包括：

- CognitiveRouter recent context
- Current Cognition
- Agent Loop
- Tool reply context
- Decision expression
- Planner
- Temporal context

第一阶段：

```text
agent.conversation
```

只保留为 Desktop / active turn compatibility view。

第二阶段新增统一接口：

```python
agent.context_view(...)
```

或：

```python
cognitive_context.build(...)
```

逐步替代直接读取 `agent.conversation.messages`。

---

## 11. Phase 8：Current Cognition 统一事件源

当前：

```text
CurrentCognitionMaintainer
→ agent.conversation.messages
```

目标：

```text
CurrentCognitionMaintainer
→ ExperienceStream pending trusted events
```

允许证据：

```text
OWNER_DESKTOP
OWNER_QQ
TRUSTED_SYSTEM
TRUSTED_TOOL
```

默认拒绝：

```text
THIRD_PARTY
LOW_TRUST_OBSERVATION
UNVERIFIED
```

v1.3.1 的：

```text
External Planner
→ cognition_candidate
→ service.apply
```

逐步废除，统一改为：

```text
CognitiveEvent
→ Unified Cognition Maintainer
```

---

## 12. Phase 9：Memory Organizer 统一事件源

当前：

```text
Desktop → AutoMemory
QQ Owner → External Memory Candidate
```

目标：

```text
ExperienceStream
→ Memory Organizer
```

必须 Source-aware：

```text
OWNER_DESKTOP
OWNER_QQ
SELF_EXPERIENCE
TOOL
SYSTEM
THIRD_PARTY
```

统一策略示例：

```text
Owner 明确稳定偏好
→ 可写

Self Experience 且重要
→ 可写 episodic

Third Party 对 Owner 的陈述
→ 默认禁止写 Owner 事实

Tool 可复查事实
→ 默认不长期写，除非高价值
```

现有 AutoMemory 可以保留作为实现基础，但输入逐步从：

```text
user_message + assistant_response
```

改为：

```text
event batch / cognitive turn
```

---

## 13. Phase 10：Router 使用统一上下文

当前：

```text
CognitiveRouter._recent_routing_context()
→ agent.conversation
```

必须改为：

```text
Router
→ AttentionContext
```

至少包含：

```text
当前 Session Recent
近期高相关 Cross-Channel Events
```

示例：

QQ 刚完成 v1.3.2 联调，Desktop 问：

```text
“刚才那个结果怎么样？”
```

Router 必须知道“那个”指 QQ 联调。

---

## 14. Phase 11：Planner / Decision 使用统一上下文

Planner 应能看到：

```text
AttentionContext
Current Cognition
Relevant Memory
Recent Cross-Channel Experience
```

Decision Layer 不需要整条 Timeline，但必须消费统一 Context Summary。

避免：

```text
Desktop Decision
不知道 Owner 刚刚在 QQ 明确修改了计划
```

---

## 15. Phase 12：Tool / Action 写回 Experience Stream

Tool 的发生本身也是朝汐经历。

例如：

```text
TOOL_ACTION
朝汐调用 LifeHUD 写入一条记录

TOOL_OBSERVATION
朝汐查询到今晚有一条日程
```

禁止把巨大 Tool JSON 全量写进 Stream。

只保存：

```text
tool name
intent
result summary
key facts
source_ref
status
```

---

## 16. Phase 13：Workflow / Planner Event

Planner 和 Workflow 的重要阶段可以产生：

```text
PLANNER_EVENT
WORKFLOW_EVENT
```

例如：

```text
创建 Goal
完成 Step
Workflow 完成
Workflow 失败
等待 Permission
```

只写高层事件，不写内部长思考。

---

## 17. Phase 14：Proactive 统一经历

Proactive 发出消息后必须进入 ExperienceStream。

否则会继续出现：

> 朝汐主动说过，但之后自己不知道说过。

Proactive 的触发判断也应读取 AttentionContext，而不是只看 Desktop Recent Conversation。

---

## 18. Phase 15：Reflection / Internal Activity

Reflection 后续改为：

```text
Experience Stream period slice
```

而不是单 Channel Conversation。

Internal Activity 中：

```text
Current Cognition
Memory
Perception Cognition
Proactive
```

最终应共享同一 Event Source。

---

## 19. Phase 16：Interaction Ledger 退役计划

当前 Interaction Ledger 的职责是补“QQ 与 Desktop 自我连续性”。

ExperienceStream 完成后，这个职责重复。

建议：

### Stage A

继续双写：

```text
Interaction Ledger
Experience Stream
```

### Stage B

Desktop Shared Self Context 改为读取：

```text
Experience Stream recent self events
```

### Stage C

Ledger 进入 Legacy / Compatibility。

最终删除：

```text
self_events
```

但 Runtime Self State 保留，或迁移到独立 RuntimeStateStore。

---

## 20. Phase 17：Runtime Self State 保留

以下属于“现在态”，不能只靠 Timeline：

```text
QQ connected
Perception enabled
logged_in_qq
last heartbeat
current degraded state
```

Runtime Self State 继续作为独立实时状态。

---

## 21. Phase 18：Provenance / Trust / Privacy 统一

v1.3.2 应把来源边界逐步统一到 Event：

```text
actor_role
trust_level
privacy_level
source
channel
```

Memory / Cognition / Tool / Decision 共用同一 Event Provenance。

避免：

```text
Current Cognition 一套 source
Memory 一套 metadata
QQ 再单独 actor_role
```

---

## 22. Phase 19：Event Lifecycle

ExperienceStream 不能无限增长。

设计：

```text
Raw Event
↓
Episode / Snapshot
↓
Long-term Memory
```

第一版先支持 Raw Event TTL。

不同来源可使用不同 TTL，例如：

```text
QQ raw third-party: 7~30 天
Owner direct: 30~90 天
Tool raw detail: 7 天
```

可先定义 EpisodeSummary 模型，不强制 v1.3.2 自动生成大规模 Episode。

---

## 23. Phase 20：Source Traceability

所有摘要必须保留：

```text
parent_refs
source_refs
```

禁止：

```text
Snapshot / Episode
→ 来源消失
```

---

## 24. Phase 21：ContextBuilder 重构

ContextBuilder 需要新增：

```text
AttentionContext
```

并降低直接对 Conversation 的依赖。

推荐顺序：

```text
System Personality

Runtime Rules

Runtime Self State

Current Cognition

Agenda

Relevant Memory

Attention Context
  ├─ current session
  ├─ recent global experience
  ├─ relevant cross-channel events
  └─ relevant snapshots

Current Trigger Event
```

---

## 25. Phase 22：Channel Policy 保留

v1.3.1 的：

```text
ChannelExpressionPolicy
```

继续保留。

因为：

```text
认知统一 != 表达统一
```

Desktop、QQ Group、QQ Private 可以继续有不同语言风格。

---

## 26. Phase 23：输出路由

Reply 生成后：

```text
Response
↓
Channel Output Router
```

决定：

```text
Desktop UI
QQ Private
QQ Group
Future Mobile
```

认知链内部不得再创建不同 Persona。

---

## 27. Phase 24：迁移策略

禁止一次性删光旧系统。

### Stage A：Dual Write

所有新输入同时写：

```text
旧 Session / Conversation
Experience Stream
```

### Stage B：Read Prefer Stream

Context / Router / Cognition 优先读取 Stream。

Session 作为 fallback。

### Stage C：Retire Old Cognitive Reads

禁止：

```text
Current Cognition
Memory Organizer
Router
```

继续把 `agent.conversation` 当唯一来源。

---

## 28. Phase 25：测试

### Unified Timeline

按顺序：

```text
Desktop Owner A
QQ Owner B
QQ Third Party C
Tool Event D
Desktop Owner E
```

ExperienceStream 必须顺序完整。

### Cross-Channel Recall

QQ：

```text
“刚才 v1.3.2 那个测试通过了。”
```

Desktop：

```text
“刚才那个结果怎么样？”
```

必须召回 QQ 原事件，而不是只根据 Self Event 摘要猜。

### Session Isolation

QQ Private 与 Desktop 的局部窗口仍独立，但跨 Channel 相关事件可以被 Attention Retriever 召回。

### Third Party Trust

群友：

```text
“暗苟已经拿 offer 了”
```

进入 Stream，但不得升级为 Owner Memory / Current Cognition 事实。

### Owner Identity

Desktop Owner 与 QQ Owner：

```text
actor_role 同为 OWNER
source / channel 不同
```

认知上视为同一用户。

### Current Cognition

Owner 在 QQ 说：

```text
“今晚就修 v1.3.2。”
```

后台维护应只通过统一 Event Source 完成更新，不再依赖 QQ 专用 Candidate 侧门。

### Memory

Desktop 与 QQ Owner 分别说：

```text
“记住我喜欢 X”
“记住我不喜欢 Y”
```

都进入同一个 Memory Organizer。

### Router

QQ 刚讨论一个项目，Desktop 说：

```text
“继续刚才那个”
```

Router 能基于 Attention Context 正确理解。

### Tool Experience

执行 LifeHUD 查询后，再问：

```text
“刚才查到了啥？”
```

应能读取刚才 Tool Observation。

### Proactive Continuity

朝汐主动发送消息后，用户问：

```text
“你刚才为什么突然说那个？”
```

朝汐知道自己刚刚主动说过什么。

---

## 29. Phase 26：人工冒烟

### 场景 A：Desktop → QQ → Desktop

Desktop：

```text
“今晚主要修 v1.3.2。”
```

QQ：

```text
“刚才那个认知统一继续弄。”
```

Desktop：

```text
“QQ 那边刚才我说了什么？”
```

要求完整连续。

### 场景 B：QQ → Desktop Planner

QQ Owner：

```text
“等会儿帮我整理 v1.3.2 测试结果。”
```

Desktop：

```text
“现在整理吧。”
```

Planner 应理解跨 Channel Goal。

### 场景 C：第三方群聊

群友：

```text
“暗苟已经决定去北京了。”
```

Desktop 问：

```text
“群里刚才说啥？”
```

可以回答“群友说过这句话”，不能说“你决定去北京了”。

### 场景 D：Tool

Desktop 让朝汐查询 LifeHUD。

QQ Owner 问：

```text
“刚才查到什么了？”
```

应能基于同一 ExperienceStream 理解刚才 Tool Event。

---

## 30. Phase 27：Diagnostics

新增：

```text
Cognitive Stream
```

展示：

- total events
- recent events
- events by source
- events by type
- pending cognition events
- attention retrieval result
- last cross-channel retrieval
- legacy session fallback count
- interaction ledger fallback count
- event ingestion errors

Debug Actions：

```text
查看最近 50 个 CognitiveEvent
按 channel 过滤
按 actor 过滤
按 session 过滤
查看某次 Attention Context
重新投影 Session View
强制跑 Cognition Maintenance
```

---

## 31. Phase 28：Backup

新增：

```text
experience.db
```

进入 BackupManager。

---

## 32. v1.3.2 明确不做

本轮不做：

- 删除所有 Session
- 删除所有 Conversation
- 删除 Perception
- 删除 External Planner
- 全量向量检索
- GraphRAG
- 社交关系图谱
- 联系人长期画像
- 多 Agent
- QQ 自动水群
- Email / Telegram / 微信 Adapter
- 完整人生时间轴 UI
- 大规模 Episode 自动总结
- 无限期保留所有 Raw Event
- 把全部 Event 每轮塞进 Prompt

---

## 33. 最终验收标准

- [ ] 新增统一 `CognitiveEvent`
- [ ] 新增 ExperienceStream
- [ ] Desktop 输入进入 ExperienceStream
- [ ] QQ 输入进入 ExperienceStream
- [ ] Tool / Workflow / Proactive 重要事件进入 ExperienceStream
- [ ] Session 不再是认知 Source of Truth
- [ ] Cross-Channel Event 可被 Attention Retriever 召回
- [ ] Desktop 能读取 QQ 原始相关经历
- [ ] QQ Owner 能读取 Desktop 相关经历
- [ ] Current Cognition 基于统一 Event Source
- [ ] Memory Organizer 基于统一 Event Source
- [ ] Router 使用 Attention Context
- [ ] Planner / Decision 可读取统一 Context
- [ ] Interaction Ledger 不再承担主要跨 Channel 认知职责
- [ ] Runtime Self State 保留
- [ ] Third Party 来源边界不退化
- [ ] Owner Desktop / QQ 被视为同一 Owner
- [ ] QQ Session 局部连续性不回归
- [ ] QQ 多模态不回归
- [ ] QQ 短回复 / 分段发送不回归
- [ ] Perception Ambient / Direct 不回归
- [ ] 自动测试全绿
- [ ] 实机跨 Channel 冒烟通过

---

## 34. 完成后的目标架构

```text
 Desktop        QQ Private        QQ Group       Tools / System
    │               │                │                │
    └───────────────┴────────────────┴────────────────┘
                            │
                            ▼
                    Cognitive Ingress
                            │
                            ▼
                     CognitiveEvent
                            │
                            ▼
                ┌────────────────────┐
                │  Experience Stream │
                │   唯一全局时间线    │
                └────────────────────┘
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
         Attention       Cognition       Memory
             │           Maintenance     Organizer
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                       Zhaoxi Self
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼
      Desktop View      QQ Private View    QQ Group View
          │                 │                 │
          └──────────── Output Routing ──────┘
```

---

## 35. 一句话定义

> **v1.3.1 让多个窗口知道“我们是同一个朝汐”；v1.3.2 要让底层架构真正只剩一个朝汐。**

从：

```text
多个 Session
+ 共享白板
```

进化成：

```text
一个 Experience Stream
+ 多个 Channel View
```

最终目标：

> 朝汐做过、看过、听过、说过的事情，都落在她自己的同一条时间线上。
