# Zhaoxi v0.5.1.1 · Integration Hardening 小型任务书

> 目标：修复 v0.5.1 首轮 Life HUD 黑盒联调中暴露出的编排层问题。  
> 原则：**不新增能力，只把现有链路焊稳。**

> 实现状态：Workflow 参数归一化、Permission Resume 后模型收尾、内部对象防泄漏、Life HUD 查询路由与 CLI 错误边界均已接入，并已加入自然语言黑盒回归。

---

## 1. Workflow 参数容错

当前问题：

```text
用户：
“开个铁幕专注测试一下”

模型生成额外参数：
note

Workflow Definition 未声明
↓
WorkflowRuntimeError
↓
Traceback 直接暴露给用户
```

要求：

- Workflow 输入必须先经过统一 Schema 校验
- 对未知字段不得直接炸穿 CLI
- 优先尝试：
  - 丢弃明显无害的多余字段，或
  - 让 Agent 根据 Schema 修正参数后重试
- 真正无法修正时，返回自然语言错误
- 内部 Traceback 只写日志，不直接显示给用户

---

## 2. Permission Resume 后必须重新进入 Agent

当前问题：

```text
Workflow
→ 等待权限
→ 用户“确认”
→ Tool 执行
→ Life HUD 写入成功
→ Context 重新读取成功
→ 直接把 dict / DTO 输出给用户
```

正确链路：

```text
Permission Resume
→ 原 Workflow 继续执行
→ WorkflowResult
→ 回到 Agent / Model
→ Final Response
```

要求：

- WorkflowResult 不得直接作为 CLI 最终输出
- ToolResult / WorkflowResult 都视为朝汐内部 Observation
- 最终用户回复必须经过正常自然语言生成
- 保留原 Goal / Workflow / Permission 上下文

---

## 3. 禁止内部对象泄漏

用户界面不得直接出现：

```text
Python dict
Pydantic model
raw JSON
ToolResult
WorkflowResult
内部 exception
```

除非：

```text
/debug
/trace
```

等明确开发者调试入口。

普通模式只输出自然语言。

---

## 4. 自然语言路由补强

重点修复以下场景：

```text
“你检查下工具看看？”
```

如果模型声称要检查 Tool：

```text
→ 必须真的调用对应能力
```

不能出现：

```text
“我先检查一下”
↓
什么也没调用
↓
直接回复
```

同时保持：

- 简单问题不乱开 Planner
- Workflow 请求能正确进入 Workflow
- Life HUD 查询优先走已有 READ Tools
- 不新增大规模 if-else Intent 路由

---

## 5. Runtime Error 统一收口

至少覆盖：

```text
Workflow 参数错误
Tool 参数错误
Permission Resume 错误
Life HUD Client 错误
Provider 错误
Workflow 状态错误
```

统一原则：

```text
内部：
完整 traceback + trace_id

用户：
简短、可理解、可继续操作的自然语言
```

程序不得因为一次 Agent 错误退出 CLI。

---

## 6. 必测黑盒场景

### Case A：查询

```text
“随便用 Life HUD 查点啥。”
```

要求：

- 至少真实调用一个 Life HUD READ Tool
- 正常自然语言回答
- 不泄漏原始 JSON

### Case B：开幕

```text
“开个铁幕专注测试一下。”
```

要求：

- 自动进入现有 Workflow
- 不因额外字段直接崩溃
- Permission 正常触发
- 用户自然语言“确认”后继续原 Workflow
- POST `/api/focus/start`
- 再读 Context 验证
- 最终自然语言回复

### Case C：状态确认

```text
“现在铁幕开着吗？”
```

要求：

- 查询 Life HUD 真实状态
- 不依赖 Memory 猜测

### Case D：落幕

```text
“落幕吧。”
```

要求：

- 获取真实 active session
- Permission
- complete
- 再读确认
- 自然语言回复

### Case E：异常不炸 CLI

故意制造：

```text
非法 Workflow 参数
Life HUD 离线
Tool Error
```

要求：

```text
CLI 继续可用
无 Traceback 糊脸
```

---

## 7. 自动测试补充

至少新增回归测试：

```text
1. unknown workflow argument → graceful handling
2. permission resume → workflow continues
3. workflow complete → agent final response
4. raw WorkflowResult never leaks to normal CLI
5. runtime exception → CLI remains alive
```

保留现有 v0.1 ~ v0.5.1 全量回归。

---

## 8. 本版不做

本版禁止顺手加入：

- v0.6 Proactive Agent
- 新外部 Tools
- Life HUD 全量写接口
- 新 Workflow
- GUI
- Voice
- RAG
- Memory 大改
- Planner 大改

只修：

> **自然语言 → Router → Workflow / Tool → Permission → Life HUD → Result → Final Response**

这一整条链。

---

## 9. 完成标准

同一段自然语言黑盒流程能够完整跑通：

```text
“随便查点 Life HUD 的东西。”
↓
正常查询

“开个铁幕专注测试一下。”
↓
请求权限

“确认。”
↓
开幕成功并自然回复

“现在铁幕开着吗？”
↓
读取真实状态

“落幕吧。”
↓
权限 → 落幕 → 验证 → 自然回复
```

整个过程中：

```text
无 Traceback
无内部 dict
无孤儿 Tool Call
无重复写入
无假成功
```

---

> **v0.5.1 让朝汐第一次碰到 Life HUD。**  
> **v0.5.1.1 要做的，是让她别再每走一步就撞一次桌角。**
