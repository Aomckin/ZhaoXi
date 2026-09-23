# Zhaoxi v1.2.7.1 调优补丁任务书
## 主题：Budget / Context Tuning

> 版本定位：基于 v1.2.7 已完成的 Agent Observability，对多轮模型调用、Tool 调用与最终回复阶段进行 Token Budget 和 Context 体积调优。
>
> 本补丁不重做 v1.2.7 的事件系统、Action State、Recovery 或行动显式化 UI；目标是利用现有观测能力，降低无效 Token 消耗，并允许 Planner 在复杂任务中受控申请额外预算。

---

## 1. 背景

v1.2.7 已具备请求级 Trace、Tool 调用关联、结构化事件、Action State、Token Budget 明细和错误归因能力。当前真正要解决的是：

1. 正常复杂任务不应因为固定预算过早被截断；
2. 不能简单粗暴把预算整体翻倍，否则会掩盖 Context 膨胀、重复 Tool Result、图片重复携带等问题；
3. Tool 已经完成、只剩最终回复时，需要为收尾保留足够预算。

近期实机场景已经证明：

```text
Tool 实际已经成功
→ 多轮上下文继续累积
→ 最后一轮回复生成触发 Token Budget Exhausted
→ 任务本身完成，但最终自然语言回复失败
```

因此本补丁的方向不是“单纯加预算”，而是把预算变成受控资源，并减少不必要的上下文重复。

---

## 2. 本补丁目标

### A. Planner 可申请额外预算

Planner 不直接修改预算，只能提交 Budget Extension Request。

最多允许：

```text
2 次申请
```

Runtime 决定批准或拒绝。

### B. 建立 Soft Budget + Hard Limit

预算结构改为：

```text
Base Budget
→ Extension 1
→ Extension 2
→ Hard Limit
```

Planner 可以获得续航，但整个任务始终存在不可突破的绝对上限。

### C. 降低重复 Context

重点检查：

- 历史 Tool Result
- 已完成 Tool 的 schema / 定义
- 图片输入
- Memory Snapshot / Recall
- 重复系统 Prompt
- 多轮模型消息回放
- Planner / Replyer / Recovery 之间的重复上下文

原则：

> 不重复携带已经不再需要的高成本信息。

### D. 保证“收尾预算”

Tool 已完成、只剩最终状态归并与自然语言回复时，不应因为前面业务步骤消耗完预算而直接失去输出能力。

---

## 3. Budget Extension 设计

### 3.1 允许申请的场景

Planner 可在以下情况下申请扩容：

- 已完成部分 Tool，仍有明确剩余动作；
- Tool 参数校验失败，但已获得可修正信息；
- 当前处于明确的重试路径；
- 已完成副作用操作，只剩最终结果整理；
- 当前上下文仍有有效进展，不是重复循环。

### 3.2 申请结构

建议：

```python
BudgetExtensionRequest(
    reason="仍有 1 个明确 Tool 操作待完成",
    remaining_actions=1,
    estimated_extra_tokens=12000,
    stage="tool_execution",
    progress_evidence={
        "completed_actions": 2,
        "last_success_step": 5,
    }
)
```

至少包含：

```text
reason
remaining_actions
estimated_extra_tokens
stage
```

可选：

```text
progress_evidence
```

### 3.3 Runtime 审批

Runtime 必须校验：

```text
extension_count < 2
```

并判断：

- 是否存在明确未完成动作；
- 最近若干轮是否产生实际进展；
- 是否连续重复相同错误；
- 是否接近 Hard Limit；
- 本次申请是否明显超过剩余任务规模；
- 当前是否只是无意义探索。

默认拒绝：

```text
连续重复相同 Tool Validation Error
连续相同 Provider 错误
连续模型轮次没有新增 Tool / State / Result
Planner 无法说明剩余动作
estimated_extra_tokens 明显异常
已经使用两次扩容
Hard Limit 即将触发
```

---

## 4. 两次扩容的语义

### Extension 1：复杂任务续航

用途：

```text
继续执行剩余业务动作
修正一次可恢复 Tool 调用
完成明确的多 Tool 任务
```

审批相对宽松。

### Extension 2：收尾 / 恢复预算

仅用于：

```text
最后一次明确 Tool 修正
最终 Action State 汇总
Recovery
最终自然语言回复
```

原则：

> 第二次扩容不得重新开启大范围探索。

---

## 5. Finalization Reserve

新增“收尾保留额度”。

目的：

```text
业务全部完成
→ Token 刚好耗尽
→ 最后一句话无法生成
```

Runtime 在 Base / Extension Budget 中保留：

```text
finalization_reserve
```

该额度默认不给 Planner 普通探索阶段使用，只用于：

```text
Action State 汇总
Recovery
最终自然语言回复
```

