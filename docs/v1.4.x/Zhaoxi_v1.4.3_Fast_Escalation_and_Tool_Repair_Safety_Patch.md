# Zhaoxi v1.4.3 轻量补丁任务书
## Fast Escalation Guard · Bounded Tool Repair · Budget Emergency Finalization

> 项目：**Zhaoxi / 朝汐**  
> 当前版本：**v1.4.3**  
> 类型：**轻量 Runtime Safety / Loop Control 补丁**  
> 背景：Fast Chat 自升级与 STANDARD 工具修复链在真实使用中出现过度升级、重复修复和 Token 预算耗尽。
>
> 核心目标：
>
> 1. **FAST 只能因为当前消息真的要求行动而升级，不能被旧上下文诱导。**
> 2. **STANDARD 工具修复必须有硬上限，相同错误不能反复打转。**
> 3. **Token 预算接近耗尽时必须及时收尾，最差也要 deterministic fallback。**

---

## 1. 当前真实故障

用户当前只说：

```text
“小金毛”
```

Fast Gate 2.0 正确判定：

```text
FAST_CONFIDENT
FAST score = 1
HEAVY score = 0
```

但 Fast Chat 读到此前上下文：

```text
“台账那条先挂着……你什么时候想补，喊我一声就成~”
```

于是模型把“小金毛”错误解释成“现在执行之前挂起的台账任务”，输出升级信号并转入 STANDARD。

升级后又出现：

```text
Foreground LLM Calls = 4
Tool Rounds = 3

LifeHUD 成功 ×2
LifeHUD 失败 ×3
search_memories ×2
request_tool_group ×1
```

最终 Token 预算耗尽，约 85 秒后仍未正常生成 Final Reply。

---

# 2. P0 · Fast Escalation Guard

当前逻辑近似：

```text
Fast LLM 输出升级信号
→ Runtime 直接接受
→ STANDARD
```

必须改为：

```text
Fast LLM 提出升级请求
↓
Runtime 验证“当前 User Message 是否真的提供本轮行动证据”
↓
通过 → STANDARD
不通过 → 拒绝升级，继续 FAST
```

---

## 3. 升级请求增加 trigger evidence

不要只输出：

```text
[escalate:tool]
```

建议改为结构化内部请求：

```json
{
  "kind": "tool",
  "reason": "需要补台账",
  "trigger_span": "把台账补一下"
}
```

关键字段：

```text
kind
reason
trigger_span
```

`trigger_span` 必须来自当前 User Message，而不是历史上下文。

---

## 4. 典型验收

### 不允许升级

Recent Context：

```text
“台账先挂着，什么时候想补喊我。”
```

Current User：

```text
“小金毛”
```

即使 Fast LLM 请求 `tool escalation`，Runtime 也必须拒绝。

### 允许升级

Current User：

```text
“那就把刚才那个台账补一下吧”
```

可验证当前消息中的：

```text
“台账补一下”
```

于是允许升级。

---

## 5. Fast Escalation 单向且最多一次

允许：

```text
FAST → STANDARD
```

禁止：

```text
FAST → STANDARD → FAST → STANDARD
```

每轮：

```text
fast_escalation_count <= 1
```

---

# 6. P0 · Bounded Tool Repair

当前 Tool 失败后可以继续：

```text
修参数
→ 再调
→ 再失败
→ 再修
```

必须增加硬上限。

---

## 7. Failure Fingerprint

每次 Tool failure 生成：

```text
tool_name
error_code
normalized_error_message
argument_shape
```

组合成：

```text
failure_fingerprint
```

同一 fingerprint：

```text
首次失败 → 允许 repair 1 次
repair 后再次同类失败 → 停止重试
```

---

## 8. Tool 失败预算

建议：

```text
same_tool_same_failure_retry <= 1
per_tool_failure_limit <= 2
repair_round_limit <= 1
```

达到上限：

