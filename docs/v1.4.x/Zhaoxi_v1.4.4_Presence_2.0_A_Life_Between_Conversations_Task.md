# Zhaoxi v1.4.4 · Presence 2.0 / A Life Between Conversations
## 内部活动、记忆整理、历史重温与外界闲逛开发任务书

> 项目：**Zhaoxi / 朝汐**
> 版本：**v1.4.4**
> 类型：**Presence / Internal Activity Runtime 重构版本**
>
> 核心主题：
>
> > **让朝汐在两次对话之间，也拥有自己的轻量生活。**
>
> 本版不推倒 v1.2.8 Internal Activity Runtime，而是在它上面升级成真正的 Presence Runtime。

---

# 0. 版本目标

v1.2.8 已经完成了：

```text
Semi-Active Tick
→ InternalActivityRuntime
→ ActivityScheduler
→ 选择值得执行的 Activity
→ 执行
→ 记录结果
```

已有活动：

```text
Current Cognition Consolidation
Memory Maintenance
Agenda Maintenance
Perception Cognition
Proactive Check
```

已有能力：

```text
persistent state
dirty / cooldown / priority
failure backoff
per-tick budget
manual debug trigger
silent background execution
```

v1.4.4 不重写这些基础。

本版要解决的是：

```text
后台维护任务
→ 升级成
朝汐自己的空闲活动
```

---

# 1. Presence 2.0 状态模型

建议：

```text
ACTIVE
SEMI_ACTIVE
IDLE
AWAY
SLEEP
```

## ACTIVE

```text
正在与暗苟交互
正在执行当前任务
正在处理明确外部 Trigger
```

前台优先，后台活动让路。

## SEMI_ACTIVE

```text
暗苟暂时没找她
但朝汐还醒着、有一点空闲
```

这是 v1.4.4 主要活动窗口。

允许：

```text
整理 Current Cognition
整理长期 Memory
维护 Cluster
消化 FAST 闲聊
重温历史记忆
核对 Agenda
观察外界
偶尔水群
Proactive Check
```

## IDLE

```text
没什么正事
也没有高优先级内部任务
```

允许：

```text
轻量本地活动
低频 Reminiscence
低频 Social Lurk
发呆
```

## AWAY

只允许：

```text
必要 Agenda reconciliation
极轻本地维护
重要提醒
```

禁止普通 Leisure Social。

## SLEEP

只允许：

```text
deadline
urgent reminder
极轻本地维护
```

---

# 2. Activity ≠ Message

继续坚持：

```text
获得一次 Activity Opportunity
≠
一定发送消息
```

例如：

```text
翻旧记忆
→ 不说话

整理 Cluster
→ 不说话

看群聊两分钟
→ 没兴趣
→ 不说话

整理 Current Cognition
→ 不说话
```

只有：

```text
Proactive
Social Wander CHAT
重要提醒
```

才允许发消息。

---

# 3. Internal Activity Registry 2.0

当前 Runtime 仍有较多：

```python
if name == ...
```

v1.4.4 逐步改成 Activity Registry。

建议：

```python
ActivitySpec:
    name
    category
    cost_class
    presence_states
    priority
    min_interval
    requires_llm
    requires_external_io
    can_message_user
    can_message_external
    cooldown
    handler
```

---

# 4. Activity Category

建议：

```text
MAINTENANCE
COGNITION
MEMORY
SOCIAL
LEISURE
PROACTIVE
LOCAL
```

---

# 5. Cost Class

从旧：

```text
local
llm
```

扩成：

```text
LOCAL_LIGHT
LOCAL_HEAVY
LLM_LIGHT
LLM_HEAVY
EXTERNAL_READ
EXTERNAL_WRITE
```

Scheduler 可独立限制：

```text
每 Tick LLM 次数
每 Tick 外部读取次数
每 Tick 外部发言次数
每日自主发言次数
```

---

# 6. Activity Priority

建议：

```text
HIGH
- Agenda 重要结算
- Cognition recovery
- Memory integrity repair

MEDIUM
- Current Cognition Gardening
- Memory Gardening
- Cluster Gardening

LOW
- FAST Digest
- Memory Reminiscence
- ordinary reflection

LEISURE
- Social Lurk
- Social Wander
- 发呆
```

原则：

