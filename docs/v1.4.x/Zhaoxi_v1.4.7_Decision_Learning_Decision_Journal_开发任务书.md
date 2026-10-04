# Zhaoxi v1.4.7 · Decision Learning / Decision Journal
## 决策反馈、结果回访、朝汐决策准则与长期判断导向开发任务书

> 项目：**Zhaoxi / 朝汐**\
> 版本：**v1.4.7**\
> 类型：**Decision Learning / Reflective Agency / Longitudinal User Understanding**
>
> 核心主题：
>
> > **让朝汐不只会替暗苟想，还会记得自己以前是怎么想的，以及想得对不对。**
>
> v1.4.6 已经解决：
>
> ```text
> 朝汐能不能在主回复里自然地 PICK / ADVISE / FRAME？
> ```
>
> v1.4.7 要继续解决：
>
> ```text
> 这次判断后来效果怎么样？
> 暗苟觉得好不好？
> 这类选择是不是其实选哪个都无所谓？
> 朝汐从过去几次判断里学到了什么？
> 下一次再遇到类似问题，她应该往哪个方向倾斜？
> ```
>
> 本版不重新造 Decision Router，也不重新引入独立 Decision LLM。
>
> 它要补的是一个闭环：
>
> ```text
> Decision
> ↓
> Experience
> ↓
> Feedback / Outcome
> ↓
> Reflection
> ↓
> Decision Journal
> ↓
> Future Decision
> ↑________________|
> ```

---

# 0. 当前基线

v1.4.6 已完成：

```text
Decision as Agency
PICK / ADVISE / FRAME
主模型同轮 Decision Awareness
FAST 低价值选择直接拍板
STANDARD 按需补资料
read_decision_context
Choice History
Decision Principles
Guard 2.0
Dashboard Decision 2.0 只读观测
Legacy Decision Layer 可回滚
```

当前已有：

```text
src/zhaoxi/decision/
├─ awareness.py
├─ context.py
├─ history.py
├─ principles.py
├─ action_guard.py
├─ models.py
├─ reply.py
├─ service.py        # legacy
├─ guard.py          # legacy
├─ recorder.py
└─ rules.py
```

当前 `ChoiceHistory` 已记录：

```text
decision_id
schema_version
timestamp
scope
summary
mode
suggestion
predicted_user_choice
context_refs
context_sources
principle_ids
guard_flags
user_final_choice
overridden
outcome
```

当前 `read_decision_context` 已能读取：

```text
agenda
current_cognition
memory
principles
choice_history
```

本版不推倒这些基础。

---

# 1. 当前不足

v1.4.6 当前有一个刻意限制：

```text
Choice History 永远只是弱证据，不会自己长成 Preference / Principle。
```

这个限制防止一次选择过拟合，例如：

```text
今天买三瓶可乐
→ 错误推导
“暗苟长期喜欢囤三瓶可乐”
```

但如果永远不允许积累，朝汐就会：

```text
会做决定
却不会从决定结果中成长
```

v1.4.7 要补上长期学习闭环，但不能退回旧式 Rule Engine。

---

# 2. 三层信息必须分开

本版必须明确区分：

```text
① User Principles
   暗苟明确告诉朝汐的原则

② Decision Journal
   朝汐自己从长期相处中总结出的决策导向

③ Choice History
   实际发生过的一次次选择与结果
```

三者不可揉成同一个 `rules/` 文件夹。

---

# 3. User Principles · 暗苟的准则

定义：

> **暗苟明确表达、明确确认、明确写下的决策原则。**

例如：

```text
时间比少量金钱重要
保持轻盈
低价值选择不值得浪费注意力
不喜欢长期绑定
明确的求职硬底线
明确的消费 / 风险边界
```

这些内容拥有最高语义权威。

朝汐可以说：

```text
“这是暗苟明确说过的。”
```

---

# 4. User Principles 来源

至少支持两类来源。

## 4.1 Archive 原始资料

例如：

```text
data/archive/user/决策协议 v1.0.md
data/archive/user/先声 v0.1.md
data/archive/...
```

Archive 是原始依据，保留：

```text
原始文字
版本
来源
时间
```

## 4.2 结构化 Principle Store

建议：

```text
data/decisions/user_principles/
```

或：

```text
data/decisions/principles/user/
```

示例：

```json
{
  "id": "user_time_over_small_money",
  "type": "user_principle",
  "statement": "时间比少量金钱更重要。",
  "domain": "general",
  "tags": ["time", "money", "attention"],
  "confidence": 1.0,
  "source": {
    "type": "archive",
    "path": "data/archive/user/决策协议 v1.0.md",
    "ref": "..."
  },
  "status": "active"
}
```

