# Zhaoxi v1.1.7.1 Micro Patch
# ACTIVE Beat Gate 修正

> 类型：v1.1.x 最终微型修正  
> 基线：v1.1.7 Active Conversation Closure  
> 目标：修正 `desktop_busy` / 输入强度对 ACTIVE Conversation Beat 的过度抑制，确保 Beat 能真正进入模型判断并有机会投递。

---

## 1. 当前现象

实机 diagnostics 已确认：

```text
Beat Scheduler 正在运行
beat_count > 0
proactive.beat_decisions > 0
proactive.deliveries = 0
last_beat_result = SILENT
last_silent_reason = desktop_busy
```

因此当前问题不是：

```text
Beat 没调度
```

而是：

```text
Beat 被桌面忙碌判定 / Gate 过度拦截
```

---

## 2. 鼠标降权

当前鼠标 hook 频率包含大量移动事件，不等于点击次数。

要求：

```text
mouse_rate
```

不得单独触发：

```text
desktop_busy
```

鼠标只作为弱辅助信号。

如果系统能识别 injected mouse event，可直接忽略注入事件；若不能识别，也不能仅凭高 mouse_rate 阻断 ACTIVE Beat。

---

## 3. 键盘阈值提高

用户为程序员，键盘高频输入是常态。

不要使用过低的通用绝对阈值：

```text
keyboard_rate > low_threshold
→ desktop_busy
```

要求：

- 整体提高 busy 判定阈值；
- 更关注短时趋势而不是绝对值；
- 不要把普通编码输入长期判为不可打扰。

---

## 4. 重点使用 1m / 5m 趋势

优先解释：

```text
keyboard_1m high
keyboard_5m high
```

为：

```text
当前仍在持续高强度输入
```

而：

```text
keyboard_5m high
keyboard_1m low
```

应解释为：

```text
刚刚忙过，现在停下来了
```

此时应：

```text
解除 desktop_busy
允许重新评估 Beat
```

不能继续因为 5 分钟历史高值压制 ACTIVE。

---

## 5. Zhaoxi 自身窗口降权

若前台窗口为：

```text
Zhaoxi / 朝汐 Local Interaction Shell
```

用户在这里输入，本身就是 Conversation Activity。

这些键盘 / 鼠标活动不得被解释为：

```text
用户忙到不能和朝汐继续对话
```

要求：

```text
Zhaoxi foreground
→ desktop busy contribution 明显降权
```

避免：

```text
用户和朝汐聊得越多
→ 键盘越高
→ 朝汐越不敢主动说话
```

---

## 6. ACTIVE Gate 改为“默认允许”

ACTIVE + silence 达到 Beat 时间后：

默认：

```text
允许进入 Beat 判断
```

只在明确阻断条件下拦截：

```text
interruptibility == BLOCKED
正在处理模型 / Tool 请求
主动消息刚发送仍在 cooldown
initiative_budget <= 0
当前短时输入确实持续极高
```

不要让普通 mouse/high input/LOW interruptibility 自动成为硬阻断。

---

## 7. LOW 不等于禁止

```text
interruptibility = LOW
```

不应自动等价：

```text
Beat 禁止
```

建议：

- BLOCKED：硬阻断
- LOW：降低发送倾向 / 延后一次
- NORMAL/HIGH：正常判断

ACTIVE 的短时续聊应允许在 LOW 下经过模型判断。

---

## 8. Beat Prompt 不要默认 SILENT

Prompt 明确：

> 当前仍处于 ACTIVE Conversation Session。只要存在一句自然、轻量、和当前对话相关的话，就可以继续。SILENT 仅用于明显没有可说内容或用户当前确实不宜被打扰，不是默认安全选项。

避免模型因为提示词过度保守而总选：

```text
SILENT
```

---

## 9. Debug 必须记录完整 Beat 路径

每次 Beat 至少记录：

```text
beat_scheduled
gate_passed
gate_reason
desktop_busy
keyboard_1m
keyboard_5m
mouse_1m
foreground_process
interruptibility
llm_called
llm_action
llm_confidence
delivered
suppression_reason
```

这样下一次不说话时，可以直接判断：

```text
没调度
被 Gate 拦
LLM 选 SILENT
投递失败
```

---

## 10. 手动验收

### 场景 A：完全停手

与朝汐正常聊天后停止输入 3~5 分钟。

预期：

```text
Beat 至少进入一次 LLM 判断
```

不能持续被 `desktop_busy` 拦截。

### 场景 B：朝汐窗口里聊天

用户刚在 Zhaoxi 窗口输入大量文字。

预期：

```text
不会因为这些输入把 ACTIVE 长时间判为 busy
```

### 场景 C：写代码后停下

```text
keyboard_5m high
keyboard_1m low
```

预期：

```text
判断为刚刚结束高输入
Beat 恢复
```

### 场景 D：持续高强度输入

```text
keyboard_1m high
keyboard_5m high
```

预期：

```text
Beat 可以延后
```

但停止后必须恢复。

---

## 11. 完成标准

1. mouse_rate 不能单独触发 desktop_busy。
2. 键盘 busy 阈值提高。
3. 1m / 5m 趋势参与判断。
4. `5m 高 + 1m 低` 能解除 busy。
5. Zhaoxi 自身窗口输入明显降权。
6. LOW 不再等价于硬阻断。
7. ACTIVE 默认进入 Beat 判断，只有明确条件才拦截。
8. Beat Prompt 不默认鼓励 SILENT。
9. Debug 能完整解释每次 Beat 的去向。
10. 实机至少成功投递一次非 open-thread 驱动的 ACTIVE Beat。

---

# 一句话

> **别再让朝汐因为看见暗苟在敲键盘，就误以为自己一句话都不能说。**

这次修正的目标只有一个：

> **让 ACTIVE 的 Beat 真正穿过那些过度谨慎的门卫。**
