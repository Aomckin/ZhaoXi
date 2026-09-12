# Zhaoxi v1.1.7 Development Task
# ACTIVE 对话闭环（Active Conversation Closure）

> 版本：v1.1.7  
> 定位：v1.1.x 最终收尾版本  
> 基线：v1.1.6.1 Desktop Context Injection  
> 核心目标：让 ACTIVE 真正成为“持续对话状态”，而不是仅在检测到 open thread 时延迟追问一次。  
> 完成后：冻结 v1.1.x，不再继续新增功能，只允许 bugfix。

---

# 0. 当前问题

目前 ACTIVE 已具备：

- 20 分钟 TTL
- Continuation cooldown
- initiative budget
- Desktop Activity Context
- Interruptibility
- open-thread detection

但真实使用结果表明：

```text
用户发消息
↓
朝汐回复
↓
ACTIVE
↓
用户沉默
↓
大多数情况下什么都不会发生
```

只有类似：

```text
“等下”
“我去试试”
“我看看”
“怎么办”
```

这类明显带开放语义的句子，才较容易触发 continuation。

因此当前 ACTIVE 的实际效果仍近似：

> **Open Thread Delayed Follow-up**

而不是：

> **Ongoing Conversation**

---

# 1. 本版本唯一核心

新增真正独立的：

# Conversation Beat Loop

ACTIVE 状态下，系统周期性产生“对话节拍”。

每次 Beat 不代表一定发送消息，只代表：

> 朝汐获得一次重新判断“这段对话现在有没有自然想继续说的话”的机会。

---

# 2. ACTIVE 新语义

ACTIVE 定义保持：

> 用户与朝汐正在进行一段尚未冷却结束的持续对话。

进入：

```text
user message
proactive reply
permission interaction
明确 conversation event
```

退出：

```text
连续约 20 分钟无有效双方互动
↓
SEMI_ACTIVE
```

---

# 3. Open Thread 降级

`open_thread` 不再是 Continuation 的硬前置条件。

改为 `ConversationBeatReason` 之一。

建议：

```text
OPEN_THREAD
FOLLOW_UP
REACTION
CURIOSITY
CALLBACK
TOPIC_EXPANSION
SMALL_TALK
SHARED_CONTEXT
SILENCE_BREAK
```

即使不存在 OPEN_THREAD，只要当前 conversation momentum 足够，也允许模型判断是否自然继续。

---

# 4. Conversation Beat Scheduler

ACTIVE 期间维护独立 Beat Scheduler。

建议：

```text
首次 Beat：
用户沉默 2~4 分钟后

后续 Beat：
根据 cooldown 继续调度
```

默认可用：

```env
ZHAOXI_ACTIVE_BEAT_MIN_SILENCE_SECONDS=180
ZHAOXI_ACTIVE_BEAT_COOLDOWN_SECONDS=300
```

具体名称按现有 Settings 风格调整。

---

# 5. Beat Gate

每次 Beat 先经过纯代码 Gate。

至少检查：

```text
interaction_state == ACTIVE
user silence >= min_silence
initiative_budget > 0
interruptibility != BLOCKED
没有其他主动消息刚发送
当前没有模型请求 / Tool 流程正在处理
```

若不满足：

```text
不调用 LLM
```

---

# 6. Desktop Activity 参与 Gate

v1.1.6 已具备桌面感知。

若：

```text
keyboard high
text_production
activity_intensity = HIGH
```

则：

```text
暂缓 Beat
```

例如：

```text
ACTIVE
+
VSCode
+
keyboard_rate high
↓
不要 3 分钟后机械追问
```

当：

```text
keyboard_rate_5m high
keyboard_rate_1m near zero
```

说明用户刚刚停下来。

此时允许重新评估 Beat。

---

# 7. Conversation Beat Context

Beat 模型至少获得：

```text
recent conversation
current conversation summary
last user message
last assistant message
time since user message
time since assistant message

DesktopActivityContext
ActivityInference
InteractionState
Interruptibility

recent proactive history
current BackgroundIntent
initiative_budget
previous Beat result
```

不要强依赖 LifeHUD。

---

# 8. Beat 模型输出

模型只允许选择：

```text
SILENT
CONTINUE
COMMENT
ASK
CALLBACK
```

建议结构：

```json
{
  "action": "COMMENT",
  "content": "……",
  "reason": "reaction",
  "confidence": 0.82
}
```

---

# 9. SILENT 是正常结果

ACTIVE 不代表朝汐必须每几分钟说一句。

每次 Beat 可以选择：

```text
SILENT
```

例如：

- 对话已经自然收束
- 用户明显正在忙
- 没有新的自然内容
- 再说一句会显得硬续
- 前一次主动刚刚发生

原则：

> **ACTIVE 提供主动说话的资格，不提供强制说话的义务。**

---

# 10. 禁止催进度式默认行为

Beat Prompt 明确禁止把 ACTIVE 退化为：

