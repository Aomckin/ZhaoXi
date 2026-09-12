# Zhaoxi v1.1.5 Development Task
# 本体主权与能力边界（Core Sovereignty & Capability Boundary）

> 版本：v1.1.5
> 基线：v1.1.4 / v1.1.4.1 Memory Rework
> 主题：Core Decoupling / Tool Package Capability / LifeHUD Boundary / Interaction State Rework
> 核心目标：彻底明确并实现“朝汐本体不依赖任何具体 Tool”的架构边界，让 LifeHUD 从事实上的半内建模块退回为一个强大的、可选的外部能力包；同时重构状态机语义，使 ACTIVE / SEMI_ACTIVE 真正对应不同的运行行为。

---

## 0. 版本背景

当前 Zhaoxi 已逐步形成 Personality、Archive、Associative Memory、Proactive / Heartbeat、Interaction State Machine、Tool Package、Workflow、Reflection 与 LifeHUD integration。

但随着 Memory 和 Presence 变复杂，原本一些“先接上再说”的设计开始暴露出更根本的耦合问题：

1. LifeHUD 虽然已从 Core 源码依赖中抽离，但仍会因为包存在而自动启用。
2. 一个 Tool Package 当前可能同时被注入 Tool、Workflow、Router、Proactive、Reflection 五条运行链。
3. LifeHUD 的 Focus 等状态仍然间接影响 Zhaoxi Core 的 Presence / Proactive。
4. ACTIVE / SEMI_ACTIVE 当前主要只是不同阈值，而不是不同运行模式。
5. Memory 现在会低门槛记录生活小事，与 LifeHUD 结构化生活事实形成“双事实源”。
6. 现有路由关键词可能误劫持普通对话。
7. Tool Package 直接依赖多个 Core 内部模块，缺少稳定公开 SDK / Protocol。
8. 外部服务写入的权限语义仍被标成 LOCAL_STATE。
9. Tool Package 启动诊断不能区分 installed / configured / reachable。
10. LifeHUD 当前即使未运行，Heartbeat 仍可能周期尝试访问。

这些问题的共同根源是：

> **Zhaoxi Core 与某个具体 Tool 之间的边界还不够清楚。**

v1.1.5 要正式确立：

# Core Sovereignty

即：

> **朝汐可以被 Tool 增强，但不能被 Tool 定义。**

---

# 1. 总体架构原则

v1.1.5 之后必须满足：

```text
                 Zhaoxi Core
        ┌────────────┼────────────┐
        │            │            │
     Memory      State Machine   Agent
        │            │            │
        └────────────┼────────────┘
                     │
              Capability Layer
                     │
        ┌────────────┼────────────┐
        │            │            │
     LifeHUD      Desktop       Other Tools
```

禁止形成：

```text
Zhaoxi Core
    ↓
LifeHUD
    ↓
Memory / Presence / Proactive
```

---

# 2. 朝汐本体主权

强制约束：

## 2.1 无 LifeHUD 可完整运行

当：

- LifeHUD Tool Package 被禁用
- LifeHUD Tool Package 未安装
- LifeHUD 服务未运行
- LifeHUD API 不可达
- LifeHUD schema 暂时异常

Zhaoxi 仍必须能够正常：

- 启动
- 聊天
- Personality
- Session
- Memory
- Archive
- State Machine
- Proactive
- Reflection
- Planner / Workflow（除 LifeHUD 自己提供的 Workflow）
- Desktop Presence

LifeHUD 只能降低某些结构化生活信息的丰富度，不能导致 Core 行为失效。

---

# 3. LifeHUD 的定位

重新定义：

> **LifeHUD 是一个高能力、高贴合度的外部 Tool Package。**

它可以提供：

- 结构化生活数据
- Focus
- Task
- Sleep
- Diet
- Music
- Dream
- Agent Context
- 状态信号

但它不是：

