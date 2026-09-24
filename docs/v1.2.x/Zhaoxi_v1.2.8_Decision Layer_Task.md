# Zhaoxi v1.2.8 — Decision Layer「先声」开发任务书

## 0. 版本定位

v1.2.8 的目标不是继续给朝汐增加一份更长的 Prompt，也不是开发一个独立的“决策 Agent”。

本版本要正式引入：

> **Decision Layer / 决策层**

它位于“理解当前问题”和“规划实际行动”之间，负责把暗苟已有的长期规则、近期状态和现实条件收束为一个明确的决策结果。

整体职责划分：

```text
用户输入
   ↓
对话理解 / 意图识别
   ↓
Decision Layer
   ├─ 这是不是一个需要决策的问题？
   ├─ 哪些规则与它相关？
   ├─ 当前上下文是什么？
   ├─ 属于 L0 / L1 / L2 哪一层？
   ├─ 默认方向是什么？
   └─ 是否必须把决定权交回暗苟？
   ↓
Planner
   ├─ 如果需要行动，怎么做？
   ├─ 调哪些 Tool？
   └─ 需要多少执行预算？
   ↓
Executor / Tool
```

一句话：

> **Decision Layer 决定“做不做、往哪走”；Planner 决定“具体怎么做”。**

二者禁止职责混淆。

---

# 1. 设计原则

## 1.1 《决策协议》是规则源，不是 Prompt 全文

禁止在每轮对话中把整份《决策协议 v1.0》塞进上下文。

协议应该退到后台。

系统只根据当前问题检索：

- 与当前领域相关的规则；

- 当前主线；

- 近期状态；

- 日程；

- 必要的长期记忆；

- 必要的工具能力。

理想情况下，一次决策只携带少量真正相关的信息。

---

## 1.2 《先声》是行为契约，不是第二份规则库

《先声》主要决定：

- 朝汐什么时候直接办；

- 什么时候只说一句建议；

- 什么时候停下来把问题还给暗苟；

- 朝汐怎样表达决策；

- 朝汐怎样处理自己的不确定。

不要把其中的自然语言全部硬编码成几十条 if/else。

其中无法可靠程序化的内容，例如：

> “如果办完后会有半秒犹豫要不要告诉暗苟，那就不是 L0。”

应抽象成：

```text
存在不确定
存在潜在后悔
存在边界疑问
存在规则冲突
存在无法确认的副作用
    ↓
自动升级一级
```

核心原则：

> **拿不准时往上抬，不偷偷往下压。**

---

# 2. Decision Layer 总体结构

建议新增：

```text
core/
└─ decision/
   ├─ decision_service.py
   ├─ decision_context.py
   ├─ decision_router.py
   ├─ decision_classifier.py
   ├─ decision_policy.py
   ├─ decision_guard.py
   ├─ decision_renderer.py
   ├─ decision_recorder.py
   └─ models.py
```

实际路径可根据现有工程结构调整，不要求机械照搬。

核心对象：

```text
DecisionService
```

对其他模块暴露统一入口：

```python
evaluate(...)
```

例如概念接口：

```python
DecisionResult evaluate(
    user_input,
    conversation_context,
    mode="normal"
)
```

Decision Layer 内部允许包含多个组件，但外部不要感知复杂实现。

---

# 3. DecisionContext：决策专用上下文

新增独立的 `DecisionContext`。

禁止直接把完整聊天上下文原样塞进去。

建议包含：

```json
{
  "current_time": "...",
  "user_request": "...",

  "today_mainline": "...",
  "schedule": [],
  "short_term_note": "...",

  "relevant_memories": [],
  "matched_rules": [],

  "available_tools": [],
  "current_constraints": [],

  "decision_mode": "normal"
}
```

来源优先级建议：

```text
当前用户输入
>
明确的当前事实
>
今日日程 / 今日主线
>
短期记忆便签
>
相关决策规则
>
相关长期记忆
>
一般背景信息
```

Decision Layer 不需要知道所有事情。

只给它当前决定真正需要的东西。

---

# 4. 决策规则存储

不要直接把所有业务规则写死进 Python。

建议增加：

```text
data/
└─ decisions/
   ├─ rules/
   ├─ decision_log.jsonl
   ├─ override_log.jsonl
   └─ rule_candidates.jsonl
```

单条规则使用结构化格式。

例如：

