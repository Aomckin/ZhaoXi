# Zhaoxi v1.4.3 轻量补丁任务书
## External Provenance Integrity · 外部信息来源完整性修复

> 项目：**Zhaoxi / 朝汐**
> 当前版本：**v1.4.3**
> 类型：**轻量 Runtime / Context Integrity 补丁**
> 目标：修复 v1.3 外部信息接入在 v1.4 ExperienceStream / Cognitive Timeline 统一后出现的“来源丢失 / 来源归属错误”问题。
>
> 核心原则：
>
> > **身份 ≠ 来源 ≠ 会话。**
>
> 谁说的、从哪里来的、在哪个会话发生，必须分别保存，不能再被一个 `Role.USER` 压扁。

---

## 1. 当前真实问题

当前外部 Owner 消息进入 ExperienceStream 后，仍然会保留：

```text
actor_role = OWNER
channel = qq
session_id = qq/...
conversation_id = ...
conversation_kind = private / group
```

这些原始字段本身并没有丢。

真正的问题发生在 Cognitive Timeline 投影阶段。

当前逻辑近似：

```python
if event.event_type in {USER_MESSAGE, EXTERNAL_MESSAGE} and event.actor_role == "OWNER":
    role = USER
```

于是：

```text
Desktop 中暗苟说的话
→ USER

QQ 私聊中暗苟说的话
→ USER

QQ群中暗苟说的话
→ USER
```

而只有：

```text
Role.EXTERNAL
Role.EXPERIENCE
```

才会被显式渲染成：

```text
[时间 · 来源 · actor · 外部资料]
```

因此 Owner 的外部消息一旦被投影成 `Role.USER`，其来源标签就从模型可见文本里消失。

最终变成：

```text
原始事实：
“这句话确实是暗苟说的，而且是在 QQ 群里说的”

进入桌面上下文后：
USER: 这句话

模型理解：
“暗苟在当前窗口里说过这句话”
```

于是出现：

```text
事实内容正确
speaker 正确
source 错误
```

这种 bug 比普通幻觉更隐蔽。

---

## 2. 当前已有的错误补偿逻辑

现有 ContextBuilder 只有在 Query 命中：

```text
QQ
桌面
窗口
哪边
哪个渠道
哪里说
哪里发
```

这类词时，才临时给历史消息补：

```text
[来源: qq]
```

这只能算按需补丁，不能作为正确 provenance 设计。

来源信息应该：

```text
始终存在于数据
+
跨上下文投影时始终显式
```

而不是：

```text
用户问起来源时才想起来来源重要
```

---

## 3. 本补丁核心目标

建立统一的：

# Provenance Contract

每条进入 Cognition / Context 的消息必须能区分：

```text
speaker identity
origin channel
origin session / conversation
```

例如：

```text
actor_role = OWNER
channel = qq
conversation_kind = group
conversation_id = 123456
```

不能只剩：

```text
Role.USER
```

---

## 4. 三个维度必须分离

### 4.1 Speaker Identity

回答：

```text
谁说的？
```

候选：

```text
OWNER
SELF
EXTERNAL
SYSTEM
```

### 4.2 Origin

回答：

```text
从哪里来的？
```

例如：

```text
desktop
qq
wechat
future_plugin_x
```

### 4.3 Conversation Scope

回答：

```text
在哪个具体会话？
```

例如：

```text
desktop/local
qq/private/123
qq/group/456
```

---

## 5. Role 继续负责“谁说的”

不要为了来源问题，把 QQ 里的 Owner 改成 `Role.EXTERNAL`。

推荐继续：

```text
OWNER speech → Role.USER
SELF speech  → Role.ASSISTANT
third party  → Role.EXTERNAL
```

来源归属通过独立 provenance envelope 表达。

---

## 6. 新增统一 Provenance Metadata

所有 Cognitive Message / Projected Message 至少携带：

```python
origin_channel
origin_session_id
origin_conversation_id
origin_conversation_kind
origin_actor_role
origin_actor_id
origin_actor_name
origin_source_plugin
```

已有字段能复用的尽量复用，不重复造数据。

重点是：

> Context Renderer 必须统一读取这些字段。

---

## 7. 新增 is_cross_context()

建议增加统一判断：

```python
def is_cross_context(event, current_context) -> bool:
    ...
```

判定至少考虑：

```text
channel 不同
OR
session_id 不同
OR
conversation_id 不同
OR
conversation_kind 不同
OR
source_plugin 不同（两边均已知时）
```

不能只比较 channel。

