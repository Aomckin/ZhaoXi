# Zhaoxi v1.4.5 · Dashboard & Control Plane
## 可观测反馈、行为调试、Presence 参数控制与 Current Cognition 编辑开发任务书

> 项目：**Zhaoxi / 朝汐**\
> 版本：**v1.4.5**\
> 类型：**Dashboard Split / Runtime Control Plane / Human-readable Feedback**
>
> 核心主题：
>
> > **把“能看见朝汐内部发生了什么”，升级成“能直观看懂、能调、能纠正”。**
>
> 本版不再扩张 Memory / Planner / Presence 的底层能力，重点是：
>
> 1. 把 Debug / 管理设施从“小桌边”拆到独立 Dashboard；
> 2. 给 Internal Activity / Debug 操作补上真正的人类可读反馈；
> 3. 把 Presence、Heartbeat、活动权限与关键调度参数做成可调 Control Plane；
> 4. 允许 Owner 直接管理 Current Cognition，而不是只能被动等模型修正；
> 5. 保持原始 JSON / Runtime Trace 作为二级工程信息，不让它继续充当主要交互反馈。

---

# 0. 当前基线

v1.4.4 已完成：

```text
Presence 2.0
Internal Activity Registry
五态 Presence
前台抢占
FAST Conversation Digest
Current Cognition Gardening
Memory Gardening
Cluster Gardening
Memory Reminiscence
Social Lurk
Social Wander
群聊历史搜索与旧消息回查
```

当前代码侧已经拥有：

```text
/api/debug/runtime
/api/debug/memory-retrieval
/api/debug/memory-clusters
/api/debug/database-maintenance
/api/debug/cognitive-stream
/api/debug/provenance
/api/debug/decision
/api/debug/internal-activity
/api/debug/presence
/api/debug/budget-context
/api/debug/tools/*
/api/recent-context
/api/settings/*
```

v1.4.5 **不重复开发这些能力**。

本版主要处理三个现状问题：

```text
A. 小桌边职责过载
B. 调试操作缺乏反馈感
C. Runtime / Presence 可调参数太少
```

当前 Internal Activity 手动调试的典型体验：

```text
点击：
“整理认知结构”

↓
等待

↓
下面出现一大段 JSON

{
  "current_presence": "SEMI_ACTIVE",
  "last_activity": {
    "name": "cognition_gardening",
    "status": "NO_CHANGE",
    ...
  }
}
```

对开发排错有用，但对真实使用很差。

v1.4.5 要变成：

```text
🌱 近期状态整理完成

没有发现需要合并、淡出或移除的内容。
本次未修改任何状态。

无变化 · 0.8 秒 · 本地轻量任务

[查看技术详情]
```

---

# 1. 版本目标

v1.4.5 统一围绕三个词：

```text
Observe
Control
Correct
```

## 1.1 Observe

暗苟无需阅读 JSON，就能知道：

```text
朝汐现在是什么 Presence
她刚刚执行了什么 Activity
有没有实际产生变化
改了什么
为什么没做
为什么失败
用了多少资源
是否向外部发言
```

## 1.2 Control

允许从 Dashboard 调节：

```text
Heartbeat 间隔
ACTIVE 持续时间
SEMI_ACTIVE 持续时间
Presence 自动切换参数
各 Presence 允许的 Activity
Activity 自动 / 手动权限
Activity 最短间隔
Activity 预算
Social Lurk / Wander 权限与限额
```

## 1.3 Correct

允许 Owner 对 Current Cognition 做人工修正：

```text
新增
编辑
置顶
锁定
淡出
标记已解决
删除
合并 Thread
调整 Watch Item / Recent Change
查看人工修改历史
撤销最近修改
```

---

# 2. 非目标

本版明确 **不做**：

```text
不重构 Memory 3.0
不重构 Retrieval
不继续深挖 Memory Graph
不重写 Internal Activity Scheduler
不新增复杂人格成长系统
不做长期自主规划
不做手机端
不做微信插件
不重写 QQ 插件
不重构 Fast Gate
不改 Planner 主链
不顺手改 LifeHUD API
不做大规模视觉换皮
```

Sunflower Garden 视觉统一继续留给 v1.4.6。

v1.4.5 可以为了 Dashboard 做基础布局，但不要提前把视觉重构做完。

---

# 3. Dashboard Split

新增独立 Dashboard。

建议路径：

```text
/dashboard
```

主界面继续：

```text
/
```

原则：

```text
小桌边 = 朝汐本人 + 生活相关轻信息

Dashboard = 管理 / 调试 / 观察 / 控制
```