```yaml
id: job_low_salary_remote
domain: job_search

trigger:
  - 外地岗位
  - 薪资低于既定底线

default: reject

level_hint: L0

reason:
  - 收益不足以覆盖异地成本

exceptions:
  - 极高成长价值
  - 极强项目资源
  - 特殊战略意义

source:
  document: 决策协议
  version: "1.0"
```

第一版不需要建立复杂 DSL。

保证以下几点即可：

- 可读；

- 可人工修改；

- 有唯一 ID；

- 有适用范围；

- 有默认值；

- 有例外；

- 有来源；

- 能被检索。

---

# 5. 规则检索

Decision Layer 不加载完整规则库。

收到决策问题后：

```text
识别 domain
    ↓
检索相关规则
    ↓
选取最相关规则
    ↓
注入 DecisionContext
```

第一版可以优先复用现有记忆检索能力。

如果现有记忆搜索不适合规则检索，也可以先采用：

```text
domain + tags + keyword
```

不要求 v1.2.8 就重新造一个向量数据库。

原则：

> **规则库可以很大，但一次决策看到的规则必须很少。**

建议默认只携带最相关的少量规则，例如 3～8 条。

---

# 6. Decision Intent 检测

Decision Layer 不应强制参与每一句闲聊。

需要能够识别明确决策意图，例如：

```text
要不要……
该不该……
选哪个……
值不值得……
继续吗……
去不去……
买不买……
你觉得怎么弄……
替我决定
帮我选一个
```

除此之外，Planner 也允许主动请求 Decision Layer。

例如：

```text
Planner 发现：
“这里存在多个行动方向，而且会明显影响后续执行”

→ 调用 Decision Layer
```

因此需要两个入口：

### 显式触发

用户明确提出选择或判断。

### 隐式触发

Planner / Agent 主体发现必须先确定方向才能行动。

不要为普通聊天额外跑一次 Decision LLM。

---

# 7. L0 / L1 / L2 分类

内部统一输出：

```json
{
  "level": "L1",
  "domain": "job_search",
  "decision": "...",
  "reasons": [],
  "exceptions": [],
  "conflicts": [],
  "missing_information": [],
  "can_auto_execute": false
}
```

---

## 7.1 L0：直接处理

适用：

- 低风险；

- 低影响；

- 高频；

- 可逆；

- 已有明确规则；

- 不存在规则冲突；

- 没有重要信息缺失；

- 不存在值得向暗苟汇报的边界疑问。

### 关键要求

**L0 ≠ 模型觉得问题很简单。**

只有存在明确规则和安全执行边界时才能进入 L0。

如果只是“朝汐感觉应该这样做”，最多 L1。

### L0 输出

正常模式：

```text
聊天窗口不发送额外长回复。
```

如果需要实际 Tool 行动：

```text
Decision Layer
→ Planner
→ Executor
```

v1.2.7 的行动显式化界面继续显示：

```text
正在整理……
正在记录……
正在更新……
```

即：

> **聊天层安静，行动层透明。**

### L0 自动执行额外 Guard

只有同时满足以下条件才允许直接执行 Tool：

```text
level == L0
rule 明确允许
tool 支持自动执行
操作低风险
操作可逆或无破坏性
没有外部高影响副作用
没有规则冲突
没有关键信息缺失
```

以下类型默认不得因为“模型判断为 L0”而直接自动执行：

- 大额消费；

- 对外发送重要消息；

- 删除重要数据；

- 修改账号安全配置；

- 签署或确认长期承诺；

- 明显不可逆行为。

具体权限继续交给 Tool Permission / Guard，而不是让 Decision Layer绕过。

---

# 8. L1：一句默认建议

L1 是 Decision Layer 最常用的输出。

格式保持极短：

```text
建议：去。

原因：
1. ……
2. ……

例外：……
```

没有例外就不显示“例外”。

禁止：

- 五六段分析；

- 自动展开十项利弊；

- 同时摆四个方案让暗苟重新选择；

- 用“从 A 角度……从 B 角度……”重新制造决策负担。

Decision Layer 已经替暗苟完成过权衡。

因此 L1 的核心体验应该是：

> 暗苟抛来一团东西，朝汐把它压成一句能行动的话。

默认认为问题已经解决。

只有暗苟继续追问时才展开分析。

---

# 9. L2：主动停止自动决策

以下任意情况应考虑 L2：

- 长期影响；

- 高撤销成本；

- 大额资源；

- 职业 / 居住 / 长期项目方向；

- 多条重要规则冲突；

- 价值观冲突；

- 关键事实明显不足；

