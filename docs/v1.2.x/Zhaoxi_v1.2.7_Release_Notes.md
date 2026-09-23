# Zhaoxi v1.2.7 发布说明

2026-09-23 · Agent Observability / 行动显式化

## 实现

- 单次 Chat、重新生成与权限续执行使用 `trace_id`、`request_id` 串联事件；Tool 事件带 `step_id`、`tool_call_id`、`invocation_id`。权限续执行沿用原任务的 `trace_id`，使用新的 HTTP `request_id`。
- Agent、认知路由、记忆检索、模型调用、Tool、回复生成和任务收束产生结构化事件；Web 复用 `/api/events` SSE，页面实时显示运行中、成功、警告、重试、失败状态，并提供不含正文与原始 Tool 参数的 Debug 展开。
- 每次 Tool 尝试保留独立状态：`completed`、`failed`、`unknown`、`superseded`。同名 Tool 的无副作用参数校验失败可被后续修复调用替代；两次成功写入仍是两次独立操作。Recovery 按最终状态列出已完成、仍失败、结果未知。
- Token 预算警告及耗尽记录前后累计、单次输入/输出/总量、上限、步骤、Provider 与模型。Prompt 长度诊断使用实际发送的 Provider payload。预算耗尽映射为 `token_budget_exhausted`，不再显示模型服务不可用。
- Provider HTTP、超时、协议、Tool 校验/执行、Agent Loop、回复生成错误分别归因。HTTP 错误日志保留状态、提供方错误码、消息角色和 Tool 回执配对计数，不记录响应正文。
- Life HUD Sensor 失败日志增加阶段、耗时、超时值、失败次数和下次轮询时间；Heartbeat 顶层异常记录脱敏错误类型。

## 验证

自动化覆盖单 Tool 成功、校验失败后修复成功、两次同名写入、写入后 Token 预算失败、Provider HTTP 失败、最终 Tool 失败、Heartbeat 顶层异常，以及预算数值字段。完整 `python -m pytest -q` 通过；页面内联 JavaScript 经 `node --check` 检查。

没有调整 Token 限值、Prompt、上下文裁剪、模型重试次数或 Heartbeat/Sensor 轮询参数。真实 Provider 与浏览器人工操作仍需在本地运行环境中确认。
