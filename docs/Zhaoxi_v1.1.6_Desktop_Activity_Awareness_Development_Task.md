# Zhaoxi v1.1.6 Development Task
# 桌面活动感知（Desktop Activity Awareness）

> 版本：v1.1.6  
> 基线：v1.1.5 Core Sovereignty  
> 主题：Desktop Presence / Foreground Semantics / Input Shape / Activity Inference  
> 核心目标：让朝汐不再只知道“是否全屏 / 是否空闲”，而能通过前台软件、窗口标题、键鼠输入频率、窗口切换和近期上下文，对用户当前活动形成低侵入、可解释、带置信度的判断，并把结果用于 ACTIVE、SEMI_ACTIVE、Interruptibility 与 Proactive。

---

## 0. 背景

v1.1.5 已完成 StateSignal、ACTIVE / SEMI_ACTIVE 重定义、Interaction State 与 Interruptibility 分离，以及 LifeHUD 与 Core 的解耦。

真实使用后发现，当前 Desktop Presence 仍过于贫瘠。朝汐主要只能看到：

```text
fullscreen
idle
user.returned
focus
```

因此主动消息容易集中在“退出全屏”“欢迎回来”“Focus 结束”一类泛化观察。

现实使用中：

- 全屏主要发生在看番 / 游戏；
- 开发、学习、求职往往需要多窗口切换；
- 前台进程 + 窗口标题比“是否全屏”更能说明当前活动；
- 键盘 / 鼠标输入频率可以帮助区分“正在写”与“正在看”。

因此新增：

# Desktop Activity Context

原则：

> **看行为形状，不记录输入内容。**  
> **看窗口语义，不把原始标题历史默认当长期记忆。**  
> **程序负责观察，模型负责理解。**

---

# 1. 不做 App Mapping

本版本明确不维护：

```text
Code.exe -> development
Firefox -> browser
Steam -> gaming
```

等硬编码映射。

同一程序可能承担完全不同用途，窗口标题已提供更丰富语义，LLM 应结合标题和上下文自行判断。

---

# 2. Raw Desktop Signals

至少采集：

```text
foreground_process
foreground_window_title
foreground_since

keyboard_rate_1m
keyboard_rate_5m

mouse_rate_1m
mouse_rate_5m

window_switch_rate_1m
window_switch_rate_5m

idle_seconds
fullscreen
desktop_available
```

---

# 3. Foreground Process / Window Title

获取当前前台窗口：

- 进程名；
- 当前窗口标题；
- 持续聚焦时长。

例如：

```text
Code.exe
memory_decision.py - ZhaoXi - Visual Studio Code
```

或：

```text
firefox.exe
JOJO的奇妙冒险 不灭钻石 第17集 - Firefox
```

只采集当前/近期焦点，不扫描全部后台窗口。

---

# 4. 标题数据边界

允许：

- 当前标题实时读取；
- 最近 10~30 分钟标题切换保存在内存；
- Activity Inference 时将有限近期标题提供给模型。

默认禁止：

- 永久保存所有标题历史；
- 每次窗口切换都写 Memory；
- 普通 diagnostics 输出完整标题；
- crash log 无条件 dump 标题。

---

# 5. Short-term Title Buffer

维护有界内存滚动缓冲：

```text
timestamp
process_name
window_title
duration
```

默认仅保留最近约 20 分钟，程序重启后无需恢复。

---

# 6. Keyboard Input Rate

只统计键盘事件频率：

```text
keyboard_rate_1m
keyboard_rate_5m
```

禁止记录：

- key code
- 具体按键
- 输入文本
- 快捷键内容

如果使用 `WH_KEYBOARD_LL`，callback 只允许计数。

---

# 7. Mouse Input Rate

只统计鼠标活动频率：

```text
mouse_rate_1m
mouse_rate_5m
```

禁止记录：

- 鼠标坐标
- 按钮类型
- 点击目标
- 移动轨迹

如果使用 `WH_MOUSE_LL`，callback 只允许计数。

---

# 8. Window Switch Rate

统计前台窗口切换频率：

```text
window_switch_rate_1m
window_switch_rate_5m
```

用于辅助区分：

- 单窗口持续写作；
- 多窗口查资料；
- 浏览跳转；
- 高频任务切换。

---

# 9. InputShape

新增抽象：

```text
InputShape:
  keyboard_rate_1m
  keyboard_rate_5m
  mouse_rate_1m
  mouse_rate_5m
  window_switch_rate_1m
  window_switch_rate_5m
  idle_seconds
```

表达“输入行为的形状”，不表达输入内容。

---

# 10. DesktopActivityContext

建议结构：

```text
observed_at
foreground_process
foreground_title
foreground_duration
recent_windows[]
input_shape
fullscreen
idle_seconds
interaction_state
interruptibility
recent_conversation_summary?
recent_memory_context?
current_intents?
tool_signals?
```

