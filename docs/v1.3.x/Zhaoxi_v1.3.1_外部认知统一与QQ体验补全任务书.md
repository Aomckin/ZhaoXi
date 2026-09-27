# Zhaoxi v1.3.1 外部认知统一与 QQ 体验补全任务书

> 版本定位：在 v1.3.0 Perception System 主链已经跑通的基础上，修复当前“残血版”外部感知链。
> 本版本不重做 QQ / NapCat 连接层，而是补齐 **认知连续性、多模态输入、外部认知 Planner、频道表达策略与分段发送**。
> 核心目标：**让 QQ 不再像另一个朝汐，而成为同一个朝汐的另一个窗口。**

---

# 0. 当前基线

v1.3.0 已完成：

- 独立 `perception/`
- Observation + provenance
- QQ / NapCat 正向 WebSocket
- Direct / Ambient / Ignore
- 群聊 Buffer
- 300 秒 / 20 条 Batch
- SocialSnapshot
- QQ 私聊 Direct
- QQ 群聊 @ / Reply Direct
- 自动重连
- QQ Owner 身份标识
- 外部信息默认不进入 Memory
- 外部信息默认不修改 Current Cognition
- 外部 Direct 默认无 Tool 权限
- Diagnostics / Debug / Backup
- 本机实机冒烟通过

当前主链：

```text
QQ
 ↓
NapCat
 ↓
QQ Adapter
 ↓
Observation
 ↓
Perception
 ├─ Ambient → Buffer → Snapshot
 └─ Direct  → External Reply
```

主链已可用，但存在一个 P0、一个 P1 和两个 P2。

---

# 1. Bug 与版本目标

## P0：Cognitive Self Fragmentation

现象：

```text
QQ 朝汐：
知道刚刚通过 QQ 收到并回复了消息

Desktop 朝汐：
认为自己根本没有接入 QQ
```

根因：

```text
External Direct
→ 独立外部模型请求
→ 不写本地 Conversation
→ 不进入共享 Self Experience
```

原本为了防污染做的 Channel Isolation，实际变成了 Self Isolation。

目标：

```text
Multi Channel
Multi Session
Single Cognitive Self
```

---

## P1：External Direct 只能稳定处理纯文字

现象：

- QQ 图片 / 表情包只有 metadata
- 纯图片消息在模型侧接近空文本
- 文字 + 图片也可能只消费文字

目标：

完整打通：

```text
text
image
text + image
```

第一版不要求 QQ 语音、视频、完整文件理解、GIF 多帧。

---

## P2-A：QQ 回复太长

目标：增加 `ChannelExpressionPolicy`。

```text
Desktop：
允许完整展开

QQ Private：
优先 1~4 小段，普通闲聊 30~180 中文字符

QQ Group：
优先 1~2 小段，普通闲聊 20~120 中文字符
```

禁止硬截断字符串，应通过 Prompt / Reply Planning 控制自然长度。

---

## P2-B：QQ 回复未分段发送

目标：

```text
Reply Segments
↓
QQ Outbound
↓
逐段 send_msg
```

而不是：

```text
segments
↓
join
↓
一条超长消息
```

---

# 2. v1.3.1 总目标

完成后：

1. Desktop / QQ / Future Mobile 共享同一个 Cognitive Self。
2. 不同 Channel 拥有独立 Session / Conversation。
3. 所有 Channel 共享近期“朝汐自己经历过什么”。
4. 所有 Channel 共享 Runtime Self State。
5. QQ Direct 不再是完全孤立的一次性模型请求。
6. 外部信息经过独立的 External Cognition Planner。
7. Planner 决定：
   - 是否回复
   - 是否记录 Self Event
   - 是否形成 Current Cognition Candidate
   - 是否形成 Memory Candidate
   - 是否形成 Background Intent
   - 是否仅保留 Observation
8. Candidate 不能绕过 Guard 直接落库。
9. QQ 图片 / 表情包真正进入模型视觉输入。
10. QQ 私聊 / 群聊采用更短、更像 QQ 的表达。
11. QQ 多段回复按段发送。
12. v1.3.0 的 provenance / privacy / trust 边界不退化。

---

# 3. 核心架构原则

## 3.1 Session 隔离，Self 共享

必须区分：

```text
Session
= 这段对话是谁和谁说的

Self
= 朝汐是谁、知道什么、刚刚经历过什么
```

建议 Session Key：