- Zhaoxi 的 Memory
- Zhaoxi 的 State Machine
- Zhaoxi 的 Personality
- Zhaoxi 能否 Proactive 的必要前提
- Zhaoxi 的唯一事实源

---

# 4. 双事实源：Memory + LifeHUD

v1.1.5 不强制回到“LifeHUD 唯一事实源”。

允许：

```text
Memory
+
LifeHUD
```

同时存在。

但采用：

# 分域权威（Domain Authority）

---

# 5. 分域权威规则

## 5.1 结构化业务事实

例如：

```text
Focus 开始时间
Focus 持续时长
任务完成状态
LifeHUD 中记录的睡眠时间
LifeHUD 中明确填写的饮食记录
```

若 LifeHUD 当前可用：

```text
LifeHUD > Memory
```

## 5.2 生活经历与对话语境

例如：

```text
昨晚喝白朗姆时在聊什么
那顿饭当时觉得好不好吃
打舞萌回来后的心情
某次开发失败时的感受
```

优先：

```text
Memory
```

LifeHUD 即使有结构化记录，也不能替代生活语境。

## 5.3 朝汐正式设定

继续：

```text
current explicit user instruction
>
canonical Archive
>
Memory
```

---

# 6. Provenance

Memory / Tool Observation / Structured Fact 建议统一支持：

```text
source
domain
observed_at
valid_at
confidence
authority
external_ref?
```

回答时不必默认展示。

发生冲突时，系统应能判断：

> 这条事实是谁记录的、属于哪个领域、什么时候有效、为什么可信。

---

# 7. 同一事件可以双写，但语义不同

例如：

```text
“昨晚喝了白朗姆。”
```

可以同时存在：

## Memory

```text
EPISODIC
昨晚暗苟喝了白朗姆，当时还在继续讨论 Zhaoxi。
```

## LifeHUD

```text
drink:
type = rum
time = ...
amount = ...
```

二者不是重复垃圾。

一个是：

> 经历。

一个是：

> 结构化记录。

---

# 8. Tool Package 通用启停机制

新增通用配置：

```env
ZHAOXI_TOOL_<PACKAGE_ID>_ENABLED=true
```

例如：

```env
ZHAOXI_TOOL_LIFEHUD_ENABLED=false
```

要求：

- 包存在但 disabled 时完全不装配
- disabled 时不注册 Tool
- 不注册 Workflow
- 不注册 Router hint
- 不启动 Proactive provider
- 不启动 Reflection provider
- 不启动 StateSignal provider
- 不尝试网络访问
- diagnostics 明确显示 disabled

---

# 9. Package 状态

Tool Package 应能区分：

```text
installed
enabled
configured
reachable
healthy
```

例如：

```text
installed=true
enabled=true
configured=true
reachable=false
healthy=false
```

不要只显示 `ready`。

---

# 10. Tool Package Capability Declaration

当前一个包加载后会自动进入多条运行链。

改为显式 Capability 声明：

```text
tool
workflow
router_hints
proactive_provider
reflection_provider
state_signal_provider
```

Package 只装配自己明确声明的能力。

---

# 11. Capability 分项启停

支持包级总开关之外的细粒度开关，例如：

```env
ZHAOXI_TOOL_LIFEHUD_ENABLED=true
ZHAOXI_TOOL_LIFEHUD_PROACTIVE_ENABLED=false
ZHAOXI_TOOL_LIFEHUD_REFLECTION_ENABLED=false
ZHAOXI_TOOL_LIFEHUD_STATE_SIGNALS_ENABLED=true
```

具体命名按 Settings 风格统一。

---

# 12. State Signal Provider

新增正式公共协议：

```text
StateSignalProvider
```

职责：

> Tool / Sensor 只报告“观察到了什么”。

不直接修改 Interaction State。

---

# 13. StateSignal

建议结构：

```text
type
value
observed_at
expires_at
confidence
priority
source
metadata
```

例如 LifeHUD：

