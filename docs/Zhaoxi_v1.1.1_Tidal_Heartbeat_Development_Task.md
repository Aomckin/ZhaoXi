# Zhaoxi v1.1.1 Development Task
# 潮汐心跳（Tidal Heartbeat）与主动型 Agent 闭环

> 版本：v1.1.1  
> 主题：Proactive Agent / Tidal Heartbeat  
> 核心目标：让朝汐在电脑常驻期间持续“看见”时间与生活状态，但只在真正值得思考时调用大模型，并在合适的时候主动联系用户。

---

## 0. 背景

Zhaoxi v1.1 已完成当前关键入口体验：

- Windows 登录后自动启动并后台常驻
- Desktop / Core 单实例运行
- 主窗口关闭后继续托盘驻留
- 全局快捷键可快速唤起朝汐
- 当前默认目标快捷键为 `Ctrl + Alt + Numpad0`
- Personality 已完成第一轮正式重构

现在朝汐已经具备：

> “电脑开着时，朝汐本来就在。”

但当前主动能力仍然更接近：

> 用户主动找朝汐 → 朝汐回应

v1.1.1 需要补齐：

> 朝汐持续观察世界 → 发现变化 → 判断是否值得主动开口 → 在合适的时候联系用户

这将是 Zhaoxi 从“常驻聊天 Agent”向“主动型生活 Agent”迈进的核心版本。

---

# 1. 核心设计原则

## 1.1 不允许“每次循环都调用大模型”

严禁实现如下模式：

```text
while True:
    sleep(...)
    call_llm()
```

原因：

- 朝汐可能每天常驻数小时甚至十几小时
- 高频循环调用大模型会产生不必要费用
- 大部分时间世界状态没有发生值得思考的变化
- 时间、任务、提醒等基础判断无需 LLM

v1.1.1 必须采用：

```text
高频观察 = 纯代码
事件筛选 = 纯代码
真正需要理解、判断、表达 = LLM
```

即：

> 程序负责判断“发生了什么”，朝汐负责判断“这意味着什么”。

---

# 2. 总体架构

建议构建如下主动循环：

```text
┌──────────────────────────────┐
│         World Sensors         │
│ 时间 / LifeHUD / Focus       │
│ Reminder / Session / System  │
└──────────────┬───────────────┘
               ↓
       Tidal Heartbeat Loop
          纯代码 / 低成本
               ↓
          Event Buffer
               ↓
        Rule / Score Gate
          纯代码筛选
               ↓
      是否值得朝汐思考？
          ↓             ↓
         否              是
         ↓               ↓
   静默 / 缓存      LLM Decision
                         ↓
               silent / defer / speak
                         ↓
                   Proactive
                         ↓
      Windows 通知 / Inbox / Session
```

---

# 3. Tidal Heartbeat

## 3.1 定义

新增“潮汐心跳”：

**Tidal Heartbeat**

它是朝汐常驻期间的轻量主动循环。

Heartbeat 本身不得调用模型。

每次 Heartbeat 只负责：

- 检查时间
- 检查计划事件
- 检查 LifeHUD 状态
- 检查 Focus 状态
- 检查 Reminder
- 检查最近交互时间
- 检查 Proactive 冷却
- 检查 Quiet Mode
- 收集新的候选事件

## 3.2 Heartbeat 周期

Heartbeat 周期必须可配置。

建议：

```env
ZHAOXI_PROACTIVE_HEARTBEAT_SECONDS=30
```

默认建议：`30 秒`

允许范围可考虑：`5 ~ 300 秒`

注意：Heartbeat 周期不等于 LLM 调用周期。即使每 30 秒运行一次，一整天也可以 0 次或极少次数调用模型。

---

# 4. World Sensors

v1.1.1 不要求建立复杂感知系统，但应整理一个统一的 Sensor 层。

建议目录：

```text
src/zhaoxi/proactive/
├── heartbeat.py
├── sensors.py
├── events.py
├── scoring.py
├── decision.py
├── buffer.py
└── ...
```

可根据现有结构调整，不要求机械照搬。

## 4.1 Time Sensor

负责：

- 当前本地时间
- 当前日期
- 时段
- 是否进入夜间
- 是否到达已注册提醒时间
- 是否达到自然巡检时间窗口

不得调用 LLM。

## 4.2 LifeHUD Sensor

优先复用现有 `lifehud` Tool Package / API。

仅采集适合 Proactive 的轻量状态，例如：

- 当前是否存在进行中的 Focus
- 当前 Focus 已持续多久
- 今日主要任务变化
- 最近任务完成事件
- 今日基础状态是否有明显变化