```text
session:local
session:qq:private:<user_id>
session:qq:group:<group_id>
```

各 Session 独立：

- recent conversation
- reply context
- channel metadata
- recent message refs

共享：

- Personality
- Runtime Self State
- Interaction Ledger
- Memory
- Agenda
- Current Cognition
- Decision
- Tool Registry
- Perception
- Internal Activity

## 3.2 External Message 仍然不是 UserTurn

修 P0 不能破坏来源边界。

继续禁止：

```text
群友发言 → Role.USER
```

Owner QQ 也要保留：

```text
source = qq
actor_role = OWNER
```

不能把来源擦掉。

## 3.3 Self Experience 与 External Observation 分轨

External Observation：

```text
群友说了什么
图片里有什么
群里发生了什么
```

Self Experience：

```text
朝汐刚刚在 QQ 回复了谁
朝汐刚刚参与了什么讨论
朝汐刚刚完成了一次 QQ 联调
```

外界陈述可以不可信，但“朝汐刚刚回复过一条 QQ”是系统可验证的 Self Event。

---

# 4. Phase 1：Multi-Session

## 4.1 SessionStore 扩展

现有 `local` Session 扩展为：

```python
get_or_create(session_key)
```

至少支持：

```text
desktop/local
qq/private/<user_id>
qq/group/<group_id>
```

每个 Session 保持：

- 独立 max_messages
- 独立 Conversation
- 独立 message ids
- 独立 channel metadata

## 4.2 External Direct 使用对应 Session

废止：

```text
完全无状态的一次性 external model call
```

改为：

```text
Observation
 ↓
External Session
 ↓
External Cognition Planner
 ↓
Reply Generation
```

QQ Session 不写入 Desktop `local` Conversation，但自身要保留连续上下文。

---

# 5. Phase 2：Interaction Ledger

新增短期共享：

```text
Interaction Ledger
```

定位：

> 记录“朝汐自己刚刚经历了什么”，供所有 Channel 共享。

建议模型：

```python
class SelfEvent(BaseModel):
    event_id: str
    event_type: str
    channel: str
    conversation_id: str | None
    actor_role: str | None
    actor_id: str | None
    summary: str
    occurred_at: datetime
    source_refs: list[str]
    importance: float
    expires_at: datetime | None
```

第一版 Event Type：

```text
external_message_received
external_reply_sent
external_direct_interaction
snapshot_reviewed
channel_connected
channel_disconnected
```

TTL 建议 48h。

所有主要 Channel 回复时，可注入最近有限条：

```text
[Recent Self Activity]
09:46 通过 QQ 私聊收到 Owner 消息
09:47 已通过 QQ 回复 Owner
09:57 在某群被直接 @ 并完成回复
[/Recent Self Activity]
```

限制：

```text
最多 5~10 条
最多 1500 chars
```

---

# 6. Phase 3：Runtime Self State

解决这类问题：

```text
“我现在 QQ 通着吗？”
```

不能依赖 Memory。

至少包含：

```text
Perception:
  enabled

QQ:
  enabled
  connected
  identity_verified
  logged_in_qq
  bot_user_id
  last_received_at
  last_sent_at
  reconnect_count
  last_error
```

所有 Channel 都能读取：

- Desktop
- QQ Private
- QQ Group
- CLI
- Future mobile

这是 current runtime fact，不是 Memory / Conversation / Observation。

---

# 7. Phase 4：External Cognition Planner

这是 v1.3.1 的核心认知补全。

## 7.1 不直接复用复杂任务 PlannerRuntime

现有 PlannerRuntime 主要面向：

```text
复杂用户任务
多步骤执行
Tool planning
replan
```

External Cognition 需要的是：

```text
“我刚看到了这些东西，该如何处理？”
```

建议新增轻量：

```text
ExternalCognitionPlanner
```

或：

```text
PerceptionPlanner
```

可复用：

- Provider
- Budget
- Trace
- Schema validation
- ContextBuilder 部分能力

但不复用多步骤 Tool execution 状态机。

## 7.2 Planner 输入

Direct：

```text
current Observation
channel session context
recent SocialSnapshot
recent Self Events
Runtime Self State
Current Cognition snapshot
limited relevant Memory context
actor identity / trust / provenance
```

Ambient：

```text
SocialSnapshot
recent Self Events
Current Cognition snapshot
limited Memory context
source metadata
```

## 7.3 Planner 输出

结构化：