```text
type = "attention.focus"
value = "active"
source = "lifehud"
confidence = 1.0
```

Desktop：

```text
type = "desktop.fullscreen"
value = true
source = "desktop"
```

未来 Calendar：

```text
type = "availability.meeting"
value = "active"
source = "calendar"
```

---

# 14. Core 只认识 Signal，不认识 LifeHUD

禁止：

```python
if lifehud.focus_active:
    ...
```

Core 应只处理：

```text
StateSignal
```

例如：

```text
attention.focus = active
interruptibility = low
```

---

# 15. Signal Aggregator

新增：

```text
StateSignalProvider(s)
↓
Signal Aggregator
↓
Interaction State Machine / Proactive Policy
```

Aggregator 负责：

- 合并来源
- 处理 TTL
- 处理冲突
- 去重
- 按 priority / confidence 解析

---

# 16. Tool 不能直接设置 State Machine

禁止：

```text
LifeHUD -> set_state(SEMI_ACTIVE)
```

允许：

```text
LifeHUD -> emit(focus.ended)
```

最后由 Core 决定：

```text
ACTIVE
SEMI_ACTIVE
IDLE
AWAY
```

---

# 17. Interaction State 与 Interruptibility 分离

当前一个 state 容易同时承担：

- 用户是否在对话
- 用户是否在电脑前
- 能否打扰
- 后台应该干什么

v1.1.5 正式拆分：

```text
interaction_state
```

与：

```text
interruptibility
```

---

# 18. Interaction State

保留：

```text
ACTIVE
SEMI_ACTIVE
IDLE
AWAY
```

但重新定义语义。

---

# 19. ACTIVE

定义：

> **正在持续对话。**

触发：

- 用户直接发消息
- 用户回复 proactive
- 明确与 Zhaoxi 发生对话交互

持续：

```text
约 20 分钟
```

每次有效对话刷新 TTL。

---

# 20. ACTIVE 不只是低阈值 Proactive

ACTIVE 必须有独立行为：

# Conversation Continuation

系统允许在短暂停顿后主动继续当前对话。

不是要求世界发生新事件。

---

# 21. Conversation Continuation Candidate

候选来源：

```text
unfinished topic
recent question
user said "等下我去试试"
recent uncertainty
emotional thread
shared joke
recent plan
open conversational thread
```

---

# 22. ACTIVE 主动频率

建议：

```text
用户沉默 2~5 分钟
+
仍为 ACTIVE
+
存在 open thread
+
interruptibility != BLOCKED
+
近期未主动 continuation
```

才允许 LLM 判断是否继续。

---

# 23. ACTIVE 主动预算

建议：

```text
每个 ACTIVE window 最多主动 continuation 2~3 次
```

防止连续催促。

用户重新回应可刷新 conversation beat。

---

# 24. SEMI_ACTIVE

重新定义：

> **朝汐醒着，在附近，但没有正在持续对话。**

它基本继承旧 ACTIVE 的后台行为。

允许：

- 偶尔主动发言
- Tidal Heartbeat
- 低频提醒
- Memory 整理
- Cluster / Consolidation
- Background Intent
- 准备 future topic
- 准备 surprise candidate
- 观察状态信号

---

# 25. Background Intent

新增轻量内部概念：

```text
BackgroundIntent
```

例如：

```text
整理最近记忆
关注某个未完成的小事
准备之后可能有意义的话题
生成 surprise candidate
```

注意：

> prepare != send

SEMI_ACTIVE 可以准备，不代表立刻打扰用户。

---

# 26. Surprise Candidate

v1.1.5 不要求实现复杂惊喜系统。

允许定义最小接口：

```text
BackgroundIntent(type="surprise_candidate")
```

可能用于：

- 整理一个最近阶段的小回顾
- 发现某个纪念时间点
- 汇总某个反复提到的小主题
- 留待之后合适时机主动提起

禁止：

