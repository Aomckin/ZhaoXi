# Zhaoxi v1.4.2 轻量补丁任务书
## Fast Gate 2.0 · Multi-Signal Confidence Routing

> 项目：**Zhaoxi / 朝汐**\
> 当前版本：**v1.4.2**\
> 类型：**轻量 Runtime 补丁，不打断 Current Cognition 2.0 主线**\
> 目标：修复 v1.4.1 Fast Gate “黑名单排除后默认 FAST”导致的误路由，同时保住普通聊天单次 LLM 的速度优势。
>
> 一句话：
>
> > **Fast Gate 不再问“有没有撞到危险关键词”，而是问“凭现有近期认知，朝汐是否真的足够直接接住这句话”。**

---

## 1. 当前问题

现有 Fast Gate 更接近：

```text
命中动作词      → 非 FAST
命中回忆词      → 非 FAST
命中外部查询词  → 非 FAST
命中私人领域词  → 非 FAST

否则            → FAST
```

因此只要一句话没有撞进词表，就可能误进 FAST。

已经抓到的真实案例：

```text
“书馆里未来开发计划9.21版，自己去看”
→ FAST
→ Fast Chat 没有 Tool
→ 只能回答“我没法自己去看”
```

以及当前截图：

```text
“去补一份吧，把这个 bug 记录起来，我等下处理”
→ FAST
```

但真实意图明显是：

```text
承接上一轮
+
执行记录 / 文件类动作
```

不应进入纯聊天通道。

---

## 2. 补丁原则

不要继续扩大：

```text
_ACTION = [...]
_EXTERNAL = [...]
_PRIVATE = [...]
```

这种硬编码词表。

改成：

> **多信号置信度门控。**

Fast Gate 不再只看当前一句话本身，而是综合系统已经拥有的轻量信息：

```text
Recent Conversation
Current Cognition
Tool Capability Match
Resource / Artifact Reference
Continuation State
历史事实需求
真实副作用需求
图片 / 权限等硬条件
```

---

## 3. Gate 改为三态输出

当前：

```text
FAST / NOT FAST
```

改为：

```text
FAST_CONFIDENT
AMBIGUOUS
HEAVY_CONFIDENT
```

链路：

```text
                     ┌─ FAST_CONFIDENT ─→ Fast Chat
User → Signal Gate ──┼─ AMBIGUOUS ──────→ Router LLM
                     └─ HEAVY_CONFIDENT ─→ 已知 Standard / Heavy Route
```

这样：

```text
高置信普通聊天
→ 仍然 0 次 Router LLM

只有证据不足 / 冲突
→ 才支付 Router 的额外 6~7s
```

---

## 4. FastGateSignals

建议统一收集：

```python
FastGateSignals:
    conversation_likeness

    recent_context_relevance
    recent_context_sufficient

    current_cognition_relevance
    current_cognition_sufficient

    continuation_confidence

    capability_match
    resource_reference_confidence

    historical_specificity
    action_side_effect_confidence
    decision_complexity

    has_image
    pending_permission
```

第一版不要求所有信号都很复杂。

重点是：

> **把已有系统知道的东西一起投票，而不是继续往关键词表里塞词。**

---

## 5. FAST 正向信号

### 5.1 普通聊天形态明显

例如：

```text
小金毛？
在吗
哈哈哈哈
今天真热
我有点烦
这也太怪了
```

可以得到：

```text
conversation_likeness = high
```

---

### 5.2 Recent Conversation 足够回答

例如：

```text
上一轮：
“Fast Chat 现在终于快了。”

当前：
“确实舒服多了。”
```

已有局部上下文已经足够：

```text
recent_context_relevance = high
recent_context_sufficient = true
```

这是强 FAST 证据。

---

### 5.3 Current Cognition 足够回答

v1.4.2 重构后的 Current Cognition 应成为 Gate 正式信号来源。

例如：

```text
“最近秋招真没啥结果”
```

如果 Current Cognition 已经知道：

```text
秋招仍是近期主线
最近缺少实质性结果
```

则：

```text
current_cognition_relevance = high
current_cognition_sufficient = true
```

可以 FAST，不需要查长期 Memory。

---

### 5.4 无真实动作 / 精确事实需求

如果当前输入：

```text
不要求真实副作用
不要求读取具体资源
不要求具体历史事实
```

作为普通 FAST 正证据。

---

## 6. HEAVY 强信号

### 6.1 Tool / Capability 高匹配

复用现有 Tool Capability / Semantic Routing 结果。

例如：

```text
“把今晚吃的记进 LifeHUD”
```

若：

```text
lifehud capability_match = high
```

直接：

```text
HEAVY_CONFIDENT
```

不要再靠 `LifeHUD` 这个词本身判断。

这样：

```text
“LifeHUD 这个 UI 好怪”
```