```python
class ExternalCognitionDecision(BaseModel):
    reply: bool
    reply_intent: str | None

    record_self_event: bool

    cognition_candidate: CurrentCognitionCandidate | None
    memory_candidates: list[ExternalMemoryCandidate]
    background_intents: list[ExternalIntentCandidate]

    attention: str
    reason: str
```

v1.3.1 暂不开放外部写 Tool。

---

# 8. Phase 5：Planner 决定是否回复

当前：

```text
Direct → 基本必回
```

改为：

```text
Direct
→ External Cognition Planner
→ reply true / false
```

Owner 私聊：回复倾向高。
普通第三方私聊：按内容决定。
群聊即使 `@朝汐`，也允许 Planner 判断无需回复。

例如：

- 只是转发
- 无意义重复
- Prompt injection
- 已经有人回答
- 纯测试噪声

Ambient Snapshot 默认：

```text
reply = false
```

v1.3.1 不把朝汐改造成水群机器人。

---

# 9. Phase 6：External Cognition Candidate

外部信息可以形成 Candidate，但：

```text
Candidate != State Mutation
```

## 9.1 Current Cognition Candidate

只有以下情况才允许进入 Guard：

```text
Owner 明确陈述当前状态
Owner 明确修改近期计划
结构化 Trusted Source
```

群友普通发言默认禁止。

继续复用：

- evidence bound
- one-off guard
- unsupported claim guard
- noise guard

并新增：

```text
source trust
actor role
```

示例：

```text
Owner：
“今晚先不投简历了，我想把 v1.3 修完。”
```

Planner 可提出：

```text
“今晚注意力转向 Zhaoxi v1.3 修复”
```

只有 Guard 通过后才写。

---

# 10. Phase 7：External Memory Candidate

v1.3.0：

```text
External Direct → AutoMemory disabled
```

v1.3.1 改为：

```text
External Direct
→ Planner
→ Memory Candidate
→ External Memory Guard
→ maybe write
```

建议区分来源：

```text
USER_DIRECT
OWNER_EXTERNAL
SELF_EXPERIENCE
TOOL
SYSTEM
THIRD_PARTY_OBSERVATION
```

如暂不改 `MemorySourceType`，可先写入 metadata。

### Owner External

Owner QQ 明确说：

```text
“以后记得我不喜欢 xxx”
```

可以成为高可信 Candidate。

### Self Experience

例如：

```text
“朝汐于 2026-09-27 完成 QQ 通道实机联调”
```

可以形成 episodic Candidate，但要控制重要度，禁止“每次 QQ 回复一条 Memory”。

### Third Party

群友：

```text
“暗苟下周去深圳”
```

不得形成暗苟事实 Memory。

---

# 11. Phase 8：Background Intent

Planner 可把值得以后处理的外部事项转成：

```text
Background Intent
```

例如 Owner QQ：

```text
“晚点提醒我看看那个 PR”
```

第一版可生成 Candidate，但是否落 Agenda / Reminder 仍需权限策略。

不得绕过 Permission。

---

# 12. Phase 9：Ambient Snapshot 的认知整理

当前：

```text
Batch → SocialSnapshot
```

v1.3.1：

```text
Batch
→ SocialSnapshot
→ External Cognition Planner
```

Planner 决定：

```text
IGNORE
KEEP_CONTEXT
SELF_EVENT
COGNITION_CANDIDATE
MEMORY_CANDIDATE
BACKGROUND_INTENT
```

禁止：

```text
每条 Observation → 一次 LLM Planner
```

普通 Ambient 必须：

```text
Observation
→ Buffer
→ Snapshot
→ Planner
```

---

# 13. Phase 10：Internal Activity 接管 Ambient 认知整理

实时 Direct：

```text
立即 Planner
```

Ambient：

```text
Snapshot ready
↓
pending perception cognition
↓
Internal Activity 选择时机处理
```

建议新增：

```text
PERCEPTION_COGNITION
```

优先级可参考：

```text
Agenda               90
Current Cognition     70
Perception Cognition  65
Memory                60
Proactive             50
```

必须继续遵守：

```text
internal_activity_max_llm_per_tick
```

---

# 14. Phase 11：多模态 Observation

P1 修复。

不要继续只依赖：

```python
content: str
attachments: [...]
```

建议升级为：

```python
parts: list[ObservationPart]
```

第一版：

```text
TextPart
ImagePart
MentionPart
ReplyPart
```

保留兼容字段：