---

# 4. 小桌边保留内容

小桌边只保留：

```text
朝汐本人
Presence
当前 Activity
朝汐留下的话
Agenda
Current Cognition 轻量摘要
少量 LifeHUD 摘要
自然交互
```

逐步移出：

```text
ActionTrace
Runtime Debug
Memory Inspector
Memory Cluster Debug
Database Maintenance
Planner Debug
Budget / Context Debug
Tool Cabinet
Presence Debug
Internal Activity Debug
Perception Debug
Cognitive Stream Debug
Provenance Inspector
Emoji Debug
Decision Debug
External Sources 管理
开发设置
```

---

# 5. Dashboard 信息架构

建议：

```text
Dashboard
│
├─ Overview
│   ├─ Core 状态
│   ├─ 当前 Presence
│   ├─ 当前 Activity
│   ├─ Heartbeat
│   ├─ 最近活动
│   └─ Runtime 简报
│
├─ Presence
│   ├─ Presence Timing
│   ├─ Heartbeat
│   ├─ 自动状态切换
│   ├─ 强制 Presence
│   └─ Presence × Activity 权限矩阵
│
├─ Activity
│   ├─ Activity Registry
│   ├─ 手动执行
│   ├─ 自动 / 手动权限
│   ├─ Cooldown / Interval / Budget
│   └─ 最近活动历史
│
├─ Cognition
│   ├─ Current Cognition Editor
│   ├─ Current Cognition History
│   ├─ FAST Digest
│   ├─ Cognitive Stream
│   └─ Provenance
│
├─ Memory
│   ├─ Retrieval Inspector
│   ├─ Cluster Inspector
│   ├─ Memory Gardening
│   └─ Database Maintenance
│
├─ Runtime
│   ├─ Runtime Observatory
│   ├─ ActionTrace
│   ├─ Planner
│   ├─ Budget / Context
│   └─ Tool Trace
│
├─ Capability
│   ├─ Tool Cabinet
│   ├─ External Sources
│   ├─ Emoji
│   └─ Social Controls
│
└─ Settings
    ├─ Interface
    ├─ Model / Thinking
    ├─ Presence
    ├─ Internal Activity
    └─ Advanced Debug
```

---

# 6. P0：Human-readable Action Feedback

这是 v1.4.5 的 P0。

任何用户主动点击的调试行为，都不能只返回 JSON。

## 6.1 统一 Action Receipt

新增统一结果模型，建议：

```python
ActionReceipt:
    action_id
    activity_name
    title
    phase
    status
    changed
    summary
    details
    metrics
    side_effects
    warnings
    error
    started_at
    finished_at
    duration_ms
    raw_payload
```

建议状态：

```text
QUEUED
RUNNING
SUCCESS
NO_CHANGE
SKIPPED
BLOCKED
FAILED
CANCELLED
```

---

# 7. Action Feedback UI

每次手动执行：

```text
点击按钮
↓
立刻出现执行中状态
↓
执行完成
↓
展示自然语言回执
↓
原始 JSON 折叠在“技术详情”
```

示例：

```text
🌱 近期状态整理完成

检查了 5 个 Thread。
没有发现需要合并、淡出或移除的内容。

无变化 · 812 ms · LOCAL_LIGHT

[查看技术详情]
```

有修改时：

```text
🧠 长期记忆整理完成

检查 18 条记忆：
· 合并重复项 2 条
· 标记冲突 1 条
· 降温 3 条

已产生 6 项修改 · 1.7 秒

[查看修改]
[技术详情]
```

失败时：

```text
⚠ 长期记忆整理失败

Embedding Provider 暂时不可用。
本次没有写入 Memory。

可重试 · 失败阶段：candidate_generation

[重试]
[技术详情]
```

---

# 8. Action Receipt 不得依赖 LLM 生成

反馈必须优先由 Runtime 的结构化结果生成。

禁止：

```text
每次 Debug 操作
→ 再调用一个 LLM
→ 解释刚才发生了什么
```

避免额外延迟、费用与幻觉。

建议：

```text
Activity Result
↓
Receipt Builder
↓
模板 + 结构化字段
↓
Human-readable Receipt
```

必要时才允许 Activity 自己提供 summary。

---

# 9. 后台 Activity 也进入 Recent Activity

不只是手动调试。

自动执行的 Internal Activity 也进入统一 Activity History。

Dashboard Overview 展示：

