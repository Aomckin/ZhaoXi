# Zhaoxi v1.1.2 Development Task
# 潮间态（Intertidal Presence）与生活感知增强

> 版本：v1.1.2  
> 主题：Unified Timeline / Interaction State / Desktop Presence Sensors / Dynamic Proactive Gate / Dynamic Suggestions  
> 核心目标：让朝汐不仅“持续醒着”，还能够理解消息发生的时间、用户当前是否活跃、是否正在使用电脑，以及什么时候更适合主动开口。

---

## 0. 背景

Zhaoxi v1.1.1 已完成「潮汐心跳 / Tidal Heartbeat」第一阶段：

- Heartbeat 常驻循环
- LifeHUD / Focus / Reminder 等事件感知
- Event Buffer
- Rule / Score Gate
- Cooldown
- Quiet Mode
- LLM Decision
- Proactive Delivery
- Windows 通知
- 主动消息 Inbox
- 主动消息与会话上下文闭环

当前系统已经能够主动发现部分生活事件，例如：

- Focus 持续时间过长
- Reminder 到期
- 部分 LifeHUD 状态变化

但实际长期使用后暴露出几个核心问题：

1. 普通聊天消息缺少可靠的时间信息，模型无法知道“什么时候发生了什么”。
2. 当前 Proactive 感知来源仍然过少，长期运行时主动性偏弱。
3. Heartbeat 仍然使用接近固定的一套主动规则，无法区别“刚刚聊完”“用户离开很久”“用户刚回来”等不同互动状态。
4. Desktop Presence 对用户当前使用电脑的状态感知不足。
5. 右侧快捷建议仍然是硬编码 Demo 文案，缺少上下文适应能力。
6. 前端仍有少量明显影响日常使用观感的问题。

v1.1.2 的目标是解决：

> 朝汐是否知道现在是什么时候、暗苟现在是否在电脑前、最近是否刚刚聊过、当前是不是适合主动说话。

---

# 1. 本版本核心目标

v1.1.2 完成后，朝汐需要能够理解：

- 每条消息是什么时候发生的
- 距离上一轮对话过去了多久
- 用户当前是否正在积极使用电脑
- 用户是否刚刚离开
- 用户是否刚刚回来
- 当前窗口是否全屏
- 用户最近是否存在键盘 / 鼠标活动
- 当前交互状态属于 ACTIVE / SEMI_ACTIVE / IDLE / AWAY 中哪一种
- 不同状态下应该使用不同的主动发言阈值
- 快捷输入建议应根据最近状态动态变化

---

# 2. Unified Timeline：统一消息时间轴

## 2.1 Message 必须带时间

普通 Conversation Message 必须增加可靠时间信息。

建议至少增加：

```python
created_at: datetime
```

要求：

- 用户消息有时间
- Assistant 消息有时间
- 主动消息有时间
- 系统恢复后的历史消息仍保留原始时间
- 时间必须持久化进 Session Store / DB
- 不允许只在前端显示时间而后端模型上下文仍然没有时间

## 2.2 时间必须进入模型上下文

当前若模型只看到：

```text
USER: 我好累
ASSISTANT: 那早点休息
USER: 好
```

是不够的。

应让模型能够理解：

```text
[2026-09-06 17:41] 暗苟酱：
程序员的八股文好多啊……

[2026-09-06 17:42] 朝汐：
……

[2026-09-06 17:51] 暗苟酱：
……
```

不要求固定使用该文本格式，但模型必须知道：

- 绝对时间
- 消息先后
- 明显时间间隔

可选：

- 相对时间
- “10 分钟前”
- “昨天晚上”

但绝对时间是 P0。

## 2.3 主动消息进入同一时间轴

Proactive Delivery 不应成为和 Conversation 完全割裂的另一套时间系统。

至少需要让朝汐在后续对话中知道：

```text
11:23 朝汐主动提醒 Focus
11:27 暗苟回复
11:28 朝汐继续聊天
17:41 暗苟再次打开朝汐
```

目标：

> 朝汐拥有一条统一的生活交互时间线。

---

# 3. Interaction State：互动状态机

新增长期运行时的互动状态。

建议至少四种：

```text
ACTIVE
SEMI_ACTIVE
IDLE
AWAY
```

