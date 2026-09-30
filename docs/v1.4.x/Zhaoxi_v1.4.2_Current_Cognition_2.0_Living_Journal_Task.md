# Zhaoxi v1.4.2 · Current Cognition 2.0 / Living Journal 开发任务书

> 项目：**Zhaoxi / 朝汐**\
> 版本：**v1.4.2**\
> 主题：**Current Cognition 2.0 / Living Journal**\
> 定位：让“近期状态”真正成为朝汐当前认知的一部分，而不是一篇后台分析报告\
> 前置基线：
>
> - v1.4.0 已完成 Runtime Observatory、Visibility Contract、Final 优先交付、Post-turn Maintenance Queue
> - v1.4.1 已完成 Fast Dialogue Lane，普通聊天可在不查长期 Memory、不调用 Router LLM 的情况下快速回复
>
> 本版核心目标：
>
> **让 Fast Chat 在不查长期 Memory 的前提下，仍然知道“最近这几天暗苟在过什么生活、哪些事还挂着、刚发生了什么变化”。**
>
> 一句话定义：
>
> > **Current Cognition = 朝汐写给自己的、会持续更新和自然淡出的近期小本子。**

---

## 0. 为什么现在必须重构 Current Cognition

v1.4.1 之后，普通聊天链路已经变成：

```text
Persona
+ Recent Conversation
+ Current Cognition
+ User Message
↓
单次 LLM
↓
Final Reply
```

这意味着 Current Cognition 已经成为 Fast Chat 的主要近期认知来源。

如果它仍然是一篇“用户近期形势分析报告”，Fast Chat 虽然会更快，但仍会：

- 带着第三方观察员口吻理解暗苟；
- 把不同主线混在一起；
- 持续携带已经结束的旧状态；
- 容易把短期情绪拔高成长期趋势；
- 每轮都读一篇过重的背景文章；
- 让朝汐“知道很多”，但不知道什么最重要。

因此 v1.4.2 不做 Prompt 小修，而是同时重构：

```text
认知主体
数据结构
更新方式
生命周期
Fast Chat 注入
Debug 可观察性
```

---

## 1. Current Cognition 2.0 的系统定位

### Recent Conversation

负责：

```text
刚刚聊了什么
```

时间尺度：

```text
分钟 ~ 数小时
```

### Current Cognition

负责：

```text
最近这几天生活大概是什么状态
目前哪些主线仍在继续
最近有哪些真正改变了认知的变化
朝汐现在需要特别留意什么
```

时间尺度：

```text
约 1~7 天
```

### Long-Term Memory

负责：

```text
长期事实
过往经历
人物关系
长期偏好
项目历史
需要主动回忆时再检索
```

### Agenda / LifeHUD / Tool

负责：

```text
精确时间
明确安排
结构化任务
可验证生活记录
```

---

## 2. 认知主体必须改正

当前问题：

```text
Current Cognition 像系统写给开发者看的“用户分析”
```

v1.4.2 必须改成：

> **朝汐写给自己的近期认知。**

Prompt 明确：

```text
你正在维护朝汐自己的 Current Cognition。

这是朝汐写给自己的近期小本子，
不是系统分析报告，
不是面向用户的回复，
不是心理画像。

用朝汐自己的认知视角书写。
提到暗苟时可以称“暗苟”，也可以自然省略主语。

禁止使用：
“用户……”
“该用户……”
“用户自述……”
“用户倾向……”
```

---

## 3. 角色感边界

Current Cognition 不是角色扮演文本。

允许：

```text
自然
有一点朝汐自己的说话感
带轻微主观认知色彩
```

禁止：

```text
卖萌堆砌
耳朵尾巴舞台描写
聊天气泡式输出
长篇文学化抒情
过度拟人自言自语
```

目标类似：

```text
这两天暗苟的注意力明显回到朝汐本体上了。
最近开发主线从继续堆功能，转向梳理 Runtime 和认知链路。
```

---

## 4. 取消“大 narrative 主导”结构

Current Cognition 2.0 不再以一篇 500~700 字大文章作为主要存储形式。

推荐内部模型：

```python
CurrentCognitionState:
    overview
    threads[]
    recent_changes[]
    watch_items[]
    updated_at
```

