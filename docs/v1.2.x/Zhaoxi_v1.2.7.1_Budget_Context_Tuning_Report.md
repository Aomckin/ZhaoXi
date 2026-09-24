# v1.2.7.1 Budget / Context Tuning 交付记录

## 基线与参数

2026-09-23 的本地真实日志中，一次复杂请求已有 5 次 Tool 成功，随后第 7 次模型轮次在最终回复阶段触及原 100,000 Token 请求上限。可确认的一轮用量为输入 16,564、输出 218，累计用量由 89,244 增至 106,026；后续记录出现 107,987。旧日志没有逐组件 Context 体积，因此无法从这份基线推导各组件的压缩幅度。

本补丁保留 100,000 Base Budget，默认第一、第二次扩容上限分别为 25,000 和 15,000，Hard Limit 为 140,000，收尾保留 8,000，预警比例 0.85。这些是由上述失败样本约束的**暂定值**，可通过 `.env` 调整；需要更多真实复杂任务才能最终定标。单次 Provider 返回的 Token 用量可能跨过阈值，Runtime 会在该轮结束后阻止下一轮继续越界。

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

## 2026-09-24 实机验收

用户明确授权向当前配置的 `api.commandcode.ai` 发送实机测试请求后，使用该服务及合成数据进行以下验收：

- 两项 Tool 的英文任务在默认预算内完成：4 次模型调用，累计 10,182 Token；`calculator`、`echo` 各成功一次。最后一轮为 `finalization`，Tool Schema 估算由 636 降为 0，Provider 输入从上一轮 2,873 降至 2,077 Token。
- 中文任务暴露了 Planner 把“最后简短说明”列为业务步骤、反复拒绝 `finish_task` 的问题。已将“最终回复不属于计划步骤”写入控制工具说明和 Planner 状态规则。修正后任务完成，但仍重复执行了两项只读测试 Tool：7 次模型调用，累计 22,257 Token，最终回复仅“任务已完成”。这说明该 Planner 场景的效率和回复质量仍有改进空间，不能将其算作高质量完成。
- 使用仅供测试的 Base 4,200、Extension 1 上限 12,000、Hard 16,200、Reserve 700 验证真实扩容：一轮调用后累计用量达到 5,072，Runtime 批准一次 `tool_execution` 扩容 12,000；两项 Tool 各成功一次，4 次调用累计 10,095 Token，最终回复完整。最终 Tool Schema 估算由 646 降至 0，Provider 输入从上一轮 2,888 降至 2,071。由于 Token 在模型返回后结算，单次调用跨过 Base 阈值 872 Token；这不是额外申请次数。
- 使用合成 Agenda、STM 和长期 Memory 的两轮普通对话共 2 次模型调用、2,351 Token，无扩容；逐轮诊断的 `memory_snapshot` 与 `retrieved_memory` 均为非零，模型回答正确接续考试、次日日程和长期偏好。没有把用户真实记录发送到测试服务。

## 仍需验证和改进

真实复杂任务样本、角色连续性、图片任务及 Memory / Recent Messages 的压缩前后成功率尚未做对照。因此默认数值仍为暂定，近期消息窗口与 Memory 语义层未进一步裁减。中文 Planner 测试出现重复工具调用和过短最终回复；当前扩容策略没有把这些无效调用当成可无限续命的理由，但仍值得单独优化。单次调用可能越过 Soft Budget；绝对 Hard Limit 在 Provider 返回后按实际 usage 执行，无法在请求发出前保证精确截断。