```text
本轮锁定该 Tool
→ 强制进入 finalization
```

---

## 9. request_tool_group 限制

如果已经明确目标能力并调用过，例如：

```text
lifehud
```

之后仅因参数错误，不允许再：

```text
request_tool_group
```

只有真正：

```text
capability_missing
```

时才允许重新查能力。

---

## 10. search_memories 去重

同一轮：

```text
同一 query
→ 最多一次
```

高相似 query：

```text
复用已有结果 / 拒绝重复调用
```

避免：

```text
search_memories
→ Agent
→ search_memories
→ Agent
```

---

# 11. P0 · STANDARD Round Budget

增加显式预算：

```text
standard_model_round_limit
standard_tool_round_limit
standard_repair_round_limit
```

建议默认：

```text
model rounds <= 3
tool rounds <= 2
repair rounds <= 1
```

对于已经走过：

```text
FAST → STANDARD
```

的请求，预算应更严格。

---

# 12. No Progress Detection

定义“有进展”：

```text
新 Tool 成功
获得新事实
完成新 mutation
解决前一错误
状态从 unknown → known
```

若连续两轮：

```text
没有新成功
没有新信息
只有重复失败 / 重复查询
```

立即强制收尾。

---

# 13. P0 · Token Budget Danger Zone

增加状态：

```text
NORMAL
WARNING
DANGER
EXHAUSTED
```

### WARNING

禁止：

```text
无关 Tool Discovery
额外 Recall
新的支线任务
```

### DANGER

立即：

```text
tools = []
final_only = true
```

禁止：

```text
新 Tool Call
request_tool_group
重复 search_memories
repair round
额外 planner step
```

只允许生成收尾回复。

### EXHAUSTED

如果连 Final LLM 都付不起：

```text
走 deterministic fallback
```

---

# 14. Deterministic Final Fallback

Runtime 本身已经知道：

```text
哪些 Tool 成功
哪些 Tool 失败
哪些结果未知
```

因此无须 LLM，也必须能生成：

```text
本轮已停止继续处理。

已完成：
- LifeHUD 查询 ×2
- 记忆检索 ×1

未完成：
- LifeHUD 写入连续失败，已停止继续重试

已完成的操作会保留。
```

要求：

```text
一定可生成
不依赖模型
信息准确优先
```

---

# 15. Partial Success Contract

最终状态建议区分：

```text
completed
partial_success
failed
cancelled
budget_exhausted
```

不能因为最后一个步骤失败，就把已经成功的 Tool 全部抹成：

```text
failed
```

---

# 16. Extra Budget Request 限制

每轮最多申请一次额外预算。

只有：

```text
已有明确进展
+
剩余一步可完成
```

才允许。

如果只是：

```text
连续 Tool failure
```

禁止申请额外预算。

---

# 17. Observatory 新增字段

复用现有 Runtime Observatory，增加：

```text
fast_escalation_requested
fast_escalation_validated
fast_escalation_rejected_reason
fast_escalation_trigger_span

tool_failure_fingerprint
tool_retry_count
tool_locked

standard_model_round
standard_tool_round
repair_round

budget_state
budget_remaining_ratio
forced_finalization_reason

partial_success
deterministic_fallback_used
```

---

# 18. Action Trace 示例

```text
Fast Chat
→ 请求升级 TOOL
→ 升级校验失败：当前消息无行动证据
→ 保持 FAST
```

或：

```text
STANDARD
→ LifeHUD 调用失败
→ 参数修复 1/1
→ LifeHUD 再次同类失败
→ 已停止继续重试
→ 强制收尾
```

---

# 19. 必测回归案例

### Case A · 本次真实故障

Recent Context：

```text
“台账什么时候想补，喊我一声。”
```

Current User：

```text
“小金毛”
```

要求：

```text
Fast Gate = FAST
Fast LLM 即使申请 tool escalation
Runtime Guard 也必须拒绝
最终仍正常 FAST 回复
```

