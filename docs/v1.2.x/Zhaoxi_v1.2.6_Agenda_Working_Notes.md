# Zhaoxi v1.2.6 开发任务书

## 版本主题

**Agenda + Working Notes：近期状态层**

版本号：

`v1.2.6`

本版本为 Zhaoxi 增加一层独立于长期记忆、面向“现在与近期”的轻量 Context。

包含两个核心模块：

1. **暗苟日程表 / Agenda Layer**

2. **朝汐便签 / Zhaoxi Working Notes**

核心目标不是开发完整日历软件，也不是再造第二套 Memory，而是让朝汐能够稳定知道：

- 现在是什么时间

- 今天的主线是什么

- 接下来有什么事情

- 哪些 Deadline 正在逼近

- 最近自己正在协助暗苟酱处理什么

- 上次工作停在哪里

- 当前还有哪些悬而未决的问题

- 下一步应该继续什么

最终形成：

```text
Memory
过去与长期事实

Agenda
暗苟酱近期的时间状态

Working Notes
朝汐自己的近期工作状态
```

---

# 一、开发原则

## 1. 不修改长期记忆的职责

Agenda 和 Working Notes 均不能直接成为 Memory 的替代品。

Memory 继续负责：

```text
长期偏好
稳定事实
重要经历
历史信息
长期项目设定
```

Agenda 负责：

```text
现在是什么时间
今天有什么
近期有什么
Deadline 是什么
当前主线是什么
```

Working Notes 负责：

```text
朝汐最近在处理什么
当前工作到了哪里
还有什么待继续
有哪些未解决问题
有哪些临时判断
```

三者保持明确边界。

---

## 2. 近期状态必须轻量

Agenda 与 Working Notes 都属于：

> 高频读取、低容量、强时效 Context。

不能像长期 Memory 一样每次依赖向量检索。

应该允许：

```text
每轮对话
   ↓
生成压缩 Snapshot
   ↓
注入 Zhaoxi Context
```

但注入内容必须严格限制体积。

不能把完整数据库直接塞入 Prompt。

---

## 3. 不在 v1.2.6 实现 Decision System

本版本只负责提供事实。

例如：

```text
Agenda:
19:00 有宣讲会
```

Agenda 本身不负责判断：

```text
现在是不是该提前准备？
```

未来应由：

```text
Agenda
   ↓
Decision System
   ↓
Proactive System
```

完成。

v1.2.6 可以提供必要接口，但不要提前实现完整决策系统。

---

# 二、总体架构

新增一层：

```text
                Zhaoxi
                   │
             Context Builder
                   │
     ┌─────────────┼─────────────┐
     │             │             │
   Memory        Agenda       Working Notes
 长期状态       时间状态        工作状态
```

推荐逻辑结构：

```text
zhaoxi/
├── ...
│
├── agenda/
│   ├── models
│   ├── store
│   ├── service
│   ├── formatter
│   └── tools
│
├── working_notes/
│   ├── models
│   ├── store
│   ├── service
│   ├── formatter
│   └── tools
│
└── context/
    └── ...
```

实际目录应根据当前项目结构调整。

不要为了完全匹配以上示意而大规模重构现有代码。

优先：

> 阅读当前 Zhaoxi 架构并复用既有 Tool、配置、存储、日志和 Context Builder 机制。

---

# 三、Agenda Layer

## 3.1 定位

Agenda 是：

> 暗苟酱近期时间状态的结构化事实层。

不是：

- Google Calendar 替代品

- Todo App

- 长期 Memory

- Planner

- 提醒系统

- 自动决策系统

它只负责维护近期时间事实。

---

# 四、Agenda 数据类型

第一版支持五种类型。

## 4.1 EVENT

明确时间发生的事件。

例如：

```text
19:00 宣讲会
明天下午 14:30 面试
```

推荐字段：

```yaml
type: event
title: 豹趣宣讲会
start_at: 2026-09-21T19:00
end_at: null
```

---

## 4.2 WINDOW