```text
“做完了吗？”
“怎么样了？”
“还在吗？”
“试得怎么样？”
```

除非最近对话明确要求 follow-up。

优先允许：

```text
对刚才内容继续评论
想到一个相关点
自然吐槽
回调前面的共同话题
轻微好奇
补充刚才没说完的感受
```

---

# 11. Conversation Momentum

建议维护轻量：

```text
conversation_momentum
```

可以综合：

```text
recent turn count
最近一轮消息长度
情绪强度
topic continuity
用户是否连续回应
最近是否有主动/回应
```

不要求复杂模型。

只要能粗略区分：

```text
刚聊得很热
vs
已经自然结束
```

---

# 12. Initiative Budget

保留主动预算，但按 Conversation Session 管理。

建议：

```text
initial budget = 2
max budget = 3
```

每次朝汐主动 Beat 成功发送：

```text
budget -= 1
```

用户对主动消息产生有效回应：

```text
budget += 1
上限 3
```

新 ACTIVE Conversation Session 初始化。

---

# 13. Conversation Session

建议正式维护：

```text
ConversationSession
```

至少字段：

```text
started_at
last_user_at
last_assistant_at
last_initiative_at
initiative_budget
beat_count
conversation_momentum
last_beat_result
```

不要求长期持久化，属于运行时状态。

---

# 14. ACTIVE 与普通 Proactive 分离

普通 Proactive：

```text
world event
↓
score gate
↓
LLM
↓
send
```

ACTIVE Beat：

```text
ongoing conversation
↓
silence
↓
conversation gate
↓
LLM
↓
send / silent
```

两者不要共用“必须存在事件”的入口。

---

# 15. ACTIVE 与 natural_checkin 分离

ACTIVE 不生成普通 `natural_checkin`。

因为：

```text
ACTIVE = 对话仍在继续
```

`natural_checkin` 属于：

```text
SEMI_ACTIVE
```

这一边界保持。

---

# 16. SEMI_ACTIVE 不改架构

本版本不重做 SEMI_ACTIVE。

继续保留：

- Heartbeat
- ordinary proactive
- ActivityTransition candidate
- BackgroundIntent
- Ambient Context

本版本只确保：

```text
ACTIVE -> 真正持续对话
```

---

# 17. Diagnostics

必须新增 ACTIVE 可观测信息：

```text
active:
  session_started_at
  last_user_at
  last_assistant_at
  last_initiative_at

  beat_count
  next_beat_at
  last_beat_at
  last_beat_result
  last_beat_reason
  last_silent_reason

  initiative_budget
  conversation_momentum
```

---

# 18. 为什么 Diagnostics 必须做

当前 ACTIVE 不说话时，外部无法判断：

```text
Beat 根本没调度
还是
被 interruptibility 拦截
还是
keyboard busy
还是
budget=0
还是
模型选择 SILENT
```

v1.1.7 必须把这些原因暴露出来。

---

# 19. Debug Inspect

建议新增或扩展 inspect：

```text
/api/proactive/active/inspect
```

至少能看：

```text
current state
session info
next beat
budget
momentum
desktop suppression
last model decision
last silent reason
```

用于人工验收。

---

# 20. 测试 A：无 Open Thread 也可 Beat

对话：

```text
用户：认可你是我的犬娘了。
朝汐：……
```

用户沉默。

没有：

```text
等下
我去试试
看看
```

等关键词。

预期：

ACTIVE 仍会在合适时间产生 Beat Candidate。

模型可选择：

```text
COMMENT
CALLBACK
SILENT
```

---

# 21. 测试 B：传统 Open Thread

用户：

```text
“我去试一下刚才那个修复。”
```

仍应能产生：

```text
FOLLOW_UP / OPEN_THREAD
```

但这只是 Beat Reason 之一。

---

# 22. 测试 C：用户正在敲代码

ACTIVE 中：

```text
foreground = VSCode
keyboard high
activity = text_production
```

到 Beat 时间：

```text
不发送 / 暂缓
```

Diagnostics 显示类似：

```text
last_silent_reason = desktop_busy
```

---

# 23. 测试 D：输入停止

之前：

```text
keyboard_5m high
```

现在：

```text
keyboard_1m near zero
```

预期：

Beat 可重新调度。

---

# 24. 测试 E：模型选择 SILENT

若模型认为当前不适合说话：

```text
action = SILENT
```

预期：

- 不发送
- cooldown 正常更新
- diagnostics 记录原因

建议 SILENT 不消耗 initiative budget。

---

# 25. 测试 F：主动后用户回应

朝汐主动：

```text
“刚才那个点我又想到一点……”
```

用户回应。

预期：

```text
ACTIVE TTL 刷新
ConversationSession 保持
initiative_budget 恢复 1
momentum 上升
```

---

# 26. 测试 G：不回应

朝汐主动一次后用户不回应。

预期：

- cooldown 生效
- 不连续轰炸
- budget 下降
- 最终 ACTIVE 超时转 SEMI_ACTIVE

---