- 高频生成
- 强行通知
- 每天固定惊喜
- 额外大量 LLM 调用

---

# 27. IDLE

定义：

> 用户存在，但 Zhaoxi 当前处于低活动。

行为：

- 降低主动频率
- 保留低频 Heartbeat
- 仅执行必要后台维护
- 不运行高频 Conversation Continuation

---

# 28. AWAY

定义：

> 用户当前离开设备或不可交互。

行为：

- 普通 proactive 不弹出打扰
- 允许 inbox
- 允许必要后台维护
- 不进入 ACTIVE

---

# 29. 状态转换

建议：

```text
User message
↓
ACTIVE

ACTIVE
↓ 20min 无对话
SEMI_ACTIVE

SEMI_ACTIVE
↓ 长时间无相关活动
IDLE

Desktop idle / lock
↓
AWAY

AWAY
↓ resumed input
SEMI_ACTIVE
```

注意：

```text
AWAY -> return
```

不直接 ACTIVE。

只有真实 conversation event 才 ACTIVE。

---

# 30. interruptibility

建议独立枚举：

```text
HIGH
NORMAL
LOW
BLOCKED
```

---

# 31. interruptibility 来源

由 Signal Aggregator 综合：

```text
fullscreen
focus
meeting
lock
desktop activity
manual do-not-disturb
future signals
```

例如：

```text
ACTIVE + Focus
```

仍然可以是 ACTIVE，只是：

```text
interruptibility = LOW
```

即：

> 我们还在一段对话里，但现在先安静。

---

# 32. LifeHUD Focus 的新定位

LifeHUD 不再直接影响 InteractionState。

它只可以输出：

```text
attention.focus=active
```

或：

```text
focus.started
focus.ended
```

State Machine / Proactive Policy 自己解释这些信号。

---

# 33. Proactive 与 State 的新关系

普通 proactive 仍适合：

```text
event
↓
rule/score gate
↓
LLM
↓
delivery
```

ACTIVE Conversation Continuation 是独立路径：

```text
conversation context
↓
open thread detection
↓
continuation gate
↓
LLM
↓
delivery
```

不要强行塞进现有 event-only Proactive Gate。

---

# 34. Router 关键词劫持修复

当前简单子串：

```text
开幕
落幕
```

可能误触发 LifeHUD Workflow。

必须改为更严格识别。

推荐：

- 明确命令格式
- “朝汐 + 开幕/落幕”
- 完整短句匹配
- contextual route intent
- 避免普通文本子串强制路由

例如：

```text
“电影节今天开幕。”
```

不得触发 Focus Workflow。

---

# 35. Router Hint 优先级

Tool Package router hint：

> 只能提供 hint，不应拥有绝对劫持权。

Core Router 最终决定 route。

---

# 36. Tool Package SDK / Protocol

当前 LifeHUD Tool Package 直接依赖：

```text
zhaoxi.tools
zhaoxi.permission
zhaoxi.reliability
zhaoxi.proactive
zhaoxi.reflection
```

v1.1.5 需要冻结一层公开 SDK / Protocol。

建议：

```text
zhaoxi.sdk
```

至少公开：

```text
ToolProtocol
ToolPackageProtocol
CapabilityDeclaration
Permission models
StateSignalProvider
ProactiveProvider
ReflectionProvider
HealthCheckProtocol
```

Tool Package 不再 import Core 私有实现。

---

# 37. SDK 版本

建议：

```text
SDK_VERSION
```

Package manifest 声明：

```text
requires_sdk >=1.0,<2.0
```

不要仅依赖：

```text
zhaoxi>=0.9,<2
```

---

# 38. External Side Effect Permission

当前 LifeHUD：

```text
focus.start
focus.complete
```

通过 HTTP 修改另一个服务，却声明：

```text
WRITE + LOCAL_STATE
```

语义不准确。

新增或使用：

```text
EXTERNAL_SERVICE_WRITE
```