必须提供三态 `context_relation = same / cross / unknown`：仅比较两边都已知的字段；任一可比较字段不同即 cross。没有已知差异，但某字段只在一边存在，或完全无法比较，结果为 unknown。空字符串视为未知。unknown 不触发 is_cross_context，也不因未知而给普通 Owner 历史刷跨上下文标签；Inspector 保留 unknown。当前外部 Trigger、第三方资料和历史图片仍按各自规则标识。

因为：

```text
QQ群 A
QQ群 B
QQ 私聊
```

都可能是 `channel=qq`。

---

## 8. 跨上下文时必须显式来源

如果：

```text
is_cross_context == true
```

则 Context Renderer 必须输出 provenance envelope。

例如：

```text
[来源: QQ群 / 群聊 123456 / 暗苟本人 / 2026-09-30 20:14]
xxxx
```

朝汐自己的历史回复：

```text
[来源: QQ群 / 朝汐发言 / 2026-09-30 20:15]
xxxx
```

第三方：

```text
[来源: QQ群 / 用户A / 第三方发言 / 2026-09-30 20:16]
xxxx
```

---

## 9. 同上下文避免无意义噪声

如果当前就在：

```text
qq/group/123456
```

历史消息也来自：

```text
qq/group/123456
```

则不需要每条都重复来源标签。

来源 envelope 主要服务：

```text
跨窗口
跨渠道
跨群
跨私聊
跨 session
```

---

## 10. 当前 Trigger 也必须有 provenance

当前正在处理的外部消息不能只靠：

```python
planner_view.add_user(item.content)
```

把它变成一个普通裸 User Message。

建议统一：

```text
ExternalInputRenderer
```

或：

```text
project_current_external_trigger(...)
```

把 speaker、channel、conversation_kind、conversation_id、actor、source_plugin 一并交给 Planner / Router / Agent Context。

---

## 11. Planner View 修复

当前类似：

```python
planner_view.add_user(item.content or "请查看图片。")
```

会让 Planner 看到：

```text
USER: xxx
```

但不知道这是 QQ 群里的 Owner 消息，还是 Desktop 当前输入。

改为统一 provenance-aware render。

至少保证 Planner Prompt 中明确：

```text
当前输入来源
speaker
conversation scope
是否为跨上下文信息
```

---

## 12. Cognitive Timeline 修复

`project_event()` 继续负责：

```text
事件 → Message Role
```

但不要在这里把来源语义丢掉。

建议：

```text
project_event()
→ metadata 保留 event_id 和降级 provenance_snapshot；旧字段仅兼容已有读者
```

然后：

```text
render_for_context()
→ 优先按 event_id 回查 ExperienceStream，查不到才回落快照
→ 根据 current_context 决定是否显式加来源 envelope
```

分离：

```text
数据投影
vs
文本渲染
```

---

## 13. 禁止 Query 关键词驱动 provenance

删除 / 降级类似：

```text
if query contains "QQ / 哪里说 / 哪边"
→ 才加来源
```

的主逻辑。

来源显示应由 cross_context 决定，而不是由用户有没有问来源决定。

用户问来源时可以更详细展示 provenance，但不能是“来源第一次出现”的时机。

---

## 14. 图片 provenance

历史图片进入 Cognition 时必须和文本一样有来源。

不能：

```text
一张 QQ 群历史图片
→ 被桌面 Context 当成当前窗口图片
```

Message metadata 至少保留：

```text
origin_channel
origin_session
origin_event_id
occurred_at
actor
```

如果图片来自旧 context，需要在 accompanying text 中标明来源，例如：

```text
[历史图片 · 来源 QQ群 xxx · 用户A · 2026-09-30]
```

---

## 15. 当前图片与历史图片严格区分

当前 Turn 图片：

```text
timeline_scope = current_trigger
```

历史 Recall 图片：

```text
timeline_scope = recent / attention
```

必须在 Debug 和 Prompt 投影中保留区分。图片 Prompt 正文必须含结构化 `[ImageProvenance {"timeline_scope":"recent|attention|current_trigger", ...}]` 前缀，不能只留在 metadata 或 Debug。相邻文字追问复用旧图时，文字仍是 current_trigger，图片使用 image_timeline_scope=recent 和原图片 event_id / 时间。

禁止：

```text
历史图
→ 当成“用户刚刚发的这张图”
```

---

## 16. Current Cognition 影响

Current Cognition 可以吸收 Owner 在外部渠道明确说出的近期状态，因为 speaker 确实是 Owner。

但不能写成：

```text
“暗苟刚刚在桌面说……”
```

除非来源确实是 desktop。

