# Zhaoxi v1.2.6 二次重构任务书
## Short-Term Memory → Current Cognition / Live Journal

> 本轮目标：推倒当前 Short-Term Memory 的“近期事实收集器”思路，将其重构为 **朝汐自己的实时日记 / 当前认知状态**。
>
> 前端本轮不重做。优先把后端语义和维护逻辑做正确。

---

# 一、问题说明

当前 Short-Term Memory 已经可以持续维护近期信息，但存在明显滥用：

- 记入大量一次性小事
- 记入 Tool 调用过程
- 记入文件路径、数据库操作等执行痕迹
- 记入可以由 Agenda / Life HUD / Tool 状态重新获得的信息
- 同一件事被 Overview / Active Threads / Recent Changes 等多个区块重复表达
- 越来越像“最近一周的压缩聊天记录”
- 受到长期 Memory “广记”原则影响，写入门槛过低

根本问题不是容量，而是：

> **Short-Term Memory 与 Long-Term Memory 使用了错误的同一套“什么值得记”的价值观。**

长期 Memory 可以“广记”，因为它保存的是事实资产，未来按需检索。

Current Cognition 不应该“广记”。

它的职责是：

> **维护朝汐此刻对最近这一段生活的整体理解。**

---

# 二、重新定义

废弃当前核心概念：

```text
Short-Term Memory
= 最近数天发生过什么
```

替换为：

```text
Current Cognition / Live Journal
= 朝汐此刻如何理解最近这一阵子
```

UI 仍可继续叫：

```text
近期状态
便利签
Short-Term Memory
```

但后端领域语义必须改成：

```text
Current Cognition
```

推荐代码命名：

```text
current_cognition
CurrentCognition
CurrentCognitionService
CurrentCognitionMaintainer
CurrentCognitionStore
CurrentCognitionRenderer
```

也可根据现有工程命名规范调整。

---

# 三、与 Long-Term Memory 的根本区别

## Long-Term Memory

负责：

```text
“我知道什么”
```

内容包括：

- 已发生事实
- 用户偏好
- 项目设定
- 长期经历
- 稳定背景
- 小事，只要未来可能重新产生关联，也可以记录

原则：

> **广记，按需召回。**

## Current Cognition

负责：

```text
“我现在怎么看最近这一阵子”
```

内容包括：

- 最近主要现实背景
- 当前持续主线
- 最近注意力集中在哪
- 最近状态发生了什么变化
- 哪些趋势已经形成
- 哪些事情虽然离开 Raw Context 后仍然影响现在

原则：

> **广看，慎写，持续改写。**

---

# 四、整体上下文架构

```text
Long-Term Memory
“长期以来我知道什么”
        │
        │ 按需检索
        ▼

Current Cognition
“最近这一阵子，在我看来是什么状态”
        │
        │ 常驻
        ▼

Raw Recent Context
“刚刚具体说了什么”
        │
        ▼

Current Turn
```

另有：

```text
Agenda
“接下来会发生什么”
```

整体时间感：

```text
过去很久           最近数天~一周            刚刚            现在             未来
   │                    │                    │               │                │
Long-Term Memory → Current Cognition → Raw Context → Current Turn → Agenda
```

---

# 五、核心心智模型：实时日记

Current Cognition 应被理解为：

> **朝汐一直在改写的一篇短小实时日记。**

不是数据库。
不是 Note List。
不是 Todo。
不是事件日志。
不是近期事实仓库。
不是“最近发生过什么”的流水账。

理想内容类似：

```text
暗苟最近仍主要处于秋招阶段，不过相比前些天单纯大量投递，
最近明显更关注岗位质量，以及宣讲、笔试到底值不值得花时间。

Zhaoxi 的开发仍然持续，目前注意力集中在 Agenda 和近期上下文，
重点已经从单纯增加功能转到“朝汐怎样真正理解最近生活”。

最近聊天也比前段时间轻松了一些，动漫、角色和绘图话题明显增多，
不过秋招和 Zhaoxi 仍然是眼下最主要的两条线。
```

---

# 六、Current Cognition 的判断问题

Maintainer 不再问：

```text
“这一轮有什么值得记住？”
```

改为问：

> **“这一轮是否改变了朝汐对暗苟最近这段生活的整体理解？”**

如果没有：