即使包含 LifeHUD，也可以：

```text
capability_match = low
conversation_likeness = high
→ FAST
```

---

### 6.2 Resource / Artifact Reference

识别当前消息是否明确指向某个已有资源：

```text
某个文档
某个版本
某个仓库内容
某份任务书
某条记录
某个私人知识源
```

例如：

```text
未来开发计划9.21版
某个 README
某个 md
仓库最新提交
书馆里那份计划
```

重点不是关键词，而是：

> **当前输入是否明显要求获取“现有资源中的具体内容”。**

若：

```text
resource_reference_confidence = high
```

禁止直接 FAST。

---

### 6.3 真实副作用需求

当前截图：

```text
“去补一份吧，把这个 bug 记录起来，我等下处理”
```

应通过：

```text
action_side_effect_confidence = high
continuation_confidence = high
```

判定：

```text
非 FAST
```

Fast Gate 不需要自己知道最终应该：

```text
写文件
写备忘
调用哪个 Tool
```

只需要知道：

> **这不是一句只靠语言就能完成的话。**

---

### 6.4 具体历史事实需求

例如：

```text
“我上次亚信面试具体问了什么？”
```

Current Cognition 只能提供近期背景，不足以回答具体历史。

得到：

```text
historical_specificity = high
short_context_sufficient = false
```

→ RECALL / Router

---

### 6.5 明确承接未完成动作

例如：

```text
继续
刚刚那个继续
那两条补一下
前面那个处理掉
去补一份吧
```

不要只用固定词表。

应结合：

```text
Recent Conversation 是否存在未完成 / 刚讨论的动作
+
当前消息是否指向该动作
```

形成：

```text
continuation_confidence
```

---

## 7. 推荐判定方式

第一版不需要训练分类器。

采用：

> **强信号 + 多证据投票。**

示意：

```text
FAST 强正证据：
- recent_context_sufficient
- current_cognition_sufficient

FAST 普通正证据：
- conversation_likeness 高
- capability_match 低
- resource_reference 低
- historical_specificity 低
- action_side_effect 低

HEAVY 强证据：
- capability_match 高
- resource_reference 高
- action_side_effect 高
- historical_specificity 高
- pending_permission
- image / structured input
```

推荐：

```text
存在 HEAVY 强证据
→ HEAVY_CONFIDENT

无 HEAVY 强证据
且 ≥1 个 FAST 强正证据
且普通 FAST 正证据达到阈值
→ FAST_CONFIDENT

其他
→ AMBIGUOUS
→ Router
```

具体阈值全部进入配置，后续通过 dogfooding 调。

---

## 8. Router 必须允许重新选择 FAST

Router 不应只返回：

```text
DIRECT / TOOL / PLAN
```

补充：

```text
FAST_CHAT
```

于是 AMBIGUOUS 路径可以：

```text
Signal Gate 不确定
↓
Router LLM
↓
“其实只是普通聊天”
↓
FAST_CHAT
```

也就是：

> **Fast Gate 负责高置信免税，Router 负责模糊区裁决。**

---

## 9. Router → FAST 暂时仍允许第二次模型调用

第一版可以接受：

```text
Router → FAST → Fast Chat LLM
```

即多约 6~7 秒。

Observatory 增加：

```text
router_to_fast_count
```

如果后续发现大量 AMBIGUOUS 最终仍然 FAST，再考虑让 Router 同时产出可直接交付回复。

本补丁暂不做，避免重新把 Router 做胖。

---

## 10. 与 Current Cognition 2.0 联动

Current Cognition 2.0 当前正在 v1.4.2 主线重构。

Gate 预留：

```text
current_cognition_relevance
current_cognition_sufficient
```

但：

```text
Fast Gate 自己不能调用 LLM
```

只消费：

```text
Current Cognition 的轻量 Snapshot / Thread metadata
```

例如：

```text
当前话题与 active thread 高相关
+
问题只需要近期状态
→ FAST 正证据
```

但：

```text
当前话题与 active thread 高相关
+
用户要求执行动作
→ 仍然非 FAST
```

Current Cognition 是背景认知，不是任务许可。

---

## 11. 与 Recent Context 联动

新增轻量信号：

```text
recent_context_relevance
recent_context_sufficient
continuation_confidence
```

要能区分：

```text
“确实舒服多了”
→ Recent Context 足够
→ FAST
```

和：

```text
“去补一份吧，把这个 bug 记录起来”
→ 明确承接上一轮动作
→ 非 FAST
```

---

## 12. Observatory 补充

复用 v1.4.0 Runtime Observatory，不新造页面。

增加：

```text
fast_gate_version = 2

fast_gate_decision
fast_gate_signals

fast_score
heavy_score

fast_positive_evidence[]
heavy_evidence[]

router_required
router_override
router_final_lane
```