```text
10:29 🌱 整理近期状态
      没有需要调整的内容

10:17 🧠 整理长期记忆
      合并 1 条重复记忆

09:52 🐾 围观群聊
      查看 23 条消息，未发言

09:31 📖 翻旧日记
      重温 1 条旧记忆，建立 1 条关联
```

Activity History 至少记录：

```text
activity
trigger = AUTO / MANUAL / DEBUG
presence
status
changed
summary
cost
duration
message_sent
external_io
timestamp
```

---

# 10. Presence Timing Control

这是本版新增的关键调试能力。

目前五态：

```text
ACTIVE
SEMI_ACTIVE
IDLE
AWAY
SLEEP
```

v1.4.5 至少允许调：

```text
ACTIVE 持续时间
SEMI_ACTIVE 持续时间
Heartbeat 间隔
```

---

# 11. ACTIVE 持续时间

定义：

> Owner 前台交互结束后，朝汐继续保持 ACTIVE 的最短驻留时间。

建议配置：

```text
active_hold_seconds
```

例：

```text
Owner 最后一轮消息完成
↓
ACTIVE 保持 120 秒
↓
若期间没有新前台活动
↓
SEMI_ACTIVE
```

注意：

```text
正在执行前台任务时
ACTIVE 不受 hold 到期影响

新的 Owner 输入
立即刷新 ACTIVE hold

强制 Debug Presence
覆盖自动计时
```

Dashboard：

```text
ACTIVE 持续时间
[ 120 秒 ]

最近一次前台交互：38 秒前
预计转入 SEMI_ACTIVE：约 82 秒后
```

---

# 12. SEMI_ACTIVE 持续时间

定义：

> ACTIVE 结束后，朝汐保持“醒着、有空”的时间窗口。

建议配置：

```text
semi_active_hold_seconds
```

例：

```text
ACTIVE
↓ 120s
SEMI_ACTIVE
↓ 20min
IDLE
```

Dashboard：

```text
SEMI_ACTIVE 持续时间
[ 20 分钟 ]

当前已半活跃：6 分 12 秒
预计进入 IDLE：约 13 分 48 秒后
```

---

# 13. Presence Transition Debug

Dashboard 必须能实时展示：

```text
当前 Presence
进入时间
已持续多久
下一状态
预计切换时间
切换原因
```

例如：

```text
当前：SEMI_ACTIVE
已持续：06:12
下一状态：IDLE
预计：13:48 后
原因：Owner 前台交互结束，ACTIVE hold 已到期
```

---

# 14. Presence 时间调节范围

建议 UI 做合理范围限制，不直接裸露无限数字。

例如：

```text
ACTIVE
5 秒 ~ 30 分钟

SEMI_ACTIVE
30 秒 ~ 6 小时

Heartbeat
5 秒 ~ 30 分钟
```

实际默认值沿用现有 Runtime 行为或当前配置，不强制迁移成建议值。

任何修改：

```text
必须持久化
必须可恢复默认
必须立即显示当前生效值
必须明确“立即生效 / 下次状态周期生效”
```

---

# 15. Heartbeat Control

允许：

```text
Heartbeat 总开关
基础 Heartbeat 间隔
不同 Presence 的 Heartbeat multiplier / interval
```

推荐 UI：

```text
Heartbeat
[开启]

ACTIVE       30 秒
SEMI_ACTIVE  60 秒
IDLE         3 分钟
AWAY         10 分钟
SLEEP        30 分钟
```

如果底层当前只有一个统一 Heartbeat：

```text
第一阶段可以先支持 base interval
+
Presence multiplier
```

禁止为了 UI 完整性重写整个 Scheduler。

---

# 16. Heartbeat Debug 信息

Overview 显示：

```text
上次 Heartbeat
下次预计 Heartbeat
当前 interval
最近一次 tick 结果
本次选中了哪些 Activity
哪些 Activity 被 skip
skip 原因
```

示例：

```text
Heartbeat · 27 秒前

下一次：约 33 秒后

上次结果：
✓ cognition_gardening
- memory_reminiscence：cooldown
- social_lurk：当前 Presence 不允许
```

---

# 17. Presence × Activity 权限矩阵

这是 v1.4.5 的核心 Control Plane。

建议 UI：

```text
                   ACTIVE  SEMI  IDLE  AWAY  SLEEP
FAST Digest          ●      ●     ●     ×      ×
Cognition Garden     ●      ●     ●     ×      ×
Memory Garden        ◐      ●     ●     ◐      ×
Cluster Garden       ◐      ●     ●     ×      ×
Reminiscence         ×      ●     ●     ×      ×
Agenda               ●      ●     ●     ●      ●
Proactive Check      ●      ●     ●     ●      ●
Social Lurk          ×      ●     ●     ×      ×
Social Wander        ×      ●     ×     ×      ×
```