---

## 5. 推荐数据模型

### 5.1 Overview

定义：当前几天整体状态的一小段概括。

限制：

```text
80~160 中文字
```

只允许写真正影响整体生活节奏的 1~2 条主线。

---

### 5.2 Threads

每个 Thread 表示：

> **仍然挂在脑子里的一条近期主线。**

建议字段：

```python
CognitionThread:
    key: str
    title: str
    summary: str
    status: active | cooling | resolved
    salience: float
    first_seen_at
    last_updated_at
    last_evidence_at
    source_refs[]
```

示例：

```json
{
  "key": "zhaoxi_runtime_cleanup",
  "title": "朝汐 Runtime 收口",
  "summary": "最近正在从继续堆功能转向梳理运行链路，已经做完运行观测和快速聊天，下一步准备重构 Current Cognition。",
  "status": "active",
  "salience": 0.91
}
```

---

### 5.3 Recent Changes

定义：最近真正发生了“状态变化”的东西。

例如：

```text
· 普通聊天已经能走 Fast Chat，不再每轮查 Memory。
· 开始把 vibe coding 留下的黑箱逐层拆开理解。
```

限制：

```text
最多 3 条
每条 <= 60~80 字
保留 1~3 天后自动淡出
```

---

### 5.4 Watch Items

定义：朝汐接下来几轮需要特别记着的轻量提醒。

不是 Agenda。

例如：

```text
· 不要把单次情绪或小事拔高成长期趋势。
· 当前 v1.4 重点是边用边修，不急着继续堆新功能。
```

限制：

```text
最多 2~3 条
```

---

## 6. 不再用全文字符串 Patch

旧方式：

```text
找到 narrative 中一段原文
→ 精确替换
→ 其余继续保留
```

v1.4.2 改成：

```text
UPSERT thread
REMOVE thread
UPDATE overview
ADD recent_change
REMOVE stale_change
UPSERT watch_item
REMOVE watch_item
```

所有更新基于稳定 key。

---

## 7. Thread Key 规则

Thread Key 必须稳定。

例如：

```text
job_search
zhaoxi_runtime_cleanup
current_cognition_rework
dorm_living_state
japanese_learning
```

模型可以建议 key，但运行时应做：

```text
normalize
deduplicate
alias merge
```

禁止语义重复 Thread 无限分裂。

---

## 8. Current Cognition 的写入判断标准

不再问：

> “最近发生了什么？”

改问：

> **“如果朝汐明天醒来不知道这件事，会不会明显误解暗苟现在的生活？”**

只有答案是“会”，才允许进入。

---

## 9. 应进入 / 不应进入示例

### 不应进入

```text
今天吃了什么
一次普通吐槽
一次随口玩笑
一次临时情绪
单次 Tool 操作
已经结束且没有后续影响的小事
```

### 可以进入

```text
连续几天寝室环境明显影响效率
秋招最近一直缺少实质进展
项目主线从堆功能转向工程理解与收口
开始加快日语学习节奏
最近明确把某条长期原则重新拿回来使用
```

---

## 10. 禁止过度心理分析

Prompt 加硬约束：

```text
不要解释隐藏动机。
不要推测人格变化。
不要给单次情绪赋予长期意义。
没有持续证据时，宁可不写。
```

---

## 11. Evidence 机制

每个 Thread 保留轻量 Evidence Reference：

```text
message_id
event_id
timestamp
source
```

Debug 中可以回答：

```text
这条 Thread 为什么存在？
```

---

## 12. Salience / 近期显著度

Thread 增加：

```text
salience 0~1
```

建议：

```text
0.8~1.0  当前最主要主线
0.5~0.8  持续中的普通主线
0.3~0.5  正在降温
<0.3     候选移出
```

不要与 Long-Term Memory importance 混用。

---

## 13. Thread 生命周期

推荐：

```text
ACTIVE
↓
COOLING
↓
RESOLVED / REMOVED
```

ACTIVE：最近持续有新证据。

COOLING：一段时间没有新证据，但仍可能回到近期状态。

RESOLVED：事情明确结束、连续多天无新证据或新状态已替代旧状态。

Resolved 不再注入 Fast Chat。

---

## 14. 结束时应该真的消失