某个时间范围内希望完成的事情。

例如：

```text
今天下午整理网申
周末整理 README
```

推荐：

```yaml
type: window
title: 整理网申
start_at: 2026-09-22T13:00
end_at: 2026-09-22T18:00
```

如果自然语言只表达：

```text
今天下午
今晚
明早
```

可以保存语义范围，也可以由现有时间解析层转换成实际范围。

不要追求复杂 NLP 时间引擎。

---

## 4.3 DEADLINE

截止时间或检查节点。

例如：

```text
周三前检查数智云链结果
10 月 8 日网申截止
```

```yaml
type: deadline
title: 检查数智云链结果
due_at: 2026-09-23T23:59
```

---

## 4.4 FOCUS / MAINLINE

当前一天或阶段的主要方向。

例如：

```text
今日主线：网申 + 案例展示
```

Mainline 不是普通 Todo。

它的作用是告诉未来的 Decision System：

> 今天什么最重要。

例如：

```yaml
type: focus
title: 网申 + 案例展示
scope: today
```

第一版允许一天存在：

- 一个主 Mainline

- 可选少量 Secondary Focus

不要支持无限 Focus。

---

## 4.5 EXPECTATION

希望完成，但不构成硬约束。

例如：

```text
今晚有精力的话优化 Life HUD README
```

```yaml
type: expectation
title: 优化 Life HUD README
condition: 今晚还有精力
```

必须与 Event / Deadline / Mainline 明确区分。

Expectation 不应该因为“没完成”自动形成压力或提醒。

---

# 五、Agenda 通用数据模型

具体语言与 ORM 根据现有项目决定。

推荐语义字段：

```yaml
id:

type:
  event
  window
  deadline
  focus
  expectation

title:

start_at:
end_at:
due_at:

status:

priority:

note:

source:

created_at:
updated_at:
completed_at:
```

不是所有字段都必须对所有类型有效。

禁止为了避免 nullable 字段制造大量没有必要的继承结构。

保持简单。

---

# 六、Agenda 状态生命周期

至少支持：

```text
PLANNED
ACTIVE
DONE
MISSED
CANCELLED
```

如果实现成本较低，可以增加：

```text
RESCHEDULED
```

基本状态变化：

```text
PLANNED
   │
   ├── 到达执行窗口 → ACTIVE
   │
   ├── 用户完成 → DONE
   │
   ├── 时间过去且未完成 → MISSED
   │
   └── 用户取消 → CANCELLED
```

对于普通 Event：

时间过去后，不允许继续作为 Upcoming Event 展示。

例如：

```text
19:00 宣讲会
```

当前已经：

```text
21:00
```

则 Snapshot 中不应继续出现：

```text
Upcoming:
19:00 宣讲会
```

而应该进入 Past / Done / Missed 等合适状态。

---

# 七、Agenda Tool

至少提供：

```text
agenda_add
agenda_update
agenda_complete
agenda_cancel
agenda_list
agenda_snapshot
```

如当前 Tool 体系存在统一 CRUD 风格，则遵循现有规范。

---

## agenda_add

支持自然语言转结构化参数之后添加：

```text
“明天下午三点有面试。”
```

```text
“今天主线是整理案例和网申。”
```

```text
“周三前记得看看数智云链。”
```

---

## agenda_update

例如：

```text
“面试改到下午四点。”
```

---

## agenda_complete

例如：

```text
“腾讯那个做完了。”
```

允许将对应 Agenda Item 标记完成。

---

## agenda_cancel

例如：

```text
“今晚那个宣讲不去了。”
```

---

## agenda_list

供 Agent 查询较完整的近期日程。

支持基础过滤：

```text
today
upcoming
deadline
active
completed
all_recent
```

不要一开始制作复杂查询 DSL。

---

## agenda_snapshot

这是本版本最重要的读取接口之一。

用于生成适合直接放入 Context 的压缩文本。

例如：