## 3.1 ACTIVE

定义：

> 用户当前正在与朝汐明显互动。

触发条件可包括：

- 用户发送消息
- 连续进行对话
- 点击 Proactive 消息并回复
- 手动唤起朝汐后发生交互

建议：

每次新互动都刷新 ACTIVE 计时。

初始参考持续时间：

```text
15 ~ 30 分钟
```

具体可配置。

ACTIVE 状态下：

- 主动发言阈值降低
- Heartbeat 更关注近期上下文
- 朝汐允许稍微更积极地跟进
- 不触发 Natural Check-in
- 不应突然因为普通事件打断正在进行的对话

语义：

> “我们现在正在一起。”

## 3.2 SEMI_ACTIVE

定义：

> 用户并未直接聊天，但当前处于较高概率愿意接受互动的状态。

来源包括：

### ACTIVE 自然衰减

```text
ACTIVE
↓ 一段时间无互动
SEMI_ACTIVE
```

### 外部状态触发

例如：

- 长时间 Idle 后重新产生键鼠输入
- 用户从 AWAY 回来
- 退出全屏
- Focus 刚刚结束
- 在常见活跃时间段重新开始使用电脑
- Desktop Window 被唤起但暂未输入

SEMI_ACTIVE 状态下：

- 主动阈值低于 IDLE
- 允许轻量 Proactive
- 可更容易产生 Natural Check-in
- 不应像 ACTIVE 一样持续黏着

建议持续：

```text
30 ~ 60 分钟
```

## 3.3 IDLE

默认状态。

语义：

> 朝汐一直在，但当前没有特别强的互动预期。

使用正常 Proactive Gate 阈值。

## 3.4 AWAY

定义：

> 用户明显不在电脑前。

可由以下条件触发：

- 长时间无键盘鼠标输入
- 锁屏
- 系统睡眠
- 用户会话不可见
- 其他明确离开状态

AWAY 状态下：

- 普通 Proactive 不主动 speak
- 普通事件可进入 Inbox
- 延迟低优先级消息
- Reminder / 高优先级事件按现有规则处理
- 不进行 Natural Check-in

从 AWAY 恢复输入时：

```text
AWAY -> SEMI_ACTIVE
```

并产生：

```text
user.returned
```

候选事件。

---

# 4. Interaction State 与 Proactive Gate

v1.1.1 的 Score Gate 需要接入 Interaction State。

不要继续使用固定阈值。

建议初始参考：

```text
ACTIVE:       threshold 0.45
SEMI_ACTIVE:  threshold 0.55
IDLE:         threshold 0.70
AWAY:         普通 speak 禁止
```

具体数值可调整，不要求机械使用。

最终评分可考虑：

```text
base_score
+ event_importance
+ urgency
+ recent_interaction
+ state_modifier
+ activity_modifier
+ context_relevance
- cooldown
- quiet_penalty
- fullscreen_penalty
- away_penalty
- duplicate_penalty
```

---

# 5. Desktop Presence Sensors

新增 Desktop 侧轻量感知。

重点：

> 只感知状态，不读取用户输入内容。

严禁实现 Keylogger。

## 5.1 Last Input / Idle Sensor

通过 Windows API 获取：

```text
距离最后一次用户输入多久
```

建议输出：

```text
last_input_seconds
user_active
idle_duration
```

允许进一步归一化成：

```text
activity_level = low / medium / high
```

但不能记录：

- 用户按了什么键
- 用户输入了什么文字
- 鼠标点了哪里
- 剪贴板内容

## 5.2 Foreground Window Sensor

只读取轻量信息：

```text
foreground_process
foreground_duration
fullscreen
```

例如：

```text
foreground_process = firefox.exe
fullscreen = true
foreground_duration = 48min
```

不要默认读取：

- 网页正文
- 窗口标题中的敏感内容
- 文档内容
- 输入框内容

如果需要窗口标题用于内部识别，应做成可配置能力，并默认关闭。

## 5.3 Fullscreen Sensor

检测当前是否存在全屏窗口。

注意：

全屏本身通常不是“更应该主动发言”的信号。

很多时候恰恰应当：

```text
fullscreen = true
↓
普通主动消息 defer
```