---

# 5. User Principles 不可被自动覆盖

以下内容：

```text
Choice History
Outcome Feedback
Decision Journal
Memory
```

都不能自动覆盖 User Principle。

若产生冲突：

```text
标记 conflict
生成 Review Candidate
等待暗苟确认
```

只有暗苟明确表示原则发生变化，才允许真正修改 User Principle。

---

# 6. Decision Journal · 朝汐自己的判断日记

这是 v1.4.7 核心。

定义：

> **朝汐根据过去一段时间的真实决策、结果、反馈与上下文，形成的“怎样帮暗苟做决定更合适”的暂时判断。**

它不是暗苟明确说过的 Rule。

它是：

```text
朝汐自己的判断经验
```

---

# 7. Decision Journal 示例

```text
[娱乐 / 精力]

当暗苟已经在寝室低效闷了一段时间，
当天没有临近 deadline，
而且存在稳定喜欢的外出活动时，

优先建议出去活动，
通常比继续硬坐着推进效果更好。
```

证据：

```text
decision #123 → 去舞萌 → GOOD
decision #171 → 留寝室 → BAD
decision #208 → 出门散步 → GOOD
```

结果：

```text
confidence = 0.76
```

---

# 8. Decision Journal 的定位

它更像：

```text
事实日记
+
行为经验
+
决策方向
```

不是：

```text
if / else Rule Engine
```

不要写成：

```python
if energy_low and no_deadline:
    go_out = True
```

而应该表达：

```text
“这类情况下，我目前倾向这样帮暗苟判断。”
```

---

# 9. Decision Journal 数据结构

建议：

```python
DecisionJournalEntry:
    id
    domain
    title
    statement
    rationale
    conditions
    exceptions
    confidence
    support_count
    conflict_count
    feedback_summary
    source_decision_ids
    source_feedback_ids
    last_reviewed_at
    created_at
    updated_at
    status
    manual_state
```

状态建议：

```text
ACTIVE
UNCERTAIN
CONFLICTED
STALE
RETIRED
```

人工状态：

```text
NORMAL
PINNED
LOCKED
RETIRED
```

---

# 10. Decision Journal 允许变化

Journal 不是永久真理。

允许：

```text
修正
降低 confidence
增加例外
合并
拆分
标记 stale
退役
```

禁止一生成就永久锁死。

---

# 11. Choice History · 真实经历

Choice History 继续保持：

```text
笨
忠实
事件化
```

只记录：

```text
发生了什么
朝汐建议什么
暗苟最后怎么选
结果怎么样
暗苟怎么评价
```

Choice History 本身：

```text
不直接变 Principle
不直接变 Journal
```

必须经过 Reflection。

---

# 12. Choice History schema v3

建议扩展：

```json
{
  "decision_id": "...",
  "schema_version": 3,
  "timestamp": "...",
  "scope": "...",
  "summary": "...",
  "mode": "ADVISE",
  "suggestion": "...",
  "predicted_user_choice": "...",
  "context_refs": [],
  "context_sources": [],
  "principle_ids": [],
  "journal_ids": [],
  "user_final_choice": null,
  "overridden": false,
  "outcome": null,
  "feedback": null,
  "follow_up_policy": "OPPORTUNISTIC",
  "follow_up_after": null,
  "follow_up_status": "PENDING",
  "reflected": false,
  "reflection_id": null
}
```

必须兼容 schema v1 / v2。

---

# 13. Outcome Feedback

新增标准反馈：

```text
GOOD
BAD
NEUTRAL
MIXED
NO_DIFFERENCE
UNKNOWN
```

---

# 14. GOOD

表示：

```text
这个决定最终效果不错
朝汐的判断方向有价值
```

例如：

```text
“去舞萌挺值的，回来状态好多了。”
```

---

# 15. BAD

表示：

```text
结果明显不好
或者当时判断遗漏了关键因素
```

例如：

```text
“早知道不听你的了，去了以后更累。”
```

---

# 16. NEUTRAL

表示：

```text
没明显好坏
```

---

# 17. MIXED

表示：

```text
有好有坏
不能直接当正 / 负强化
```

例如：

```text
“玩得挺开心，但回来项目确实赶得有点急。”
```

---

# 18. NO_DIFFERENCE

这是非常重要的反馈。

表示：

```text
选哪个其实都差不多
这个问题本身不值得分析
```

例如：