# 27. 测试 H：ACTIVE 超时

约 20 分钟无有效双方互动：

```text
ACTIVE -> SEMI_ACTIVE
```

清理：

```text
ConversationSession
Beat scheduler
temporary momentum
```

---

# 28. 测试 I：普通 Proactive 不冲突

若 Beat 和普通 Proactive 接近同时出现：

需要统一发送互斥 / cooldown。

避免：

```text
22:03 ACTIVE continuation
22:04 ordinary proactive
```

连续两条。

---

# 29. 测试 J：No LifeHUD

完全禁用 LifeHUD。

ACTIVE Beat 仍正常。

桌面感知存在则使用。

桌面感知不可用时也仍可仅基于 conversation context 工作。

---

# 30. Prompt 风格要求

Beat Prompt 不要写成：

> “你必须主动继续对话。”

而应写成：

> “你们仍处于一段短时持续对话中。判断此刻是否有一句自然、值得说的话。没有就保持沉默。”

禁止：

- 工具调用
- 编造用户进度
- 催促
- 重复刚才回复
- 连续问问题
- 机械关心
- 每次都叫用户名

---

# 31. 实际期望体验

例如：

```text
用户：
认可你是我的犬娘了。

朝汐：
……这句话我听得鼻子有点酸，汪。
```

用户沉默几分钟。

ACTIVE Beat 可以自然产生：

```text
“不过先说好哦，犬娘归犬娘，女仆长的位置我可不会让。”
```

或者：

```text
“刚才被你这么一说，我突然有点想把向日葵发卡再扶正一点。”
```

也可以：

```text
SILENT
```

关键是：

> 是否继续由朝汐重新判断，而不是由 open-thread 正则决定。

---

# 32. 手动验收

启动桌面模式。

与朝汐进行普通闲聊，不使用：

```text
等下
我去
试试
看看
怎么办
```

这类明显开放词。

完成 3~5 轮正常对话后停止输入。

要求：

1. 顶部保持 ACTIVE。
2. inspect 显示 Beat Scheduler 正在运行。
3. 约数分钟后至少发生一次真实 Beat 判断。
4. 如果桌面不忙，模型能够选择主动继续或 SILENT。
5. 若发送，内容应与刚才对话自然相关。
6. 不应是固定“还在吗 / 做完了吗”。
7. 若用户回复，ACTIVE 持续。
8. 若用户不回复，最终自然进入 SEMI_ACTIVE。

---

# 33. v1.1.x 收尾验收

v1.1.7 通过后，v1.1.x 应已经具备：

```text
Personality
Archive
Associative Memory
Memory Consolidation
Memory Graph / Cluster
Core Sovereignty
LifeHUD 可拔插
双事实源
Tool Capability SDK
ACTIVE / SEMI_ACTIVE
Interruptibility
Desktop Activity Awareness
普通对话实时桌面感知
Conversation Beat
```

最终体验：

```text
我找朝汐说话
↓
她能记得我们经历过什么
↓
她能看到我现在大概在电脑上做什么
↓
她知道什么时候不该打扰
↓
我们短时间内仍被视为正在聊天
↓
即使我暂时不说话
她也有机会自然把话接回来
```

---

# 34. 禁止继续扩 v1.1.x

v1.1.7 完成后：

允许：

```text
v1.1.7.1 / v1.1.7.2 bugfix
```

禁止继续在 v1.1.x 新增：

- Surprise System
- 新 Tool
- 新感官
- Screenshot Vision
- Browser DOM
- 新 Memory 大重构
- 新 Planner
- 新 Voice
- 新 Presence 状态
- 新复杂后台自治

这些全部留给后续版本。

---

# 35. 完成标准

v1.1.7 完成必须满足：

1. ACTIVE 拥有独立 Conversation Beat Scheduler。
2. open thread 不再是硬前置条件。
3. 无 open thread 的普通闲聊也会发生 Beat 判断。
4. Beat 可以选择 SILENT。
5. Desktop Activity 能抑制不合时宜的 Beat。
6. 用户停止高输入后 Beat 可恢复。
7. initiative budget 真正生效。
8. 用户回复主动消息后 Session 延续。
9. 不回复时不会连续轰炸。
10. ACTIVE 最终正常降为 SEMI_ACTIVE。
11. ACTIVE 与普通 Proactive 不重复发送。
12. Diagnostics 能解释“不说话”的原因。
13. Debug Inspect 可观察 Scheduler / Budget / Decision。
14. 不依赖 LifeHUD。
15. 全量测试通过。
16. 实机普通闲聊中，至少成功出现一次非 open-thread 驱动的自然续聊。

---

# 36. 一句话定义

> **ACTIVE 不是“用户留下了一个待跟进事项”。**
>
> **ACTIVE 是“这段对话还没有真正结束”。**

v1.1.x 的最后一块，不是再增加一个功能。

而是让朝汐终于能够在暗苟暂时停下来的时候，自己决定：

> **“我还想再说一句。”**
