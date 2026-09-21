# Zhaoxi v0.5.1 · Life HUD First Contact 开发任务书

> 项目：**Zhaoxi / 朝汐**  
> 版本：**v0.5.1 · Life HUD First Contact**  
> 性质：外部 Tool 对接 / 契约对齐 / Workflow 联调  
> 目标：**让 Zhaoxi v0.5 正式、稳定地读取 Life HUD v0.8 Agent Context API，并让现有铁幕 Workflow 使用 Life HUD 真实状态。**
>
> 本版本不继续扩展 Zhaoxi Core，不新增 Planner / Memory / Permission / Workflow 大能力。
>
> 本版本的任务只有一句话：
>
> **把已经造好的朝汐，真正接到已经造好的 Life HUD 上。**

> 实现状态：Agent Context schema 1 Client、10 个 READ Tools、错误与重试边界、铁幕写前/写后事实核验均已接入；自动化测试与本机 `/today` 黑盒握手通过。

---

# 1. 对接基线

Life HUD v0.8+ 当前提供正式只读 Agent Context API：

```text
Base URL:
http://localhost:8025/api/agent/context

schemaVersion:
"1"
```

默认上下文入口：

```text
GET /today
```

分域接口：

```text
GET /recent?days=7
GET /status
GET /focus
GET /tasks
GET /dreams
GET /life
GET /journal?limit=20
GET /media
GET /growth
```

Zhaoxi 必须以该契约为准，不继续沿用旧的猜测接口。

---

# 2. 当前已知差异

当前 Zhaoxi v0.5 与 Life HUD v0.8 至少存在以下错位：

```text
Life HUD 默认端口：
localhost:8025

Zhaoxi 当前：
127.0.0.1:8080
```

以及：

```text
Life HUD：
/api/agent/context/*

Zhaoxi：
尚未完整实现 Agent Context API
```

当前铁幕状态读取仍主要依赖旧业务接口：

```text
/api/focus/current
```

而 Life HUD v0.8 已提供更适合 Agent 的：

```text
/api/agent/context/focus
/api/agent/context/status
```

此外当前还缺少：

```text
schemaVersion 校验
ISO 8601 UTC 强类型解析
Agent Context Pydantic DTO
400 / 5xx 契约化错误处理
unknown field 前向兼容
null / [] 语义对齐
```

---

# 3. 核心原则

## 3.1 Life HUD 是事实源

Zhaoxi 不复制 Life HUD 的事实数据库。

例如：

```text
“现在是否正在铁幕？”
“今天 Focus 多少分钟？”
“昨晚睡了多久？”
“还有几个任务？”
```

优先实时查询 Life HUD。

不要依赖：

```text
Zhaoxi Memory 猜测
Conversation 历史猜测
本地重复缓存事实
```

---

## 3.2 Agent Context 只读

`/api/agent/context/*` 全部视为：

```text
READ
```

这些接口：

- 不创建数据
- 不修改数据
- 不删除数据

因此应走 Zhaoxi Permission 的 READ 策略。

写操作继续使用 Life HUD 对应业务 API。

---

## 3.3 禁止直读 Life HUD 数据库 / JSON

调用链必须保持：

```text
Zhaoxi
↓
HTTP Tool
↓
Life HUD REST API
↓
Life HUD Service
↓
Life HUD Data
```

禁止：

```text
Zhaoxi
↓
直接读取 Life HUD data/
数据库
内部 Java 文件
```

---

# 4. 配置对齐

统一 Life HUD 配置。

建议：

```env
ZHAOXI_LIFEHUD_BASE_URL=http://127.0.0.1:8025
ZHAOXI_LIFEHUD_CONTEXT_PATH=/api/agent/context
ZHAOXI_LIFEHUD_SCHEMA_VERSION=1
ZHAOXI_LIFEHUD_TIMEOUT_SECONDS=10
ZHAOXI_LIFEHUD_MAX_RETRIES=2
```

不要把：

```text
8080
8025
/api/agent/context
```

散落硬编码在 Tool / Workflow 中。

---

# 5. Life HUD Client

建立统一客户端，例如：

```text
src/zhaoxi/tools/lifehud/
├── client.py
├── models.py
├── errors.py
├── tools.py
└── ...
```

具体目录可按现项目结构调整。

Client 负责：

```text
HTTP 请求
状态码判断
JSON 解析
schemaVersion 校验
超时
有限重试
错误转换
```

Tool 本身不要重复写 HTTP 逻辑。

---

# 6. Agent Context 数据模型

使用 Pydantic 建立最小强类型契约。

至少覆盖：

```text
AgentEnvelope
TodayContext
RecentContext
StatusContext
FocusContext
TasksContext
DreamsContext
LifeContext
JournalContext
MediaContext
GrowthContext
```

