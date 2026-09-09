# Zhaoxi 开发版本计划

> **项目名：朝汐 / Zhaoxi**
>
> 定位：面向个人数字生活的全能 Agent。  
> 角色设定：金毛犬娘女仆。  
> 核心目标：让使用者尽量只需要“表达意图”，由 Zhaoxi 负责理解、规划、调用工具、整理结果并完成交互。
>
> **架构原则：Zhaoxi Core 是“她自己”，Tools 是“她能使用的工具”。**
>
> Life HUD、GitHub、Calendar、Gmail、文件系统、天气、浏览器等都属于 Tools，不与 Zhaoxi Core 焊死。

---

# 0. 总体架构

```text
                         用户
                          │
               文字 / 语音 / 桌面 / QQ
                          │
                          ▼
                ┌───────────────────┐
                │    Zhaoxi Core    │
                │      朝汐主体      │
                └─────────┬─────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
   Conversation        Memory           Agent Runtime
   Context             Personality      Planner
   Session             Reflection       Permission
                          │
                          ▼
                    Tool Registry
                          │
      ┌───────────┬───────┼────────┬───────────┐
      ▼           ▼       ▼        ▼           ▼
   Life HUD     GitHub  Calendar  Gmail      Files
      │
   Sleep / Focus / Food / Dream / Diary / ...
```

Zhaoxi 不应成为所有数据的唯一存储位置。

- **Zhaoxi Core**：负责理解、记忆、推理、规划、人格、权限与 Agent 执行。
- **Tools**：负责访问真实外部系统与业务数据。
- **外部系统**：继续拥有自己的数据与业务逻辑，Zhaoxi 只通过工具协议访问。
- **Interfaces**：Web、CLI、Desktop、Voice、QQ 等只负责把消息送入 Core，不复制第二套大脑。

---

# 1. 开发总原则

## 1.1 Core 与 Tools 解耦

任何具体工具都不应成为 Core 的硬编码依赖。

禁止逐渐长成：

```text
if lifehud:
elif github:
elif calendar:
elif gmail:
...
```

应通过统一 Tool Registry 注册：

```text
Tool
├── name
├── description
├── input_schema
├── permission
└── execute()
```

Core 只负责：

> 理解需求 → 选择工具 → 调用 → 获取结果 → 继续推理 → 返回结果

---

## 1.2 模型可替换

模型提供方必须抽象。

```text
ModelProvider
├── OpenAI
├── Gemini
├── DeepSeek
├── Local
└── ...
```

Core 不应依赖某一家模型的具体 API。

---

## 1.3 数据归属明确

- 睡眠、饮食、Focus、任务等结构化生活事实 → **Life HUD**
- Git 提交、Issue、PR → **GitHub**
- 日程 → **Calendar**
- 邮件 → **Gmail**
- 文件与文档 → **Files**
- 长期语义偏好、上下文关系、人物与项目认知 → **Zhaoxi Memory**

Zhaoxi 连接世界，而不是把整个世界重新复制一遍。

---

## 1.4 输入必须比手动记录便宜

Zhaoxi 的重要价值之一，是降低记录与操作成本。

理想交互：

> “朝汐，记一下，昨晚两点睡，十点半醒。”

而不是：

> 打开模块 → 新增 → 选择类型 → 填时间 → 填字段 → 保存

---

# 2. Zhaoxi Core 版本路线

---

## v0.1 · Awakening

### 目标

> **让 Zhaoxi 第一次作为一个完整 Agent 独立运行。**

这一版不追求接入大量真实业务工具，重点是把“朝汐本人”的骨架搭出来。

### 核心任务

#### 1. Model Provider

完成统一模型接口：

- 模型配置
- API Key / Base URL
- Model 切换
- Temperature / Token 等参数
- Provider 异常处理
- 后续支持多 Provider

#### 2. Conversation / Context

建立基础会话系统：

- Session
- 最近 N 条消息
- System Prompt
- 当前上下文
- Token 控制
- 上下文裁剪

明确：

> Conversation Context ≠ Long-term Memory

#### 3. Agent Runtime

建立基础 Agent Loop：

```text
User Message
    ↓
Build Context
    ↓
Model
    ↓
Direct Answer / Tool Call
    ↓
Tool Execution
    ↓
Observation
    ↓
Model
    ↓
Final Answer
```

需要支持：

- Tool Call
- Tool Result
- 最大循环次数
- 超时
- 错误返回
- 基础中断

#### 4. Tool System

先实现工具框架，而不是具体业务工具。

包括：

- Tool Interface
- Tool Registry
- Tool Schema
- Tool Description
- Tool Result
- Tool Error
- Tool 自动注册或集中注册

首批测试工具：

- `echo`
- `calculator`
- `current_time`

用于证明完整 Tool Calling 链路可运行。