---

# 11. Activity Inference

新增：

```text
ActivityInference:
  primary_activity
  confidence
  alternative_hypotheses[]
  reason_summary
```

程序不直接硬判：

```text
正在写小说
正在编码
```

而是将 title + process + input shape + recent context 交给模型形成概率判断。

例如：

```text
primary_activity = 正在高强度修改 Zhaoxi 代码或技术文档
confidence = 0.89
```

---

# 12. 推测必须保留不确定性

禁止把概率判断当事实。

更合理的表达：

```text
“看标题和输入状态，你好像正在写东西？”
```

而不是：

```text
“你正在写小说。”
```

---

# 13. Context Fusion

Activity Inference 可结合：

```text
foreground title
process
input shape
recent conversation
recent Memory
current Intent
Tool Signals
current time
```

例如：

```text
title = memory_decision.py - ZhaoXi
keyboard high
recent conversation = 正在修朝汐记忆系统
```

可高置信推测：

```text
正在继续开发 Zhaoxi
```

---

# 14. Activity Mode

程序层可保留非常粗的中间标签：

```text
text_production
reading
browsing
mixed_work
media_consumption
gaming
idle
unknown
```

这些只是辅助特征，不通过 App Mapping 产生。

---

# 15. Activity Intensity / Duration

支持：

```text
activity_intensity = LOW / MEDIUM / HIGH
activity_duration
```

依据键鼠频率、窗口切换、idle 和持续时间计算。

---

# 16. Activity Transition

新增：

```text
ActivityTransition
```

重点检测：

```text
text_production -> idle
browsing -> text_production
fullscreen media -> desktop
gaming -> desktop
high_input -> silence
```

可产生高层事件：

```text
activity.started
activity.stopped
activity.intensity_changed
activity.context_switched
activity.deep_work_ended
```

不要每次窗口切换都触发 Proactive。

---

# 17. 场景推断参考

## 写代码 / 写文本

```text
Code.exe
标题含项目/文件
keyboard high
mouse low
switch low
持续 20min+
```

=> `text_production / coding-like`

## 看代码

```text
Code.exe
keyboard near zero
mouse low
```

=> `reading`

## 查资料 + 实现

```text
VSCode ↔ Browser
window_switch high
keyboard medium/high
mouse medium
```

=> `mixed_work / research + implementation`

## 看番

```text
fullscreen
标题有媒体语义
keyboard/mouse near zero
```

=> `media_consumption`

## 游戏

```text
fullscreen
游戏相关标题
keyboard/mouse active
```

=> `gaming`

## 写小说 / 长文本

```text
title = chapter_07.md - VSCode
keyboard high
switch very low
recent Memory = 最近在写故事
```

=> `long-form text production / likely writing`

---

# 18. ACTIVE 集成

Desktop Activity Awareness 必须服务 Conversation Loop。

例如：

```text
ACTIVE
+
keyboard high
+
text_production
```

仍保持 ACTIVE，但：

```text
interruptibility = LOW
```

Conversation Continuation 应暂缓。

---

# 19. ACTIVE 输入停止

若：

```text
keyboard_rate_5m high
keyboard_rate_1m near zero
idle_seconds rising
```

说明：

> 刚刚持续在写，现在停下来了。

此时 Continuation 可以重新成为候选。

不要机械地在“沉默 3 分钟”后追问。

---

# 20. SEMI_ACTIVE 集成

SEMI_ACTIVE 的主动判断应优先使用 Activity Context，而不是只围绕：

```text
fullscreen
returned
focus
```

例如：

```text
VSCode 高频输入 35min
↓
输入明显停止
```

可以形成候选：

```text
“刚才好像写了挺久，现在终于停下来啦？”
```

---

# 21. Fullscreen 降级

保留：

```text
fullscreen=true/false
```

但它只是辅助特征。

禁止单独因为：

```text
fullscreen.entered
fullscreen.exited
```

就产生高权重主动消息。

应结合：

```text
media session ended
gaming session ended
activity transition
```

后再判断。

---

# 22. AmbientContextSnapshot

为 SEMI_ACTIVE 增加：

```text
current_activity
activity_duration
recent_activity_transition
recent_conversation_topics
recent Memory clusters
current intents
recent proactive history
tool signals
time
```

这将成为普通主动关心、BackgroundIntent 与 future surprise 的主要输入之一。

---

# 23. BackgroundIntent

Activity Context 可以辅助生成：

```text
BackgroundIntent
```

例如：

```text
最近连续几晚都在开发 Zhaoxi
```

可准备：

```text
下次合适时提起最近开发强度
```

但：

> `prepare != send`

本版本仍不要求完整 Surprise System。