更有价值的是状态变化：

```text
fullscreen.entered
fullscreen.exited
```

尤其：

```text
fullscreen.exited
```

可以作为 SEMI_ACTIVE 的候选触发。

---

# 6. 状态变化事件优先于静态状态

Sensor 不应每次 Heartbeat 都重复生成：

```text
fullscreen=true
user_active=true
```

更重要的是：

```text
user.returned
user.away
activity.started
activity.stopped
fullscreen.entered
fullscreen.exited
focus.started
focus.ended
conversation.started
conversation.cooled
```

目标：

> 朝汐生活在“变化”里，而不是被静态状态刷屏。

这些事件必须支持：

- dedupe
- TTL
- last_seen
- 状态缓存

---

# 7. Desktop Sensor 与 Heartbeat 集成

Heartbeat 每次循环只负责轻量采样。

例如：

```text
Heartbeat
↓
读取 Last Input
读取 Foreground App
读取 Fullscreen
读取 Interaction State
↓
比较上一轮 snapshot
↓
生成状态变化事件
↓
Event Buffer
```

要求：

- 不调用 LLM
- 不产生高 CPU 占用
- 不做低级键盘 Hook
- 不记录输入内容

---

# 8. Natural Check-in 调整

v1.1.1 已存在 Natural Check-in。

v1.1.2 需要结合 Interaction State。

规则参考：

### ACTIVE
不触发 Natural Check-in。

### SEMI_ACTIVE
可较容易触发轻量 check-in。

### IDLE
使用正常低频 check-in。

### AWAY
禁止触发。

此外：

- 用户刚回来
- 刚退出全屏
- 刚结束 Focus

可作为低成本 check-in 候选。

---

# 9. Quick Suggestions：动态便携输入建议

当前右侧“可以这样找我”的四条内容为硬编码 Demo 文案。

需要改为动态 Suggestions。

## 9.1 目标

四条建议应根据：

- 最近对话
- 当前时间
- LifeHUD 状态
- 当前 Interaction State
- 最近 Proactive
- 最近活动

动态变化。

例如：

```text
帮我看看今天还有什么没收尾。
朝汐，陪我聊会儿。
看看 LifeHUD 现在是什么状态。
我准备继续写代码了。
```

## 9.2 不允许高频额外调用模型

优先复用已有 LLM 调用。

建议：

```text
普通聊天 / Proactive Decision 调用模型
↓
顺便返回 quick_suggestions
↓
缓存
```

如果长期没有模型调用，再使用低频刷新：

```text
每 2 ~ 4 小时最多额外刷新一次
```

具体周期可配置。

## 9.3 Suggestions 约束

四条建议：

- 不要同质化
- 至少一条偏聊天
- 至少一条偏行动
- 至少一条与当前生活状态有关
- 不要永远都是“帮我制定计划”
- 不要泄露内部 Event / Debug 信息
- 如果无上下文，允许使用通用但自然的建议

---

# 10. Quick Suggestions 缓存

建议保存：

```text
generated_at
suggestions[]
source_context
```

无需持久保存太久。

应用重启后可重新生成或使用短期缓存。

---

# 11. 前端小修：图片输入按钮

当前输入框左侧“图片”文字在窄区域中出现竖向排布：

```text
图
片
```

视觉效果异常。

修改要求：

- 改为纯图片 / 相册图标按钮
- 不继续显示两个竖排汉字
- Hover / Tooltip 显示“添加图片”
- 保留现有上传能力
- 保留当前输入区整体结构
- 不重做整个输入组件

---

# 12. 前端小修：Zhaoxi 应用图标

当前 Desktop 标题栏仍显示 Python 默认图标。

需要替换为 Zhaoxi 自有应用图标。

优先统一：

- Desktop 标题栏图标
- Windows 任务栏图标
- System Tray 图标
- Web favicon

当前阶段：

- 可直接使用 UI 内现有蓝底“汐”字图标作为占位正式图标
- 不要求本版本设计复杂 Logo
- 不允许继续使用 Python 默认图标

注意：

不要打包或传播字体文件。

---

# 13. 时间显示统一

当前主动消息存在：

- 左侧显示 UTC / ISO 时间
- 右侧显示本地时间