#### 5. Personality

朝汐人格独立配置，不仅作为一句 Prompt。

至少拆分：

- Identity
- Relationship
- Tone
- Behavior
- Boundaries
- Service Style

推荐人格配置版本化：

```text
personality/
└── zhaoxi_v1.yaml
```

#### 6. 基础设施

- Config
- Logging
- Session Storage
- Error Handling
- 基础测试
- 开发环境配置
- README

### v0.1 验收

至少完成：

```text
用户：现在几点？
Zhaoxi：调用 current_time → 返回自然回答

用户：12 * 17 是多少？
Zhaoxi：调用 calculator → 返回结果

用户：今天有点累。
Zhaoxi：不调用工具 → 正常对话
```

核心验收标准：

> Zhaoxi 已经拥有可以持续扩展的“大脑、上下文、Agent 循环和工具插槽”。

---

## v0.2 · Memory

### 目标

> **让 Zhaoxi 开始真正“记得”。**

### Memory 分层

```text
Working Memory
当前 Session 与短时上下文

Episodic Memory
过去发生过什么

Semantic Memory
长期事实、偏好、关系与项目认知
```

### 核心任务

- Memory 数据模型
- 新增
- 查询
- 搜索
- 修改
- 删除 / Forget
- 时间戳
- 来源 Source
- Confidence
- Tag / Type
- Memory 检索
- Memory 注入 Context
- Memory 去重与冲突基础处理

### 必须支持

> “记住这件事。”

> “你还记得我之前怎么说的吗？”

> “这条是什么时候记下来的？”

> “把这个忘掉。”

### 设计要求

Memory 不应变成无限增长的垃圾场。

需要预留：

- 自动摘要
- 合并
- 过期
- 冲突
- 可信度
- 来源追踪

---

## v0.3 · Planner

### 目标

> **从 Tool Calling 升级到真正的多步 Agent。**

### 核心能力

```text
Goal
 ↓
Plan
 ↓
Action
 ↓
Observation
 ↓
Re-plan
 ↓
Action
 ↓
Final
```

### 核心任务

- 多步骤任务规划
- 连续调用多个工具
- Observation
- 失败重试
- Tool fallback
- 中途重新规划
- 用户补充信息
- Cancellation
- 最大执行步数
- 总超时
- Execution Trace

### 示例

> “帮我准备明天下午的面试。”

未来可规划为：

```text
查 Calendar
→ 找面试信息
→ 找公司与岗位资料
→ 找历史复盘
→ 汇总准备重点
→ 返回结果
```

此时 Zhaoxi 才真正从：

> “会调用工具的聊天程序”

走向：

> “会办事的 Agent”

---

## v0.4 · Permission

### 目标

> **建立统一权限、安全确认与审计层。**

### 权限等级

推荐至少：

```text
READ
WRITE
DELETE
EXTERNAL_ACTION
DANGEROUS
```

### 示例

| 操作 | 权限 |
|---|---|
| 查询天气 | READ |
| 查询 Life HUD | READ |
| 新增生活记录 | WRITE |
| 创建日历事件 | WRITE |
| 发邮件 | EXTERNAL_ACTION |
| 删除记录 | DELETE |
| 执行高风险系统命令 | DANGEROUS |

### 核心任务

- Tool 权限声明
- Core 统一权限检查
- 确认流程
- 审计日志
- 操作来源
- 用户授权策略
- 可配置自动许可
- Undo / Rollback Hook
- Tool 输出不可信边界
- Prompt Injection 基础防护

---

## v0.5 · Workflow

### 目标

> **让常用复杂操作从“每次重新思考”升级为可复用流程。**

### 核心任务

- Workflow 定义
- Workflow 模板
- 参数化
- Tool 链
- 条件判断
- 可暂停
- 可恢复
- 执行历史
- Workflow 与 Planner 协同

### 示例

#### 铁幕工作流

```text
“朝汐，开幕。”

读取当前状态
→ 创建 Focus Session
→ Life HUD 进入铁幕
→ 获取当前目标
→ 必要时切换桌面环境
→ 返回开始信息
```

#### 面试准备工作流

```text
Calendar
→ Files
→ Job Records
→ Historical Interview Review
→ Preparation Summary
```

---

## v0.6 · Proactive Agent

### 目标

> **让 Zhaoxi 不只等待命令，而是能在值得的时候主动出现。**

### 核心任务

- Event Bus
- Scheduled Event
- Tool Event
- Condition Trigger
- Notification
- Interrupt Policy
- Quiet Mode
- Night Mode
- Priority
- Frequency Limit

### 主动等级

```text
INFO
NOTICE
IMPORTANT
URGENT
```

### 原则

> **值得打扰才打扰。**

特别需要避免把 Zhaoxi 做成“电子班主任”。