以及当前核心公共类型：

```text
Status
Focus
FocusSession
Tasks
CheckIn
TimelineItem
```

要求：

```text
extra fields → ignore
null → 合法
[] → 合法
```

不要因为 Life HUD schema 1 新增可选字段就直接炸掉。

---

# 7. schemaVersion

每个 Agent Context 响应必须检查：

```text
schemaVersion == "1"
```

不支持的版本：

```text
→ 明确返回 UnsupportedSchemaVersion
→ 不继续猜字段
→ 不让模型把异常数据当事实
```

不要：

```text
“字段看起来差不多，先凑合解析”
```

---

# 8. 时间语义

Life HUD 契约：

```text
Instant
→ ISO 8601 UTC
→ 例如 2026-08-31T02:30:00Z

LocalDate
→ YYYY-MM-DD
```

Zhaoxi 应正确解析：

```text
Z
时区偏移
nullable endedAt
```

展示给用户时可以转换成本地时区。

原始事实保持原时间语义。

---

# 9. 第一批 Life HUD READ Tools

优先实现统一 Tool 集：

```text
lifehud_today
lifehud_recent
lifehud_status
lifehud_focus
lifehud_tasks
lifehud_dreams
lifehud_life
lifehud_journal
lifehud_media
lifehud_growth
```

Tool Description 必须告诉模型各工具适用范围。

---

## 9.1 lifehud_today

默认 Agent 入口。

适用于：

```text
“今天怎么样？”
“我今天干了什么？”
“今天接下来该干嘛？”
“看看我现在的整体状态。”
```

返回应包含：

```text
status
focus
tasks
sleep
meal
dreams
rituals
media
timeline
```

不要把完整 JSON 原样糊进自然语言回复。

---

## 9.2 lifehud_recent

参数：

```text
days: 1 ~ 30
```

默认：

```text
7
```

适用于：

```text
最近几天
这一周
近期趋势
最近发生了什么
```

---

## 9.3 分域 Tools

仅需要单域信息时优先使用：

```text
/status
/focus
/tasks
/dreams
/life
/journal
/media
/growth
```

避免每个简单问题都请求 `/today`。

---

# 10. Tool 选择建议

将契约语义写进 Tool Description。

例如：

```text
用户问“今天该做什么”
→ 优先 lifehud_today

用户问“今天 Focus 多久”
→ lifehud_focus

用户问“这周干了啥”
→ lifehud_recent(days=7)

用户问“最近日记”
→ lifehud_journal

用户问“现在在玩什么”
→ lifehud_media
```

不要额外写死大量 Intent if-else。

让现有 Agent Runtime / Planner 根据 Tool Description 选择。

---

# 11. 铁幕 Workflow 对齐

现有：

```text
铁幕开幕
铁幕落幕
```

继续保留。

但状态确认应优先通过 Agent Context：

```text
GET /api/agent/context/focus
```

或：

```text
GET /api/agent/context/status
```

读取：

```text
activeFocus
focus.active
mode
status
id
```

---

## 11.1 开幕

流程建议：

```text
读取 focus context
↓
若已有 RUNNING session
→ 不重复创建
→ 根据真实状态响应

若没有 active focus
↓
Permission
↓
POST /api/focus/start
↓
重新读取 context/focus 验证
↓
Workflow complete
```

写接口继续使用 Life HUD 业务 API。

---

## 11.2 落幕

流程：

```text
读取 focus context
↓
获取真实 active FocusSession.id
↓
若无 active
→ 不调用 complete

若存在
↓
Permission
↓
POST /api/focus/{id}/complete
↓
重新读取 context/focus
↓
确认 active 已结束
↓
Workflow complete
```

不要只因为 HTTP 200 就假设事实已经改变。

**写后重新读事实源确认。**

---

# 12. 错误处理

严格对齐 Life HUD 契约。

## 12.1 HTTP 400

要求：

```text
不原样重试
读取 detail
转成参数错误
让 Agent / Planner 修正参数或向用户说明
```

例如：

```text
recent days=114
→ 400
→ 修正到合法范围或说明
```

## 12.2 Network / 5xx

使用：

```text
有限次数指数退避
```

默认最多：

```text
2 次重试
```

Workflow 不允许无限重试。

自动退避只适用于幂等的 Agent Context `GET`。`POST /api/focus/start`、`complete` 等写操作没有幂等键时不得因超时或 5xx 自动重放，避免重复副作用；写入结果不确定时应重新读取 Agent Context 核验，仍无法确认则明确告知用户。

## 12.3 Life HUD 未启动

例如：

```text
Connection refused
```

Zhaoxi 必须明确知道：

```text
Life HUD 当前不可访问
```

不能：