---

# 24. Activity 与 Memory

原始标题历史不直接写入 Memory。

例如短期观察：

```text
VSCode
GitHub
memory_decision.py
Zhaoxi task
```

如果值得形成长期生活痕迹，Memory 只保存高层经历：

```text
晚上约 21 点，暗苟持续在 VSCode 与 GitHub 之间切换，继续开发 Zhaoxi。
```

---

# 25. 数据保留策略

```text
Raw keyboard/mouse event
→ 不落盘

Rate
→ 内存 rolling window

Window title buffer
→ 内存短期保存

ActivityInference
→ 短期缓存

Long-term Memory
→ 只保存高层生活事件
```

---

# 26. Windows 实现建议

现有 Win32 Presence 基础上扩展。

可能涉及：

```text
GetForegroundWindow
GetWindowThreadProcessId
OpenProcess
QueryFullProcessImageNameW
GetWindowTextW
GetWindowTextLengthW
```

键鼠频率使用轻量 hook 或等价机制，只计数。

---

# 27. Sampling 与成本

建议：

```text
raw desktop sample: 1~5s
activity feature update: 5~15s
semantic activity inference: 30~120s 或事件触发
```

禁止每秒调用 LLM。

优先：

```text
纯代码提取特征
↓
需要语义理解/主动行为时才调用模型
```

---

# 28. LLM 调用时机

可以在：

- foreground title 变化并稳定一段时间；
- ActivityTransition；
- SEMI_ACTIVE proactive candidate；
- ACTIVE continuation candidate；
- BackgroundIntent evaluation；

需要时使用最新 `DesktopActivityContext`。

不允许“窗口每变一下就问模型一次”。

---

# 29. StateSignal 输出

Desktop Activity Provider 可输出：

```text
desktop.foreground_process
desktop.foreground_title
desktop.activity_mode
desktop.activity_intensity
desktop.input_active
desktop.activity_transition
```

State Machine 仍只消费标准 Signal。

本模块不得依赖 LifeHUD。

---

# 30. Interruptibility

参考策略：

```text
AWAY / lock -> BLOCKED

持续高输入 + text production -> LOW

fullscreen media/game -> LOW

刚刚停止长时间高输入 -> NORMAL / HIGH

SEMI_ACTIVE + user present + no intense activity -> HIGH

其他 -> NORMAL
```

具体阈值可配置，不要写死在多个模块。

---

# 31. 配置项

建议：

```env
ZHAOXI_DESKTOP_ACTIVITY_ENABLED=true
ZHAOXI_DESKTOP_ACTIVITY_WINDOW_TITLE_ENABLED=true
ZHAOXI_DESKTOP_ACTIVITY_INPUT_RATE_ENABLED=true

ZHAOXI_DESKTOP_ACTIVITY_TITLE_BUFFER_MINUTES=20
ZHAOXI_DESKTOP_ACTIVITY_SAMPLE_INTERVAL_SECONDS=2
ZHAOXI_DESKTOP_ACTIVITY_INFERENCE_INTERVAL_SECONDS=60
```

---

# 32. Diagnostics

建议新增：

```text
desktop_activity:
  enabled
  title_enabled
  input_rate_enabled
  foreground_process
  activity_mode
  activity_intensity
  activity_duration
  keyboard_rate_1m
  keyboard_rate_5m
  mouse_rate_1m
  mouse_rate_5m
  window_switch_rate_1m
  last_transition
  healthy
```

普通 diagnostics 默认不显示完整窗口标题。

---

# 33. Inspect

新增开发调试入口，例如：

```text
/api/desktop/activity/inspect
```

可查看：

```text
current title
recent title buffer
raw rates
activity hypothesis
confidence
reason
```

仅用于显式 inspect / debug。

---

# 34. 测试要求

至少覆盖：

### Foreground
- 正确获取 process name
- 正确获取 title
- title buffer 更新
- 不扫描后台所有窗口

### Keyboard
- 只更新 counter
- 不保存 key code
- 1m / 5m rate 正确

### Mouse
- 只更新 counter
- 不保存坐标
- rate 正确

### Window switch
- 切换频率正确

### Activity inference
- Code + high keyboard -> text production
- Code + low input -> reading
- Browser + frequent switching -> browsing/mixed
- fullscreen + media title + low input -> media
- fullscreen + high input -> gaming/interactive

### ACTIVE
- 高键盘输入时 continuation 延迟
- 输入停止后 continuation 恢复

### SEMI_ACTIVE
- 长时间 text production 结束后产生 ActivityTransition 候选
- 不再只依赖 fullscreen change

### Persistence
- raw title buffer 不长期落盘
- raw input events 不落盘
- diagnostics 不默认泄露 title

### Independence
- LifeHUD 完全禁用时仍正常运行