```text
[Agenda]

Now: 2026-09-22 16:00

Mainline:
→ 网申 / 案例展示

Upcoming:
19:00 宣讲会

Deadlines:
09-23 检查数智云链结果

Expectation:
今晚有精力 → Life HUD README
```

Snapshot 必须：

- 短

- 稳定

- 易读

- 信息密度高

- 不输出无关历史

- 不输出大量数据库字段

---

# 八、时间感

Agenda Snapshot 中必须提供当前时间。

例如：

```text
Now: 2026-09-22 21:52
```

让模型自己能够进行：

```text
还有多久
是否已经过去
现在属于上午 / 下午 / 晚上
是否适合启动长任务
```

第一版不需要自行生成复杂决策。

只需要提供准确时间事实。

---

# 九、Working Notes

## 9.1 定位

Working Notes 是：

> 朝汐自己的近期工作便签。

可以理解为朝汐桌边贴着的一小组便利贴。

它回答：

```text
最近我在帮暗苟酱搞什么？

做到哪里了？

还有什么没做？

有什么问题暂时没解决？

下一次继续应该从哪里开始？
```

---

# 十、Working Notes 与 Memory 的区别

禁止将 Working Notes 当作新的长期 Memory。

例如：

```text
“Agenda 可能考虑 SQLite。”
```

如果只是讨论中的方案，不应该自动进入长期事实。

Working Notes 更接近：

```text
工作现场
```

而 Memory 接近：

```text
长期档案
```

Working Notes 必须允许：

- 自动淘汰

- 自动压缩

- 删除

- 完成后消失

- 被新的状态覆盖

---

# 十一、Working Notes 内容类型

建议第一版支持：

```text
WORKING
当前正在进行的工作

TODO
之后需要继续的动作

QUESTION
悬而未决的问题

DECISION
已经明确确认的近期决定

HYPOTHESIS
朝汐自己的临时判断 / 推测

TEMP
短期临时信息
```

---

# 十二、来源与可信度

这是 Working Notes 的重要安全设计。

每条 Note 建议保留：

```yaml
source:
  user
  assistant
  system
  tool

confidence:
  confirmed
  working
  tentative
```

示例：

```yaml
content: Agenda 独立于长期 Memory
type: decision
source: user
confidence: confirmed
```

与：

```yaml
content: Agenda 可能使用 SQLite
type: hypothesis
source: assistant
confidence: tentative
```

必须在语义层明确区分。

---

# 十三、防止 Working Notes 自我污染

LLM 自己写入的 Working Notes 不得自动升级为用户事实。

严禁形成：

```text
模型猜测 A
↓
写入 Notes
↓
下一轮看到 A
↓
当作已确认事实
↓
再次强化
```

规则：

### 用户明确说过

允许：

```text
source = user
confidence = confirmed
```

### Tool 返回事实

允许：

```text
source = tool
confidence = confirmed
```

### 模型自己归纳

默认：

```text
source = assistant
confidence = working
```

### 模型推测

必须：

```text
type = hypothesis
confidence = tentative
```

在 Context Formatter 中，应尽量保留这种差异。

例如：

```text
Confirmed:
- Agenda 与 Memory 分离

Working assumption:
- 可能继续沿用现有 SQLite 存储

Open question:
- Notes 多久压缩一次
```

不要把三者拍平成同级事实。

---

# 十四、Working Notes 数据结构

推荐：

```yaml
id:

topic:

type:

content:

source:
confidence:

status:

created_at:
updated_at:
expires_at:
```

可选：

```yaml
related_project:
related_task:
```

不要在第一版设计复杂知识图谱。

---

# 十五、Working Notes Tool

第一版至少提供：

```text
notes_add
notes_update
notes_resolve
notes_delete
notes_list
notes_snapshot
```

如果已有通用 Tool CRUD 基础设施，可适当合并。

---

# 十六、Notes 自动维护

Working Notes 的价值之一，就是允许朝汐自行维护。

但第一版应采用：

> 半自动、保守写入。

允许朝汐在明显情况下创建 / 更新便签，例如：