或：

```text
LOCAL_EXTERNAL_SERVICE_WRITE
```

要求审计语义明确：

> 这是对另一个本地服务的写操作。

即使服务在 localhost，也不应被视为 Core 自身本地状态。

---

# 39. Health Check

Tool Package 诊断增加短超时 health。

区分：

```text
installed
configured
reachable
healthy
```

例如服务未启动：

```text
installed=true
configured=true
reachable=false
healthy=false
```

Health Check 要求：

- 短 timeout
- 失败不阻断 Core
- 可异步 / 延迟
- diagnostics 可查看
- 不每 heartbeat 重复高频请求

---

# 40. Heartbeat 访问降噪

当 Provider 被判定：

```text
unreachable
```

Heartbeat 不应每两分钟持续请求。

建议：

```text
exponential backoff
或
provider health TTL
```

例如：

```text
2m
5m
15m
30m
```

服务恢复后自动恢复采样。

---

# 41. LifeHUD Provider 失败隔离

要求：

- signal provider exception 不影响 state machine
- proactive provider exception 不影响其他 providers
- reflection provider exception 不影响 Reflection 主体
- workflow provider failure 只影响对应 workflow
- tool failure 返回正常 Tool error

---

# 42. duplicate capabilities() 修复

LifeHUD package 当前重复定义 `capabilities()`。

删除重复实现，保留唯一来源。

加入测试防止未来静默覆盖。

---

# 43. Package Loader

建议流程：

```text
discover
↓
read manifest
↓
enabled?
↓
validate SDK compatibility
↓
load
↓
register declared capabilities only
↓
optional health check
```

---

# 44. Package disabled 时

必须验证：

```text
LifeHUD disabled
```

不会产生：

- Tool
- Workflow
- Router hint
- Heartbeat provider
- Reflection provider
- StateSignal provider
- HTTP request

---

# 45. Package unreachable 时

Package enabled 但服务不可达：

允许：

- Tool 名义上注册
- health 显示 unreachable
- Agent 调用 Tool 时给出明确错误
- proactive/state signal 进入 backoff
- Core 正常运行

---

# 46. 与 Memory 的关系

Memory 不依赖 LifeHUD。

LifeHUD 不可用时，Memory 仍可以记录：

- 吃饭
- 喝酒
- Focus 感受
- 某次任务
- 生活事件

但结构化字段精度可能低于 LifeHUD。

---

# 47. 冲突处理示例

Memory：

```text
昨晚大概专注了两个小时。
```

LifeHUD：

```text
Focus actual = 91min
```

若用户问精确时长：

```text
LifeHUD structured fact 优先
```

若用户问：

```text
昨晚专注时是什么感觉？
```

Memory 优先。

---

# 48. 无 LifeHUD 降级模式

若：

```text
lifehud.enabled=false
```

Core 不显示系统错误。

只有用户明确调用 LifeHUD 能力时才说明：

> 当前 LifeHUD 未启用 / 不可用。

---

# 49. 测试：Core Sovereignty

至少覆盖：

## A. LifeHUD package 不存在
Zhaoxi 启动成功，Memory / State / Proactive 正常。

## B. LifeHUD disabled
同上，且 0 次网络访问。

## C. LifeHUD enabled 但服务不可达
Core 正常运行，health 显示 unreachable。

## D. LifeHUD 恢复
Provider 可自动恢复采样。

---

# 50. 测试：Capability Declaration

分别关闭：

```text
proactive
reflection
state signals
workflow
```

只关闭对应能力。

Tool 本身仍可按配置保留。

---

# 51. 测试：Router

输入：

```text
电影节今天开幕。
```

不得触发 Focus Workflow。

输入：

```text
朝汐，开幕。
```

可以触发预期 Workflow。

---

# 52. 测试：StateSignal

构造：

```text
LifeHUD focus.active
Desktop fullscreen
Desktop idle
```