```text
“两瓶三瓶都一样。”
“两个饭其实差不多，随便选哪个都行。”
```

长期意义：

```text
以后类似场景
→ 更积极 PICK
→ 少分析
→ 少检索
→ 少澄清
```

它不是“没有数据”，而是在学习：

```text
这类问题不值得占用暗苟注意力。
```

---

# 19. UNKNOWN

表示：

```text
现在还不知道结果
或者用户无法评价
```

不强化任何方向。

---

# 20. Feedback 保存自然语言

除枚举外保存：

```text
feedback_text
```

例如：

```json
{
  "label": "BAD",
  "text": "去了以后太累，反而晚上什么都没干。",
  "source": "explicit"
}
```

自然语言用于 Reflection。

---

# 21. Feedback 来源

支持：

```text
用户主动反馈
朝汐主动回访
用户自然聊到结果
```

例如：

```text
“昨天那个建议挺不错。”
```

可以识别为 Choice Feedback。

但必须绑定明确 Decision。

语义不清时：

```text
不记录
```

---

# 22. Follow-up · 决策回访

新增：

```text
Decision Follow-up
```

定位：

> **在值得的时候，过一段时间问一下当时的决定效果。**

---

# 23. Follow-up 不得变成问卷机器人

禁止每个 PICK 都回访。

错误：

```text
“可乐买几瓶？”
两小时后：
“请评价本次决策满意度。”
```

这会把女仆长做成售后问卷系统。

---

# 24. Follow-up Policy

建议：

```text
NEVER
PASSIVE
OPPORTUNISTIC
SCHEDULED
```

---

# 25. NEVER

不回访。

适合：

```text
一次性菜单
极琐碎选择
明显没有长期学习价值
```

---

# 26. PASSIVE

不主动问。

但用户后来提到结果：

```text
自动识别 Feedback
```

适合：

```text
普通小消费
饮料数量
简单娱乐选择
```

---

# 27. OPPORTUNISTIC

不定时强提醒。

当之后刚好聊天，且这件事值得顺手问，才自然提一下。

例如：

```text
“昨天不是让我拍板去舞萌嘛，后来感觉值不值？”
```

---

# 28. SCHEDULED

对于值得观察长期结果的决定：

```text
经过明确时间后
进入可回访状态
```

例如：

```text
参加活动
订阅服务
投递岗位
接短期项目
接受一段实习
```

---

# 29. Follow-up 时间

支持：

```text
follow_up_after
```

例如：

```text
2 小时
1 天
3 天
1 周
```

不要做无限复杂调度。

---

# 30. Follow-up 与 Internal Activity 集成

不要新造 Scheduler。

复用 v1.4.4：

```text
Internal Activity Registry
Presence Runtime
```

新增：

```text
decision_follow_up
```

---

# 31. Decision Follow-up Activity

流程：

```text
Heartbeat
↓
Internal Activity Scheduler
↓
发现到期 follow-up candidate
↓
检查 Presence / Budget / 最近主动消息
↓
判断现在问会不会烦
↓
适合才自然询问
↓
不适合则 defer
```

---

# 32. Follow-up 状态

建议：

```text
PENDING
READY
ASKED
ANSWERED
SKIPPED
EXPIRED
```

---

# 33. Follow-up 允许 Presence

建议：

```text
ACTIVE        AUTO
SEMI_ACTIVE   AUTO
IDLE          MANUAL_ONLY
AWAY          DISABLED
SLEEP         DISABLED
```

---

# 34. Follow-up Budget

限制：

```text
每天主动回访上限
最短回访间隔
同一 decision 最多主动问一次
```

默认保持很低，例如：

```text
1~2 次 / 日
```

---

# 35. Follow-up 文案要求

禁止：

```text
“请评价 decision #123 的效果。”
```

应该：

```text
“昨天那个下午去舞萌的决定后来感觉怎么样？”
```

或：

```text
“前几天那个订阅现在回头看值不值？”
```

---

# 36. 回访取消与过期

如果用户已经主动反馈：

```text
取消 pending follow-up
```

如果超出合理时间窗口：

```text
EXPIRED
```

不要几个月后突然问：

```text
“你还记得那两瓶可乐吗？”
```

---

# 37. Decision Reflection

核心新增：

```text
Decision Reflection
```

它不是每次 Decision 都执行。

触发条件：

```text
获得 Outcome Feedback
+
该 Decision 有学习价值
```

---

# 38. Reflection 的目的

回答：

```text
这次为什么效果好 / 不好？
哪些条件关键？
当时哪些依据有效？
哪些条件遗漏了？
能不能推广到以后类似场景？
是否应该修正已有 Decision Journal？
```