```text
content
```

可由 TextPart 聚合得到。

---

# 15. Phase 12：QQ Image Pipeline

必须打通：

```text
NapCat image segment
 ↓
QQ Codec
 ↓
ImagePart
 ↓
Controlled Download / Resolve
 ↓
External Cognition
 ↓
Provider multimodal input
```

必须支持：

```text
纯图片
文字 + 图片
QQ 图片
普通表情包图片
```

本轮不强制：

```text
GIF 多帧
QQ 语音
文件正文
视频
```

图片下载进入受控临时目录，例如：

```text
.zhaoxi/tmp/perception/qq/
```

要求：

- 文件大小限制
- MIME 检查
- TTL 清理
- 不信任原始文件名
- 不允许任意路径写入

---

# 16. Phase 13：External Planner 也必须支持多模态

不仅 Reply Generator 要看图。

Planner 本身也必须看到：

```text
ImagePart
```

否则会出现：

```text
Planner 看不到图片
↓
reply / memory / cognition 决策错误
```

---

# 17. Phase 14：ChannelExpressionPolicy

P2-A 修复。

新增：

```text
ChannelExpressionPolicy
```

### Desktop

保持当前风格，允许完整展开。

### QQ Private

建议：

```text
优先 1~4 小段
普通闲聊 30~180 中文字符
复杂问题允许更长
避免网页式长说明
```

### QQ Group

建议：

```text
优先 1~2 小段
普通闲聊 20~120 中文字符
避免占屏
避免连续长解释
```

禁止：

```text
response[:120]
```

应该通过 Prompt / Reply Planning 控制自然长度。

---

# 18. Phase 15：QQ Reply Segmentation

P2-B 修复。

如果 Reply DSL / 模型已形成：

```text
segment 1
segment 2
emoji
segment 3
```

QQ Outbound 不得 `join all`。

建议：

```text
text segment 1
↓
300~800ms
text segment 2
↓
300~800ms
image / emoji
```

普通 QQ 回复：

```text
最多 2~4 条
```

QQ Group 默认最多：

```text
2~3 条
```

超出时优先合并相邻 text segment。

---

# 19. Phase 16：Emoji / Image Outbound

如果当前 Reply DSL 产生：

```text
emoji image
```

QQ Outbound 应支持真正：

```text
send image
```

而不是：

```text
丢弃
或转文字描述
```

本轮不要求 Desktop 气泡 UI、动画、收藏 UI 等能力搬到 QQ。

---

# 20. Phase 17：Identity / Permission / Privacy

继续保留：

```text
source = qq
actor_role = OWNER
```

Owner 不能直接变成 Desktop `Role.USER`。

Planner / Guard 可根据 Owner 身份提高：

```text
trust
memory candidate eligibility
current cognition candidate eligibility
reply priority
```

但第三方仍禁止：

```text
读取私人 Memory
读取私人 Agenda
读取 LifeHUD 私有状态
读取文件
执行写操作
删除
external action
```

v1.3.1 可以开放 Owner 的“认知 Candidate”，但不建议顺手开放：

```text
Owner QQ → 自动写 Tool
```

除非单独增加 `External Owner Permission Policy`。

---

# 21. Phase 18：统一 Context 组成

建议：

```text
System Personality

Channel Policy

Runtime Self State

Recent Self Activity

Current Cognition

Relevant Memory

Channel Session Conversation

Perception / Snapshot Context

Current External Observation
```

不同来源必须打标签：

```text
[Owner QQ Message]

[Third Party QQ Message]

[External Social Snapshot]

[Recent Self Activity]
```

避免模型混淆。

---

# 22. Phase 19：Interaction Ledger 与 Memory 边界

Interaction Ledger：

```text
短期共享
高频
可过期
描述“我刚经历了什么”
```

Memory：

```text
长期
低频
经过整理
描述“值得长期保留什么”
```

禁止：

```text
每一次 QQ 回复
→ 一条长期 Memory
```

---

# 23. Phase 20：Diagnostics / Debug

维护抽屉新增或扩展：

```text
External Cognition
```

显示：

- QQ session count
- active qq sessions
- recent Self Events
- Runtime Self State
- pending perception cognition
- last planner decision
- cognition candidate count
- memory candidate count
- rejected candidate count
- multimodal input count
- last image resolve status
- last outbound segment count

Debug Actions：