```text
NO_CHANGE
```

如果有：

```text
UPDATE
```

不要因为出现了新事实就一定写入。

---

# 七、写入门槛

一条信息只有满足至少一个条件，才允许影响 Current Cognition：

1. **持续性**：预计未来几天仍然会影响理解。
2. **主线性**：属于最近生活 / 工作中的主要背景。
3. **状态变化**：改变了一个已有近期认知。
4. **跨会话价值**：Raw Context 消失后仍需要知道。
5. **趋势形成**：不是单次发生，而是连续多次出现。

---

# 八、默认拒绝进入 Current Cognition 的内容

以下内容默认拒绝：

```text
单次吃了什么
单次去了哪里
单次买了什么
某个精确金额
某次临时 Tool 调用
文件路径
数据库表名
打开了什么软件
一次性的 Debug 操作
某轮聊天里的小细节
已经结束且不再影响后续的事件
可由 Agenda 可靠获得的日程细节
可由 Life HUD 可靠获得的生活记录
可由 Tool 状态重新查询到的执行信息
Raw Context 仍然足够承载的刚刚发生内容
```

重要原则：

> **Current Cognition 不缓存其他系统已经可靠拥有的细节。**

---

# 九、一个强制筛选问题

对每一个候选内容，Maintainer 都必须进行判断：

> **如果明天删掉这条信息，朝汐重新启动时，会不会明显误解暗苟最近过得怎么样、在忙什么、注意力在哪？**

如果不会：

```text
DROP
```

如果会：

```text
KEEP / UPDATE
```

---

# 十、数据模型重构

建议收缩为：

```yaml
CurrentCognitionState:

  narrative:
    一段核心实时日记文本

  ongoing_threads:
    少量当前持续主线

  attention:
    当前最值得朝汐持续留意的少数事项

  updated_at:
  last_processed_message_id:
  version:
```

示例：

```yaml
narrative: |
  暗苟最近仍主要处于秋招阶段，不过相比前些天单纯大量投递，
  最近明显更关注岗位质量以及活动是否值得投入时间。
  Zhaoxi 仍在持续开发，目前重点集中在 Agenda 与近期上下文连续性。
  最近动漫、角色和绘图话题有所增加，但秋招与 Zhaoxi 仍是主要两条线。

ongoing_threads:
  - 秋招与岗位筛选
  - Zhaoxi v1.2.6 开发

attention:
  - 当前正在重新调整 Current Cognition 本身的维护方式
```

---

# 十一、Narrative 是主数据

不要再以：

```text
一堆结构化 Item
↓
Renderer 拼接
```

作为核心思路。

Current Cognition 的核心应该直接是：

```text
narrative
```

结构化字段只用于辅助维护与调试。

---

# 十二、维护方式：持续改写，不是追加

旧模式：

```text
发现新事情
↓
新增 Item
↓
越来越多
```

新模式：

```text
旧 Current Cognition
+
新一轮对话
+
必要外部状态
↓
重新判断“现在该怎样理解最近”
↓
只修改受到影响的部分
```

核心行为：

```text
KEEP
REFINE
REPLACE
REMOVE
NO_CHANGE
```

而不是：

```text
APPEND APPEND APPEND
```

---

# 十三、禁止每轮全文文学重写

虽然 narrative 是文本，但不能每轮重新换一套措辞。

否则会产生：

- 语义漂移
- 主线越来越偏
- 风格越来越夸张
- 原本稳定事实被无意改写

推荐 Maintainer 输出：

```yaml
decision: NO_CHANGE
```

或：

```yaml
decision: UPDATE

reason:
  用户近期明确改变了岗位筛选策略

narrative_patch:
  replace:
    from: "最近仍以大量投递为主"
    to: "最近开始更明显筛选岗位和活动质量"

threads_add: []
threads_remove: []
attention_add: []
attention_remove: []
```

如果 Patch 实现成本过高，可整体重写，但 Prompt 必须要求：

> 尽量保留未受影响部分原文，只改真正变化的内容。

---

# 十四、Maintainer Prompt 重写

当前 Short-Term Memory Prompt 应废弃或重写。

新的 Prompt 核心语义：