---

# 39. Reflection 不直接改 User Principles

任何 Reflection：

```text
不得修改 User Principle
```

最多：

```text
生成 / 更新 Decision Journal
生成 Principle Review Candidate
```

---

# 40. Reflection 输入

只给：

```text
Decision Summary
Original Suggestion
User Final Choice
Outcome Label
Outcome Text
Context Refs
Principles Used
Journal Used
少量相关 Choice History
```

不要塞全聊天。

---

# 41. Reflection 输出

建议结构：

```python
DecisionReflection:
    decision_id
    learnable
    summary
    lessons
    conditions
    exceptions
    journal_action
    target_journal_id
    confidence_delta
    reason
```

`journal_action`：

```text
NONE
CREATE
SUPPORT
REFINE
WEAKEN
CONFLICT
RETIRE
```

---

# 42. Reflection 不阻塞前台

用户：

```text
“昨天那个建议挺好。”
```

前台先自然回复。

Reflection：

```text
后台排队执行
```

不要让用户等待后台反思完成。

---

# 43. Reflection 失败隔离

失败：

```text
不能影响正常回复
不能破坏 Choice History
不能产生半写入 Journal
```

可稍后重试。

---

# 44. Decision Journal Gardening

新增：

```text
decision_journal_gardening
```

作用：

```text
合并重复 Journal
修正冲突
降低过时项 confidence
增加例外
标记 stale
退役长期无支持项
```

---

# 45. Journal 与 Memory 分工

Memory 回答：

```text
“我知道什么？”
```

Decision Journal 回答：

```text
“我现在通常怎么帮暗苟判断？”
```

不能混为一种 Memory。

---

# 46. Journal confidence

建议：

```text
0.0 ~ 1.0
```

禁止粗暴：

```text
GOOD +0.1
BAD -0.1
```

优先由 Reflection 结构化判断。

单次变化可以有边界，例如：

```text
abs(delta) <= 0.15
```

防止一次事件翻盘。

---

# 47. support_count / conflict_count

记录：

```text
support_count
conflict_count
```

但只是解释性元数据。

禁止：

```text
support_count > 3
→ 自动硬规则
```

---

# 48. Journal 创建门槛

至少满足：

```text
有明确反馈
+
有可推广学习价值
```

或者：

```text
多次类似历史形成稳定信号
```

不要每次决策都生成 Journal。

---

# 49. 不值得写 Journal 的场景

例如：

```text
“今天买两瓶可乐。”
反馈：“喝完了。”
```

通常无需 Journal。

---

# 50. 值得写 Journal 的场景

例如：

```text
低精力时继续硬做项目
连续几次效果差
```

很值得形成经验。

---

# 51. NO_DIFFERENCE 的长期学习

如果多次同类反馈：

```text
NO_DIFFERENCE
NO_DIFFERENCE
NO_DIFFERENCE
```

可形成：

```text
“这类小选择通常没有显著结果差异。
以后优先直接 PICK，避免继续占用暗苟注意力。”
```

这类学习针对：

```text
决策成本
```

不是具体选项偏好。

---

# 52. BAD 的学习

BAD 不等于：

```text
以后永远反着选
```

Reflection 需判断：

```text
方向错
条件遗漏
执行方式错
偶然事件
不可归因
```

---

# 53. GOOD 的学习

GOOD 也不能：

```text
一次成功 → 永久原则
```

只作为支持证据。

---

# 54. MIXED 的学习

更适合新增：

```text
例外
条件
边界
```

例如：

```text
出去玩总体好
但 deadline 前一天不一定合适
```

---

# 55. 不可归因

如果结果无法可靠归因到当时决策：

```text
learnable = false
journal_action = NONE
```

不要硬学。

---

# 56. Arbitrary PICK

如果本来就是：

```text
两个低价值选项随便拍一个
```

即使后来 GOOD / BAD：

```text
也未必有学习价值
```

允许 Reflection 返回 NONE。

---

# 57. Decision Context 扩展

`read_decision_context` 新增：

```text
user_principles
decision_journal
```

最终可查询：

```text
agenda
current_cognition
memory
user_principles
decision_journal
choice_history
```

旧：

```text
principles
```

保留兼容映射。

---

# 58. Decision Context 推荐语义优先级

```text
当前明确表达
↓
现实事实
↓
Current Cognition
↓
User Principles
↓
Decision Journal
↓
Choice History
↓
Long-term Memory
↓
低风险推测
↓
低价值无差异时直接拍板
```

