# v1.2.7.1 Budget / Context Tuning 交付记录

## 基线与参数

2026-09-23 的本地真实日志中，一次复杂请求已有 5 次 Tool 成功，随后第 7 次模型轮次在最终回复阶段触及原 100,000 Token 请求上限。可确认的一轮用量为输入 16,564、输出 218，累计用量由 89,244 增至 106,026；后续记录出现 107,987。旧日志没有逐组件 Context 体积，因此无法从这份基线推导各组件的压缩幅度。

本补丁保留 100,000 Base Budget，默认第一、第二次扩容上限分别为 25,000 和 15,000，Hard Limit 为 140,000，收尾保留 8,000，预警比例 0.85。这些是由上述失败样本约束的**暂定值**，可通过 `.env` 调整；需要新版本实机样本才能最终定标。单次 Provider 返回的 Token 用量可能跨过阈值，Runtime 会在该轮结束后阻止下一轮继续越界。

## 实现

- Planner 使用 `request_budget_extension` 提交结构化申请。Runtime 根据当前计划与 Observation 独立校验剩余步骤、真实进展、重复失败、申请规模和 Hard Limit；最多批准两次，第二次限收尾、恢复或最后一次可修正调用。模型提交的 `progress_evidence` 不直接作为审批事实。
- 请求级预算区分 `understanding / planning / tool_execution / recovery / finalization`。普通阶段保留收尾额度；完成步骤后的最终回复不携带 Tool Schema。普通 Agent 也在收尾阶段取消 Schema，保留 `requires_tool_call` 等原有约束。
- 每轮从实际 Provider payload 统计 System Prompt、近期消息、STM/Agenda、Memory Recall、Tool Schema、Tool Result、Planner 状态和其他文本的近似 Token，另记图片数量与 payload 字符数；总输入 Token 以 Provider usage 为准。图片 Token 无法从当前接口可靠拆分，显示为未知。
- 已被 Action State 吸收的旧成功 Tool Result 在发送给模型的副本中压缩，保留常用记录 ID、标题、时间和状态；持久化原文不变。明确进入无 Tool 的收尾阶段才释放该轮无需再次识别的图片；视觉处理中仍保留原图。移除了 Desktop Activity 中与 Presence 重复的交互状态字段。
- 预算申请、审批、拒绝、收尾额度、Context 测量及压缩事件进入结构化 Trace。主输入栏只显示现有用户级阶段，侧边栏保留行动记录；维护抽屉的 `Budget / Context Debug` 展示配置和最近一次请求的用量、申请历史及逐轮组成。

## 验证

- Python 全量回归通过；Web Node 测试 42 项通过。
- 离线 Provider Mock 集成用例完成两项 Tool 操作并生成最终回复，确认最终请求没有 `tools` 字段，逐轮组件估算与 Provider 返回的输入 Token 可在 Debug 报告中对应。
- 预算单元用例覆盖两次扩容、Hard Limit、保留额度、重复失败拒绝、第二次申请限制以及普通请求不扩容。

## 待实机验证

旧日志只提供失败基线，不能证明补丁后的任务成功率、角色连续性、Memory / Recent Messages 的实际收益或最终参数最优。一次受限的实机模型探针被环境的自动审批拒绝：它会把内部 System Prompt、Tool Schema 和任务数据发往未获明确授权的外部模型服务。当前没有继续发送。获得用户对该目的地的明确授权后，应用真实复杂请求对比逐轮 Context、最终回复、STM/Agenda/Memory 连续性，再确定预算数值及是否需要进一步裁减近期消息。