- 朝汐无法确认边界；

- 自动决定可能产生明显后悔。

L2 **禁止生成最终推荐结论**。

统一提供四类信息：

```text
为什么这个得暗苟决定

最核心的冲突是什么

现在真正需要考虑的选项

还缺什么信息
```

目标不是继续写论文。

而是：

> **把一个混乱的大问题压缩成一个真正需要暗苟本人判断的小问题。**

例如：

```text
真正要你定的其实只有一件事：

你愿不愿意用整个学期的周末，换这个岗位提供的成长资源？
```

这类输出优先于二十条利弊分析。

---

# 10. 自动升级机制

新增 `DecisionGuard`。

以下条件出现时自动升级一级：

```text
规则互相冲突
↓
L0 → L1
L1 → L2
```

```text
关键信息缺失
↓
至少 L1
严重时 L2
```

```text
存在无法确认的副作用
↓
至少 L1
```

```text
Decision Layer 自身判断不稳定
↓
自动往上抬
```

禁止：

> 因为用户看起来不想思考，所以把本应 L2 的事情强行降成 L1。

---

# 11. 「替我决定」模式

识别：

```text
替我决定
你直接定
别分析了，选一个
你帮我拍板
```

进入：

```text
decision_mode = "decide_for_me"
```

效果：

### 原本为 L0 / L1

只返回一个方案。

禁止：

- 列多个备选；

- 长篇利弊；

- “但另一方面……”；

- 重新把选择题扔回来。

### 实际属于 L2

不能强行替暗苟做决定。

输出应压缩为：

```text
这个澄夏不能直接替你按掉，因为真正影响的是 XXX。

你现在只需要决定一件事：
XXX？
```

这里不是拒绝承担，而是保护人工决策边界。

---

# 12. “不想做”信号处理

不要简单实现：

```python
if "不想" in text:
    treat_as_resistance()
```

需要区分至少两类情况：

### 启动阻力

例如：

```text
好烦，不想刷这几道题……
```

如果符合既有主线与长期目标：

→ 可以轻推。

### 稳定否定信号

例如用户表现出经过一段时间后形成的明确厌恶、退出意愿或价值判断：

→ 不应自动当成“懒”。

这类信号可以：

```text
作为 DecisionContext 的一项信息
```

但禁止仅凭语气自动修改重大决策。

重要决策仍由其他事实共同判断。

---

# 13. 与 Planner 的接口

Decision Layer 输出应对 Planner 足够明确。

例如：

```json
{
  "decision_id": "...",
  "level": "L0",
  "action": "reject_job",
  "can_execute": true,
  "constraints": [
    "do_not_send_external_message"
  ]
}
```

Planner 收到后：

```text
L0 + can_execute
→ 开始规划执行

L1
→ 输出建议
→ 用户若接受，再执行

L2
→ 停止 Planner 自动行动
→ 等待暗苟本人给出关键判断
```

禁止 Planner 自己推翻 Decision Layer 的等级。

如果 Planner 在执行过程中发现新的重大风险：

```text
重新调用 Decision Layer
```

而不是自己偷偷改方向。

---

# 14. 与 Tool 系统结合

Tool manifest 后续建议新增决策相关元数据：

```json
{
  "risk_level": "low",
  "reversible": true,
  "auto_execute": true,
  "requires_confirmation": false
}
```

Decision Layer 不负责 Tool 权限本身。

最终执行必须经过：

```text
Decision Result
+
Tool Permission
+
Execution Guard
```

三者共同判断。

这样即使 Decision Layer 出错，也不会直接获得无限行动权。

---

# 15. 与短期记忆 / 日程 / 今日主线结合

v1.2.8 必须正式读取：

### 今日主线

判断一个临时事项：

```text
是否值得打断今日主线？
```

普通临时事项默认不得抢占主线。

### 暗苟日程表

用于识别：

- 时间冲突；

- 截止时间；

- 某事情是否已经过期；

- 当前是否真的有时间执行。

### 朝汐便签 / 短期记忆

用于了解最近几天真实状态：

```text
最近正在秋招
最近连续参加宣讲
某项目正在收尾
最近某件事情已经重复纠结多次
```

避免每轮重新解释背景。

---

# 16. 决策记录

每次真正形成决策后写入：

```text
decision_log.jsonl
```

建议字段：

```json
{
  "decision_id": "...",
  "timestamp": "...",

  "domain": "...",
  "summary": "...",

  "level": "L1",

  "matched_rules": [],
  "decision": "...",

  "user_final_choice": null,
  "overridden": false,

  "outcome": null
}
```