不要每次 Heartbeat 拉取整个 LifeHUD 全量数据。

需要：

- 控制请求数量
- 缓存上一次状态
- 只产生“变化事件”

例如：

```text
上一次：
focus_active=true
focus_duration=55min

本次：
focus_active=true
focus_duration=90min
```

可产生：

```text
focus.long_running
```

而不是每 30 秒重复产生同一事件。

## 4.3 Session / Interaction Sensor

至少识别：

- 用户最近一次主动与朝汐聊天时间
- 最近一次主动消息时间
- 当前窗口是否活跃（若现有能力可获取）
- 当前是否存在进行中的用户交互
- 是否处于 Quiet Mode

用于避免在用户刚刚聊天后立刻再次主动发言。

---

# 5. Event Model

统一主动事件结构。

建议至少包含：

```python
event_id
event_type
source
created_at
importance
urgency
dedupe_key
payload
expires_at
```

示例：

```text
event_type: focus.long_running
source: lifehud
importance: 0.65
urgency: 0.40
dedupe_key: focus-long-running:<session_id>
```

---

# 6. Event Buffer

## 6.1 目的

禁止：

```text
事件 A -> LLM
事件 B -> LLM
事件 C -> LLM
```

改为：

```text
事件 A ┐
事件 B ├→ Event Buffer → 一次判断
事件 C ┘
```

让朝汐能够看到一段时间内的整体生活状态。

## 6.2 Buffer 行为

Event Buffer 需要：

- 去重
- 合并
- TTL / 过期
- 保留高价值事件
- 防止无限增长

建议普通候选事件可聚合 `5 ~ 10 分钟`。

明确提醒 / 高优先级事件不需要等待聚合窗口。

---

# 7. Rule / Score Gate

## 7.1 核心要求

在调用模型之前必须经过纯代码筛选。

评分可以考虑：

```text
事件重要性
+ 紧迫度
+ 是否首次发生
+ 是否与当前 Focus / 任务相关
+ 距离上次主动发言时间
+ 距离上次用户交互时间
+ 当前是否存在多个相关事件
- Quiet Mode
- 重复事件惩罚
- 最近主动发言过多
- 用户正处于深度工作
- 已提醒但未变化
```

## 7.2 建议输出

可统一输出：

```python
score: float
decision_hint:
    drop
    inbox
    candidate
    urgent
```

建议阈值初始参考：

```text
0.00 ~ 0.30 -> drop
0.30 ~ 0.60 -> inbox
0.60 ~ 0.80 -> candidate
0.80 ~ 1.00 -> urgent / speak candidate
```

具体阈值可由实现过程微调。

不要为了“智能”把这层改成 LLM。

---

# 8. Cooldown

必须加入主动发言冷却。

目标：防止

```text
20:00 喝水
20:03 休息
20:07 任务
20:10 吃饭
```

变成桌宠式通知轰炸。

## 8.1 普通冷却

新增配置，例如：

```env
ZHAOXI_PROACTIVE_COOLDOWN_MINUTES=45
```

普通主动消息在冷却期间降低评分或直接 defer。

## 8.2 可绕过冷却的事件

以下类型可考虑绕过普通 cooldown：

- 用户明确设置的 Reminder
- 高优先级到期任务
- 明确危险 / 高价值事件
- 强时效性事件

不要所有事件都绕过。

---

# 9. Quiet Mode

必须真正接入 Heartbeat / Gate。

Quiet Mode 下：

- 普通主动消息不弹通知
- 普通事件可以进入 Inbox
- 可延后到 Quiet Mode 结束后重新判断
- 明确高优先级提醒可按现有策略决定是否放行

Quiet Mode 不应只是 UI 状态。

---

# 10. LLM Decision Layer

## 10.1 何时调用

只有 Rule / Score Gate 判定：

> “这批事件值得朝汐本人思考”

才允许调用主模型。

## 10.2 LLM 输入

不要把整个系统状态全部塞给模型。

只提供必要、结构化摘要，例如：

```text
当前时间：22:00

最近事件：
- 当前 Focus 已持续 102 分钟
- 今日已完成两个主要任务
- 最近 90 分钟朝汐未主动发言

交互状态：
- 用户最近正在持续工作
- Quiet Mode 关闭

请判断：
1. 是否应该主动发言
2. 是否延后
3. 如果主动发言，应说什么
```

## 10.3 LLM 输出

尽量要求结构化结果：

```json
{
  "action": "speak",
  "priority": "medium",
  "reason": "...",
  "content": "..."
}
```