三态而不是简单 Boolean：

```text
AUTO
MANUAL_ONLY
DISABLED
```

含义：

```text
AUTO
→ Scheduler 可自动选中，也允许手动执行

MANUAL_ONLY
→ 自动 Scheduler 不选，但 Dashboard 可以手动执行

DISABLED
→ 自动与手动都拒绝
```

---

# 18. Activity Config

每个 Activity 至少允许查看：

```text
category
cost_class
priority
min_interval
cooldown
requires_llm
requires_external_io
can_message_user
can_message_external
presence policy
```

可调参数第一阶段建议只开放：

```text
启用状态
AUTO / MANUAL_ONLY / DISABLED
priority
min_interval
daily budget
presence policy
```

高级内部字段先只读。

不要一次性把所有 Registry 字段都变成旋钮。

---

# 19. Activity Budget Control

允许调：

```text
每 Tick Activity 上限
每 Tick LLM Activity 上限
每日 LLM Activity 上限
每日 External Read 上限
每日 External Write 上限
每日 Social Wander 发言上限
```

UI 必须显示：

```text
今日已用 / 总预算
```

例如：

```text
LLM Activity
3 / 12

External Read
7 / 50

Social Write
0 / 3
```

---

# 20. Social Control

继续保持 v1.4.4 的安全原则：

```text
Social Wander 默认 OFF
明确群白名单
Privacy Gate
Group Cooldown
Daily Budget
actor_role = SELF
External Provenance
```

Dashboard 增加：

```text
Social Lurk 开关
Social Wander 开关
授权群列表
每群 cooldown
每日发言预算
最近一次 Lurk / Wander
最近一次拒绝原因
```

禁止 Dashboard 的便捷性绕过现有安全边界。

---

# 21. Current Cognition Editor

这是 v1.4.5 的另一个 P0。

Current Cognition 结构：

```text
Overview
Threads
Recent Changes
Watch Items
```

Dashboard 中提供真正的编辑器。

---

# 22. Current Cognition 编辑能力

至少支持：

```text
Overview
- 编辑
- 恢复自动生成

Threads
- 新增
- 编辑
- 置顶
- 锁定
- 合并
- 标记 resolved
- 淡出
- 删除

Recent Changes
- 新增
- 编辑
- 删除

Watch Items
- 新增
- 编辑
- 完成
- 删除
```

---

# 23. 人工修改必须是一等状态

禁止：

```text
直接 UPDATE SQLite 文本
```

否则 Maintainer 下一轮可能把内容重新长回来。

建议人工变更带：

```python
source = "OWNER_MANUAL"
manual_state
manual_revision
updated_by = "owner"
updated_at
```

建议状态：

```text
NORMAL
PINNED
LOCKED
RESOLVED
DISMISSED
```

---

# 24. PINNED / LOCKED 语义

## PINNED

```text
优先保留
排序靠前
Maintainer 可补充，但不能自动淡出
```

## LOCKED

```text
Owner 手工确定内容
Maintainer 不允许自动改写正文
可引用
可判断 stale
但必须请求 Owner 或产生建议，而不是直接覆盖
```

---

# 25. RESOLVED / DISMISSED

## RESOLVED

表示：

```text
事情确实完成 / 不再需要持续跟踪
```

从活跃 Current Cognition 退出，但保留历史。

## DISMISSED

表示：

```text
Owner 明确认为这条不该继续存在
```

为了防止“打地鼠”：

```text
同一旧证据
在一个抑制窗口内
不得重新生成等价 Thread
```

建议维护：

```text
dismissed_fingerprint
dismissed_until
source_evidence_refs
```

---

# 26. Current Cognition 修改历史

所有手工修改写 revision log：

```text
revision_id
target_type
target_id
operation
before
after
actor
timestamp
```

Dashboard 可查看：

```text
刚刚：
暗苟将「项目工程理解」标记为 resolved

昨天：
暗苟锁定「秋招主线」
```

第一阶段至少支持：

```text
撤销最近一次 Owner Manual 修改
```

---

# 27. Cognition Maintainer Guard

Maintainer 必须尊重：

```text
PINNED
LOCKED
RESOLVED
DISMISSED
```

禁止：

```text
模型一次维护
→ 把 Owner 锁定内容覆盖掉
```

建议维护结果增加：

```text
manual_guard_hits
manual_guard_skips
```

便于 Debug。

---

# 28. Dashboard Overview

首页不要是一堆 Debug 折叠框。