### Case B · 明确承接

```text
“那就把台账补一下吧”
```

要求：

```text
Fast escalation valid
→ STANDARD
```

### Case C · Tool 第一次失败

允许一次 repair。

### Case D · 同类错误第二次出现

```text
停止 repair
锁定 Tool
强制 finalization
```

### Case E · 重复 Memory Search

同义 query 复用已有结果或拒绝重复调用。

### Case F · 已知 Tool 后申请 Tool Group

若只是参数错误，拒绝 `request_tool_group`。

### Case G · Budget Danger

```text
禁止新 Tool
直接 final_only
```

### Case H · Budget Exhausted

必须生成 deterministic fallback，而不是空白或“回复生成失败”。

---

# 20. 推荐测试

至少新增：

```text
test_fast_escalation_requires_current_turn_evidence
test_fast_escalation_cannot_be_triggered_by_history_only
test_fast_escalation_valid_for_explicit_current_action

test_same_tool_same_failure_only_repairs_once
test_tool_locked_after_repeated_failure
test_duplicate_memory_search_reused_or_blocked
test_request_tool_group_blocked_after_known_tool_failure

test_budget_warning_blocks_discovery
test_budget_danger_forces_finalization
test_budget_exhausted_uses_deterministic_fallback
test_partial_success_is_preserved
test_no_progress_forces_stop
```

---

# 21. 推荐开发顺序

### Phase 1 · Fast Escalation Guard

- [ ] structured escalation
- [ ] trigger_span
- [ ] current-turn validation
- [ ] rejection path
- [ ] max 1 escalation

### Phase 2 · Tool Repair Budget

- [ ] failure fingerprint
- [ ] retry count
- [ ] repair limit
- [ ] tool lock
- [ ] duplicate search guard

### Phase 3 · STANDARD Round Budget

- [ ] model round
- [ ] tool round
- [ ] repair round
- [ ] no-progress detection

### Phase 4 · Budget Emergency Finalization

- [ ] NORMAL / WARNING / DANGER / EXHAUSTED
- [ ] danger → final_only
- [ ] no new Tool
- [ ] extra-budget restriction

### Phase 5 · Deterministic Fallback

- [ ] partial result summary
- [ ] success / failure distinction
- [ ] budget exhausted fallback

### Phase 6 · Observatory / Tests

- [ ] trace fields
- [ ] regression tests
- [ ] desktop real-model smoke test

---

# 22. 本补丁不做

不做：

```text
重新设计 Fast Gate 2.0
重新设计 Planner
Memory 3.0 再次重构
LifeHUD API 重构
Tool Catalog 大改
```

只处理：

> **错误升级、重复修复、预算耗尽后无法收尾。**

---

# 23. 完成标准

```text
1. FAST 升级不能仅凭历史上下文触发。

2. 当前消息没有行动意图时，Fast LLM 的升级申请会被 Runtime 拒绝。

3. Fast → Standard 每轮最多一次。

4. 同一 Tool 的同类错误最多 repair 一次。

5. 连续失败后 Tool 会被本轮锁定。

6. 重复 search_memories 不会反复调用。

7. 已知 Tool 后不会因为参数错误重新 request_tool_group。

8. STANDARD 有明确 model/tool/repair round budget。

9. Token Budget 进入 DANGER 后立即停止新 Tool。

10. Token Budget Exhausted 时仍能生成 deterministic fallback。

11. Partial Success 会保留并准确展示。

12. Observatory 能解释：
    - 为什么升级
    - 为什么升级被拒绝
    - 为什么 Tool 停止重试
    - 为什么强制收尾
    - 是否使用 fallback
```

---

# 24. 一句话定义

> **当前消息没叫朝汐干活，就别被旧上下文拽去干活；工具已经撞墙，就别继续拿头撞；预算见底时，至少把已经做完的事情好好交代出来。**