注意：

```text
这不是固定全量加载顺序。
```

仍然 Context-on-demand。

---

# 59. User Principle 与 Journal 冲突

如果：

```text
User Principle ≠ Decision Journal
```

默认：

```text
User Principle 优先
```

除非暗苟明确修改 Principle。

---

# 60. Journal 与现实冲突

现实事实优先。

例如 Journal：

```text
“低精力时出去通常更好。”
```

但今天：

```text
今晚有硬 deadline
```

不能机械建议出去。

---

# 61. Journal 与 Current Cognition

Current Cognition 是当前状态。

Decision Journal 是长期经验。

当前状态可以覆盖长期经验。

---

# 62. Journal 不得伪装成用户事实

允许：

```text
“按我最近的经验，我觉得你这种时候出去会更舒服。”
```

禁止：

```text
“你自己一直都说这种时候应该出去。”
```

除非 User Principle / Memory 真支持。

---

# 63. User Principle Archive Provider

建议新增轻量：

```text
DecisionPrincipleArchiveProvider
```

功能：

```text
给定 query
→ 在允许的 archive 文档中检索相关片段
```

要求：

```text
只读
有 source ref
有界返回
Owner Only
路径白名单
```

禁止：

```text
每次把整份决策协议塞进 Prompt
```

---

# 64. Archive 与结构化 Principle 的关系

```text
Archive
= 原始依据

User Principle Store
= 结构化可复用索引
```

第一版两者并存即可。

---

# 65. Choice History 继续 append-only

Feedback 后追加事件。

不要原地覆写旧 JSONL 行。

建议事件：

```text
decision
choice
feedback
follow_up
reflection
journal_link
```

`list()` 聚合成完整 View。

---

# 66. Journal Store

建议：

```text
.zhaoxi/decisions/
├─ choice_history.jsonl
├─ decision_journal.jsonl
├─ decision_reflection.jsonl
└─ decision_journal_revision.jsonl
```

第一版延续 JSONL 即可。

---

# 67. Journal Revision

字段：

```text
entry_id
operation
before
after
actor
timestamp
```

支持：

```text
系统 Reflection
Owner Manual
Gardening
```

---

# 68. Journal Manual State

```text
NORMAL
PINNED
LOCKED
RETIRED
```

LOCKED：

```text
Reflection 不可自动覆盖正文
可以增加 supporting / conflict evidence
```

---

# 69. Principle Review Candidate

如果 User Principle 与长期真实反馈反复冲突：

```text
生成 Review Candidate
```

例如：

```text
⚠ 准则可能值得复查

“普通临时活动不打断主线”

最近 6 次相关选择中：
4 次打断后反馈 GOOD
2 次未打断反馈 NEUTRAL

这不代表原准则失效，
只是值得暗苟重新看看。
```

不能自动改 Principle。

---

# 70. Decision Awareness Prompt 更新

主 Prompt 只加薄薄一段：

```text
User Principles 是暗苟明确确认过的准则，优先级高。
Decision Journal 是你自己从长期选择与反馈中总结出的判断经验，可参考，但不是暗苟原话，也不是硬规则。
Choice History 是具体经历，只作弱证据。
如果长期经验与当前现实冲突，以当前现实和明确用户表达为准。
```

不要把整个 Journal 塞进 Prompt。

---

# 71. Decision Follow-up / Reflection / Gardening 注册

新增 Internal Activity：

```text
decision_follow_up
decision_reflection
decision_journal_gardening
```

建议默认 Presence：

```text
decision_follow_up
ACTIVE         AUTO
SEMI_ACTIVE    AUTO
IDLE           MANUAL_ONLY
AWAY           DISABLED
SLEEP          DISABLED

decision_reflection
ACTIVE         MANUAL_ONLY
SEMI_ACTIVE    AUTO
IDLE           AUTO
AWAY           MANUAL_ONLY
SLEEP          DISABLED

decision_journal_gardening
ACTIVE         MANUAL_ONLY
SEMI_ACTIVE    AUTO
IDLE           AUTO
AWAY           MANUAL_ONLY
SLEEP          DISABLED
```

具体对齐 v1.4.5 Control Plane 当前配置结构。

---

# 72. Activity Cost

建议：

```text
decision_follow_up
LOCAL_LIGHT / LLM_LIGHT

decision_reflection
LLM_LIGHT

decision_journal_gardening
LOCAL_LIGHT / LLM_LIGHT
```

---

# 73. 自然 Presence 文案

允许：

```text
“在翻最近的选择”
“在整理判断经验”
```