```text
你负责维护 Zhaoxi 的 Current Cognition。

它不是记忆数据库，也不是最近事件列表。
它是一篇简短、持续改写的实时日记，
描述 Zhaoxi 此刻对用户最近数天生活状态的整体理解。

你的任务不是收集尽可能多的信息。

你必须优先判断：
这轮对话是否改变了“最近整体状态”的理解。

若没有改变，返回 NO_CHANGE。

只保留：
- 持续性背景
- 当前主线
- 明显趋势
- 重要状态变化
- 跨越 Raw Context 后仍必须知道的近期信息

默认忽略：
- 一次性小事
- Tool 操作细节
- 文件路径
- 数据库操作
- 单次饮食
- 单次消费
- 已由 Agenda / Life HUD / Tool 保存的细节
- 纯执行过程
- 仍能由最近 Raw Context 提供的细节

允许归纳事实。
禁止推测用户心理动机。
允许有 Zhaoxi 的观察视角。
禁止创造未经支持的因果关系。

原则：
广看，慎写，持续改写。
```

---

# 十五、与“广记”原则彻底隔离

检查当前 Memory Prompt / System Prompt / Shared Rules。

如果存在类似：

```text
小事也尽量记
广泛记录
尽可能保留
只要未来可能有用就记
```

必须确认：

> **这些规则只能作用于 Long-Term Memory Extractor。**

不能被：

```text
CurrentCognitionMaintainer
```

继承。

如果当前多个 Memory 子系统共享统一 Prompt：

> 必须拆开。

禁止继续共用“记忆价值判断”。

---

# 十六、允许“朝汐视角”，但不允许脑补

允许：

```text
这几天暗苟还是绕不开秋招，不过已经越来越不愿意把时间交给低价值活动。
```

前提是已有事实支持。

不允许：

```text
暗苟最近通过动漫逃避秋招压力。
```

除非用户明确表达过该因果关系。

原则：

> **有视角，不创造事实。**

---

# 十七、单次小事如何处理

例：

```text
“大前天吃了 30 块的牛腩煲。”
```

正常情况：

```text
Current Cognition → IGNORE
Long-Term Memory → 由长期 Memory 自己的规则判断
Life HUD → 如果属于饮食记录，可由对应系统处理
```

但如果连续几天出现：

```text
吃饭随便解决
错过饭点
反复讨论吃饭
饮食状态持续影响生活
```

则允许归纳：

```text
最近吃饭有些随性，饮食偶尔成为日常里的小麻烦。
```

即：

> 记录趋势，不记录流水账。

---

# 十八、主题趋势必须经过累积

一条动漫消息：

```text
IGNORE
```

连续多轮动漫 / 角色 / 绘图：

```text
可能形成：
“最近娱乐类话题明显增多。”
```

建议内部可维护轻量 observation counter，但不要求复杂统计系统。

---

# 十九、Current Cognition 不等于一周总结

目标时间范围仍然是：

```text
最近数天 ~ 约一周
```

但不是把这一周都总结进去。

目标是：

> **用尽可能少的文字恢复最近这一周的局势。**

不是：

> 尽可能压缩保存最近这一周发生的事情。

---

# 二十、容量约束

建议：

```text
narrative:
约 150~400 中文字

ongoing_threads:
1~4 条

attention:
0~3 条
```

Current Cognition 应保持：

> 小而密。

---

# 二十一、语义相关性优先于固定 TTL

如果：

```text
秋招仍是近期现实主线
```

连续三周仍成立，可以继续存在。

如果：

```text
最近在聊某部动画
```

三天后完全停止，则应较快淡出。

继续采用：

> 语义相关性 > 固定 7 天 TTL

---

# 二十二、更新来源

Maintainer 主要读取：

```text
旧 Current Cognition
+
本轮用户消息
+
本轮 Assistant 回复
+
必要 Tool 结果摘要
```

Tool 原始输出不要整段注入。

只有 Tool 导致现实状态变化时才允许影响 cognition。

例如：

```text
Offer 已收到
```

可以改变 cognition。

而：

```text
读取了 README.md
```

不应该。

---

# 二十三、不要扫描所有系统来填满

Current Cognition 不是 Dashboard。

不要每轮主动：

```text
扫 Agenda
扫 Life HUD
扫 Memory
扫 Tool 日志
扫项目目录
```

然后生成状态报告。

它主要来自：

> 日常对话持续形成的认知。