例如进入夜航模式后：

- 普通任务延期 → 不提醒
- GitHub 多了几个 Commit → 不提醒
- 明早重要面试 → 可以适时提醒
- 真正紧急事件 → 正常提醒

---

## v0.7 · Presence

### 目标

> **让 Zhaoxi 从一个后台 Agent 变成真正存在于日常中的角色。**

### 入口

- Web Chat
- CLI
- Desktop
- 系统托盘
- 快捷键
- Voice
- QQ / 夏苟

### 设计原则

所有 Interface 都只负责：

```text
Input
→ Unified Message
→ Zhaoxi Core
→ Unified Response
→ Render
```

禁止不同客户端各自维护一套 Agent 逻辑。

### 可重点推进

- Desktop 常驻
- 快捷呼出
- 语音唤醒
- TTS
- 通知
- 当前状态显示

---

## v0.8 · Reflection

### 目标

> **让 Zhaoxi 不只记录事件，而开始理解一段生活。**

### 核心能力

- Daily Reflection
- Weekly Reflection
- Monthly Reflection
- Seasonal Reflection
- Project Reflection
- Dream Reflection
- Pattern Analysis

### 信息来源

```text
Zhaoxi Memory
+
Life HUD
+
GitHub
+
Calendar
+
Files
+
其他 Tools
```

### 原则

Reflection 不能只生成数字报表。

理想能力：

> “八月过得怎么样？”

Zhaoxi 能结合结构化数据、项目进展、生活事件、日记与梦想，形成有来源、有上下文的总结。

---

## v0.9 · Reliability

### 目标

> **正式版之前集中处理长期运行所需的可靠性。**

### 核心任务

- 完整日志
- Trace
- Metrics
- Tool 调用审计
- 错误恢复
- Retry Policy
- Timeout Policy
- Context 崩溃恢复
- Session 恢复
- Memory 修复
- 数据备份
- Provider Fallback
- Token / Cost Control
- Prompt Injection 加固
- Tool Sandbox
- 高风险操作防护
- 自动化测试
- 集成测试
- 长时间运行测试

---

## v1.0 · Zhaoxi

### 正式版目标

不是“世界上所有工具都已经接完”。

而是：

> **Zhaoxi 已经成为可以每天真实使用的个人 Agent。**

### v1.0 验收标准

用户开始习惯：

> “有事找朝汐。”

而不是：

> “这件事应该打开哪个软件？”

Zhaoxi 已具备：

- 稳定对话
- 长期 Memory
- Tool Calling
- 多步 Planner
- Workflow
- Permission
- Proactive Agent
- 多入口交互
- Reflection
- 稳定运行

---

# 3. Tools 独立版本路线

Tools 与 Zhaoxi Core 不共用版本号。

例如完全允许：

```text
Zhaoxi Core v0.6

lifehud-tool v0.8
github-tool v0.3
calendar-tool v0.2
files-tool v0.4
weather-tool v0.1
```

学习一个新工具，不等于“朝汐的大脑升级”。

---

# 4. Tool 开发优先级

## Tier S：第一阶段核心工具

### 1. lifehud-tool

Zhaoxi 第一优先级真实 Tool。

原因：

- 与个人生活记录直接关联
- 当前手动记录摩擦最大
- 数据结构由自己控制
- 最适合作为 Agent Tool 的第一个大型实践对象

建议版本：

#### v0.1 Read

- 查询任务
- 查询 Focus
- 查询睡眠
- 查询饮食
- 查询梦想
- 查询日记
- 查询状态

#### v0.2 Write

- 新增记录
- 修改记录
- 创建 Focus
- 结束 Focus
- 更新梦想
- 新增日记

#### v0.3 Natural Record

重点优化：

> “朝汐，记一下……”

自然语言 → 结构化 Life HUD 数据。

#### v0.4 Full API

逐步覆盖 Life HUD 全业务域。

#### v0.5 Event Integration

Life HUD 可以主动向 Zhaoxi 推送事件。

#### v1.0 Stable

成为 Zhaoxi 最稳定、最完整的第一方 Tool。

---

### 2. files-tool

目标：

> “朝汐，帮我找一下之前那份东西。”

能力：

- 文件搜索
- Markdown
- PDF
- 文档读取
- 元数据
- 文件定位
- 内容检索
- 安全写入
- 归档

第一阶段以 Read 为主。

---

### 3. calendar-tool

能力：

- 查询日程
- Free / Busy
- 新增事件
- 修改事件
- 删除事件
- 提醒
- Planner 联动

---

## Tier A：高价值生产力工具

### github-tool

能力演进：

```text
v0.1 Repo / Commit Read
v0.2 Issue / PR Read
v0.3 Project Summary
v0.4 Issue / PR Write
v0.5 Workflow Integration
```