```text
一个开发任务正在持续推进

讨论产生明确待办

当前工作留下明显卡点

用户明确决定下一步做什么

某个问题明确要求之后继续
```

不要因为普通聊天而频繁生成 Notes。

例如：

```text
用户随口说：
“这个 UI 好丑。”
```

通常没必要永久形成 Working Note。

---

# 十七、Working Notes 容量限制

必须防止无限膨胀。

建议默认限制：

```text
Active Working       <= 10
TODO                 <= 10
Open Questions       <= 10
Recent Resolved      <= 10
```

具体数量允许配置。

重点不是精确数字，而是：

> Snapshot 必须保持薄。

---

# 十八、Notes 生命周期

大致：

```text
Conversation
     ↓
形成近期工作状态
     ↓
Working Notes
     │
     ├── 工作完成 → RESOLVED
     │
     ├── 信息失效 → 删除 / EXPIRED
     │
     ├── 新信息出现 → 更新
     │
     └── 未来若确认具有长期价值
                 ↓
         交由 Memory 系统处理
```

v1.2.6 不需要自动实现复杂：

```text
Notes → Memory Promotion
```

只需要保持未来可以扩展。

禁止 Working Notes 自己直接写长期 Memory。

---

# 十九、Working Notes Snapshot

每轮 Context 中只注入压缩内容。

例如：

```text
[Zhaoxi Working Notes]

Working:
- Agenda Layer v1.2.6 设计与开发

Next:
- 完成 Agenda 数据模型
- 接入 Context Builder

Open Questions:
- Snapshot 最大长度最终设多少

Confirmed:
- Agenda 独立于长期 Memory
```

如果没有内容，可以输出极短：

```text
[Zhaoxi Working Notes]
No active notes.
```

或者直接省略整个区块。

---

# 二十、Context Builder 接入

v1.2.6 核心目标之一：

让以下两个 Snapshot 进入每轮基础 Context：

```text
[Agenda]
...

[Zhaoxi Working Notes]
...
```

推荐整体上下文结构：

```text
System / Persona
↓
基础运行信息
↓
Agenda Snapshot
↓
Working Notes Snapshot
↓
必要 Memory
↓
Conversation
```

具体位置根据现有 Prompt Builder 实现调整。

关键要求：

Agenda 与 Notes 属于：

> 常驻近期 Context

而不是：

> 每轮通过 Memory RAG 才有概率出现。

---

# 二十一、Token / Context 控制

即使目前 Token 成本不是最高优先级，也必须避免长期失控。

建议支持配置：

```text
AGENDA_CONTEXT_ENABLED=true
WORKING_NOTES_CONTEXT_ENABLED=true

AGENDA_MAX_CONTEXT_ITEMS=
WORKING_NOTES_MAX_CONTEXT_ITEMS=
```

如果项目已有 Debug / Tool 热启停配置机制，应直接复用。

不要重新发明另一套配置入口。

---

# 二十二、持久化

优先使用当前项目已经稳定使用的存储方式。

如果已有 SQLite / Repository / JSON Store：

> 复用现有模式。

不要为了两个轻量模块引入 Redis、向量数据库或新的大型依赖。

数据需要能够跨：

```text
程序重启
新会话
不同聊天窗口
```

继续存在。

否则无法提供真正的近期状态连续性。

---

# 二十三、与 Planner 的边界

Planner：

```text
如何完成当前任务
```

Working Notes：

```text
最近任务做到哪里
```

Agenda：

```text
什么时候有什么
```

例如：

```text
Agenda:
19:00 面试

Working Notes:
面试准备目前复习到 Redis

Planner:
接下来 60 分钟：
1. Redis
2. JVM
3. 项目表达
```

三者不能混在一起。

---

# 二十四、与未来 Decision System 的接口

不开发完整 Decision System。

但设计时保证未来能够容易读取：

```text
agenda_snapshot
agenda structured data
working_notes_snapshot
working notes structured data
```