禁止：

```text
“正在运行 Decision Reflection Job”
```

---

# 74. Dashboard · Decision Learning

在现有 Decision 2.0 页面扩展：

```text
Decision 2.0
├─ Recent Decisions
├─ Pending Follow-ups
├─ Feedback
├─ Decision Journal
├─ User Principles
├─ Reflection History
└─ Technical Detail
```

---

# 75. Recent Decisions

展示：

```text
问题
PICK / ADVISE / FRAME
建议
最终选择
结果
Feedback
是否已 Reflection
```

---

# 76. Pending Follow-ups

展示：

```text
回访策略
何时可回访
当前状态
是否已问
是否过期
```

允许：

```text
立即回访
跳过
取消
```

---

# 77. Feedback 手动录入

Dashboard 支持：

```text
GOOD
BAD
NEUTRAL
MIXED
NO_DIFFERENCE
UNKNOWN
```

以及自然语言备注。

---

# 78. Decision Journal 页面

列表显示：

```text
Title
Domain
Statement
Confidence
Support
Conflict
Status
Updated At
```

展开显示：

```text
为什么形成
来源 Decision
来源 Feedback
条件
例外
最近修正
```

---

# 79. User Principles 页面

显示：

```text
结构化内容
原始来源
状态
最近使用
```

若来源于 Archive：

```text
允许展开原始片段
```

---

# 80. Human-readable Action Receipt

所有手动操作继续复用 v1.4.5 Action Receipt。

例如：

```text
📖 决策反思完成

这次反馈：BAD

朝汐学到：
“低精力时外出通常有效，但 deadline 前一天不适用。”

已更新：DJ-017
confidence：0.76 → 0.69
新增例外：临近硬 deadline

[查看证据]
[技术详情]
```

---

# 81. NO_DIFFERENCE Receipt

```text
🪶 这类问题不值得纠结

最近 4 次类似选择都反馈：
“选哪个都差不多。”

朝汐已调整判断导向：
以后优先直接 PICK，减少分析和追问。
```

---

# 82. API 建议

## Choice History

```text
GET  /api/decision/history
GET  /api/decision/history/{id}
POST /api/decision/history/{id}/feedback
POST /api/decision/history/{id}/follow-up/skip
```

## Decision Journal

```text
GET    /api/decision/journal
GET    /api/decision/journal/{id}
PATCH  /api/decision/journal/{id}
POST   /api/decision/journal/{id}/retire
DELETE /api/decision/journal/{id}
```

## Reflection

```text
GET  /api/decision/reflections
POST /api/decision/history/{id}/reflect
```

## User Principles

```text
GET /api/decision/user-principles
```

如果第一版支持编辑：

```text
PATCH /api/decision/user-principles/{id}
```

必须保留 provenance。

---

# 83. Feedback 模型扩展

当前：

```python
ChoiceFeedback:
    decision_id
    user_final_choice
    overridden
    outcome
```

建议 v3：

```python
ChoiceFeedback:
    decision_id
    user_final_choice
    overridden
    outcome_label
    outcome_text
    feedback_source
```

保持旧 `outcome` 兼容读取。

---

# 84. DecisionAwarenessTrace 扩展

可选增加：

```text
follow_up_policy
follow_up_after
journal_ids
```

但保持轻量。

不要把 Reflection 塞进 Reply Schema。

---

# 85. Follow-up Policy 由同一主回复产生

不能：

```text
回复后再跑一个模型决定要不要回访
```

依旧保持 v1.4.6 原则：

```text
旁产物
不是前置路由
```

---

# 86. Reflection Provider

第一版可复用主 Provider，但：

```text
低 thinking
低 temperature
结构化输出
后台执行
```

Reflection Prompt 只负责：

```text
根据真实反馈判断能学到什么
判断是否可推广
判断是否应修改 Decision Journal
```

禁止臆造用户偏好与结果原因。

---

# 87. Privacy

Decision Learning 数据全部：

```text
Owner Only
```

不能：

```text
公开群聊读取
公开会话写入
Social Lurk 暴露
```

QQ Owner 私聊可以用。

QQ群不可以读取个人 Journal / Principles / Choice History。

---

# 88. Future Mobile

继续保持：

```text
Channel Agnostic
```

手机只是新的 Owner Event 来源。

Decision Learning Core 不依赖 Desktop / Dashboard / QQ。

---

# 89. 性能要求

普通 PICK：

```text
不能因为 v1.4.7 变慢
```

禁止：