至少支持：

```text
silent
defer
speak
```

注意：最终主动消息必须保持朝汐人格。

不要生成：

```text
Reminder: You should rest.
```

而应该由当前 Personality 自然表达。

---

# 11. Natural Check-in

纯事件驱动会导致：

> 没有明确事件时，朝汐一整天可能完全不会主动出现。

因此需要新增：

**Natural Check-in**

用于低频、非任务型主动关心。

## 11.1 原则

Natural Check-in 不是固定每 N 分钟调用模型。

而是：

```text
Heartbeat
↓
规则判断是否进入 check-in 候选
↓
满足条件才调用模型
```

## 11.2 候选条件参考

例如：

- 数小时没有互动
- 用户电脑仍处于活跃状态
- 当前没有 Focus
- Quiet Mode 关闭
- 最近没有主动消息
- 今天存在一些轻量、可聊的生活上下文

## 11.3 示例

可能生成：

```text
暗苟酱今天好像一直在忙诶。
朝汐没什么急事，就是路过看看。
```

Natural Check-in 频率必须低。

P0 阶段宁可太少，不要太多。

---

# 12. 主动消息闭环

主动消息不应只停留在通知弹窗。

必须完成：

```text
事件
↓
朝汐决定主动发言
↓
生成 Proactive Delivery
↓
Windows 通知
↓
右侧主动消息 Inbox
↓
用户点击
↓
打开朝汐
↓
能够继续围绕该事件聊天
```

---

# 13. Inbox

当前 Desktop 已存在“主动消息”区域。

v1.1.1 需要让其真正成为轻量 Inbox。

最低要求：

- 显示最近主动消息
- 显示时间
- 显示内容摘要
- 未读 / 已读状态
- 点击后打开对应上下文
- 不要求复杂消息管理 UI

不要在本版本做大型通知中心。

---

# 14. 主动消息与 Session 上下文

这是 P0 必须完成的一点。

如果朝汐主动说：

```text
暗苟酱，Focus 已经 100 分钟啦。
```

用户点击后不能只打开一个空白窗口。

后续用户回复：

```text
再让我写十分钟嘛
```

朝汐必须知道这句话对应刚才的 Focus 主动消息。

因此需要保存至少：

```text
delivery_id
event_id
event_type
content
relevant_payload
timestamp
```

并在用户通过通知 / Inbox 进入时，为当前交互补入必要上下文。

不要把完整内部 Event 原始数据直接暴露给用户。

---

# 15. 防重复与幂等

必须避免：

- 每次 Heartbeat 重复生成同一事件
- 同一 Focus 每 30 秒提醒一次
- 应用重启后重新提醒已经处理的事件
- 同一 Reminder 多次触发

至少使用：

```text
dedupe_key
last_seen
last_delivered
resolved / expired
```

等机制完成去重。

---

# 16. 成本控制与可观测性

最低要求记录：

- Heartbeat 次数
- Sensor 事件数
- Gate 丢弃事件数
- Inbox 事件数
- LLM Decision 次数
- 最终主动发言次数

建议加入 diagnostics / metrics。

目标不是精确计费。

目标是能回答：

> 朝汐今天运行 10 小时，到底因为 Proactive 调用了多少次模型？

---

# 17. 配置项

建议新增或整理：

```env
ZHAOXI_PROACTIVE_HEARTBEAT_SECONDS=30
ZHAOXI_PROACTIVE_COOLDOWN_MINUTES=45
ZHAOXI_PROACTIVE_NATURAL_CHECKIN_ENABLED=true
ZHAOXI_PROACTIVE_NATURAL_CHECKIN_MIN_HOURS=3
ZHAOXI_PROACTIVE_EVENT_BUFFER_SECONDS=300
```

名称可根据现有项目风格调整。

不要一次暴露几十个微调参数。

---

# 18. 与现有 Proactive 的关系

必须优先复用现有：

- `ProactiveRuntime`
- `Scheduler`
- `PolicyState`
- `InboxNotificationSink`
- Desktop Notification
- 现有 `/api/proactive`
- 现有 Quiet Mode
- 现有 Proactive Store

不要重写现有 Proactive 子系统。

v1.1.1 的核心是：

> 在现有 Proactive 上补“持续观察 + 事件筛选 + LLM 判断 + 主动闭环”。

---

# 19. 不允许修改的部分

本版本不要顺手重构：

- Personality
- Memory 主体
- Planner
- Workflow
- Reflection
- Voice
- Permission
- LifeHUD 业务逻辑
- Desktop UI 大改
- 全局快捷键
- Windows 自启动

