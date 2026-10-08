# 2026-10-09 空内容认知计数与失败指标修复

完成 [周日志审计](2026-10-08-weekly-failure-log-audit.md) 剩余已确认代码问题 **B03 / B04**。连同 [后台预算与失败队列修复](2026-10-09-background-snapshot-recovery.md)，B01—B04 的代码修复均已完成。

## B03：空内容事件不再导致认知计数 TypeError

`InternalActivityRuntime._pending_turns()` 原先把 `and` 表达式直接交给 `sum`；Owner 事件内容为空字符串或 None 时，表达式返回字符串 / None，导致整数相加失败。

现在用过滤条件选事件，每条符合条件的事件累加整数 1。待处理数量与 bootstrap 的用户消息数量均只统计：

- actor_role 为 OWNER；
- 类型为 USER_MESSAGE 或 EXTERNAL_MESSAGE；
- 去除空白后存在文本内容。

纯图片、None、空字符串及纯空白事件不会触发文本认知 bootstrap，也不会打断候选检查。事件与附件继续保留，不重新加入图片占位句；主动视觉及图片工具引用的流程不变。已有认知游标仍用于限定待处理范围，其他角色 / 系统事件不计为 Owner 文本。

## B04：整体结果与操作进度分开记录

`ActionTrace.overall_result_status()` 集中推导整体结果。回复失败或最新 runtime_finished 为 failed 时，整体结果为 failed；确认等待、预算耗尽及部分完成保持各自明确状态。

`finish()` 在写入整体结果前固定操作任务状态，避免“回复失败”把已经执行成功的工具改成任务失败。指标同时输出 `task_status`、`response_status`；Gateway 的响应 activity 字段也使用同一推导，不再只读取 completed 默认值。

| 场景 | task_status | response_status | result_status |
| --- | --- | --- | --- |
| 普通回复成功 | completed | succeeded | completed |
| 没有成功操作，回复失败 | failed | failed | failed |
| 工具已完成，最终回复失败 | completed | failed | failed |
| 部分工具完成，回复失败 | partial | failed | failed |
| 部分工具完成，正常交付结果 | partial | succeeded | partial_success |
| 操作均失败，正常交付失败说明 | failed | succeeded | failed |
| 等待操作确认 | waiting_for_permission | waiting_for_permission | waiting_for_permission |
| 工具已完成，预算耗尽后交付保底结果 | completed | succeeded | budget_exhausted |

`partial_success` 指标与整体 result_status 一致，具体操作的部分完成由 task_status 和 actions 保留。关闭详细指标时，内部终态仍会正确更新；finish 重复调用不重复汇总。历史日志及历史审计数字不重写。

## 摘要上下文兼容补充

扩大回归发现上一轮专用摘要上下文漏掉 SocialTrace 来源标签，已在精简输入中补回该标签。仍保留 snapshot 引用、群来源、时间、`[sN]` 摘要文本及 1,200 字符限制，没有恢复完整对话上下文。

## 验证

最终相关回归 **434 项通过，0 失败、0 错误、0 跳过**，包括 **21 个新增用例**：

- 本地 / QQ 事件的 None、空字符串、空白文本；图片事件保留及游标限定。
- 纯图片事件不会启动文本认知 bootstrap，候选检查不产生失败。
- 正常、回复失败、操作部分完成、操作均失败、等待确认、预算耗尽及详细指标关闭。
- 真实 Gateway 聊天 / 重新生成失败的最终日志和指标。

另给已有“写入成功后回复超时”接口用例增加断言并单独复验通过：写入仅一次，已完成工具保留，返回 activity 与最后日志的整体状态都为 failed。该用例已包含在 434 项中，不重复累加。

覆盖观测、内部活动、Interfaces、Agent 循环安全、Current Cognition、Cognitive Stream、Perception、调试观测及预算策略；也覆盖上一轮后台队列修复。Python AST、`git diff --check`、证据 JSON 和文档链接检查通过。仅有现存 Starlette/httpx 弃用警告。

[验证证据](evidence/2026-10-09-cognition-count-and-result-metrics.json) 保存测试命令、数量、用例名称和源码 SHA-256。

## 加载及剩余范围

需要完整退出托盘中的 Core 并正常重启，加载这些代码修复。本轮未重启实际 Core、未调用真实模型，尚未以线上日志确认失败率下降。

B05 的回复协议根因、B07—B09 的后台输出 / 维护 / 调用预算问题仍需补证据；B06 是历史模型配置故障，B10 是连接环境与恢复改进，不将它们标为本轮已修复。