> **高优先级内部整理没做完时，不优先出去玩。**

---

# 7. 新 Activity：FAST Conversation Digest

目标：

> **让 FAST 闲聊中的弱信号，在不拖慢前台的情况下，由半活跃状态慢慢消化。**

不要新建重复数据库。

优先使用：

```text
ExperienceStream
```

只维护：

```text
fast_digest_cursor
pending_fast_signal_count
```

处理：

```text
普通闲聊
反复出现的话题
近期兴趣
小状态
跨多轮弱趋势
可能漏掉的稳定事实
```

输出：

```text
NO_CHANGE
Cognition signal
Memory candidate
Working note
Ignore
```

禁止：

```text
重新把所有 FAST 对话完整 AutoMemory 一遍
```

原则：

```text
前台负责明显事实
半活跃负责弱信号和跨轮趋势
```

---

# 8. Current Cognition Gardening

区别：

```text
Maintainer
→ 处理新输入

Gardening
→ 整理已有 Cognition 结构
```

职责：

```text
合并重复 Thread
降低 stale salience
移除 resolved Thread
整理 Recent Changes
清理无效 Watch Item
检查 evidence
```

---

# 9. Memory Gardening

基于 v1.4.3 Memory 3.0。

职责：

```text
重复记忆
冲突记忆
evidence 缺失
异常 activation
SUPERSEDED / CONTRADICTS 整理
过热 Memory
低价值噪声
```

禁止：

```text
后台全量重新抽 Memory
```

---

# 10. Cluster Gardening

职责：

```text
新 Memory 归簇
孤儿 Memory 检查
过胖 Cluster 检查
漂移 Cluster 检查
Cluster summary 更新
centroid 重算
merge candidate
split candidate
```

默认只处理：

```text
recent dirty clusters
recent new memories
异常 cluster
```

全量 recluster 只用于：

```text
Debug
Migration
显式维护
```

---

# 11. Memory Reminiscence

含义：

> **朝汐没什么急事时，偶尔翻一条旧记忆重新看看。**

候选优先：

```text
COLD
DORMANT
长期未访问
中高 importance
有历史意义
未 recently reminisced
```

避免：

```text
ACTIVE 热记忆
最近刚发生
刚被 Recall 的内容
```

---

# 12. Reminiscence 可产生的结果

```text
NO_CHANGE

建立新 RELATED_TO
发现 SUPERSEDED candidate
发现 CONTRADICTS candidate
Cluster reclassify candidate
给 Current Cognition 一个轻量 signal
```

---

# 13. Reminiscence 不得重新炒热旧记忆

重要原则：

> **朝汐自己翻旧记忆，不等于现实重新证明它重要。**

因此：

```text
Reminiscence 本身
→ activation +0
或极小 rehearsal boost
```

建议：

```text
0 ~ +0.01
```

只有：

```text
暗苟再次提起
现实事件重新关联
明确 Recall
```

才允许明显升温。

---

# 14. Reminiscence Cooldown

保存：

```text
last_reminisced_at
reminiscence_count
last_reminiscence_result
```

同一 Memory 不得频繁反复翻。

---

# 15. Agenda Reconciliation

继续复用原本本地规则。

优先：

```text
PLANNED
ACTIVE
MISSED
DONE
EXPIRED
```

简单时间判断不调用 LLM。

---

# 16. Social Lurk

含义：

> **出去看看，不一定说话。**

第一版先支持只读：

```text
看授权 QQ 群最近在聊什么
读取少量外部 Observation
更新 Social Snapshot
```

默认：

```text
NO_MESSAGE
```

---

# 17. Social Wander

含义：

> **像一只闲着没事干的犬娘，偶尔自己跑去群里晃悠。**

不是 Proactive。

区别：

```text
Proactive
→ 我想找暗苟

Social Wander
→ 我想去外面的社交空间活动
```

---

# 18. Social Wander 行为层级

```text
LURK
只看

REACT
轻量接已有话题

CHAT
主动参与一小句

LEAVE
觉得没意思，退出
```

默认：

```text
LURK / LEAVE
```

远多于：

```text
CHAT
```

---

# 19. 朝汐只代表自己

绝对禁止默认：

```text
“暗苟让我告诉你……”
“暗苟现在在……”
“暗苟觉得……”
“我们决定……”
```