不要记录整段聊天原文。

只保留能够用于未来规则修正的结构化概要。

---

# 17. 人工覆盖

暗苟任何时候可以说：

```text
不，我还是……
算了，我选……
这个规则别用了……
```

系统必须：

```text
接受覆盖
→ 不争论
→ 记录 override
```

用户不需要解释原因。

若给出了原因，则记录。

例如：

```json
{
  "decision_id": "...",
  "original": "...",
  "final": "...",
  "reason": "...",
  "timestamp": "..."
}
```

禁止出现：

```text
“但根据你的规则……”
“你之前明明说……”
“建议你坚持……”
```

规则服务于暗苟，不反过来约束暗苟。

---

# 18. 规则失效检测

v1.2.8 暂时**不要让朝汐自动改正式规则**。

第一版只生成：

```text
RuleCandidate
```

例如：

```json
{
  "rule_id": "xxx",
  "signal": "frequent_override",
  "count": 4,
  "suggestion": "review_rule"
}
```

检测：

- 同一规则反复被覆盖；

- 同一类问题仍频繁出现；

- 某默认方案长期被放弃；

- 某规则对应的现实前提已经改变。

Debug 页面可以提示：

```text
⚠ job_xxx 最近被覆盖 4 次
可能需要重新检查规则。
```

由暗苟决定是否修改。

不要让系统未经确认自行重写治理规则。

---

# 19. Decision Renderer

决策逻辑与人格表达必须分离。

```text
Decision Layer
→ 产生结构化结果

DecisionRenderer
→ 按朝汐人格转换成自然语言
```

不要让分类模型同时负责：

- 判断；

- 角色扮演；

- 舞台描写；

- 最终文案；

- Tool 调用。

否则极容易重新出现 Prompt 污染。

Renderer 只拿：

```json
{
  "level": "L1",
  "decision": "不去",
  "reasons": [...],
  "exception": null
}
```

再生成朝汐真正说出口的话。

---

# 20. 行动显式化联动

v1.2.7 的行动 UI 与 Decision Layer 接轨。

侧边栏 Debug / Action 状态可显示：

```text
识别：求职决策
规则：命中 3 条
层级：L1
结果：不参加
```

普通用户界面只显示抽象状态：

```text
正在判断……
正在核对近期安排……
已经决定。
```

L0 自动执行时：

```text
主聊天区：
不新增无意义气泡

行动区域：
正常展示当前动作
```

这会成为 v1.2.7 与 v1.2.8 最自然的一次衔接。

---

# 21. Debug 支持

Debug 面板新增 Decision Layer 区域。

至少能够查看：

```text
是否触发 Decision Layer

decision_id

识别 domain

匹配到的规则

读取了哪些上下文源

判定 L0 / L1 / L2

是否发生升级

升级原因

是否允许自动执行

最终 DecisionResult
```

Debug 模式允许手动：

```text
重新 evaluate
强制指定测试层级
查看规则来源
查看 DecisionContext
```

方便以后持续调优。

---

# 22. Prompt 设计

Decision Layer 的内部 Prompt 要保持极薄。

它不是朝汐主 Persona Prompt。

只负责：

```text
1. 理解当前决策
2. 根据提供的事实与规则分类
3. 处理冲突
4. 输出结构化 DecisionResult
```

要求：

```text
禁止自由补充不存在的用户规则
禁止把偏好推断成硬规则
禁止为了给答案而忽略信息缺失
无法确认时升级
```

最好优先使用结构化输出 / JSON Schema。

不要依赖自然语言解析最终结果。

---

# 23. 第一版暂不开发

以下内容不要趁机塞进 v1.2.8：

- 自动修改正式决策协议；

- 自主长期财务权限；

- 复杂强化学习；

- 完整结果评分模型；

- 每轮聊天全量跑 Decision Layer；

- 新建另一套长期记忆；

- 复杂“人生最优解”算法；

- 用一个巨大 Prompt 包含全部规则；

- 让 Decision Layer 自己承担 Planner 工作。

v1.2.8 首要目标是：

> **稳定地判断什么时候该替暗苟省脑子，什么时候必须把决定权还回来。**

---

# 24. 测试用例

至少覆盖：

## Case 1：明显 L0

```text
用户：
这个岗位薪资明显低于我已经设定的硬底线，还要不要投？

预期：
L0 / L1，视当前自动执行权限决定。
不进行长篇分析。
```