具体数值通过实机日志确定，本任务书不写死。

---

## 6. Context 体积诊断

利用 v1.2.7 已有真实 Provider payload 统计，对复杂任务逐轮记录 Context 构成。

建议 Debug 增加：

```text
system_prompt_tokens
recent_messages_tokens
memory_snapshot_tokens
retrieved_memory_tokens
tool_schema_tokens
tool_result_tokens
image_tokens / image_count
planner_state_tokens
other_tokens
total_input_tokens
```

如果 Provider 无法直接给出组件 Token，可在发送前使用当前 tokenizer / 近似估算。

总输入 Token 仍以 Provider 返回值为最终依据。

---

## 7. Tool Result 压缩

刚执行完成的 Tool Result 保留完整必要字段。

若后续已经被 Action State 吸收，则压缩为短摘要。

例如：

```text
agenda_add: success
record_id=xxx
```

后续模型若仍需要 Tool 返回的关键 ID，则必须保留，不得提前丢弃。

---

## 8. Tool Schema 注入优化

检查当前每轮模型调用是否重复注入全部 Tool Schema。

尽量复用现有动态能力发现与 Semantic Capability Routing：

- 已确定只需要某一 Tool Group 时，不重新附带无关 Tool；
- 某 Tool 已完成且后续不可能再次调用时，可从后续轮次移除；
- Recovery / Final Reply 阶段如果不允许 Tool Call，则不携带 Tool Schema。

不得破坏现有 `requires_tool_call / required_tool / 强制 Tool Choice / Discovery` 等契约。

---

## 9. 图片 Context 优化

首次视觉理解阶段保留原图。

已提取结构化信息后，如果后续 Tool / Final Reply 不再需要重新看图：

```text
使用视觉摘要 / 结构化提取结果
不再重复发送原图
```

如果确实需要二次视觉判断，则继续保留原图。

不能简单“一轮后必删”。

---

## 10. Memory Context 调优

当前 Agenda 与 STM 每轮常驻 Context，长期 Memory 按需检索。

检查：

- STM Snapshot 是否过长；
- Agenda 是否携带过多与当前任务无关的未来事项；
- 长期 Memory Recall 是否与 STM / Recent Messages 重复；
- 同一条事实是否在多个层重复出现。

原则：

```text
保留语义层级
减少内容重复
```

不要通过简单关闭 Memory 换 Token。

---

## 11. Recent Messages 调优

检查复杂 Agent 请求中：

- 最近消息是否真的需要全部进入每一轮 Tool Call；
- Tool Loop 内部是否可以改用本轮 Task State，而不是反复回放完整聊天历史；
- 已经被 STM / Action State 明确吸收的信息是否重复存在。

不直接粗暴砍消息窗口。

必须基于实机 Trace 对比压缩前后任务成功率和角色连续性。

---

## 12. Prompt 体积检查

统计：

```text
System Persona
Agent Rules
Tool Instructions
Memory Instructions
Planner Instructions
Reply Instructions
Few-shot
```

只处理：

- 明显重复；
- 多处表达同一约束；
- 已由 Runtime 强制保证、无需反复提示模型的内容。

不以“少 Token”为由删除关键人格、权限、安全或 Tool 契约。

---

## 13. Model Call 分阶段预算

为不同阶段建立预算类别：

```text
understanding
planning
tool_execution
recovery
finalization
```

先支持阶段级统计、警告和扩容判断，不急着给每阶段写死额度。

---

## 14. 防止死循环续命

Budget Extension 必须与 Progress Detection 绑定。

Runtime 可维护：

```text
last_tool_name
last_error_code
last_action_state_change
last_success_step
state_hash
```

如果连续多轮：

```text
无 Action State 变化
无新 Tool Success
无新有效信息
错误码重复
```

则：

```text
budget_extension_allowed = false
```

并进入 Recovery。

---

## 15. Action Trace / Debug 展示

主界面保持现有简化设计，不增加工程细节。

侧边栏 Action Record 可显示：

```text
正在继续处理复杂任务…
已申请额外预算
额外预算已批准
```

Debug 显示：

```text
Base Budget
Used
Extension Count
Requested
Approved
Rejected Reason
Hard Limit
Finalization Reserve
```

不要在主聊天界面展示具体 Token 数字。

---

## 16. 日志

新增结构化事件：

```text
budget_extension_requested
budget_extension_approved
budget_extension_rejected
finalization_reserve_entered
context_compacted
tool_result_compacted
image_context_released
```

预算申请日志至少包含：

```text
trace_id
request_id
step
extension_index
reason_code
used_before
requested_extra
approved_extra
hard_limit
```

不记录 Planner 的长篇自由文本 reasoning。

---

## 17. 配置

所有数值进入统一配置，避免散落魔法数字。

例如：