必须先回答：

```text
朝汐现在怎样？
刚刚做了什么？
系统有没有异常？
```

推荐首屏：

```text
朝汐
SEMI_ACTIVE · 发呆中

Presence 已持续 06:12
预计 13:48 后进入 IDLE

Heartbeat：27 秒前
下一次：约 33 秒后

今日内部活动：17
产生修改：5
LLM 活动：3
外部发言：0
```

下面：

```text
最近活动
Runtime Health
Cognition 摘要
Memory 摘要
Plugin 状态
```

---

# 29. Dashboard 与 Engineering Layer

人类层与工程层分开。

## Living / Control Layer

默认展示：

```text
当前状态
活动反馈
控制参数
近期认知
历史活动
```

## Engineering Layer

折叠或二级页：

```text
原始 JSON
Trace
Provider Payload 摘要
Runtime Metrics
Memory Candidate
Provenance
Database Diagnostics
```

---

# 30. 原始 JSON 继续保留

原始 JSON 不删。

要求：

```text
所有 Action Receipt
都有“技术详情”

技术详情
→ 原始 Runtime Payload / JSON
```

这样：

```text
普通使用
不需要读 JSON

排错
仍然可以看完整数据
```

---

# 31. Settings 持久化

新增所有可调项必须明确持久化位置。

优先：

```text
Runtime settings store
SQLite / JSON config layer
```

不要要求：

```text
手工编辑 .env
重启才能生效
```

除非底层参数确实只能启动时加载。

Dashboard 必须区分：

```text
立即生效
下次 Tick 生效
下次 Presence Transition 生效
需要 Core 重启
```

---

# 32. 配置来源优先级

建议：

```text
Owner Runtime Override
↓
Persistent Dashboard Settings
↓
.env
↓
Code Default
```

Debug 临时 override 必须可：

```text
恢复默认
```

---

# 33. Presence Debug

保留已有：

```text
Force ACTIVE
Force SEMI_ACTIVE
Force IDLE
Force AWAY
Force SLEEP
```

增强：

```text
当前强制状态
强制开始时间
已持续时间
恢复自动
自动状态下的下一状态预测
```

手动 Force Presence 时：

```text
Presence transition timer 暂停
```

恢复自动后：

```text
重新根据当前最近交互时间计算
```

避免旧 timer 立即把状态弹走。

---

# 34. Presence Timing Debug 快捷区

新增快速测试模式：

```text
快速测试 Presence Transition
```

例如临时设置：

```text
ACTIVE = 10 秒
SEMI_ACTIVE = 20 秒
Heartbeat = 5 秒
```

用于观察：

```text
ACTIVE
↓
SEMI_ACTIVE
↓
IDLE
```

无需改 `.env`。

快捷区必须明显标记：

```text
DEBUG OVERRIDE
```

并支持：

```text
一键恢复正常配置
```

---

# 35. Manual Activity Execution

所有 Registry Activity 都应在 Dashboard 可见。

允许：

```text
手动执行
查看上次执行
查看上次状态
查看 cooldown
查看下一次自动可运行时间
```

如果 MANUAL_ONLY：

```text
手动按钮可用
自动调度不选
```

如果 DISABLED：

```text
按钮禁用
并说明原因
```

---

# 36. Activity Skip Feedback

Scheduler skip 原因必须人类可读。

例如：

```text
memory_reminiscence
跳过：距离上次执行仅 12 分钟
还需等待约 48 分钟

social_lurk
跳过：当前 Presence = ACTIVE，不允许自动围观群聊

memory_gardening
跳过：本 Tick LLM 预算已用尽
```

不要只显示：

```text
"reason": "cooldown"
```

---

# 37. 当前 Activity 实时反馈

Presence 与 Activity 分离：

```text
Presence
= 她目前处于什么生活状态

Activity
= 她此刻正在做什么
```

主界面继续显示轻量：

```text
半活跃 · 在整理记忆
```

Dashboard 展示详细：

```text
Activity：
Memory Gardening

开始于：10:17:03
已运行：1.2s
成本：LLM_LIGHT
触发：AUTO
```

---

# 38. 状态完成后的反馈保留

Activity 完成后不能立即消失。

Dashboard 至少保留：

```text
最近 50 ~ 200 条
```

具体数量可配置或固定一个合理上限。

主界面只需要：

```text
短暂显示最近一次结果
```

例如几秒后淡出。

---

# 39. API 建议

不要求必须完全按以下命名，但功能需要完整。

## Settings