```text
根据 Memory 猜一个今天状态
假装操作成功
```

---

# 13. null 与空集合

以下全部是正常业务状态：

```text
sleep = null
meal = null
activeFocus = null
dreams.active = []
timeline = []
```

禁止把：

```text
“用户今天没记录睡眠”
```

解释成：

```text
“Life HUD 数据异常”
```

---

# 14. 字段语义注意事项

必须遵守：

```text
status.checkIn
→ 全局最近一次 Check-in
→ 不一定是今天

sleep
→ 今天结束边界前最近一次醒来的睡眠
→ 可能来自前一晚

meal
→ 今天最新一餐

focus.effectiveMinutes
→ 仅今天

timeline
→ 今天最新 10 条

tasks.special
→ 区分每日任务与特别行动
```

不要自行重新解释这些字段。

---

# 15. Memory 边界

本次正式接入后，继续贯彻 v0.3.2 原则：

```text
Life HUD Fact
≠
Zhaoxi Long-term Memory
```

例如：

```text
Life HUD：
今天 Focus 183 分钟

→ 不自动长期保存
```

但朝汐可以基于多次事实形成：

```text
Zhaoxi Memory：
最近晚上主要在做项目开发。
```

也就是说：

```text
事实 → Tool
认知 → Memory
```

---

# 16. Planner / Workflow 使用

Planner 可以把 Life HUD Context Tools 当普通 READ Tool 使用。

例如：

```text
“帮我看看最近一周开发和生活状态怎么样。”
```

可能：

```text
Plan
1. lifehud_recent(7)
2. lifehud_focus
3. lifehud_life
4. 分析
5. 回复
```

但不要为了简单查询强制 Planner。

---

# 17. Permission 对齐

Agent Context Tools：

```text
READ
→ 按 READ 策略自动执行
```

Life HUD 写业务：

```text
WRITE / DELETE
→ 继续经过 Permission Gateway
```

不得因为：

```text
“都是 Life HUD Tool”
```

就统一绕过 Permission。

---

# 18. 测试要求

必须加入 Mock / Fake Life HUD Server 或 HTTP Mock。

自动测试不能依赖开发者本机真实运行 Life HUD。

至少覆盖：

```text
A. /today 正常解析
B. unknown field 忽略
C. schemaVersion 不支持
D. null / [] 合法
E. 400 不重试
F. 5xx 有限重试
G. Life HUD 离线 graceful failure
H. 铁幕开幕：读状态 → start → 再读确认
I. 重复开幕：已有 active 时不重复创建
J. 铁幕落幕：读 id → complete → 再读确认
```

---

# 19. 黑盒冒烟测试

自动测试通过后，人工至少跑：

```text
“我今天怎么样？”
```

预期：

```text
自动调用 Life HUD Context
根据真实数据回答
```

```text
“今天 Focus 了多久？”
```

预期：

```text
lifehud_focus
```

```text
“我最近在玩什么？”
```

预期：

```text
lifehud_media
```

```text
“朝汐，开幕。”
```

预期：

```text
检查真实 Focus 状态
→ Permission
→ start
→ 再确认
```

```text
“朝汐，落幕。”
```

预期：

```text
读取真实 session id
→ Permission
→ complete
→ 再确认
```

最后故意关闭 Life HUD：

```text
“我今天 Focus 多久？”
```

要求：

```text
朝汐明确说无法访问 Life HUD
```

不能脑补。

---

# 20. 本版不要做

不要顺手扩成 v0.6。

本版本不做：

```text
Proactive Agent
主动提醒
定时任务
天气
Calendar
GitHub
Gmail
Voice
Desktop
MCP
RAG
复杂缓存
Life HUD 全量写 Tool
自动生活建议大重构
```

除现有 Focus Workflow 所需写接口外，先把**读上下文**彻底对齐。

---

# 21. 完成标准

v0.5.1 完成时必须满足：

```text
1.
Zhaoxi 能通过正式 Agent Context API 理解 Life HUD 的“今天”。

2.
schemaVersion、时间、null、unknown field、400、5xx 全部按契约处理。

3.
铁幕 Workflow 使用 Life HUD 真实 Context 判断状态。

4.
Life HUD 是事实源，Zhaoxi 不复制或猜测实时生活事实。

5.
Life HUD 离线或异常时，朝汐宁可承认不知道，也不伪造成功。

6.
新增其他 Life HUD Agent Context Tool 时，不需要修改 Zhaoxi Core。
```

---

# 22. 版本定义

```text
v0.5
朝汐拥有 Workflow。

v0.5.1
朝汐第一次真正把 Life HUD 当成外部世界来使用。
```

> **这不是一次“HTTP 接口联调”。**
>
> **这是 Zhaoxi Core 第一次与独立事实系统完成正式握手。**