来源规则必须由 Runtime 固定执行：OWNER + cross_context → 保留来源；OWNER + same_context → 可省文字标签；unknown → 不猜测来源。不能让模型临场判断“有意义”。例如：

```text
“暗苟在 QQ 群里提到……”
```

同上下文可以只保留事实，但 evidence source 必须持久化，包括 overview、thread、change、watch。Current Cognition 的模型投影根据证据和当前上下文确定来源标签；Desk 展示继续呈现自然摘要。

---

## 17. AutoMemory 影响

第三方消息：

```text
actor_role != OWNER
```

继续不得直接作为 Owner fact。

Owner 外部消息可以进入 AutoMemory，但 Evidence 必须保留：

```text
source_event_id
origin_channel
origin_session
```

以后 Debug 能回答：

```text
“这条 Memory 是暗苟在哪说的？”
```

---

## 18. ExperienceStream 作为来源真相层

渲染必须先用 event_id / origin_event_id 回查 ExperienceStream；有效事件的来源和身份优先于投影快照。只有事件不可查询时，才使用 provenance_snapshot 降级；Inspector 显示 experience_stream / snapshot / legacy。禁止建立第二份来源真相层。来源快照修正的回归测试须同时覆盖真相优先与事件消失后的降级。

ExperienceStream 已经保存：

```text
source
channel
session_id
actor_role
actor_id
conversation_id
metadata.conversation_kind
```

因此本补丁不要重新造一套来源数据库。

原则：

> **ExperienceStream 是 provenance source of truth。**

其他层只做：

```text
投影
渲染
筛选
```

---

## 19. Source Plugin 也保留

v1.3.3 已经把 QQ / future external source 做成插件化。

因此 provenance 必须包含：

```text
source_plugin
```

避免未来微信、Telegram 或其他 adapter 接进来以后再次重演同样问题。

---

## 20. 推荐统一对象

可以新增轻量：

```python
Provenance:
    channel: str
    session_id: str | None
    conversation_id: str | None
    conversation_kind: str | None
    actor_role: str | None
    actor_id: str | None
    actor_name: str | None
    source_plugin: str | None
    occurred_at: datetime | None
```

不一定必须 Pydantic 新模型。

重点是统一 helper：

```text
from_event()
from_observation()
render_label()
is_cross_context()
```

---

## 21. Context Renderer 建议

新增：

```python
render_message_with_provenance(
    message,
    current_channel,
    current_session_id,
    current_conversation_id,
)
```

规则：

```text
same-context
→ 不加标签

cross-context Owner
→ [来源: ...]

cross-context SELF
→ [来源: ...]

EXTERNAL
→ 永远保留 actor + source

EXPERIENCE
→ 保留行动记录来源
```

---

## 22. Social Snapshot

Social Snapshot 必须继续明确：

```text
群聊摘要
外部资料
不是 Owner 直接发言
```

不能因为摘要里出现“我……”就被投影成 Owner 第一人称事实。

---

## 23. Interaction Ledger

Interaction Ledger 本来已经有：

```text
source
conversation_id
actor_role
actor_id
source_refs
```

不需要改核心结构。

但 Debug 可以复用它辅助显示最近在哪个外部渠道收到 / 回复了什么。

---

## 24. Debug / Observatory

新增：

```text
Provenance Inspector
```

每条 timeline item 可显示：

```text
event_id
role
actor_role
channel
session_id
conversation_id
conversation_kind
source_plugin
timeline_scope
cross_context
rendered_source_label
```

---

## 25. 必测回归案例

### Case A · Desktop 普通历史

当前：

```text
desktop/local
```

历史也来自：

```text
desktop/local
```

要求：

```text
正常 USER / ASSISTANT
不额外刷来源标签
```

### Case B · QQ 私聊 Owner → Desktop

暗苟在 QQ 私聊说：

```text
“晚上继续改朝汐。”
```

之后 Desktop Context 回忆。

要求：

```text
Role.USER
+
显式来源：QQ 私聊
```

不得表现成当前桌面历史发言。

### Case C · QQ 群 Owner → Desktop

要求：

```text
Role.USER
+
来源 QQ 群
+
conversation_id / 群范围可追踪
```

### Case D · QQ 第三方 → Desktop

群友说：

```text
“暗苟今天没来。”
```

要求：

```text
Role.EXTERNAL
+
actor
+
source
```

不得变成 Owner fact。

### Case E · QQ 群 A → QQ 群 B

虽然 channel 都是 qq，但 conversation_id 不同，必须：

```text
cross_context = true
```

### Case F · QQ 私聊 → QQ 群

conversation_kind 不同，必须显式来源。