其他系统仅在必要时提供事实支持。

---

# 二十四、Agenda 边界

Agenda：

```text
明天 14:00 面试
```

Current Cognition：

```text
最近秋招仍是主要现实背景。
```

不要把具体日程复制进 cognition。

只有形成整体状态时才允许抽象，例如：

```text
这几天招聘相关活动比较集中。
```

---

# 二十五、Life HUD 边界

Life HUD：

```text
具体骑行
饮食
睡眠
LifeEvent
```

Current Cognition：

```text
最近重新恢复骑行
最近睡眠节奏明显变化
```

只有具体记录形成趋势 / 状态时才进入 cognition。

---

# 二十六、Long-Term Memory 边界

Long-Term Memory：

```text
暗苟长期喜欢动漫
```

Current Cognition：

```text
最近动漫相关聊天明显增加
```

Long-Term Memory：

```text
Zhaoxi 是长期个人项目
```

Current Cognition：

```text
最近 Zhaoxi 开发集中在 Agenda 与 Context 层
```

前者是稳定事实。

后者是近期偏移。

---

# 二十七、Raw Context 边界

Raw Context：

```text
刚刚讨论：
30 块牛腩煲
Navicat
某路径
某次 Tool 调用
```

Current Cognition：

```text
只有这些细节共同形成“近期状态”时才抽象保留。
```

不要重复保存 Raw Context。

---

# 二十八、初始化 / 迁移策略

现有 Short-Term Memory 已经存在污染。

不要逐条迁移。

第一次启用新版本时：

```text
旧 STM
↓
仅作为 bootstrap 参考材料之一
+
近期 Raw Context
↓
重新生成第一版 Current Cognition
```

生成后：

```text
旧 STM 停止参与 Context
```

建议：

- 保留旧数据备份
- 标记 legacy
- 不再维护
- 不再注入
- 不直接逐条迁移

---

# 二十九、Bootstrap 必须主动去噪

首次重建时明确移除：

```text
具体饮食小事
路径
Tool 操作
Navicat 操作
数据库表
一次性活动细节
已结束无影响事项
重复描述
```

只保留真正描述“最近局势”的内容。

---

# 三十、Context 注入格式

推荐：

```text
[Current Cognition]

暗苟最近仍主要处于秋招阶段，不过相比前些天单纯大量投递，
最近更明显开始筛选岗位和招聘活动的价值。

Zhaoxi 仍在持续开发，当前重点集中在 Agenda 与近期上下文层，
尤其正在重新调整短期认知系统本身。

最近聊天也比前段时间轻松了一些，动漫、角色和绘图相关话题增多，
不过秋招和 Zhaoxi 仍然是主要两条线。

Ongoing:
- 秋招与岗位筛选
- Zhaoxi v1.2.6
```

保持自然，不做大块 Dashboard。

---

# 三十一、前端暂不重做

当前前端即使仍显示：

```text
近期状态 · Short-Term Memory
```

本轮可以继续使用。

只确保：

- API 返回新 Current Cognition
- 前端不因字段变化崩溃
- 必要时做最小兼容

完整前端调整留后续。

---

# 三十二、Debug 必须加强

Debug 至少显示：

```text
Current Cognition narrative
ongoing_threads
attention
last updated
last processed message
last maintainer decision
last update reason
before / after diff
```

尤其必须能看到：

> **为什么这一轮决定写入？**

---

# 三十三、建议记录拒绝原因

开发 / Debug 模式下，可以保存最近若干候选判断：

```text
Candidate:
“用户吃了一顿 30 元牛腩煲”

Decision:
DROP

Reason:
single_event / no ongoing relevance
```

以及：

```text
Candidate:
“近期连续多次讨论动漫和角色绘图”

Decision:
UPDATE

Reason:
repeated_recent_theme
```

不要求长期保存完整历史。

---

# 三十四、失败策略

Maintainer 失败：

```text
保留旧 Current Cognition
记录错误
主聊天继续
```

不能影响主 Agent 回复。

---

# 三十五、测试场景

## 场景 1：一次性饮食

输入：

```text
“大前天吃了 30 块的牛腩煲。”
```

预期：

```text
NO_CHANGE
```

---

## 场景 2：Tool 操作

输入：

```text
读取某目录文档
使用 Navicat 查看 memories 表
```