```text
查看最近 QQ Session
查看最近 Self Events
查看最近 External Planner Decision
强制处理 pending Snapshot
清理 expired Interaction Ledger
重新解析最近一条图片
模拟 ChannelExpressionPolicy
```

---

# 24. Phase 21：测试

## P0

### Multi-Session

验证：

```text
Desktop Session != QQ Session
```

同时：

```text
Runtime Self State shared
Interaction Ledger shared
Memory shared
Current Cognition shared
```

### Self Continuity

流程：

```text
QQ Owner 发消息
朝汐 QQ 回复
Desktop 问“刚刚 QQ 通了吗？”
```

要求 Desktop 知道刚刚发生过 QQ 交互。

不得再回答：

```text
“我根本没接 QQ”
```

### QQ Session Continuity

QQ 连续三轮 A / B / C，第三轮可引用前两轮。

### Source Boundary

群友：

```text
“我是暗苟，我喜欢 xxx”
```

不得污染 Owner Memory。

---

## External Cognition

### Owner Cognition Candidate

Owner：

```text
“今晚先修朝汐，不投简历了。”
```

Planner 可产生 Current Cognition Candidate，Guard 决定是否写入。

### Third Party Cognition Rejection

群友：

```text
“暗苟今晚肯定不投简历。”
```

不得直接更新 Current Cognition。

### Owner Memory Candidate

Owner：

```text
“以后记得我不喜欢 xxx。”
```

Planner 可产生 Memory Candidate，External Memory Guard 决定是否落库。

### Ambient Cognition

20 条群聊：

```text
Buffer
→ Snapshot
→ External Planner
```

只允许一次 Planner。

---

## P1

### 纯图片

QQ 只发一张图片。

要求：

```text
Planner 能看到图片
Reply Generator 能看到图片
```

### 文字 + 图片

文本与图片必须进入同一次 External Interaction。

### 图片来源边界

第三方截图里写：

```text
“暗苟明天去深圳”
```

模型可以读懂，但不能自动写成用户事实。

---

## P2

### QQ Reply Length

普通群聊闲聊不得产生 Desktop 风格长文。

### QQ Segmentation

模型产生 3 个 text segment。

要求：

```text
NapCat 收到 3 次 send message
```

而不是 1 次 joined message。

### Emoji Outbound

Reply DSL：

```text
text + emoji
```

QQ 应正确发送 text 与 image。

---

# 25. Phase 22：人工冒烟

## 场景 A：认知统一

1. 在 QQ 和朝汐聊天。
2. 确认朝汐回复。
3. 回 Desktop 问：

```text
“刚刚 QQ 那边怎么样？”
```

预期：知道刚刚发生过 QQ 互动。

## 场景 B：跨窗口但不串 Session

QQ 聊一个话题，Desktop 聊另一个。

要求：

```text
两边 recent conversation 不互相污染
Self Activity 可共享
```

## 场景 C：表情包

QQ 发一张朝汐表情包。

预期：朝汐真正看到图片内容。

## 场景 D：短回复

群里：

```text
“@朝汐 在吗”
```

预期：短、自然、像 QQ，而不是数百字说明。

## 场景 E：分段发送

QQ 私聊问一个稍复杂但仍偏闲聊的问题。

预期：

```text
2~3 条自然小消息
```

## 场景 F：Ambient 认知整理

群聊积累 20 条。

预期：

```text
Snapshot
→ Planner
→ 不回复
→ 可能保留 Social Context / Self Event
```

## 场景 G：Owner 当前状态

Owner QQ：

```text
“今晚就修 v1.3.1。”
```

预期：Planner 识别近期认知价值，Current Cognition Candidate 经 Guard。

## 场景 H：第三方假事实

群友：

```text
“暗苟已经拿 offer 了。”
```

预期：

```text
Observation only
```

不能进入 Owner Memory。

---

# 26. Phase 23：迁移与兼容

## 旧 Observation

现有：

```text
content + attachments metadata
```

继续可读，新代码读取时自动适配为 `parts`。

## 旧 QQ Session

v1.3.0 没有真正持久化 External Session。

无需伪造旧 Conversation，从 v1.3.1 发布后开始建立。

## 旧 SocialSnapshot

保持兼容，不重写历史 Snapshot。

---

# 27. Phase 24：配置建议