例如：

```text
“某场面试正在进行”
```

结束后：

```text
REMOVE / RESOLVE
```

不要变成一段“墓碑式总结”。

长期历史若值得保留，交给 Long-Term Memory。

---

## 15. Fast Chat 专用 Renderer

新增：

```text
render_for_fast_chat()
```

目标长度：

```text
200~350 中文字
```

建议格式：

```text
[近期认知]
这几天：
...

还挂着：
- ...
- ...

刚变化：
- ...

需要留意：
- ...
[/近期认知]
```

---

## 16. Fast Chat 注入优先级

超预算时按顺序保留：

```text
1. overview
2. ACTIVE 高 salience threads
3. recent_changes
4. watch_items
5. COOLING threads
```

禁止为了塞满而全部注入。

---

## 17. FAST 不因 Current Cognition 自动行动

这是关键边界。

Current Cognition 可能写：

```text
“LifeHUD 饮食记录还在整理”
```

用户只说：

```text
“小金毛？”
```

Fast Chat 仍只能聊天，不能自动查 LifeHUD 或续任务。

Current Cognition 是：

```text
背景认知
```

不是：

```text
隐式任务队列
```

---

## 18. Agenda 与 Current Cognition 严格分离

不要在 Cognition 里保存：

```text
明天 10:00 面试
后天下午交材料
今晚 23:00 截止
```

这些属于 Agenda。

Current Cognition 只可抽象为：

```text
这几天秋招仍是主要生活主线。
```

---

## 19. LifeHUD 与 Current Cognition 严格分离

不要复制结构化数据：

```text
早餐 3/5
午饭 12:14
晚饭 18:22
```

最多抽象成：

```text
最近又开始认真整理饮食记录。
```

而且必须确实有近期认知价值。

---

## 20. 与 Long-Term Memory 的关系

Current Cognition 不负责长期保存。

Thread 结束时是否值得长期记忆，由 AutoMemory 自己判断。

Current Cognition 不主动把所有 resolved Thread 转长期 Memory。

---

## 21. 更新触发机制

继续复用 v1.4.0 的 Post-turn Maintenance Queue。

正确链路：

```text
Final Reply
↓
立即交付
↓
Post-turn Maintenance
↓
Current Cognition Maintainer
```

禁止 Fast Chat 等待 Current Cognition 更新。

---

## 22. 不要求每轮调用 LLM

Current Cognition Maintainer 不应每轮无脑调用模型。

先做 Local Gate。

候选信号：

```text
新 User Final Turn
主线关键词变化
明确状态变化
新的计划 / 结束事件
连续若干轮未整理
时间跨度超过阈值
```

如果只是：

```text
纯玩笑
纯寒暄
无状态变化
```

可直接：

```text
skip maintenance
```

---

## 23. Maintainer 两阶段设计

```text
Phase A · 本地候选筛选
↓
是否可能影响 Current Cognition？

No
→ skip

Yes
→ Phase B · LLM 维护
```

目标：不让后台维护本身又变成新的模型税。

---

## 24. Maintainer 输入

只给：

```text
当前 Current Cognition State
本轮 User Message
本轮 Final Reply
必要 Recent Context
本轮 Experience 关键事件
```

不要给：

```text
整个长期 Conversation
整个 Memory 库
完整 Tool Trace
所有历史 Current Cognition
```

---

## 25. Maintainer 输出

禁止返回整篇自由文本。

改成结构化 Operations，例如：

```json
{
  "overview": {
    "action": "keep|replace",
    "value": "..."
  },
  "thread_ops": [
    {
      "action": "upsert",
      "key": "zhaoxi_runtime_cleanup",
      "title": "朝汐 Runtime 收口",
      "summary": "...",
      "salience": 0.9
    },
    {
      "action": "remove",
      "key": "old_interview"
    }
  ],
  "change_ops": [],
  "watch_ops": []
}
```

Runtime 负责：

```text
校验
合并
去重
限制数量
保存
```

---

## 26. 数量上限

建议：

```text
ACTIVE Threads <= 4
COOLING Threads <= 3
Recent Changes <= 3
Watch Items <= 3
```

超过时按：

```text
salience
last_evidence_at
status
```

收口。

---