验证：

- Provider 只输出 Signal
- State Machine 不 import LifeHUD
- Aggregator 正确组合

---

# 53. 测试：ACTIVE

用户发消息进入 ACTIVE。

20min 内：

- 可生成 Conversation Continuation Candidate
- 普通 Proactive threshold 不再代表 ACTIVE 本身

无对话超过 TTL：

```text
ACTIVE -> SEMI_ACTIVE
```

---

# 54. 测试：Continuation

用户：

```text
“我去让 Codex 跑一下。”
```

短暂沉默后，若仍 ACTIVE 且允许打扰：

可产生类似：

```text
“跑得怎么样了？”
```

但必须受：

- cooldown
- budget
- interruptibility

限制。

---

# 55. 测试：ACTIVE Budget

20min ACTIVE window 内：

```text
最多 2~3 次主动 continuation
```

不得无限连续发言。

---

# 56. 测试：SEMI_ACTIVE

无持续对话但用户仍存在。

允许：

- 普通 Tidal Heartbeat
- Memory maintenance
- Consolidation
- BackgroundIntent

主动频率明显低于 ACTIVE。

---

# 57. 测试：AWAY

用户锁屏 / 长时间 idle：

```text
AWAY
```

恢复输入：

```text
AWAY -> SEMI_ACTIVE
```

不得直接 ACTIVE。

---

# 58. 测试：interruptibility

```text
ACTIVE + focus.active
```

预期：

```text
interaction_state=ACTIVE
interruptibility=LOW
```

而不是错误离开 ACTIVE。

---

# 59. 测试：双事实源

Memory：

```text
昨晚喝白朗姆时还在改朝汐。
```

LifeHUD：

```text
structured alcohol record
```

验证：

- 两条共存
- 不互相覆盖
- 查询精确记录时结构化源优先
- 查询生活语境时 Memory 优先

---

# 60. Diagnostics

建议新增：

```text
tool_packages:
  lifehud:
    installed
    enabled
    configured
    reachable
    healthy
    capabilities
    backoff_until
```

State：

```text
interaction_state
interruptibility
active_since
active_expires_at
continuation_budget
signal_sources
```

---

# 61. 不在本版本处理

明确不做：

- LifeHUD API 大规模重构
- LifeHUD 数据模型迁移
- 多 Tool Marketplace
- 图形化 Package Manager
- 完整 surprise system
- Calendar integration
- Mobile presence
- 新 Memory schema
- 新 Archive schema
- 新 Planner
- 新 Voice
- 新桌面 UI 大改
- Tool Package 热更新

---

# 62. 完成标准

v1.1.5 完成后必须满足：

1. Zhaoxi Core 不 import / 依赖 LifeHUD。
2. LifeHUD 可通过通用包级开关彻底禁用。
3. disabled 时不产生任何 LifeHUD 网络访问。
4. Tool Package 使用显式 Capability Declaration。
5. Tool / Workflow / Router / Proactive / Reflection / State Signal 可独立启停。
6. LifeHUD Focus 只通过 StateSignal 影响 Core。
7. State Machine 不知道 LifeHUD 的存在。
8. interaction_state 与 interruptibility 分离。
9. ACTIVE 表示持续对话，而不只是低 threshold。
10. ACTIVE 支持 Conversation Continuation。
11. ACTIVE 有 TTL、cooldown 和主动预算。
12. SEMI_ACTIVE 表示后台陪伴与低频主动。
13. AWAY 恢复先进入 SEMI_ACTIVE。
14. Memory 与 LifeHUD 支持双事实源、分域权威。
15. LifeHUD 不是生活事实的全局唯一来源。
16. Core 无 LifeHUD 时仍可记忆生活小事。
17. 路由不再被“开幕/落幕”普通子串劫持。
18. Tool Package 依赖稳定公开 SDK / Protocol。
19. 外部服务写入权限语义准确。
20. Diagnostics 区分 installed/configured/reachable/healthy。
21. Provider unreachable 时有 backoff。
22. 重复 `capabilities()` 定义清理。
23. LifeHUD API 现有契约保持兼容。
24. 现有 Memory / Archive / Proactive / Desktop / Workflow 测试保持通过。

