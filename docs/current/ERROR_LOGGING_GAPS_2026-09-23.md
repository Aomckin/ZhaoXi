# 报错记录颗粒度缺陷盘点（2026-09-23）

范围：检查 `.zhaoxi/logs/zhaoxi.log` 中近期报错，并对照当前源码。这里只整理可观测性和错误归因问题，不改变运行逻辑。日志计数是检查时的快照，后续运行会变化；`zhaoxi.log.1` 未纳入计数。

## P1：会直接误判故障或无法确认副作用

1. **Token 预算超限缺少用量明细。** 9 月 22 日 22:13、23:59 和 9 月 23 日 13:34 均记录 `provider_token_budget_exhausted`，却没有累计用量、上限、本次调用用量、调用序号以及输入/输出 Token 拆分。三次均在 HTTP 200 后触发。`CallBudget.record_tokens()` 只抛错误；`log_prompt_usage()` 只在 DEBUG 下运行。INFO 日志无法判断是单次上下文过大、历史消息重复，还是多个正常调用累计超限。建议在超限事件记录 `used_before / call_total / used_after / limit / step / provider_model`，不记录提示词正文。证据：日志约 8207–8209、8773–8775、8874–8876 行；`src/zhaoxi/reliability/retry.py`、`src/zhaoxi/models/resilient.py`、`src/zhaoxi/models/prompt_diagnostics.py`。

2. **回退摘要没有区分“失败后已修复”与“仍失败”。** 9 月 22 日 23:58 的 `agenda_add` 参数校验失败，23:59 重试成功；最终固定文案仍说“部分操作未能完成”。当前实现逐条统计工具结果的 `success`，没有按动作或目标汇总最终状态。建议为每次调用记录 `step / tool_call_id / invocation_id / outcome / superseded_by`，在请求结束时输出已完成、仍失败、结果未知三个列表；用户提示只根据最终状态生成。证据：日志 8759–8775 行；`src/zhaoxi/core/agent.py` 的 `_recoverable_turn_content()`。

3. **主日志里的工具结果不可与具体副作用稳定对应。** 主日志仅有工具名、参数键名和布尔 `success`；两次 `add_job` 的行看起来完全一样，无法从主日志确认写入的是哪两条或是否重复。权限审计另有 `invocation_id` 和参数摘要，但主日志没有该 ID，跨文件对账需要借助时间和请求号猜测。建议主日志加入 `tool_call_id / invocation_id / result_code`，写操作还应记录脱敏的目标或新建记录 ID；继续避免记录原始参数。证据：日志 8755–8758 行、`.zhaoxi/audit/permission.jsonl` 同时间段；`src/zhaoxi/core/agent.py` 工具循环、`src/zhaoxi/permission/executor.py`。

4. **跨层错误关联不完整，而且“模型服务不可用”会掩盖本地预算错误。** Agent 的普通 WARNING 只写 `ProviderError` 类型，Web 层常为 `trace=- request=-` 且只写 `AgentLoopError` 类型。要结合多行才能找到根因；预算超限时展示的仍是“模型服务暂时不可用”。建议在跨层日志保留同一 `trace_id / request_id / error_code / stage`，把 `budget_exhausted` 与 HTTP/网络错误分开映射。证据：日志 7071–7074、8207–8209、8773–8775 行；`src/zhaoxi/core/agent.py` 的 `log_internal_failure()` 和回退通知、`src/zhaoxi/web/app.py` 的 chat/regenerate 异常处理。

## P2：会增加定位时间或导致关键失败静默

5. **HTTP 400 只保留截断的原始响应，缺少结构化协议诊断。** 当前将响应文本压成一行后截取前 500 字符；9 月 22 日多次 `Messages with role 'tool'...` 的嵌套 JSON 因而被截在 `providerMetadata` 中间。无法从日志直接确认发送时的消息角色序列、工具调用 ID 配对或文本/原生传输方式。建议记录解析后的 `provider_error_type / provider_error_code / HTTP status`，并记录脱敏的消息角色序列、工具调用数量和配对检查结果；不保留完整响应体或消息正文。证据：日志 8663 行；`src/zhaoxi/models/openai_compatible.py` 的 HTTP 异常分支。

6. **参数校验日志只含字段和错误类别。** 例如 `agenda_add` 的 `type: missing`、`update_stage` 的 `status: enum`，能确认发生了什么校验错误，却看不出字段期望的枚举集合、是否把 `kind` 当成别名、模型是否已看到正确 schema。建议增加脱敏的 `expected_type / allowed_enum / supplied_keys / schema_version_or_hash / step`；绝不记录原始参数值。证据：日志 8548–8550、8759–8761 行；`src/zhaoxi/permission/executor.py` 的 `_validation_issues()`。

7. **传感器与心跳异常只记类型，部分异常完全无日志。** LifeHudSensor 的大量 `TimeoutError` 记录了失败次数和下次轮询时间，但没有调用耗时、超时阈值、失败阶段或底层错误类别；`heartbeat.run()` 的顶层 `except Exception` 只增计数，未写错误日志。建议记录安全的阶段、耗时、超时阈值、恢复时间，并为心跳顶层异常发一条含异常类型和简短错误码的日志。证据：日志 8840–8847 行；`src/zhaoxi/proactive/heartbeat.py` 的 `_sensor_failure()` 与 `run()`。

## 已有能力与边界

- 主日志已有时间戳、严重级别、模块和大部分 Agent 请求的 trace；工具校验日志主动省略参数值，避免泄露用户内容。这些设计应保留。
- 权限审计已有单次调用的 `invocation_id`、参数摘要和执行结果。优先补关联字段，避免复制一份敏感参数到普通日志。
- DEBUG 已有提示词组件长度和 Provider 用量；不过它默认关闭，且 `collect_prompt_diagnostics()` 使用 `Message.to_provider_dict()`，而真实请求使用 `_provider_messages()`。文本工具调用回放时，DEBUG 的“精确输入大小”也可能偏离真实请求；修复预算诊断时应统一测量最终发送的 payload。
- 此次盘点未验证完整历史日志，也未调用真实 Provider 复现；结论限于当前源码与上述日志样本。