## 27. 总体文本预算

Fast Chat 注入：

```text
目标 200~350 字
硬上限 450 字
```

不要求填满。

最近生活简单时，100 多字完全可以。

---

## 28. 小桌边显示

小桌边展示“朝汐自己的小本子”版本：

```text
近期状态 · Current Cognition

这几天
...

还挂着
• ...
• ...

刚变化
• ...
```

不显示：

```text
salience
thread key
evidence id
内部状态枚举
```

---

## 29. Dashboard / Debug

Debug 展示完整结构：

```text
Overview

Threads
- key
- status
- salience
- first_seen
- last_updated
- last_evidence

Recent Changes
Watch Items
Evidence

Last Maintenance
- triggered / skipped
- reason
- duration
- model call
- operations
```

---

## 30. Observatory 接入

v1.4.0 已有 Runtime Observatory。

新增：

```text
current_cognition_gate
current_cognition_triggered
current_cognition_skipped
current_cognition_model_ms
current_cognition_ops_count
threads_added
threads_updated
threads_removed
```

不新造页面。

---

## 31. Migration

旧 Current Cognition 不继续滚动维护。

首次启动 v1.4.2：

```text
旧 narrative / threads / attention
↓
一次 migration
↓
Current Cognition 2.0 State
```

Migration 后旧数据只读备份。

不要长期双格式兼容。

---

## 32. Migration 原则

宁可少迁一点，也不要把旧 narrative 的所有历史残留重新塞进新结构。

推荐：

```text
提取 1~3 条真正还在持续的 Thread
生成一个短 Overview
旧 narrative 归档
```

---

## 33. 当前场景示例

理想输出可以类似：

```text
【这几天】
最近主要还是秋招和朝汐两条线。秋招继续推进，但已经越来越倾向只把精力留给真正值得的机会；朝汐这边则从继续堆功能转向边用边拆黑箱，先把运行链路和普通聊天速度收了下来。

【还挂着】
• v1.4 正在作为长期打磨版本推进，下一步是把近期认知本身重做。
• 秋招仍是现实主线，但不再想被低价值笔试和宣讲拖着走。

【刚变化】
• 普通聊天已经能走 Fast Chat，一句话不再拉起整套 Agent Runtime。

【我需要记着】
• Current Cognition 是背景认知，不是任务队列，不能因为这里写着某件事就自动续做。
```

而不是：

```text
用户近期围绕……
用户回望……
用户倾向……
```

---

## 34. FAST Chat 验收重点

### Case A · 普通寒暄

Current Cognition 中有 LifeHUD、秋招、项目。

用户：

```text
小金毛？
```

要求：

```text
正常聊天
不自动续任何 Thread
不调用 Tool
```

### Case B · 近期主线连续性

用户：

```text
最近感觉秋招真没啥结果
```

FAST 不查 Memory，但朝汐仍应知道秋招最近一直是主要生活主线。

### Case C · 具体历史回忆

用户：

```text
我上次亚信面试具体问了啥？
```

Current Cognition 不负责回答。

应：

```text
退出 FAST
→ Long-Term Memory Recall
```

---

## 35. Current Cognition 维护验收

### Case D · 小事不写

```text
哈哈这个好蠢
```

应：

```text
maintenance skipped
```

### Case E · 单次情绪不拔高

```text
今天有点烦
```

不得自动生成：

```text
暗苟近期持续处于烦躁状态
```

### Case F · 持续变化进入 Thread

连续几轮都在追 Runtime Trace、拆 Fast Chat、讨论 Current Cognition，应形成一个稳定 Thread，而不是每轮新建一个。

### Case G · Thread 自然退出

某场面试结束后数天无后续：

```text
active
→ cooling
→ resolved
→ 不再注入 Fast Chat
```

---

## 36. 性能要求

Current Cognition 不得破坏 v1.4.1 的 Fast Chat 性能。

硬要求：

```text
FAST foreground_llm_calls = 1
```

Current Cognition Maintenance 永远属于 background。

---

## 37. 文件与模块建议

候选：

```text
src/zhaoxi/current_cognition/models.py
src/zhaoxi/current_cognition/service.py
src/zhaoxi/current_cognition/maintainer.py
src/zhaoxi/current_cognition/renderer.py
src/zhaoxi/current_cognition/prompts.py
```