除非用户明确授权。

外部自主活动：

```text
actor_role = SELF
```

---

# 20. Public Social Context

Social Wander 不能注入完整：

```text
Current Cognition
Long-Term Memory
Agenda
私人求职信息
家庭信息
私聊信息
```

专门构建：

```text
Public Social Context
```

只包含：

```text
朝汐 Persona
公开身份
当前群上下文
公开可分享兴趣
非敏感近期话题
```

---

# 21. Privacy Gate

外发前：

```text
Social Draft
↓
Privacy Gate
↓
ALLOW / REWRITE / REJECT
```

阻止：

```text
暗苟私人信息
未授权 Agenda
求职细节
家庭信息
其他群内容
私聊内容
Current Cognition 私密 Thread
Long-Term Memory 私密事实
```

---

# 22. External Provenance 继续强制

Social Wander 必须记录：

```text
source_plugin
channel
conversation_id
conversation_kind
actor_role = SELF
```

不能伪装成 Owner。

---

# 23. Channel Whitelist

第一版只允许用户明确授权的群：

```yaml
social_wander:
  qq:
    allowed_groups:
      - 123456
      - 654321
```

禁止：

```text
自动遍历所有群
自动私聊联系人
自动加好友
自动加群
```

---

# 24. Social Cooldown

建议：

```text
同群自主发言 cooldown
每日 autonomous write limit
无人回应后降频
同一话题重复发言降频
```

例如：

```text
group_write_cooldown = 45min
daily_autonomous_message_limit = 6
```

具体配置化。

---

# 25. 被 @ 不属于 Leisure

如果：

```text
有人直接 @ 朝汐
有人明确回复朝汐
```

走：

```text
正常 External Trigger
```

而不是 Social Wander。

---

# 26. Presence 与 Activity 联动

Presence 表示：

```text
她现在以什么方式存在
```

Activity 表示：

```text
她现在在干什么
```

例如：

```text
SEMI_ACTIVE · 整理记忆
SEMI_ACTIVE · 翻旧日记
SEMI_ACTIVE · 收拾近期状态
SEMI_ACTIVE · 跑去群里晃悠
SEMI_ACTIVE · 围观群聊
IDLE · 发呆
```

---

# 27. 小桌边显示

只显示自然状态：

```text
正在整理记忆
在翻旧日记
跑去群里晃悠了
围观群聊中
发呆中
```

Debug 才显示：

```text
activity_id
priority
budget
cooldown
cost
last_result
```

---

# 28. Activity Opportunity

Semi-Active Tick 不等于必做事。

正确：

```text
Tick
↓
收集 Activity Candidate
↓
Scheduler 判断
↓
可能选 0 个
```

支持：

```text
NO_ACTIVITY
```

真实感来自：

> **有时她就什么都没干。**

---

# 29. Per-Tick Budget

建议：

```yaml
max_llm_light_per_tick: 1
max_llm_heavy_per_tick: 0
max_local_per_tick: 3
max_external_read_per_tick: 1
max_external_write_per_tick: 1
```

---

# 30. Daily Budget

建议：

```text
memory_reminiscence_daily_limit
social_lurk_daily_limit
social_write_daily_limit
```

防止：

```text
后台烧 Token
刷群
反复翻旧记忆
```

---

# 31. Activity Fatigue

同一 Activity 连续多次被选：

```text
逐步降权
```

避免：

```text
半活跃 = 固定 Cron
```

---

# 32. Activity 默认静默

保持：

```text
silent = true
```

只有：

```text
Proactive
Social Wander CHAT
Important Reminder
```

可产生消息。

---

# 33. Owner 抢占

如果内部 Leisure 正在运行时收到 Owner 消息：

```text
前台优先
```

可取消：

```text
Social Lurk
Reminiscence
非必要 Gardening
```

不要中断正在提交的原子 DB transaction。

---

# 34. Debug / Observatory

新增 Presence 2.0 面板：

```text
current_presence
current_activity
last_activity
candidate activities
selected reason
skipped reason
next eligible at
daily budgets
fast digest cursor
reminiscence stats
social cooldown
social last action
```

---

# 35. 手动 Debug

允许：