除非为 Proactive 接口集成必须做极小调整。

---

# 20. 测试要求

至少补充以下测试。

## Heartbeat

- Heartbeat 周期正常运行
- Heartbeat 本身不调用模型
- Quiet Mode 状态能够正确读取
- Stop / Shutdown 时 Heartbeat 正常退出

## Sensor

- 状态未变化时不重复产生事件
- LifeHUD 变化能够生成正确事件
- 时间 Reminder 到期只产生一次事件

## Event Buffer

- 相同 dedupe_key 去重
- 事件可过期
- 多事件可聚合

## Score Gate

- 低分事件 drop
- 中分事件进入 inbox
- 高分事件进入 LLM Decision
- cooldown 生效
- urgent 可按规则绕过 cooldown
- Quiet Mode 抑制普通 speak

## LLM Decision

- Gate 未通过时绝不调用模型
- Decision 支持 silent / defer / speak
- 非法输出具有 fallback
- 模型失败不会导致 Heartbeat 崩溃

## Delivery

- speak 生成 Proactive Delivery
- Delivery 可进入 Inbox
- 点击 / 激活后可恢复必要上下文
- 相同事件不重复发送

## Metrics

- 能统计 Heartbeat / Event / Decision / Delivery 数量

---

# 21. 手动验收场景

## 场景 A：无事发生

运行朝汐 30 分钟。

预期：

- Heartbeat 持续运行
- 无意义事件不会调用模型
- 不主动弹消息
- diagnostics 可看到 Heartbeat 数增加

## 场景 B：长时间 Focus

LifeHUD 开启 Focus。

持续超过设定阈值。

预期：

- Heartbeat 发现状态变化
- 生成候选事件
- Gate 判断是否值得主动
- 仅在合适时调用一次模型
- 朝汐主动提醒
- 不在之后每次 Heartbeat 重复提醒

## 场景 C：Quiet Mode

开启 Quiet Mode。

触发普通主动候选。

预期：

- 不弹 Windows 通知
- 可进入 Inbox 或 defer
- Quiet Mode 结束后按策略重新判断

## 场景 D：Reminder

创建明确 Reminder。

到期。

预期：

- 不受普通 Natural Check-in 逻辑影响
- 正常触发
- 只触发一次
- 点击后可以围绕 Reminder 继续聊天

## 场景 E：自然巡检

数小时未与朝汐互动。

电脑仍活跃。

无 Focus。

Quiet Mode 关闭。

预期：

- Heartbeat 产生 natural_checkin 候选
- Gate 判断是否值得
- 最多调用一次模型
- 可能主动发一句轻量、自然的话
- 不形成固定时钟式骚扰

---

# 22. 完成标准

v1.1.1 完成后应满足：

1. 朝汐常驻期间持续 Heartbeat。
2. Heartbeat 本身零 LLM 成本。
3. 大部分无意义状态变化被纯代码层过滤。
4. 多事件可合并后一次交给朝汐判断。
5. Proactive 有明确 cooldown。
6. Quiet Mode 真正生效。
7. 存在低频 Natural Check-in。
8. 只有值得思考时才调用模型。
9. 主动消息使用当前朝汐人格生成。
10. Windows 通知与 Inbox 均可接收主动消息。
11. 点击主动消息后能延续对应上下文。
12. 同一事件不会被重复骚扰。
13. Proactive 模型调用次数可观测。
14. 模型失败不影响 Heartbeat 与 Desktop 常驻。
15. 现有测试保持通过。

---

# 23. 开发完成后汇报

Codex 完成后请明确汇报：

- 修改文件
- 新增模块
- Heartbeat 实现方式
- Sensor 来源
- Event Model
- Event Buffer
- Score Gate 规则
- Cooldown 策略
- Natural Check-in 触发机制
- LLM Decision Prompt / 输出结构
- Inbox 与 Session 闭环方式
- 新增配置
- Metrics
- 自动测试结果
- 手动验收步骤
- 已知限制

---

# 24. 本版本理念

v1.1.1 不追求：

> “朝汐不停地说话。”

而追求：

> **“朝汐一直醒着。”**

她会看时间。

会留意生活是否发生变化。

会知道暗苟正在忙、正在休息、刚刚完成了什么。

绝大多数时候，她什么都不说。

只有当一件事情真的值得她开口时，她才从后台轻轻敲一下门。

这就是：

# Tidal Heartbeat

> 潮水一直在动。  
> 但不是每一次潮起，都需要惊动岸上的人。