继续沿用现有包，不必新建第二套 Current Cognition。

建议废弃旧：

```text
全文 narrative patch contract
精确字符串替换
700 字大摘要思路
```

---

## 38. 推荐开发顺序

### Phase 1 · 数据模型

- [ ] CurrentCognitionState 2.0
- [ ] Thread / Change / Watch Item
- [ ] stable key
- [ ] status / salience
- [ ] evidence refs
- [ ] 数量上限

### Phase 2 · Renderer

- [ ] Fast Chat renderer
- [ ] 小桌边 renderer
- [ ] Debug renderer
- [ ] 文本预算

### Phase 3 · Maintainer Contract

- [ ] Local maintenance gate
- [ ] Structured Ops
- [ ] upsert / remove
- [ ] validation
- [ ] dedup
- [ ] no over-analysis prompt

### Phase 4 · Lifecycle

- [ ] ACTIVE / COOLING / RESOLVED
- [ ] stale decay
- [ ] explicit resolve
- [ ] resolved 不注入

### Phase 5 · Fast Chat Integration

- [ ] FAST 使用轻量 snapshot
- [ ] Current Cognition 不触发隐式 Tool
- [ ] FAST 仍保持单模型调用

### Phase 6 · Migration

- [ ] 旧状态一次性迁移
- [ ] 旧 narrative 归档
- [ ] 不维护双格式

### Phase 7 · Debug / Observatory

- [ ] Thread 查看
- [ ] Evidence 查看
- [ ] Last Maintenance
- [ ] skip reason
- [ ] ops count

### Phase 8 · 实机 dogfooding

至少连续使用：

```text
3~7 天
```

重点看：

```text
会不会越来越胖
会不会旧事赖着不走
会不会过度心理分析
会不会把 Current Cognition 当任务队列
Fast Chat 是否真的借到了“近期生活感”
```

---

## 39. 本版明确不做

不做：

```text
Long-Term Memory 算法重构
真实 Embedding
Memory Lifecycle 收口
Planner UI
Dashboard 总体改版
Presence 2.0
向日葵视觉统一
手机端
```

v1.4.2 只负责：

> **让朝汐真正拥有一份能用、会变、会忘、写给自己的近期认知。**

---

## 40. 完成标准

v1.4.2 完成后必须满足：

```text
1. Current Cognition 不再出现“用户……”式第三方分析语气。

2. Fast Chat 不查长期 Memory 时，仍能理解最近几天的主要生活状态。

3. Current Cognition 总注入文本通常 <= 350 字，硬上限 <= 450 字。

4. 内容以 Overview + Threads + Changes + Watch Items 组织，不再是一整篇 narrative。

5. Thread 支持 Upsert / Remove，不再靠全文精确 Patch。

6. 已结束或失效的近期状态可以真正离开 Current Cognition。

7. 单次情绪、小事、玩笑不会被拔高成长期趋势。

8. Current Cognition 不保存 Agenda / LifeHUD 的精确结构化事实。

9. Current Cognition 不会因为包含“未完成事项”就自动驱动 FAST Chat 继续执行 Tool。

10. Maintainer 不再每轮强制调用 LLM，无变化时可本地 skip。

11. Maintenance 永远在后台，不增加 Fast Chat 前台模型调用数。

12. Debug 可以回答：
    “这条近期认知为什么存在？”
    “最后什么时候更新？”
    “为什么还没被移除？”

13. 连续 dogfooding 数天后，Current Cognition 不应明显膨胀或积累旧状态化石。
```

---

## 41. 最终目标体验

完成后，暗苟对朝汐说：

```text
最近感觉秋招真没啥结果。
```

朝汐不需要先查长期 Memory，也不应该像第一次听到。

她脑子里本来就应该有：

```text
最近秋招仍是主要现实主线，而且这段时间确实缺少实质进展。
```

于是可以直接接住话。

而当暗苟问：

```text
我上次亚信面试具体问了哪些题？
```

朝汐才真正去：

```text
Long-Term Memory Recall
```

这就是 v1.4.2 想建立的区别：

> **不是每句话都回忆一生，但也不是每句话都从零开始。**