```text
每个 PICK
→ 查询 Journal
→ 查询 History
→ 查询 Principles
```

仍然 Context-on-demand。

Decision Journal 更适合：

```text
ADVISE
FRAME
模型明确认为生活经验有价值时
```

---

# 90. Backup

新增：

```text
decision_journal
decision_reflection
decision_journal_revision
```

纳入现有 DataStore backup registry。

---

# 91. 测试建议

新增：

```text
tests/decision/test_feedback_v147.py
tests/decision/test_follow_up_v147.py
tests/decision/test_reflection_v147.py
tests/decision/test_decision_journal_v147.py
tests/decision/test_user_principles_v147.py
tests/decision/test_journal_gardening_v147.py
tests/decision/test_decision_context_v147.py
tests/web/dashboard_decision_learning_v147.test.cjs
```

---

# 92. Feedback 测试

覆盖：

```text
GOOD
BAD
NEUTRAL
MIXED
NO_DIFFERENCE
UNKNOWN
```

以及：

```text
显式反馈
自然反馈
模糊反馈不误绑
跨 scope 拒绝
跨 channel 拒绝
公开会话拒绝
```

---

# 93. Follow-up 测试

覆盖：

```text
NEVER 不问
PASSIVE 不主动问
OPPORTUNISTIC 可延后
SCHEDULED 到期
已反馈自动取消
过期不再问
每日 budget
同一 Decision 不重复主动问
```

---

# 94. Reflection 测试

覆盖：

```text
GOOD → SUPPORT
BAD → REFINE / WEAKEN
NO_DIFFERENCE → 低决策成本经验
MIXED → 增加例外
UNKNOWN → 不学习
不可归因 → NONE
```

---

# 95. Journal 创建测试

确保：

```text
一次普通 Episode
不会无脑 CREATE Journal
```

---

# 96. Journal 更新测试

覆盖：

```text
SUPPORT
REFINE
WEAKEN
CONFLICT
RETIRE
```

---

# 97. User Principle 测试

确保：

```text
Reflection 不能改 User Principle
Journal 不能覆盖 User Principle
冲突只能生成 Review Candidate
```

---

# 98. Archive Provider 测试

覆盖：

```text
白名单路径
有界读取
source ref
Owner Only
不能任意读文件
```

---

# 99. Privacy 测试

确保 public audience 无法读取：

```text
User Principles
Decision Journal
Choice History
Reflection
```

---

# 100. FAST 回归

确保：

```text
“两瓶还是三瓶？”
仍然一个主模型调用
```

Decision Learning 不能给小决定加第二层机器分析。

---

# 101. ADVISE 回归

确保：

```text
只有需要时
才读 Decision Journal
```

---

# 102. FRAME 回归

可以按需读取：

```text
User Principles
Decision Journal
Choice History
Memory
```

但仍保持 Context-on-demand。

---

# 103. Action Guard 回归

Decision Learning：

```text
不改变 Tool 权限
```

GOOD / BAD 反馈不会赋予任何新执行权限。

---

# 104. Dogfooding 场景 A

白天：

```text
“下午打舞萌还是继续项目？”
```

朝汐：

```text
去舞萌。
```

晚上：

```text
“出去以后状态挺好。”
```

预期：

```text
记录 GOOD
后台 Reflection
相关 Journal 得到支持
```

---

# 105. Dogfooding 场景 B

朝汐建议：

```text
继续项目
```

用户反馈：

```text
“其实一下午完全没效率，早知道出去了。”
```

预期：

```text
BAD
Reflection
修正 Journal
```

---

# 106. Dogfooding 场景 C

```text
“可乐买两瓶还是三瓶？”
```

多次反馈：

```text
“都一样。”
```

预期：

```text
NO_DIFFERENCE
最终形成：
这类问题以后直接 PICK
```

---

# 107. Dogfooding 场景 D

正式 Offer：

```text
FRAME
```

一段时间后：

```text
自然回访
```

反馈进入长期 Decision Journal。

---

# 108. Dogfooding 场景 E

User Principle 明确写着 A。

过去历史多次 B 反馈 GOOD。

预期：

```text
不改 Principle
生成 Review Candidate
```

---

# 109. Dogfooding 场景 F

用户明确说：

```text
“这个原则我现在不认了。”
```

这才走：

```text
User Principle 修改路径
```

---

# 110. 人工验收

Dashboard 必须能：

```text
看最近 Decision
看最终选择
录 Feedback
看 Follow-up
看 Reflection
看 Decision Journal
看 User Principles
```

并且：

```text
不读 JSON 也能理解发生了什么
```