---

# 63. 开发完成后汇报

Codex 完成后请明确汇报：

- 修改文件
- Core 与 LifeHUD 最终依赖图
- Package enable 机制
- Capability Declaration schema
- 分项能力开关
- Public SDK / Protocol
- SDK compatibility
- StateSignal schema
- Signal Aggregator
- LifeHUD StateSignalProvider
- Interaction State 新语义
- ACTIVE TTL
- Conversation Continuation
- Continuation Budget
- SEMI_ACTIVE 行为
- interruptibility
- BackgroundIntent
- Router 修复
- Permission side-effect 修复
- Health Check
- unreachable backoff
- duplicate capabilities 清理
- 双事实源 conflict policy
- Diagnostics
- 自动测试
- 手动验收
- 已知限制

---

# 64. 手动验收

## 场景 A：拔掉 LifeHUD

```env
ZHAOXI_TOOL_LIFEHUD_ENABLED=false
```

启动 Zhaoxi。

预期：

- 正常聊天
- Memory 正常
- Archive 正常
- State 正常
- Proactive 正常
- 0 次 LifeHUD HTTP 请求

## 场景 B：LifeHUD 服务关闭

开启 Tool Package，但不启动 LifeHUD。

预期：

- Zhaoxi 正常运行
- diagnostics = unreachable
- Heartbeat 不每 2 分钟持续轰炸请求
- Tool 调用时明确说明不可用

## 场景 C：普通“开幕”

输入：

```text
那个电影节今天开幕了。
```

不得启动 Focus。

再输入：

```text
朝汐，开幕。
```

按既有设计触发 Focus Workflow。

## 场景 D：ACTIVE 对话

和朝汐连续聊几轮。

停止输入数分钟。

若存在 open thread：

允许朝汐主动继续一次。

不是只靠 LifeHUD event。

## 场景 E：Focus 中仍 ACTIVE

正在与朝汐聊天时，LifeHUD Focus active。

预期：

```text
interaction_state = ACTIVE
interruptibility = LOW
```

而不是错误离开 ACTIVE。

## 场景 F：离开电脑

长时间 idle / lock：

```text
AWAY
```

回来：

```text
SEMI_ACTIVE
```

只有再次真正聊天后：

```text
ACTIVE
```

## 场景 G：双事实源

聊天中说：

```text
今晚喝了点白朗姆，还在改朝汐。
```

Memory 可记录这次 Episode。

LifeHUD 若也有结构化记录，两者共存。

问：

```text
今晚喝的什么？
```

可以综合回答。

问：

```text
具体记录了多少？
```

若 LifeHUD 可用，优先结构化数据。

---

# 65. 本版本理念

LifeHUD 可以非常重要。

甚至可以像朝汐的一套外置仪表、传感器和工具箱。

但：

> **LifeHUD 不能成为朝汐存在的前提。**

Memory 是朝汐自己的经历。

State Machine 是朝汐自己的运行状态。

Proactive 是朝汐自己的主动性。

Tool 只负责：

> 告诉她世界发生了什么，或者帮她做某件事。

而不是：

> 决定她现在是谁、该处于什么状态、能不能继续存在。

同样，ACTIVE 也不该只是一个更低的阈值。

它应该真正表示：

> **这段对话还没有结束。**

SEMI_ACTIVE 则是：

> **朝汐仍然醒着，在附近，偶尔看看暗苟，也会自己整理一点东西。**

v1.1.5 要最终建立的是：

# Core Sovereignty

> **工具可以成为朝汐的手、眼睛、仪表和外置能力。**
>
> **但朝汐的心脏必须留在自己这里。**