### Case G · 历史图片

QQ 群历史图片进入 Desktop Attention Recall。

要求：

```text
明确历史来源
不能称“你刚发的这张图”
```

### Case H · 当前外部图片

当前 QQ Trigger 带图。

要求：

```text
仍作为 current_trigger
```

不能因为 provenance envelope 把它降级成历史图片。

### Case I · Current Cognition

Owner QQ 消息：

```text
“这两天都在准备面试。”
```

允许进入 Current Cognition。

但 evidence 必须保留：

```text
qq / private / event_id
```

### Case J · 第三方群聊

群友：

```text
“暗苟最近很焦虑。”
```

不得直接进入 Owner Current Cognition / Memory 作为事实。

---

## 26. 回归测试重点

至少新增：

```text
test_cross_channel_owner_message_keeps_source
test_cross_session_same_channel_keeps_source
test_cross_group_keeps_conversation_scope
test_external_actor_never_becomes_owner_turn
test_historical_image_keeps_provenance
test_current_trigger_image_not_mislabeled
test_social_snapshot_stays_external
test_owner_external_memory_keeps_evidence_source
```

---

## 27. 推荐开发顺序

### Phase 1 · Provenance Contract

- [x] Case E：同为 QQ 的群 A → 群 B，作为基础验收门槛
- [x] unknown 分支、空字段及 source_plugin 边界

- [x] 定义统一 provenance helper
- [x] is_cross_context()
- [x] render_source_label()

### Phase 2 · Cognitive Timeline

先双轨，再退出旧主分支：新 render 输出模型，旧 render 副本只进 Debug。用 Case A–J 对比旧/新文本，确认正文、身份、当前图片地位无退化后，删除 Query 关键词驱动的生产分支。Debug shadow 保留，不能作为模型输入。

- [x] Legacy shadow / 新投影的诊断双轨与 Case A–J 比对
- [x] ExperienceStream 优先、快照降级和过期快照测试
- [x] 连续同源组头合并（渠道、会话、类型、插件、timeline_scope）；身份变化保留简短发言者标识

- [x] project_event 保留 metadata
- [x] Context renderer 跨上下文强制来源
- [x] 删除 Query 关键词才加来源的主逻辑

### Phase 3 · Perception Runtime

- [x] 当前 external trigger provenance-aware
- [x] Planner View 不再裸 `add_user()`
- [x] Fast / Standard Channel Reply 使用一致 provenance

### Phase 4 · Image Provenance

- [x] current vs history image
- [x] source metadata
- [x] historical image label

### Phase 5 · Cognition / Memory

- [x] Current Cognition evidence source
- [x] AutoMemory evidence provenance
- [x] 第三方事实边界不退化

### Phase 6 · Debug / Tests

- [x] Provenance Inspector
- [x] 上述回归案例
- [ ] QQ 私聊 / QQ群 / Desktop 实机 smoke test（真实 NapCat；隔离程序链路测试不等同实机）

---

## 28. 本补丁不做

不做：

```text
重新设计 QQ 插件协议
重新设计 Perception DB
重写 ExperienceStream
Memory Graph 重构
外部消息权限体系大改
微信插件
```

本补丁只修：

> **外部信息一旦进入统一 Cognition 后，来源不能丢。**

---

## 29. 完成标准

另须自动验证连续同源标签不重复刷：golden prompt 快照必须比对完整 Provider 可见文字；不同来源重新开始组头，图片结构化 scope 不可被合并掉。

完成后必须满足：

```text
1. “谁说的”和“在哪说的”不再被混成一个 Role。

2. Owner 的 QQ 发言仍然是 USER，但跨上下文时明确标注 QQ 来源。

3. 同一个 channel 的不同群 / 私聊也能正确区分。

4. 第三方外部消息不会被投影成 Owner 发言。

5. 历史图片不会被误认为当前窗口刚发的图片。

6. Planner / Router / Agent 对当前外部 Trigger 都能看到来源。

7. Current Cognition / AutoMemory 能保留 evidence provenance。

8. 不再依赖 Query 是否提到“QQ / 哪里说”才临时补来源。

9. Source Plugin 可扩展到未来微信等渠道，不再为每个插件单独打补丁。

10. Debug 能回答：
    - 谁说的？
    - 从哪里来的？
    - 在哪个会话？
    - 当前窗口还是历史外部上下文？
```

---

## 30. 一句话定义

> **v1.4.3 External Provenance Integrity 的目标不是“给 QQ 加个标签”，而是让朝汐永远知道：这句话是谁说的、在哪说的、现在为什么会出现在我脑子里。**