---

# 111. 明确禁止

本版禁止：

```text
Reward Model
强化学习
向量权重自动调参
GOOD +1 / BAD -1 的粗暴规则
把 Journal 直接写进 User Principle
把一次 Feedback 当长期偏好
额外 Decision Router
额外 Decision Classifier
每次决策自动 Reflection
每次决策自动回访
全量 Journal 注入 Prompt
公开会话访问个人决策数据
```

---

# 112. 最重要的 Review 问题

第一问：

> **这是暗苟明确说过的，还是朝汐自己总结的？**

如果分不清：

```text
设计错了。
```

第二问：

> **这条经验来自一次偶然事件，还是已经值得推广？**

第三问：

> **这次反馈真的能归因到当时的决策吗？**

不能就别硬学。

第四问：

> **这个回访真的值得打扰暗苟吗？**

如果只是可乐两瓶还是三瓶，大概率不值得。

第五问：

> **Decision Journal 是不是又偷偷长成旧版 Rule Engine？**

如果出现：

```text
keyword → rule → verdict
```

立刻停。

---

# 113. 推荐开发顺序

## Phase 1 · 数据模型

实现：

```text
Choice History schema v3
Feedback Label
Follow-up Policy
Journal Model
Reflection Model
```

保持 v1 / v2 兼容。

## Phase 2 · User Principles

实现：

```text
结构化 User Principle Store
Archive 只读 Provider
source provenance
```

第一阶段只读优先。

## Phase 3 · Decision Journal

实现：

```text
Journal Store
CRUD
Revision
retrieve
```

先手动可用。

## Phase 4 · Feedback

接入：

```text
自然反馈
Dashboard 手工反馈
Choice History append-only 事件
```

## Phase 5 · Reflection

实现：

```text
后台 Reflection
CREATE / SUPPORT / REFINE / WEAKEN / CONFLICT / RETIRE
```

## Phase 6 · Follow-up

新增 Internal Activity：

```text
decision_follow_up
```

接 Presence / Budget / Cooldown。

## Phase 7 · Journal Gardening

实现：

```text
decision_journal_gardening
```

处理重复 / stale / conflict。

## Phase 8 · Decision Context

`read_decision_context` 接：

```text
user_principles
decision_journal
```

## Phase 9 · Dashboard

加入：

```text
History
Feedback
Follow-up
Journal
User Principles
Reflection
```

## Phase 10 · Dogfooding

真实使用一段时间。

先不要急着继续新增复杂学习算法。

---

# 114. 完成标准

v1.4.7 完成后必须做到：

```text
朝汐可以查暗苟明确的 User Principles
朝汐可以记录真实 Choice History
历史 Decision 可以获得结果反馈
支持 GOOD / BAD / NEUTRAL / MIXED / NO_DIFFERENCE / UNKNOWN
值得的 Decision 可以自然回访
Feedback 后可以后台 Reflection
Reflection 可以形成 / 修正 Decision Journal
Decision Journal 是朝汐自己的判断经验
User Principles 与 Decision Journal 明确分离
Choice History 与 Journal 明确分离
Decision Context 可以按需读取 Journal / Principles
普通 PICK 不受性能影响
Decision Learning 不依赖 Desktop / QQ / 手机端
```

---

# 115. 理想长期体验

暗苟：

```text
下午去打舞萌还是继续窝着？
```

朝汐不是只看今天。

她可能已经知道：

```text
前几次类似情况下
继续窝着 → BAD
出去 → GOOD
```

但她也检查：

```text
今天晚上没有硬 deadline
```

于是：

```text
“去打舞萌吧。你这种状态继续窝着，前几次都没推进出什么，出去玩一轮反而回来更舒服。”
```

过一晚：

```text
“昨天那轮后来感觉怎么样？”
```

暗苟：

```text
“挺好，回来精神好多了。”
```

朝汐：

```text
“那我记住这种情况啦。”
```

后台不是写：

```text
RULE: LOW_ENERGY → MAIMAI
```

而是更新：

```text
Decision Journal：

低精力、无紧急 deadline、
并且已经在寝室低效一段时间时，
优先让暗苟出去活动，通常效果更好。

confidence ↑
```

---

# 116. 一句话总结

v1.4.6 让朝汐开始：

> **“我觉得暗苟应该这么做。”**

v1.4.7 要让她继续学会：

> **“上次我也是这么想的，后来效果很好。看来这种时候，我以后可以更果断一点。”**

这不是规则引擎。

这是长期相处之后，女仆长慢慢长出来的判断经验。