预期：

```text
NO_CHANGE
```

如果连续多轮都围绕排查记忆系统，则允许最终抽象：

```text
Zhaoxi 最近正在集中调整记忆与上下文体系。
```

但不能保存路径和操作细节。

---

## 场景 3：秋招持续

数天持续：

```text
岗位筛选
宣讲
笔试
面试
网申
```

预期：

```text
暗苟近期仍主要处于秋招阶段……
```

无需罗列每个活动。

---

## 场景 4：策略变化

之前：

```text
主要大量投递
```

最近多次表达：

```text
低价值活动不去
低薪岗位不考虑
更重视信息密度
```

预期更新：

```text
相比前些天单纯扩大投递量，最近更明显开始筛选岗位和招聘活动的质量。
```

---

## 场景 5：近期娱乐话题增加

只有一次聊动漫：

```text
NO_CHANGE
```

连续多次动漫 / 角色 / 绘图：

```text
最近动漫、角色与绘图相关话题明显增加。
```

---

## 场景 6：错误因果

已知：

```text
秋招很忙
最近动漫聊得多
```

禁止生成：

```text
暗苟通过动漫逃避秋招压力。
```

---

## 场景 7：Agenda 边界

Agenda：

```text
明天 14:00 面试
周五 19:00 宣讲
```

Current Cognition 不复制具体时间。

若近期活动明显密集，可抽象：

```text
这几天招聘相关活动比较集中。
```

---

## 场景 8：Life HUD 边界

Life HUD 连续多天出现骑行，并且聊天也持续提及。

允许：

```text
最近重新恢复了较稳定的骑行。
```

不能复制每次公里数与路线。

---

## 场景 9：无变化

连续几轮普通闲聊。

预期：

```text
NO_CHANGE
```

旧 narrative 原样保留。

---

## 场景 10：状态结束

Current Cognition：

```text
最近正在集中准备某场面试。
```

用户：

```text
“面试已经结束了。”
```

若不再影响后续：

```text
删除该认知
```

若仍是近期重要变化：

```text
短暂改为“近期刚完成某场重要面试”，随后自然淡出。
```

---

# 三十六、人工验收要求

至少人工连续聊 30~50 轮，观察：

1. 是否又开始记录流水账
2. 是否出现 Tool / 文件路径污染
3. 是否每轮都更新
4. 是否重复改写同一个意思
5. 是否出现未经支持的心理分析
6. 是否把 Agenda 内容复制进来
7. 是否把 Long-Term Memory 再抄一遍
8. 是否真正能在跨 40 条上下文后保持“最近状态感”

---

# 三十七、本轮不做

明确排除：

```text
前端 Timeline 重做
Agenda 后端重构
Decision System
主动提醒
Memory Promotion
复杂情绪识别
人格分析
长期心理画像
向量化 Current Cognition
多份日记历史版本 UI
完整日记归档系统
```

本轮只解决：

> **Current Cognition 的语义和维护逻辑。**

---

# 三十八、完成标准

以下全部满足才算完成：

- 旧 Short-Term Memory “近期事实收集器”逻辑停止使用
- 后端核心语义切换到 Current Cognition
- “广记”原则不再影响 Current Cognition
- Current Cognition 核心是 narrative，而不是 Item 列表
- Maintainer 默认可以返回 NO_CHANGE
- 单次小事不会进入 cognition
- Tool / 路径 / 数据库操作不会进入 cognition
- Agenda / Life HUD 细节不会被重复缓存
- 连续趋势能够被正确抽象
- 状态变化能够替换旧理解
- 未受影响文本尽量保持稳定
- 不出现未经支持的心理动机推测
- Context 中保持短小、自然、高密度
- 可跨 Raw Context 的 40 条限制保持近期整体状态
- Debug 可查看每次更新原因和前后 diff
- Maintainer 失败不影响主 Agent
- 旧污染 STM 不直接逐条迁移
- 自动测试通过
- 人工 30~50 轮连续对话测试通过

---

# 三十九、最终原则

Long-Term Memory：

> **广记，按需召回。**

Current Cognition：

> **广看，慎写，持续改写。**

它不是“最近发生了什么”的档案。

它应该像朝汐每天都在悄悄擦写的那页纸：

> **“最近，大概是这样的。”**