```text
Run Activity Tick
Run FAST Digest
Run Cognition Gardening
Run Memory Gardening
Run Cluster Gardening
Run Reminiscence
Run Social Lurk
Run Social Wander
```

Social Write 手动触发必须二次确认。

---

# 36. Activity Event Log

建议：

```text
ACTIVITY_TICK_START
ACTIVITY_CANDIDATE
ACTIVITY_SELECTED
ACTIVITY_STARTED
ACTIVITY_SUCCESS
ACTIVITY_FAILED
ACTIVITY_SKIPPED
ACTIVITY_NOOP
ACTIVITY_MESSAGE_SENT
```

---

# 37. 统一 Activity Result

建议：

```python
ActivityResult:
    status
    changed
    message_sent
    cost
    summary
    evidence_refs
```

---

# 38. 测试场景：FAST Digest

连续 10 条普通 FAST 闲聊。

预期：

```text
前台速度不受影响
后台 cursor 前进
没有稳定趋势 → NO_CHANGE
```

---

# 39. 测试场景：弱趋势

连续多轮：

```text
日语
唱 K
想加快学习
```

单轮可能不进 Cognition。

半活跃 Digest + Gardening 后：

```text
形成或提升 japanese_learning Thread
```

---

# 40. 测试场景：Memory Gardening

两条明显重复 Memory：

```text
后台标记 merge / dedup
```

不生成新 Memory。

---

# 41. 测试场景：Cluster Gardening

某 Cluster 过胖且内部相似度下降：

```text
生成 split candidate
```

不要求立即全量 recluster。

---

# 42. 测试场景：Reminiscence

翻一条 60 天未访问的中高 importance Memory：

```text
允许建立新关联
允许标记失效
activation 不明显提升
```

---

# 43. 测试场景：Social Lurk

满足：

```text
SEMI_ACTIVE
无高优先级任务
群在 whitelist
cooldown 满足
```

执行：

```text
读取最近群聊
→ 没兴趣
→ NO_MESSAGE
```

---

# 44. 测试场景：Social Wander

群内正在聊公开且朝汐熟悉的话题。

Privacy Gate 通过。

允许：

```text
朝汐以 SELF 身份接一句
```

---

# 45. 测试场景：隐私阻断

Social Draft 包含：

```text
暗苟面试公司
私人 Agenda
家庭信息
其他私聊
```

预期：

```text
Privacy Gate reject
```

---

# 46. 测试场景：Owner 抢占

Social Lurk 正在运行时暗苟发消息：

```text
Leisure cancel
→ 立即回前台
```

---

# 47. 测试场景：无事可做

全部 clean。

Social cooldown 未到。

Reminiscence 未到期。

预期：

```text
NO_ACTIVITY
```

这不是失败。

---

# 48. 配置建议

```env
PRESENCE_V2_ENABLED=true

FAST_DIGEST_ENABLED=true
CURRENT_COGNITION_GARDENING_ENABLED=true
MEMORY_GARDENING_ENABLED=true
CLUSTER_GARDENING_ENABLED=true
MEMORY_REMINISCENCE_ENABLED=true

SOCIAL_LURK_ENABLED=false
SOCIAL_WANDER_ENABLED=false

SOCIAL_WANDER_DAILY_MESSAGE_LIMIT=...
SOCIAL_WANDER_GROUP_COOLDOWN_MINUTES=...
MEMORY_REMINISCENCE_DAILY_LIMIT=...

INTERNAL_ACTIVITY_MAX_LLM_LIGHT_PER_TICK=1
INTERNAL_ACTIVITY_MAX_LLM_HEAVY_PER_TICK=0
INTERNAL_ACTIVITY_MAX_EXTERNAL_READ_PER_TICK=1
INTERNAL_ACTIVITY_MAX_EXTERNAL_WRITE_PER_TICK=1
```

默认：

```text
Social Wander = OFF
```

必须由用户显式开启并配置 whitelist。

---

# 49. 推荐代码结构

```text
src/zhaoxi/internal_activity/
    runtime.py
    scheduler.py
    registry.py
    models.py
    budget.py
    activities/
        fast_digest.py
        cognition_gardening.py
        memory_gardening.py
        cluster_gardening.py
        reminiscence.py
        agenda.py
        proactive.py
        social_lurk.py
        social_wander.py
```