```text
base_budget
extension_1_limit
extension_2_limit
hard_limit
finalization_reserve
budget_warning_ratio
```

允许通过现有配置系统 / `.env` / model settings 管理。

普通设置页暂时不必全部暴露，Debug 可只读展示当前值。

---

## 18. 本补丁不做

- 不重构 v1.2.7 Action Event 架构；
- 不重做 Action Trace UI；
- 不改 STM / Agenda 领域模型；
- 不修改 Tool 权限体系；
- 不新增模型供应商；
- 不引入新的 Agent Framework；
- 不为了节省 Token 删除人格；
- 不自动把历史长期记忆批量摘要；
- 不实现无限预算；
- 不允许 Planner 自己直接改 Hard Limit。

---

## 19. 推荐实现顺序

### Phase 1：只测量，不优化

先用真实复杂请求跑数据：

```text
逐轮 input/output
Context Components
Tool Result
Image
Memory
Tool Schema
```

输出一份真实样本报告。

### Phase 2：Budget Extension

完成：

```text
Base Budget
Extension Request
Runtime Approval
最多两次
Hard Limit
Finalization Reserve
```

先不动 Context。

### Phase 3：低风险 Context 压缩

优先：

1. 已完成 Tool Result 压缩
2. Final Reply 阶段移除 Tool Schema
3. 不再需要时释放原图
4. 去除明显重复 Prompt

### Phase 4：Memory / Recent Messages 调优

这部分最容易影响生活感和连续性，最后做。

必须实机对比。

### Phase 5：参数落定

根据真实日志确定：

```text
Base Budget
Extension 1
Extension 2
Hard Limit
Finalization Reserve
```

任务书不预设最终数值。

---

## 20. 验收场景

### Case 1：普通聊天

不触发 Extension。

Token 消耗不明显增加。

### Case 2：单 Tool 请求

正常 Base Budget 完成，不申请扩容。

### Case 3：多 Tool 复杂任务

Base Budget 接近阈值，Planner 明确还有剩余动作：

```text
Extension 1 -> approved
```

任务继续并完成。

### Case 4：一次修正后继续

Tool Validation Failed 后获得 schema 信息，Planner 申请扩容，Runtime 批准，修正成功。

### Case 5：连续相同错误

连续多轮相同 Tool、相同 Error、无 Action State 变化时：

```text
budget extension -> rejected
```

进入 Recovery。

### Case 6：第二次扩容只用于收尾

业务动作已基本完成，第二次申请理由为 `finalization` 时可批准。

不得开启新的大范围 Tool 探索。

### Case 7：Hard Limit

达到两次扩容或 Hard Limit 后，后续申请必须拒绝。

### Case 8：业务完成但回复生成需要预算

Tool 全部成功，普通业务预算接近耗尽时，使用 Finalization Reserve 完成最终回复。

### Case 9：图片复杂任务

第一轮使用图片，后续确认不再需要视觉信息后，不再重复携带原图。

### Case 10：Tool Result 压缩

执行多个 Tool 后，下一轮上下文 Token 明显下降，Action State 仍完整，关键 ID 未丢失。

### Case 11：Memory 连续性

经过 Context 调优后：

- STM 正常；
- Agenda 时间事实正常；
- 长期 Memory Recall 未被粗暴关闭；
- 普通生活对话角色连续性无明显退化。

---

## 21. 完成标准

- [ ] 可记录 Context 主要组件 Token 占比
- [ ] Planner 可结构化申请额外预算
- [ ] Runtime 独立审批预算
- [ ] 最多允许两次扩容
- [ ] 第二次扩容限制更严格
- [ ] 存在绝对 Hard Limit
- [ ] 存在 Finalization Reserve
- [ ] 无进展循环不得通过扩容继续烧 Token
- [ ] Tool Result 可在安全条件下压缩
- [ ] 不再需要的图片不会持续重复发送
- [ ] Final Reply 不携带无用 Tool Schema
- [ ] Prompt 明显重复项完成清理
- [ ] Memory / Recent Messages 调优经过真实场景验收
- [ ] 普通任务不会无意义申请扩容
- [ ] 复杂任务不会轻易在最后回复前被硬截断
- [ ] Action Trace UI 保持轻量
- [ ] Debug 可完整查看预算申请、审批、拒绝与 Context 变化

---

## 22. 最终设计原则

本补丁不是：

> 给朝汐更多 Token。

而是：

> **让朝汐知道什么时候值得继续花 Token，Runtime 知道什么时候应该给；同时让已经处理过的信息不再一轮轮背在身上。**

理想状态：

```text
简单任务
→ 少花

复杂任务
→ 可以申请续航

已经成功的内容
→ 压缩

重复失败
→ 不续命

最后只差一句话
→ 留钱把话说完
```

先把预算变成“可管理的资源”，再决定具体给多少。