需要统一。

用户可见时间：

- 使用本地时区
- 默认当前项目可继续使用 Asia/Shanghai
- 不直接显示长 ISO UTC 字符串

建议用户可见格式：

```text
2026/9/6 11:23
```

或：

```text
今天 11:23
```

内部仍保留 timezone-aware datetime。

---

# 14. Debug 信息与正式对话分离

当前主动消息可能在聊天区域显示：

```text
[朝汐主动消息 · ISO时间]
相关背景：当前 Focus ...
```

这些内容过于工程化。

修改要求：

正式聊天区只显示朝汐真正说的话。

例如：

```text
暗苟酱，你已经盯着那些八股看了快一个半小时啦……
```

以下信息移入 Debug / Activity / Inspector：

```text
delivery_id
event_type
source
score
trigger_reason
related_payload
raw timestamp
```

不应混入朝汐正常发言正文。

---

# 15. 与现有系统的关系

优先复用：

- Tidal Heartbeat
- Event Buffer
- Score Gate
- Proactive Runtime
- Proactive Store
- Session Store
- Conversation
- Desktop Presence
- LifeHUD Tool
- existing metrics

不要重写 v1.1.1。

本版本是：

> 在现有潮汐心跳之上，增加时间感、桌面环境感与互动状态感。

---

# 16. 建议配置项

可考虑新增：

```env
ZHAOXI_ACTIVE_TIMEOUT_MINUTES=20
ZHAOXI_SEMI_ACTIVE_TIMEOUT_MINUTES=45
ZHAOXI_AWAY_IDLE_MINUTES=30

ZHAOXI_PROACTIVE_THRESHOLD_ACTIVE=0.45
ZHAOXI_PROACTIVE_THRESHOLD_SEMI_ACTIVE=0.55
ZHAOXI_PROACTIVE_THRESHOLD_IDLE=0.70

ZHAOXI_QUICK_SUGGESTIONS_REFRESH_MINUTES=180
```

名称可按现有 Settings 风格调整。

不要一次暴露大量细粒度参数。

---

# 17. Metrics / Diagnostics

建议新增：

```text
interaction_state
last_user_interaction_at
last_input_seconds
foreground_process
fullscreen
away_since
state_transitions
quick_suggestions_generated
quick_suggestions_llm_calls
```

注意：

Diagnostics 不暴露敏感窗口内容。

---

# 18. 测试要求

## Unified Timeline

- 用户消息保存 created_at
- Assistant 消息保存 created_at
- Proactive 消息保存时间
- Session Reload 后时间仍正确
- 模型上下文能看到消息时间
- 不同日期 / 跨天时间正确

## Interaction State

- 用户发消息 -> ACTIVE
- ACTIVE 超时 -> SEMI_ACTIVE
- SEMI_ACTIVE 超时 -> IDLE
- 长时间无输入 -> AWAY
- AWAY 后恢复输入 -> SEMI_ACTIVE
- 新互动刷新 ACTIVE timeout

## Desktop Sensors

- 能读取 last input
- 不记录按键内容
- 能检测全屏
- 全屏状态变化只生成一次事件
- foreground process 切换可生成变化事件
- Sensor 异常不会导致 Heartbeat 崩溃

## Dynamic Gate

- ACTIVE 阈值低于 IDLE
- AWAY 抑制普通 Proactive
- fullscreen 抑制普通低优先级主动消息
- fullscreen.exited 可产生候选事件
- user.returned 可产生候选事件

## Suggestions

- 不再使用四条硬编码内容
- 缓存有效
- 正常聊天 LLM 调用可顺便刷新建议
- 长时间无模型调用时最多低频刷新
- 不形成高频额外 LLM 成本

## UI

- 图片按钮不再竖排文字
- Tooltip 正常
- Desktop 不再显示 Python 默认图标
- 本地时间显示统一
- Debug 信息不混入正式聊天正文

---

# 19. 手动验收场景

## 场景 A：连续聊天

1. 与朝汐发送多轮消息
2. 查看 Interaction State

预期：

```text
ACTIVE
```

并持续刷新 ACTIVE timeout。

## 场景 B：聊天结束

停止互动。

预期：

