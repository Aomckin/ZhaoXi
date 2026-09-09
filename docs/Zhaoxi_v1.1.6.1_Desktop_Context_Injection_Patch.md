# Zhaoxi v1.1.6.1 Patch Task
# Desktop Context Injection

> 基线：v1.1.6 Desktop Activity Awareness  
> 类型：小补丁  
> 目标：将已经采集完成的 DesktopActivityContext 正式注入普通对话 Runtime Context，让朝汐在 DIRECT / 普通聊天中真正“看得到”当前前台软件、窗口标题和输入状态。

---

## 0. 问题

v1.1.6 已经实现：

- foreground process
- foreground window title
- keyboard / mouse rate
- window switch rate
- DesktopActivityContext
- ActivityInference
- Proactive / Continuation 集成
- Inspect

但当前普通聊天链路中，朝汐模型并没有稳定拿到 DesktopActivityContext。

因此即使采集端已经能看到：

```text
Code.exe
memory_decision.py - ZhaoXi - Visual Studio Code
keyboard_rate_1m = 80
```

用户直接问：

```text
你现在能看到我在哪个软件吗？
```

朝汐仍可能回答：

```text
我现在看不到你的焦点软件。
```

问题本质：

```text
Desktop Sensor
↓
DesktopActivityContext
├─ Proactive ✅
├─ Continuation ✅
├─ Inspect ✅
└─ Ordinary Conversation ❌
```

---

## 1. 核心修复

把当前 DesktopActivityContext 注入普通对话 Runtime Context。

目标：

```text
Desktop Sensor
↓
DesktopActivityContext
↓
Runtime Context
├─ Ordinary Conversation ✅
├─ Conversation Continuation
├─ Proactive
└─ Inspect
```

---

## 2. 注入字段

普通对话至少能看到：

```text
available
stale
age_seconds
observed_at

foreground_process
foreground_title
foreground_duration

keyboard_rate_1m
keyboard_rate_5m
mouse_rate_1m
mouse_rate_5m
window_switch_rate_1m
window_switch_rate_5m

fullscreen
idle_seconds

activity_mode
activity_intensity
activity_confidence
activity_summary

interaction_state
interruptibility
```

字段按现有数据结构适配，不要求重复定义 schema。

---

## 3. 不新增额外 Activity LLM 调用

普通聊天本身已经需要调用模型。

因此：

- 若已有缓存 ActivityInference：一起注入；
- 若没有缓存：只注入 raw DesktopActivityContext；
- 由当前聊天模型自己结合标题和输入状态理解。

禁止：

```text
每条普通消息额外调用一次 ActivityInference LLM
```

---

## 4. Staleness

必须处理过期感知。

例如：

```text
available = true
stale = false
age_seconds = 1.8
```

可以自然表达：

> 你现在在 VS Code。

如果：

```text
stale = true
```

则只能表达：

> 我最后看到你刚才在 VS Code。

如果：

```text
available = false
```

才允许说：

> 我现在读不到你的桌面活动。

避免把旧快照伪装成实时状态。

---

## 5. Prompt / Context Builder

建议新增独立 Runtime 区块：

```text
[Desktop Activity]
...
```

不要混入 Personality / Memory / Archive。

它属于：

```text
runtime observation
```

不是长期事实。

---

## 6. 隐私边界保持不变

继续遵守 v1.1.6：

- 不记录按键内容
- 不记录鼠标坐标
- 不扫描后台所有窗口
- 不自动长期保存原始标题
- 普通日志不 dump 完整 title
- Memory 只存高层生活事件

本补丁只改变：

> 当前模型是否能看到已经存在的实时感知。

---

## 7. 测试

新增至少以下测试。

### A. 普通对话能拿到 Desktop Context

Mock：

```text
foreground_process = Code.exe
foreground_title = memory_decision.py - ZhaoXi
keyboard_rate_1m = 80
activity_mode = text_production
```

断言：

普通 DIRECT 对话最终模型输入包含这些信息。

### B. 已有 ActivityInference

若已有缓存：

```text
primary_activity = 正在修改 Zhaoxi 代码
confidence = 0.88
```

普通对话应一起收到。

### C. 无 ActivityInference

缓存为空时：

仍注入 raw process / title / rates。

不得因此触发额外模型调用。

### D. stale snapshot

快照过期时，Context 中明确：

```text
stale = true
```

不得伪装成 current state。

### E. unavailable

Desktop 不可用时：

```text
available = false
```

普通聊天可以诚实说明当前无法读取。

### F. 隐私回归

验证：

- Session / Memory 不新增 raw title 持久化
- diagnostics 行为不变
- 普通日志不额外输出 title
- 原有 v1.1.6 Desktop / Proactive 测试保持通过

---

## 8. 手动验收

启动 Desktop 模式后，打开 VS Code。

确认 inspect 已能看到：

```text
Code.exe
当前窗口标题
keyboard rate
```

然后直接问朝汐：

```text
你现在能看到我在哪个软件吗？
```

预期：

朝汐能基于实时桌面 Context 回答。

例如：

```text
能看到，你现在焦点在 VS Code。
```

如果标题能说明项目，可自然补充：

```text
看标题好像还在改 ZhaoXi。
```

但需要保留概率语气。

---

## 9. 完成标准

1. 普通聊天正式获得 DesktopActivityContext。
2. 不新增额外 Activity LLM 调用。
3. 已缓存 ActivityInference 可复用。
4. raw Context 在无 inference 时仍可使用。
5. stale / unavailable 有明确语义。
6. 不改变 v1.1.6 隐私与持久化边界。
7. Proactive / Continuation / Inspect 原行为保持。
8. 全量测试通过。

---

## 10. 本补丁一句话

> **v1.1.6 已经让朝汐睁开眼睛。**
>
> **v1.1.6.1 负责把这双眼睛真正接到她的普通对话里。**