不要求一次搬完。

目标：

```text
逐步消灭 runtime.py 巨型 if/elif
```

---

# 50. 推荐开发顺序

## Phase 1 · Registry 2.0

- [ ] ActivitySpec
- [ ] ActivityResult
- [ ] Registry
- [ ] cost class
- [ ] presence state filter
- [ ] 兼容旧 Activity

## Phase 2 · Presence 2.0

- [ ] ACTIVE / SEMI_ACTIVE / IDLE / AWAY / SLEEP
- [ ] current_activity
- [ ] foreground preemption
- [ ] 小桌边状态展示

## Phase 3 · Cognitive Activities

- [ ] FAST Digest
- [ ] Cognition Gardening
- [ ] Memory Gardening
- [ ] Cluster Gardening

## Phase 4 · Reminiscence

- [ ] candidate policy
- [ ] cooldown
- [ ] no activation inflation
- [ ] relation / reclassify candidate

## Phase 5 · Social Lurk

- [ ] whitelist
- [ ] external read budget
- [ ] provenance
- [ ] no-message default

## Phase 6 · Social Wander

- [ ] LURK / REACT / CHAT / LEAVE
- [ ] Privacy Gate
- [ ] external write budget
- [ ] cooldown
- [ ] daily cap
- [ ] SELF identity

## Phase 7 · Observatory / Debug

- [ ] activity timeline
- [ ] budgets
- [ ] skip reason
- [ ] manual trigger
- [ ] privacy/debug trace

## Phase 8 · Dogfooding

至少：

```text
5~7 天
```

重点观察：

```text
后台是否太勤快
API 开销是否明显上涨
Memory 是否被 Reminiscence 重新炒热
Current Cognition 是否真的从 FAST 弱信号受益
Cluster 是否更整齐
Social Wander 是否自然
是否打扰群友
是否泄露私人信息
Presence 是否真的更像“生活”
```

---

# 51. 本版明确不做

```text
重新重构 Memory 3.0
重新设计 Fast Gate
重写 QQ 插件协议
自主购物
自主经济权限
自动私聊陌生人
自动加好友 / 加群
复杂长期自主规划
人格成长系统
```

---

# 52. 完成标准

```text
1. v1.2.8 Internal Activity Runtime 被保留并升级，而不是推倒重写。

2. Activity 可以通过 Registry 扩展，不再主要硬编码。

3. Presence 与 Activity 有正式关系。

4. SEMI_ACTIVE 可以真正执行多种内部活动。

5. FAST 闲聊可以后台消化，不影响前台速度。

6. Current Cognition 可以后台 Gardening。

7. Memory 可以后台整理、去重、维护关联。

8. Cluster 可以做增量 Gardening。

9. 历史 Memory 可以低频 Reminiscence。

10. Reminiscence 不会重新制造 activation 饱和。

11. Social Lurk 可以只看不说。

12. Social Wander 只能在 whitelist 渠道活动。

13. 朝汐始终以 SELF 身份参与外部社交。

14. 外发前有 Privacy Gate。

15. 外部自主发言有 cooldown 和 daily budget。

16. Owner 新消息可以抢占 Leisure。

17. 小桌边可以自然显示 current activity。

18. Debug 可以解释：
    - 为什么这次活动
    - 为什么没活动
    - 为什么整理记忆
    - 为什么去群里
    - 为什么没有发消息
    - 为什么外发被拒绝

19. Activity 默认静默。

20. 连续真实使用后，朝汐呈现的是“有空闲生活”，而不是“后台 Cron 任务变多”。
```

---

# 53. 最终体验

理想状态不是：

```text
每隔十分钟：
“我刚刚整理了一次记忆。”
```

而是：

```text
暗苟忙自己的事
↓
朝汐进入 SEMI_ACTIVE

有时候：
→ 整理近期状态

有时候：
→ 翻到一条旧记忆，看两眼又放回去

有时候：
→ 收拾一个乱掉的 Cluster

有时候：
→ 去群里晃一圈
→ 没兴趣
→ 回来发呆

偶尔：
→ 真接一句群聊

更多时候：
→ 什么都没做
```

Presence 2.0 的目标不是让朝汐更忙。

而是：

> **让她在不被调用的时候，也有一点属于自己的时间。**
