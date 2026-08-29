# Zhaoxi v0.3.1 · Cognitive Integration 小型任务书

> 目标：把 v0.2 的 Memory 与 v0.3 的 Planner 真正接进自然对话流程。  
> 核心结果：**用户只说人话，朝汐自己判断什么时候该记、什么时候该规划。**

> 实现状态：已完成。当前实现通过独立的 Cognitive Router 和回复后的 Auto Memory Decision 接入自然对话，测试不依赖真实模型 API。

---

## 1. Auto Planning

新增轻量 `Cognitive Router`，普通消息进入 Core 后先判断：

- `DIRECT`：直接回答
- `TOOL`：进入现有 Agent Runtime
- `PLAN`：自动进入 Planner

### 要求

- 简单问题禁止启动 Planner
- 复杂、多步骤、有依赖关系的目标自动进入 Planner
- 保留 `/plan`，但降级为开发/调试用的强制入口
- 自动进入 Planner 后继续复用现有：
  - Goal / Plan / PlanStep
  - Re-plan
  - Retry / fallback
  - `/resume`
  - `/trace`
  - `/cancel`

### 基础验收

```text
“现在几点？”
→ 不启动 Planner

“帮我检查长期记忆里有没有重复和冲突。”
→ 自动启动 Planner

“帮我查一下记忆并整理，但不要修改。”
→ Planner 执行只读任务
```

---

## 2. Auto Memory

在每轮正常交互结束后增加 `Memory Decision`。

建议决策类型：

```text
IGNORE
CREATE
UPDATE
MERGE
CONFLICT
```

### 应自动记忆的内容

优先：

- 长期偏好
- 稳定个人习惯
- 明确项目状态变化
- 长期目标
- 重要关系与上下文
- 后续很可能再次使用的信息

忽略：

- 一次性闲聊
- 低价值瞬时状态
- 无长期意义的生活碎片
- 已存在且无新增信息的重复内容

### 用户显式意图拥有最高优先级

必须支持：

```text
“记住 XXX”
→ 强制保存

“不要记这个”
→ 禁止本轮自动保存

“忘掉 XXX”
→ 调用现有删除/遗忘能力
```

---

## 3. Memory 更新与去重

不要让自动记忆只会不断 `CREATE`。

至少实现基础判断：

```text
已有：
Zhaoxi 当前版本 v0.2

新信息：
“v0.3 做完了”

→ UPDATE，而不是再创建一条互相冲突的“当前版本”
```

对于近似重复内容：

```text
→ MERGE
```

对于可能发生变化的事实：

```text
→ CONFLICT / temporal update
```

保留旧信息的历史价值，不要无脑覆盖。

---

## 4. 推荐主流程

```text
User
 ↓
Cognitive Router
 ├─ DIRECT
 ├─ TOOL
 └─ PLAN
      ↓
现有 Agent / Planner Runtime
      ↓
Final Response
      ↓
Memory Decision
 ├─ IGNORE
 ├─ CREATE
 ├─ UPDATE
 ├─ MERGE
 └─ CONFLICT
```

Planner Routing 属于“输入阶段”。

Auto Memory 属于“本轮结束后的认知整理阶段”。

不要把两者搅成一个大模块。

### 实现兼容性约束

- Auto Memory 每轮只发出一次普通 JSON 决策请求，不使用强制 `tool_choice`；
- 决策响应通过内部模型校验，损坏或缺失时安全降级；
- 对明确记忆指令以及身份、命名缘由、稳定偏好等高价值事实提供保守兜底；
- 主 Agent 在回复生成前不得声称普通对话已经自动保存；
- Auto Memory 失败不影响本轮用户回复，并且日志不记录记忆正文。

---

## 5. 不做

v0.3.1 只补认知整合，不扩业务范围。

本版不做：

- 新外部 Tools
- Life HUD 接入
- 新 GUI
- Voice / TTS
- Workflow Engine
- 主动 Agent / 定时任务
- 大规模 Memory 重构
- 向量数据库
- RAG

现有 Memory 与 Planner 能力优先复用，不重复造轮子。

---

## 6. 必测场景

### Case A：简单请求

```text
“现在几点？”
```

要求：

- 不进入 Planner
- 正常 Tool Call
- 不产生垃圾 Memory

### Case B：自然形成记忆

```text
“我发现晚上开发比刷算法舒服。”
```

要求：

- 正常回复
- 自动产生长期偏好 Memory

### Case C：更新已有事实

```text
“Zhaoxi v0.3 做完了。”
```

要求：

- 自动识别项目状态变化
- 优先 UPDATE / MERGE
- 不制造多个“当前版本”

### Case D：复杂目标

```text
“帮我检查长期记忆里有没有重复或者冲突。”
```

要求：

- 无需 `/plan`
- 自动进入 Planner
- 能通过 `/trace` 查看执行轨迹

### Case E：禁止记忆

```text
“不要记住下面这件事：XXX”
```

要求：

- 本轮禁止 Auto Memory

---

## 7. 完成标准

以下体验成立时即可结束 v0.3.1：

> 用户不需要知道 `/plan`、`remember_memory` 等内部机制。

朝汐能够自然做到：

```text
该直接回答 → 直接回答
该调用工具 → 调工具
该规划 → 自己规划
该记住 → 自己记住
不值得记 → 自动忽略
用户不让记 → 绝不保存
```

`/plan` 等命令继续保留，仅作为开发者调试与强制控制入口。

### 验收结果

- [x] 简单请求不会启动 Planner；
- [x] 复杂、多步骤目标会自动进入 Planner；
- [x] 稳定偏好、身份与命名缘由可以形成长期记忆；
- [x] 已有事实支持 UPDATE、MERGE 与 temporal CONFLICT；
- [x] “不要记”会阻止本轮 Auto Memory；
- [x] 只读规划任务会阻止状态变更工具；
- [x] Auto Memory 不再为结构化决策发送强制 Tool Choice 请求；
- [x] Provider 或决策解析失败能够安全降级；
- [x] v0.1 至 v0.3 回归测试保持通过。

---

> **v0.2 给朝汐记忆。**  
> **v0.3 给朝汐规划。**  
> **v0.3.1 让她知道什么时候该用它们。**