---

# 35. 性能要求

桌面采样必须轻量：

- CPU 开销可忽略
- 不阻塞 UI
- Win32 sampling / hook 独立线程
- 内存 buffer 有界
- 无持续原始磁盘写入
- 模型调用严格低频

---

# 36. 不在本版本处理

明确不做：

- 截图分析
- OCR
- 读取剪贴板
- 浏览器 DOM
- 浏览器扩展
- Accessibility 全量树
- 输入文本捕获
- keylogger
- 鼠标轨迹记录
- 所有后台窗口扫描
- App Mapping
- 完整 Surprise System
- 长期桌面行为统计看板

---

# 37. 完成标准

v1.1.6 完成后必须满足：

1. 获取当前前台进程。
2. 获取当前窗口标题。
3. 统计键盘输入频率。
4. 统计鼠标输入频率。
5. 统计窗口切换频率。
6. 不保存按键内容。
7. 不保存鼠标坐标。
8. 标题默认只实时/短期保存。
9. 不维护 App Mapping。
10. 能形成 DesktopActivityContext。
11. 能结合 title + input shape + recent context 推测活动。
12. ActivityInference 带 confidence。
13. ActivityTransition 可形成高层事件。
14. fullscreen 只是普通辅助特征。
15. ACTIVE 可根据高输入降低打扰。
16. ACTIVE 在输入停止后恢复 Continuation 候选。
17. SEMI_ACTIVE 可使用 Activity Context 生成更自然主动候选。
18. 普通 Proactive 不再单靠 fullscreen change。
19. 本模块不依赖 LifeHUD。
20. Raw input event 不落盘。
21. 原始标题不默认长期落盘。
22. Memory 只保存高层经历。
23. diagnostics 不默认暴露完整标题。
24. inspect 可用于调试。
25. 现有 v1.1.5 State / Proactive / Desktop 测试保持通过。

---

# 38. 手动验收

## A. 写代码

VSCode 持续高频输入：

```text
foreground = Code.exe
title = 当前文件/项目
keyboard high
activity = text production / coding-like
interruptibility = LOW
```

## B. 看代码

VSCode 但几乎无输入：

```text
activity = reading
```

## C. 查资料

VSCode 与浏览器频繁切换：

```text
activity = mixed research / implementation
```

## D. 看番

全屏播放动画：

```text
fullscreen = true
keyboard/mouse low
title 有媒体语义
activity = media consumption
```

退出全屏后不应仅因 fullscreen exit 主动发言。

## E. 游戏

游戏全屏 + 高频输入：

```text
activity = gaming / interactive
```

## F. ACTIVE 对话中动手

用户说：

```text
“我去试下刚才这个修复。”
```

随后 VSCode 高频输入。

预期：

- 保持 ACTIVE
- Continuation 暂缓
- 不机械追问

输入明显停止后，Continuation 可再次成为候选。

## G. SEMI_ACTIVE

用户未聊天，持续高输入 30 分钟后停止。

预期：

可形成：

```text
刚才持续写了很久，现在停下来了
```

类 ActivityTransition，使主动消息围绕真实活动，而不是“退出全屏”。

---

# 39. 开发完成后汇报

Codex 完成后请明确汇报：

- 修改文件
- Foreground API
- Window Title 获取方式
- Keyboard Rate 实现
- Mouse Rate 实现
- Window Switch 统计
- Title Buffer
- Raw 数据保留策略
- DesktopActivityContext schema
- ActivityInference schema
- Activity Mode / Intensity / Duration
- ActivityTransition
- Context Fusion
- LLM 调用条件
- ACTIVE 集成
- SEMI_ACTIVE 集成
- Interruptibility 集成
- Proactive 降噪
- StateSignal 输出
- Diagnostics / Inspect
- CPU / Memory 开销
- 自动测试
- 手动验收
- 已知限制

---

# 40. 本版本理念

过去朝汐看到的是：

```text
全屏了。
退出全屏了。
回来了。
开始 Focus 了。
```

这些只是粗糙状态灯。

v1.1.6 之后，希望她看到的是：

```text
现在前台开着什么。
窗口上写着什么。
刚才一直在敲键盘，还是只在看。
是在一个窗口里持续写，还是在浏览器和编辑器之间切换。
刚刚持续忙了多久。
现在是不是终于停下来了。
```

她不需要知道暗苟具体敲了哪些字，也不需要知道鼠标点了哪里。

她只需要能理解：

> **暗苟此刻大概正在做什么。**

程序负责观察这些痕迹。

模型负责理解它们的意义。

Memory 只留下真正值得记住的高层经历。

这就是：

# Desktop Activity Awareness

> **朝汐不需要盯着暗苟的手。**
>
> **她只需要看得懂，暗苟现在像是在忙什么。**