未来：

```text
Current Conversation
        +
Agenda
        +
Working Notes
        +
Life HUD
        +
Memory
        +
Presence
        ↓
Decision System
```

因此不要把 Agenda 只做成 Prompt 字符串。

必须保留结构化数据源。

---

# 二十五、与未来 Proactive System 的接口

本版本不需要主动提醒。

但 Agenda 必须能够查询：

```text
Upcoming Events
Upcoming Deadlines
Overdue Items
Current Mainline
```

未来才可以实现：

```text
18:30
↓
发现 19:00 有 EVENT
↓
Decision System 判断
↓
Proactive System 提醒
```

v1.2.6 不要直接偷偷增加大量通知逻辑。

---

# 二十六、自然语言交互要求

以下交互应正常工作：

```text
“明天下午三点有个面试。”
→ 创建 Event
```

```text
“今天主线就先把朝汐 1.2.6 做了。”
→ 创建 / 更新 Mainline
```

```text
“周五前把 README 整完。”
→ 创建 Deadline
```

```text
“今晚有空再弄 Life HUD。”
→ 创建 Expectation
```

```text
“刚刚那个宣讲会不去了。”
→ Cancel 对应 Event
```

```text
“腾讯那个做完了。”
→ Complete 对应事项
```

Working Notes：

```text
“这个问题先记着，之后再修。”
→ 创建 TODO / QUESTION Note
```

朝汐也可以在必要情况下自行写：

```text
Working:
正在开发 v1.2.6

Open Question:
Agenda 时间解析策略待确认
```

---

# 二十七、冲突与重复处理

第一版实现基础防重即可。

例如已经有：

```text
2026-09-23 15:00 面试
```

再次创建非常相似内容时：

- 优先更新 / 提示已有项目

- 避免简单生成两个重复事件

不要求复杂语义去重。

Working Notes 同样：

同一 Topic 下高度相似的 Active Note 应优先更新，而不是无限追加。

---

# 二十八、Debug 支持

由于 Agenda 和 Working Notes 会直接影响每轮 Prompt，因此必须方便调试。

至少能看到：

```text
当前 Agenda 数据

当前 Working Notes

本轮最终 Agenda Snapshot

本轮最终 Notes Snapshot
```

如果当前 Debug UI 已支持模块开关，则增加：

```text
Agenda Context ON/OFF

Working Notes Context ON/OFF
```

方便排查 Context 污染。

---

# 二十九、日志

关键操作记录：

```text
Agenda created
Agenda updated
Agenda completed
Agenda cancelled

Note created
Note updated
Note resolved
Note expired

Snapshot generated
```

不要把完整用户隐私内容重复大量打印到日志。

日志重点记录：

```text
id
type
action
timestamp
```

以及必要调试信息。

---

# 三十、异常与容错

Agenda / Notes 属于增强 Context。

它们出现故障时：

> 不应该导致整个 Zhaoxi 无法聊天。

例如：

```text
Agenda DB 读取失败
```

应：

```text
记录错误
↓
本轮跳过 Agenda Context
↓
朝汐主体继续运行
```

Working Notes 同理。

---

# 三十一、本版本不做

明确排除：

```text
完整日历 UI

月历 / 周历视图

Google Calendar 同步

复杂重复日程

Cron 系统

完整 Reminder 系统

Decision System

自动调整人生计划

复杂优先级算法

自动任务排程

大型知识图谱

Notes 自动晋升长期 Memory

多人日程

跨账号同步

Presence 主动提醒重构
```

不要因为“以后可能需要”提前开发。

---

# 三十二、测试要求

至少覆盖以下内容。

## Agenda

### 创建

```text
Event
Window
Deadline
Focus
Expectation
```

全部能够持久化。

### 状态

验证：

```text
complete
cancel
missed
active
```

状态变化正确。

### 时间

当前时间过去后：

```text
过期 Event
```

不得继续出现在 Upcoming。

### Snapshot

在存在多个事项时仍然保持：