```text
GET  /api/settings/presence
PUT  /api/settings/presence

GET  /api/settings/internal-activity
PUT  /api/settings/internal-activity
```

## Presence

```text
GET  /api/presence/status
POST /api/debug/presence
POST /api/debug/presence/reset
```

## Activity

```text
GET  /api/internal-activity/registry
GET  /api/internal-activity/history
POST /api/internal-activity/{name}/run
PUT  /api/internal-activity/{name}/config
```

## Current Cognition

```text
GET    /api/current-cognition
PATCH  /api/current-cognition/overview

POST   /api/current-cognition/thread
PATCH  /api/current-cognition/thread/{id}
DELETE /api/current-cognition/thread/{id}

POST   /api/current-cognition/watch
PATCH  /api/current-cognition/watch/{id}
DELETE /api/current-cognition/watch/{id}

GET    /api/current-cognition/revisions
POST   /api/current-cognition/revisions/{id}/undo
```

现有 API 能复用的优先复用。

---

# 40. 不允许的 API 设计

避免：

```text
POST /api/debug/raw-sql
POST /api/debug/set-any-config
POST /api/debug/cognition-overwrite-all
```

Control Plane 必须经过领域层。

---

# 41. Activity Receipt API

建议所有手动 Activity 返回：

```json
{
  "receipt": {
    "title": "近期状态整理完成",
    "status": "NO_CHANGE",
    "changed": false,
    "summary": "没有发现需要合并、淡出或移除的内容。",
    "duration_ms": 812,
    "cost_class": "LOCAL_LIGHT"
  },
  "raw": {}
}
```

前端默认消费：

```text
receipt
```

Debug 才展示：

```text
raw
```

---

# 42. SSE / 实时事件

已有 SSE 可以扩展：

```text
activity_started
activity_progress
activity_finished
presence_transition
heartbeat_tick
```

至少确保：

```text
手动 Activity
点击后立即有 RUNNING 反馈
```

不要等请求完成才第一次更新 UI。

---

# 43. Failure Isolation

Dashboard 调试操作不能拖垮主聊天。

例如：

```text
Memory Gardening Debug 失败
≠
Chat API 失败
```

要求：

```text
独立错误边界
独立 timeout
独立 receipt
```

---

# 44. 前台抢占保持

v1.4.4 已有 Foreground Preemption。

v1.4.5 调参数时不能破坏：

```text
Owner 新输入
→ 可中断低优先级后台活动
→ 前台优先
```

Dashboard 显示：

```text
Activity CANCELLED
原因：Owner foreground preemption
```

---

# 45. Activity 权限与安全

手动执行也不能绕过：

```text
Privacy Gate
External Provenance
Social whitelist
Daily Budget
Tool permission
External Source boundary
```

“Debug”不是超级管理员后门。

---

# 46. UI 交互要求

所有可调参数必须做到：

```text
看得懂当前值
知道默认值
知道是否已修改
知道什么时候生效
可以恢复默认
```

避免：

```text
一个数字输入框
旁边没有单位
```

必须明确：

```text
120 秒
20 分钟
3 次 / 日
```

---

# 47. 数值输入保护

需要：

```text
min
max
step
clamp
validation
```

异常值不能：

```text
NaN
Infinity
负数
0 秒高频死循环
```

Heartbeat 尤其要限制过低频率。

---

# 48. Preset

可选做三个轻量 Preset：

```text
安静
正常
活跃
```

只覆盖：

```text
Presence Timing
Heartbeat
Activity Budget
```

不要覆盖：

```text
Social Wander 白名单
Privacy 设置
Owner Manual Cognition
```

Preset 必须展示将修改哪些值。

---

# 49. Debug Preset

开发调试可以单独有：

```text
快速 Presence 测试
```

例如：

```text
ACTIVE 10s
SEMI_ACTIVE 20s
Heartbeat 5s
```

必须明确：

```text
仅 Debug Override
```

并一键退出。

---

# 50. 数据迁移

优先设计为：

```text
无需离线 Memory Migration
```

如新增 Runtime Settings / Cognition Revision：

```text
创建独立表
向后兼容
默认值读取现有行为
```

不要修改现有 Memory 数据语义。

---

# 51. 兼容性

必须保持：

```text
旧配置未设置新字段
→ 行为不变

Dashboard 未打开
→ Runtime 正常工作

前端旧缓存
→ 至少有版本检查或刷新提示

Internal Activity disabled
→ Dashboard 给出明确不可用状态
```

---

# 52. 测试要求

至少增加：