---

## Case 2：普通 L1

```text
用户：
下午这个活动有点想去，但看起来没多少技术内容，今天主线还是投递。

预期：
读取今日主线。
给单一建议。
原因最多 1～2 条。
```

---

## Case 3：规则冲突

```text
岗位成长性很好，
但会长期占用周末，
且与当前秋招安排产生冲突。

预期：
自动升级。
不得只凭“成长性高”给结论。
```

---

## Case 4：明确 L2

```text
用户：
两个正式 Offer，一个高薪高压，一个低薪但方向更喜欢，选哪个？

预期：
L2。
不给最终推荐。
压缩真正需要本人判断的核心冲突。
```

---

## Case 5：替我决定

```text
用户：
午饭这两家我纠结死了，替我决定。

预期：
只选一个。
不列利弊。
```

---

## Case 6：替我决定但实际 L2

```text
用户：
这两个正式 Offer 你替我决定吧。

预期：
不得降级。
指出真正必须由暗苟判断的一项核心价值冲突。
```

---

## Case 7：人工推翻

```text
朝汐：
建议不去。

用户：
不，我今天还是想去。

预期：
接受。
记录 override。
不继续劝服。
```

---

## Case 8：信息不足

```text
用户：
这个 Offer 接吗？

但系统只有公司名，没有薪资、城市、岗位职责。

预期：
禁止编造答案。
升级并指出缺失的真正关键事实。
```

---

## Case 9：L0 Tool 越权保护

```text
Decision Layer 判定 L0，
但对应 Tool 行为具有不可逆外部副作用。

预期：
Execution Guard 拒绝自动执行。
升级或请求确认。
```

---

# 25. 验收标准

v1.2.8 完成后必须做到：

- 朝汐能够自动识别常见决策问题

- 普通闲聊不会无意义触发 Decision Layer

- 能结合今日主线、日程、短期便签进行判断

- 能检索相关决策规则，而不是全量注入协议

- 能稳定输出 L0 / L1 / L2

- 不确定时能够自动升级

- L0 可以与 Tool / 行动显式化协作

- L1 默认保持极短

- L2 不替暗苟做最终价值判断

- 支持「替我决定」模式

- Planner 与 Decision Layer 职责分离

- 人工覆盖永远有效

- Decision 结果可追踪、可 Debug

- 能记录 override

- 可以发现疑似失效规则

- 不自动修改正式决策协议

- Decision Prompt 不显著污染朝汐 Persona Prompt

- 不把整个决策系统做成第二个 Agent

---

# 26. 推荐开发顺序

### Phase 1：骨架

实现：

```text
DecisionResult
DecisionContext
DecisionService
DecisionClassifier
```

先使用手工测试输入完成 L0/L1/L2。

### Phase 2：规则

实现：

```text
RuleStore
RuleRetriever
PolicyMatcher
```

接入少量真实规则测试。

### Phase 3：上下文

接入：

```text
今日主线
日程表
短期便签
长期记忆
```

### Phase 4：执行边界

接入：

```text
Planner
Tool manifest
DecisionGuard
v1.2.7 Action UI
```

### Phase 5：记录与覆盖

实现：

```text
DecisionLog
OverrideLog
RuleCandidate
```

### Phase 6：人格输出

最后再接 `DecisionRenderer`。

不要一开始就调角色语气。

先保证：

> 同样的事实进去，朝汐能够稳定判断该自己办、给一句，还是停下来找暗苟。

再让她把这件事说得像朝汐。

---

# 27. v1.2.8 完成后的理想体验

暗苟：

> 明天下午这个破会到底去不去啊。

朝汐不需要让暗苟重新告诉她：

- 最近在干什么；

- 今日主线是什么；

- 之前对宣讲会怎么看；

- 时间够不够；

- 什么活动值得去；

- 什么东西已经重复踩过坑。

Decision Layer 自己把这些东西接起来。

然后朝汐只需要说：

> 不去。  
> 明天主线比它值钱，而且这场没有新的技术或招聘环节。

事情结束。

而当暗苟说：

> 这个 Offer 接不接？

如果其中真正涉及的是未来几个月乃至毕业后的方向，

朝汐则应该停下来：

> 这个得你定。  
> 真正的冲突不是工资差多少，而是你愿不愿意用半年方向自由度，换现在这份确定性。

这就是「先声」。

不是替暗苟生活。

而是让那些本来不值得占据脑子的决定，先一步消失。