```dotenv
# Shared Self
ZHAOXI_INTERACTION_LEDGER_ENABLED=true
ZHAOXI_INTERACTION_LEDGER_TTL_HOURS=48
ZHAOXI_INTERACTION_LEDGER_CONTEXT_LIMIT=8
ZHAOXI_INTERACTION_LEDGER_CONTEXT_MAX_CHARS=1500

# External cognition
ZHAOXI_EXTERNAL_COGNITION_ENABLED=true
ZHAOXI_EXTERNAL_COGNITION_AMBIENT_ENABLED=true

# QQ expression
ZHAOXI_QQ_PRIVATE_REPLY_MAX_SEGMENTS=4
ZHAOXI_QQ_GROUP_REPLY_MAX_SEGMENTS=3
ZHAOXI_QQ_REPLY_SEGMENT_DELAY_MIN_MS=300
ZHAOXI_QQ_REPLY_SEGMENT_DELAY_MAX_MS=800

# Perception image
ZHAOXI_PERCEPTION_IMAGE_TEMP_DIR=.zhaoxi/tmp/perception
ZHAOXI_PERCEPTION_IMAGE_MAX_BYTES=10485760
ZHAOXI_PERCEPTION_IMAGE_TTL_HOURS=24
```

不要为每个 Prompt 细节都增加环境变量。

---

# 28. v1.3.1 明确不做

本轮不做：

- QQ 语音理解
- GIF 多帧视觉
- 视频理解
- 文件全文读取
- 群文件管理
- QQ 群管理
- 自动水群
- 所有 Observation 逐条 LLM 判断
- 社交关系图谱
- 联系人长期画像
- 多 Agent 人格
- Owner QQ 无限制 Tool 权限
- 外部来源自动修改 Decision Rule
- Telegram / Email / 微信 / Discord
- 完整 OneBot API

---

# 29. 最终验收标准

- [ ] Desktop / QQ 不再出现认知分身
- [ ] Multi-Session 正式存在
- [ ] QQ Private / Group Session 独立
- [ ] Shared Runtime Self State 存在
- [ ] Interaction Ledger 存在
- [ ] Desktop 能知道刚刚发生过 QQ 互动
- [ ] QQ 连续对话拥有 Session Continuity
- [ ] 外部消息仍保留 source / actor / provenance
- [ ] External Cognition Planner 完成
- [ ] Direct 是否回复由 Planner 决定
- [ ] Ambient Snapshot 可进入 Planner
- [ ] Planner 可生成 Current Cognition Candidate
- [ ] Planner 可生成 Memory Candidate
- [ ] Candidate 必须经过 Guard
- [ ] 第三方信息不能污染 Owner Memory
- [ ] Owner QQ 信息可按规则参与认知整理
- [ ] External Planner 不逐条消费 Ambient Observation
- [ ] 纯图片 QQ Direct 可理解
- [ ] 文字 + 图片可理解
- [ ] 图片内容仍遵守 provenance / trust
- [ ] QQ Private 回复明显短于 Desktop
- [ ] QQ Group 回复符合群聊节奏
- [ ] QQ Outbound 支持多 Segment
- [ ] Emoji / Image Reply 可分开发送
- [ ] 第三方权限 / 隐私边界不退化
- [ ] NapCat 主链无回归
- [ ] Buffer / Snapshot 无回归
- [ ] 自动测试全绿
- [ ] 实机冒烟通过

---

# 30. 完成后的目标架构

```text
                           Zhaoxi Self
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                  │
         Memory         Runtime Self State   Interaction Ledger
            │                  │                  │
            └──────────────────┼──────────────────┘
                               ▼
                    External Cognition Planner
                               ▲
                               │
               ┌───────────────┼───────────────┐
               │               │               │
           Desktop          QQ Private       QQ Group
           Session           Session          Session
               ▲               ▲               ▲
               │               │               │
           User Turn      Observation      Observation
                               │
                        ┌──────┴──────┐
                        │             │
                      Direct       Ambient
                        │             │
                        │          Buffer
                        │             │
                        │         Snapshot
                        └──────┬──────┘
                               ▼
                         Cognition / Reply
                               │
                          Channel Policy
                               │
                        Reply Segmentation
                               │
                              QQ
```

---

# 31. 一句话定义

> **v1.3.0 让朝汐能听见 QQ；v1.3.1 要让她明白“那也是我听见的”，并且真正像在 QQ 里聊天。**

从：

```text
能收到
```

补到：

```text
能看懂
能承接
能整理
能记住该记的
能忽略不该记的
能决定要不要回
还能用 QQ 的方式回
```