重点服务：

- Life HUD
- Meme Vault
- Zhaoxi 自身
- 项目复盘
- 开发进度总结

---

### gmail-tool

能力演进：

```text
v0.1 Search / Read
v0.2 Summarize
v0.3 Draft
v0.4 Send with Permission
v0.5 Workflow Integration
```

发送邮件必须经过 Permission 层。

---

# 5. Tier B：环境与信息工具

## weather-tool

- 当前天气
- 未来天气
- 降雨
- 温度变化
- Proactive Agent 联动

## browser-tool

- Web Search
- 页面读取
- 信息整理
- Planner 联动

需要重点防范 Prompt Injection。

## system-tool

- 桌面状态
- 启动程序
- 切换壁纸
- 通知
- 系统信息

高风险系统操作必须严格受 Permission 层控制。

---

# 6. Tier C：未来扩展

可根据实际生活继续增加：

- Music Tool
- Anime / Movie Tool
- Game Tool
- Meme Vault Tool
- Smart Home Tool
- Personal Website Tool
- Job Search Tool
- Finance Tool
- Location / Map Tool
- Photo Tool
- Health Device Tool
- Home Assistant Tool
- 其他第三方服务

原则：

> **有真实需求再接，不为了“全能”而堆 API。**

Zhaoxi 的全能来自可扩展工具系统，而不是把所有能力一次性塞进仓库。

---

# 7. 推荐实际开发顺序

```text
Phase 1
Zhaoxi Core v0.1
↓
Agent 能独立运行
↓
lifehud-tool v0.1
↓
第一次真实 Tool Calling
```

```text
Phase 2
Core v0.2 Memory
+
lifehud-tool v0.2 / v0.3
↓
“朝汐，记一下”真正可用
```

```text
Phase 3
Core v0.3 Planner
+
files-tool
+
calendar-tool
+
github-tool
↓
开始跨系统办事
```

```text
Phase 4
Core v0.4 Permission
+
高风险 Write Tools
↓
从“能做”走向“敢长期用”
```

```text
Phase 5
Workflow
+
Proactive Agent
+
Desktop / Voice
↓
真正进入日常生活
```

```text
Phase 6
Reflection
+
Reliability
↓
长期陪伴型 Personal Agent
```

---

# 8. 第一阶段 MVP

第一阶段不追求“大而全”。

建议真正的 MVP：

### Zhaoxi Core v0.1

完成：

- 模型抽象
- Conversation
- Context
- Agent Runtime
- Tool Registry
- Personality
- Logging
- Session

### lifehud-tool v0.1 ~ v0.3

完成最有价值的一件事：

> **“朝汐，记一下……”**

例如：

```text
“朝汐，记一下，昨晚两点睡，十点半醒。”

“今天铁幕 13:40 到 17:20，刷了六题。”

“晚饭辣椒炒肉翻车了，记到饮食里。”

“今天把 Life HUD v0.5 做完了，顺便记个项目进展。”
```

目标：

> 让使用者开始愿意把原本需要手动维护的记录交给 Zhaoxi。

如果这一点成立，Zhaoxi 就已经不是 Demo，而是真正开始承担日常工作。

---

# 9. 项目长期定义

Zhaoxi 最终不应该成为：

- 第二个 Life HUD
- 套着犬娘皮肤的 ChatBot
- 一个巨大 if-else 路由器
- 所有个人数据的唯一数据库
- 为了展示 Agent 技术而存在的 Demo

而应该成为：

> **用户与个人数字世界之间的统一 Agent。**

她负责：

```text
听懂
→ 记得
→ 思考
→ 规划
→ 找到正确工具
→ 执行
→ 检查
→ 整理
→ 再和用户交互
```

Life HUD 是生活事实系统。

GitHub 是代码事实系统。

Calendar 是时间事实系统。

Files 是文档事实系统。

而 Zhaoxi：

> **连接这些系统，并让人不再需要亲自管理它们之间的碎片。**

---

# 10. 一句话版本路线

| 版本 | 定位 |
|---|---|
| v0.1 | 朝汐醒来 |
| v0.2 | 朝汐开始记得 |
| v0.3 | 朝汐开始自己规划 |
| v0.4 | 朝汐知道什么能做、什么要先问 |
| v0.5 | 朝汐能复用完整工作流 |
| v0.6 | 朝汐知道什么时候应该主动出现 |
| v0.7 | 朝汐真正进入桌面、语音与日常 |
| v0.8 | 朝汐开始理解一段生活 |
| v0.9 | 朝汐变得足够稳定可靠 |
| **v1.0** | **有事找朝汐** |

---

> **核心原则**
>
> **Zhaoxi 不保存用户的整个世界。**
>
> **Zhaoxi 连接用户的世界。**