Debug 示例：

```text
Fast Gate 2.0

Decision: AMBIGUOUS

FAST Evidence
✓ recent_context_relevance: 0.81
✓ conversation_likeness: 0.63

HEAVY Evidence
✓ continuation_confidence: 0.76
✓ action_side_effect: 0.71

→ Router required
```

---

## 13. 必测回归案例

### Case A · 高置信 FAST

```text
“小金毛？”
```

要求：

```text
FAST_CONFIDENT
Router = 0
Foreground LLM = 1
```

---

### Case B · Current Cognition 支撑 FAST

```text
“最近秋招真没啥结果”
```

如果 Current Cognition 中存在秋招近期 Thread：

```text
FAST_CONFIDENT
```

不查长期 Memory。

---

### Case C · Artifact 获取

```text
“书馆里未来开发计划9.21版，自己去看”
```

要求：

```text
绝不能 FAST_CONFIDENT
```

至少：

```text
AMBIGUOUS → Router
```

或者：

```text
HEAVY_CONFIDENT
```

---

### Case D · 当前截图

上文刚讨论：

```text
缺一份 bug 记录文件
```

当前：

```text
“去补一份吧，把这个 bug 记录起来，我等下处理”
```

要求：

```text
continuation_confidence = high
action_side_effect_confidence = high

→ 非 FAST
```

---

### Case E · 提到工具但只是聊天

```text
“LifeHUD 这个界面看着有点怪”
```

要求：

```text
capability_match 低
conversation_likeness 高
→ FAST
```

不能因为工具名被误杀。

---

### Case F · 具体历史

```text
“亚信上次具体问了我哪些题？”
```

要求：

```text
historical_specificity 高
→ 非 FAST
```

---

### Case G · 模糊承接

```text
“之前那个你觉得怎么样？”
```

若 Recent Context 无法高置信消歧：

```text
AMBIGUOUS
→ Router
```

---

## 14. 轻量实现建议

不要重写整个 Cognitive Router。

升级现有 Gate 或新增：

```text
FastDialogueGateV2
```

建议输出：

```python
FastGateDecision:
    lane: FAST_CONFIDENT | AMBIGUOUS | HEAVY_CONFIDENT
    reason: str
    signals: FastGateSignals
    fast_score: float
    heavy_score: float
```

Signal Collector 尽量只消费：

```text
本地 Conversation
Current Cognition Snapshot
现有 Tool Capability 索引
Session / pending state
已有资源引用元数据
```

禁止：

```text
Fast Gate 自己开 LLM
Fast Gate 自己查长期 Memory
Fast Gate 自己跑 Tool
```

---

## 15. 推荐开发顺序

### Phase 1

- [ ] FastGateDecision 改三态
- [ ] FastGateSignals
- [ ] Observatory 输出

### Phase 2

- [ ] Recent Context signals
- [ ] Current Cognition signals
- [ ] continuation confidence

### Phase 3

- [ ] Tool Capability match
- [ ] Resource / Artifact reference signal
- [ ] action side-effect signal
- [ ] historical specificity

### Phase 4

- [ ] Router 支持 AMBIGUOUS 后重新选择 FAST
- [ ] 保持 high-confidence FAST 零 Router

### Phase 5

- [ ] 上述 7 组回归测试
- [ ] 实机 dogfooding 20~30 条消息

---

## 16. 完成标准

补丁完成后：

```text
1. Fast 不再采用“没撞关键词就通过”的黑名单逻辑。

2. High-confidence 闲聊仍保持：
   Router LLM = 0
   Foreground LLM = 1

3. Current Cognition 和 Recent Context 可以成为 FAST 正向证据。

4. Tool Capability、Resource Reference、历史精确需求、真实副作用可以成为 HEAVY 证据。

5. 证据冲突或不足时交给 Router，而不是盲目 FAST。

6. Router 在模糊区可以重新选择 FAST。

7. “LifeHUD 这个 UI 好怪”不会因为工具名被误杀。

8. “书馆里9.21版自己去看”不会再次进入 FAST。

9. “去补一份吧，把这个 bug 记录起来”不会再次进入 FAST。

10. Fast Gate 的每次决定都能在 Debug 中解释：
    为什么快？
    为什么升级？
    为什么交给 Router？
```

---

## 17. 核心结论

旧 Fast Gate：

```text
没发现危险
→ FAST
```

新 Fast Gate：

```text
多条证据证明“现有近期认知已经足够”
→ FAST

明显需要动作 / 资源 / 历史事实
→ HEAVY

证据打架
→ Router 当裁判
```

这次补丁不追求让 Gate “聪明到不需要 Router”。

目标是：

> **高置信场景继续快，模糊场景宁可多花一次 Router，也不要快错。**