```text
tests/web/dashboard_*.test.cjs
tests/internal_activity/test_presence_settings.py
tests/internal_activity/test_activity_policy.py
tests/internal_activity/test_activity_receipt.py
tests/current_cognition/test_manual_editor.py
tests/current_cognition/test_manual_guard.py
```

---

# 53. Presence Timing 测试

覆盖：

```text
Owner 输入刷新 ACTIVE timer
ACTIVE hold 到期 → SEMI_ACTIVE
SEMI_ACTIVE hold 到期 → IDLE
新 Owner 输入立即回 ACTIVE
Force Presence 暂停自动切换
恢复自动后重新计算
修改 ACTIVE duration 后正确生效
修改 SEMI_ACTIVE duration 后正确生效
Heartbeat interval 修改正确生效
```

---

# 54. Activity Matrix 测试

覆盖：

```text
AUTO
MANUAL_ONLY
DISABLED
```

组合：

```text
不同 Presence
不同 Activity
自动 Scheduler
手动 Debug
```

确保 MANUAL_ONLY：

```text
不会被自动选中
但手动可执行
```

---

# 55. Current Cognition Manual Guard 测试

必须覆盖：

```text
PINNED 不被自动淡出
LOCKED 不被自动覆盖
RESOLVED 不再进入活跃 Thread
DISMISSED 不被旧证据立即重新生成
Owner Manual revision 可追踪
undo 可恢复
```

---

# 56. Action Feedback 测试

每种结果至少一个：

```text
SUCCESS
NO_CHANGE
SKIPPED
BLOCKED
FAILED
CANCELLED
```

UI 不得要求读取 raw JSON 才知道结果。

---

# 57. Dashboard 人工验收场景 A

打开 Dashboard。

应在 3 秒内看懂：

```text
当前 Presence
当前 Activity
Heartbeat 状态
最近一次 Activity
Core 是否健康
```

---

# 58. 人工验收场景 B

点击：

```text
整理认知结构
```

应：

```text
立即显示“正在整理”
↓
完成
↓
明确显示“有变化 / 无变化”
↓
显示发生了什么
```

原始 JSON 必须折叠。

---

# 59. 人工验收场景 C

将：

```text
ACTIVE = 10 秒
SEMI_ACTIVE = 20 秒
Heartbeat = 5 秒
```

观察：

```text
ACTIVE
↓
SEMI_ACTIVE
↓
IDLE
```

Dashboard 倒计时 / 预计切换必须合理更新。

然后：

```text
一键恢复正常配置
```

---

# 60. 人工验收场景 D

将：

```text
memory_reminiscence
SEMI_ACTIVE = AUTO
ACTIVE = MANUAL_ONLY
```

验收：

```text
ACTIVE 时 Scheduler 不自动执行
ACTIVE 时手动按钮可执行

SEMI_ACTIVE 时 Scheduler 可自动执行
```

---

# 61. 人工验收场景 E

编辑 Current Cognition：

```text
把某 Thread 标记 LOCKED
```

触发一次 Cognition Gardening。

必须：

```text
LOCKED 文本不被自动改写
```

---

# 62. 人工验收场景 F

删除 / Dismiss 一个错误 Thread。

继续使用若干轮。

必须：

```text
同一批旧证据
不能立刻重新生成等价 Thread
```

---

# 63. 人工验收场景 G

Social Wander 保持 OFF。

Dashboard 操作其它 Activity。

必须确认：

```text
不会发生外部写消息
```

随后仅在显式授权测试群中单独验证 Social。

---

# 64. 性能要求

Dashboard 本身不能让主聊天变慢。

要求：

```text
Debug 数据按需加载
Inspector 不默认全量查询
Activity History 分页
Current Cognition Revision 分页
Memory Inspector 延迟加载
```

不要首页启动：

```text
十几个 Debug API 并发全打
```

---

# 65. 前端拆分要求

当前 `index.html` / 前端逻辑已经偏重。

v1.4.5 应顺势拆模块。

建议：

```text
dashboard.html
dashboard.js
dashboard.css

dashboard/
  overview.js
  presence.js
  activity.js
  cognition.js
  memory.js
  runtime.js
  settings.js
```

不强制完全按此目录，但禁止继续把所有 Dashboard 逻辑塞回 `index.html`。

---

# 66. 后端拆分建议

`web/app.py` 已较大。

v1.4.5 可以做**最小必要路由拆分**：

```text
dashboard routes
settings routes
debug routes
```

但不要借机做全量 Web Backend 重构。

原则：

```text
为了 v1.4.5 可维护性而拆
≠
重写整个 FastAPI 层
```

---

# 67. 文档要求