```text
ACTIVE -> SEMI_ACTIVE -> IDLE
```

按配置时间自然衰减。

## 场景 C：离开电脑

长时间不进行键鼠输入。

预期：

```text
IDLE / SEMI_ACTIVE -> AWAY
```

普通 Proactive 不弹。

## 场景 D：重新回来

AWAY 后恢复键鼠输入。

预期：

```text
AWAY -> SEMI_ACTIVE
```

产生一次 `user.returned` 候选。

不得每次键鼠输入重复产生。

## 场景 E：全屏

进入全屏程序。

预期：

- `fullscreen.entered`
- 普通低优先级 Proactive 被 defer

退出全屏：

- `fullscreen.exited`
- 可进入 SEMI_ACTIVE / Proactive 候选

## 场景 F：时间上下文

晚上和朝汐聊天。

第二天下午继续对话。

预期：

朝汐能够从上下文知道：

> 上一次对话发生在昨天晚上。

而不是把两段消息当作连续发生。

## 场景 G：快捷建议

观察右侧四条建议。

预期：

- 不再固定
- 能随近期聊天 / LifeHUD / 时间变化
- 数小时内不会频繁额外调模型
- 至少有聊天类和行动类建议

---

# 20. 不在本版本处理

暂不处理：

- Personality 再重构
- Voice 大改
- Reflection 大改
- Planner 大改
- Workflow 大改
- Memory 主体重构
- 屏幕截图理解
- OCR
- 键盘内容监听
- 鼠标点击内容监听
- 浏览器网页正文读取
- 深度 Desktop Automation
- 复杂推荐系统
- 大型 UI 重构

---

# 21. 完成标准

v1.1.2 完成后应满足：

1. 所有普通消息拥有可靠时间。
2. 时间进入模型上下文。
3. Proactive 与普通对话位于可理解的统一时间线上。
4. Interaction State 正常运行。
5. 支持 ACTIVE / SEMI_ACTIVE / IDLE / AWAY。
6. 不同状态使用不同主动阈值。
7. 能感知用户是否长期离开电脑。
8. 能感知用户是否刚回来。
9. 能感知全屏状态及变化。
10. 只记录键鼠“是否活跃”，不记录输入内容。
11. Desktop Sensor 不显著增加资源占用。
12. Natural Check-in 接入 Interaction State。
13. 右侧四条快捷建议不再硬编码。
14. Suggestions 不产生高频额外 LLM 成本。
15. 图片上传按钮不再出现竖排“图片”。
16. Desktop / Taskbar 不再显示 Python 默认图标。
17. 用户可见时间统一为本地时间。
18. Debug 背景信息不混入正式朝汐发言。
19. 现有 v1.1.1 Proactive 能力保持正常。
20. 现有自动测试保持通过。

---

# 22. 开发完成后汇报

请明确汇报：

- 修改文件
- Message / Session 时间字段方案
- 模型上下文如何注入时间
- Interaction State 状态机
- 状态转换条件
- Desktop Sensor 实现方式
- 使用的 Windows API
- 是否读取任何输入内容
- Fullscreen 判断方式
- Dynamic Gate 调整
- Natural Check-in 调整
- Suggestions 生成与缓存方案
- Suggestions 额外 LLM 调用频率
- 图标修改位置
- 图片按钮修改位置
- 时间显示修改位置
- Debug 信息分离方案
- 自动测试结果
- 手动验收步骤
- 已知限制

---

# 23. 本版本理念

v1.1.1 解决的是：

> **朝汐一直醒着。**

v1.1.2 解决的是：

> **朝汐知道暗苟现在大概处于什么状态。**

她应该逐渐理解：

- 暗苟刚刚还在和她聊天。
- 暗苟已经离开电脑很久。
- 暗苟刚刚回来。
- 暗苟正在全屏做别的事情。
- 暗苟结束了一段活动。
- 昨晚的话题和今天下午的话题之间隔了很久。

她不需要窥视屏幕里的每一行字。

只需要像一个真正生活在身边的人一样，知道：

> 现在是什么时候。  
> 暗苟在不在。  
> 现在是不是适合开口。

这就是：

# Intertidal Presence

> 潮水不仅要流动。  
> 还要知道岸边的人，此刻离海有多近。