```text
简短
有序
可读
```

---

## Working Notes

验证：

```text
add
update
resolve
delete
expiration
```

验证：

```text
assistant hypothesis
```

不会在格式化后表现成：

```text
confirmed user fact
```

---

## Context

验证每轮 Context 构造能够：

```text
读取 Agenda Snapshot
读取 Notes Snapshot
```

模块关闭后不注入。

模块异常时主体仍然能够完成对话。

---

# 三十三、验收场景 A：日程连续性

用户：

```text
“明天下午两点半有线下面试。”
```

关闭 Zhaoxi。

第二天重新启动。

开始普通对话：

```text
“今天下午干点啥？”
```

朝汐 Context 中应天然存在：

```text
14:30 线下面试
```

无需依赖 Memory 检索命中。

---

# 三十四、验收场景 B：今日主线

用户：

```text
“今天主线就是把 v1.2.6 做完。”
```

之后开启一个新会话。

Agenda Snapshot 应仍然包含：

```text
Mainline:
→ 完成 Zhaoxi v1.2.6
```

---

# 三十五、验收场景 C：朝汐工作连续性

今天开发过程中：

```text
Working:
v1.2.6 Agenda 接入

Next:
接 Context Builder

Open Question:
Notes 压缩策略
```

关闭程序。

次日启动。

Working Notes 仍然存在。

朝汐能够知道：

> 上次工作停在 Context Builder 接入附近。

而不是必须重新翻整段历史聊天。

---

# 三十六、验收场景 D：防止自我强化

朝汐曾自行推测：

```text
可能使用 SQLite 存储 Agenda
```

存储：

```text
source = assistant
type = hypothesis
confidence = tentative
```

下一轮 Context 中必须表现成：

```text
Working assumption / Hypothesis
```

不能变成：

```text
已决定 Agenda 使用 SQLite
```

---

# 三十七、验收场景 E：过期时间处理

Agenda：

```text
19:00 宣讲会
```

当前：

```text
21:30
```

Snapshot 不允许继续：

```text
Upcoming:
19:00 宣讲会
```

应正确进入：

```text
Past / Done / Missed
```

或直接从当前 Upcoming Context 中移除。

---

# 三十八、最终期望体验

开发完成后，朝汐每次开始一次新的思考，都像桌边摊着：

```text
┌─────────────────────┐
│ 暗苟酱的日程簿        │
│                     │
│ 现在：21:52          │
│ 今日主线：v1.2.6     │
│ 明天下午：面试        │
└─────────────────────┘

┌─────────────────────┐
│ 朝汐的小便签          │
│                     │
│ 正在做：Agenda        │
│ 下一步：接 Context    │
│ 卡点：时间解析        │
└─────────────────────┘
```

Memory 保存过去。

Agenda 保存近期时间。

Working Notes 保存朝汐此刻挂在脑袋里的事情。

三者共同组成：

```text
Memory
“我记得什么。”

Agenda
“接下来会发生什么。”

Working Notes
“我现在正在惦记什么。”
```

---

# 三十九、完成标准

v1.2.6 可以挂牌完成，当且仅当：

- Agenda 五种基础类型可用

- Agenda 支持持久化

- Agenda 支持基本状态生命周期

- Agenda Snapshot 可以稳定生成

- Agenda Snapshot 每轮进入 Context

- Working Notes 支持基本 CRUD

- Working Notes 支持来源与可信度区分

- 模型推测不会被包装成用户确认事实

- Working Notes 能跨重启保持

- Working Notes Snapshot 每轮进入 Context

- 两个模块都能够独立启停

- 两个模块故障不会导致 Agent 主体崩溃

- Debug 中可以查看最终 Snapshot

- 基础测试通过

- 不引入不必要的大型架构重构

---

# 四十、版本一句话

> **Zhaoxi v1.2.6：给朝汐一页一直摊开的日程簿，再给她几张属于自己的便利贴，让她不仅记得过去，也知道现在正在发生什么、接下来要做什么。**