新增：

```text
docs/v1.4.x/
  Zhaoxi_v1.4.5_Dashboard_Control_Plane_Task.md
  Zhaoxi_v1.4.5_开发记录.md
  Zhaoxi_v1.4.5_Release_Notes.md
```

更新：

```text
docs/current/CURRENT_STATUS.md
docs/current/CODEBASE_STATUS.md
README（仅在确实需要时）
```

---

# 68. Debug 文案原则

尽量使用：

```text
正在做什么
做完了吗
有没有变化
变了什么
为什么没做
```

少用只有开发者才懂的：

```text
NO_CHANGE
LOCAL_LIGHT
cooldown
policy_denied
```

这些术语可以保留在二级详情。

---

# 69. Activity Receipt 示例集合

## NO_CHANGE

```text
🌱 近期状态整理完成

当前结构很干净，
没有需要合并、淡出或移除的内容。

无变化 · 812 ms
```

## CHANGED

```text
🧠 长期记忆整理完成

处理了 18 条候选：
合并 2 条重复记忆
标记 1 条冲突
降温 3 条

6 项变化 · 1.7 秒
```

## SKIPPED

```text
📖 这次没有翻旧日记

距离上次重温还太近，
约 42 分钟后才会重新进入候选。

已跳过
```

## BLOCKED

```text
🐾 没有去群里发言

Social Wander 当前关闭。

未发生外部写入
```

## CANCELLED

```text
🧠 记忆整理中止

暗苟发来了新消息，
后台活动已让路给前台对话。

没有未完成写入
```

---

# 70. 最终完成标准

v1.4.5 不能只以：

```text
Dashboard 页面能打开
```

作为完成。

必须同时满足：

### Dashboard Split

```text
Debug / 管理内容离开小桌边
小桌边恢复轻量生活界面
Dashboard 职责清晰
```

### Feedback

```text
手动 Activity 不读 JSON 也能理解结果
后台 Activity 有最近活动历史
失败 / 跳过 / 无变化都有明确反馈
```

### Control

```text
Heartbeat 可调
ACTIVE 持续时间可调
SEMI_ACTIVE 持续时间可调
Presence 自动状态可观察
Activity × Presence 权限可调
Activity 关键 interval / budget 可调
```

### Correct

```text
Current Cognition 可人工编辑
人工状态不会被 Maintainer 轻易覆盖
有 revision history
至少支持最近一次 undo
```

### Safety

```text
Social 默认安全边界不变
Debug 不绕过 Privacy / Provenance / Budget
Foreground Preemption 不回归
```

---

# 71. 推荐开发顺序

## Phase 1 · Dashboard Shell

```text
/dashboard
导航
Overview
从小桌边迁移第一批 Debug
```

先完成职责拆分，不改 Runtime。

## Phase 2 · Action Receipt

```text
统一 Receipt Model
Receipt Builder
Activity History
手动 Debug 反馈
SSE RUNNING / FINISHED
```

完成“反馈感”。

## Phase 3 · Presence Control

```text
Heartbeat
ACTIVE hold
SEMI_ACTIVE hold
Presence transition status
快速 Debug override
```

## Phase 4 · Activity Control Plane

```text
Presence × Activity Matrix
AUTO / MANUAL_ONLY / DISABLED
priority / min_interval / budget
```

## Phase 5 · Current Cognition Editor

```text
CRUD
PINNED
LOCKED
RESOLVED
DISMISSED
revision
undo
Maintainer Guard
```

## Phase 6 · Engineering Layer Migration

```text
Runtime
Memory
Planner
Provenance
Tool
Decision
Perception
Social
```

全部从小桌边收进 Dashboard。

## Phase 7 · Dogfooding & Cleanup

至少真实使用：

```text
Presence 自动切换
后台 Activity
Current Cognition 人工纠错
手动 Gardening
Social Lurk
```

修复真实反馈问题。

---

# 72. 本版核心 UX 验收语句

开发过程中可以反复问：

> **暗苟现在能不能不看 JSON，就知道朝汐刚才实际做了什么？**

以及：

> **暗苟能不能直接告诉朝汐“你多久算活跃、多久算半活跃、空闲时可以做什么、最近这件事你记错了”？**

两个答案都必须是：

```text
可以。
```

---

# 73. 一句话总结

v1.4.4 让朝汐开始拥有：

> **两次对话之间的时间。**

v1.4.5 要补上的，是暗苟与这套自主系统之间真正可用的控制界面：

> **看得懂她做了什么，调得动她怎么活动，发现她记错时也能直接修正。**
