# v1.4.8.x · 边做边说中间回复与纯正文补修

## 日用反馈与证据

00:01:33–00:03:06 请求 `bb81de1c-5894-45be-8925-b024d94ef3dd`：LifeHUD ×2 和 agenda_add 的工具结果已确认，第三轮最终生成失败（empty_model_reply），第四轮一次补修失败（invalid_reply_protocol）；耗时 93.53 秒，预算 NORMAL、repair_round=1。截图中的中间台词来自上次运行时固定文案，没有携带人格。日志仅保存协议形状和长度，不能断言补修具体缺少哪个字段。

中间回复以用户提供的 [v1.4.8.x 补丁任务书](../v1.4.x/Zhaoxi_v1.4.8x_Interim_Reply_Say_While_Acting_补丁任务书.md) 为执行依据。最终正文补修属于此前已授权的失败缺口修复，单独说明，不改变中间回复契约。

## 中间回复实现

- Agent、Planner 使用同一次模型输出的原生 `response.content + response.tool_calls`。台词是自然文本，不新增 Step Schema、MainReply 字段或人格模板。提示沿用完整人格和关系上下文；可留空，无工具调用时走原最终流程。
- 模型能力提示不依赖当前时长或发送次数。运行时才检查时长、开关、次数、长度、内部协议、提前终态宣告、重复文案及新行动；首步可以先说“我先看看”。有效候选在下一步工具执行前通过原 ActionTrace / SSE 展示。
- 同一句台词不进入 Conversation 的工具草稿，不进入之后模型请求，也没有 Memory、Cognition 或 Decision 写入入口。保留工具调用和工具结果记录，最终回复独立覆盖请求及真实结果。
- 删除计时等待后自动插入的固定状态台词。正常路径不调用额外模型、工具、Router 或检索；单次模型请求迟迟未返回时不会凭空产生中间台词。
- 复用原短暂聊天气泡，最终回复追加，不覆盖中间气泡；刷新后可不保留中间气泡。取消和请求匹配沿用原路径。
- 旧 `emit_interim_reply` 处理器保留，默认不暴露 schema。显式设置 `ZHAOXI_INTERIM_LEGACY_TOOL_ENABLED=true` 可用于调试回滚；不是正常启用方式。
- 新增 `interim_candidate_generated` / `interim_candidate_suppressed`；原因包括 too_fast、duplicate、too_long、no_progress、max_count、unsafe_content、terminal_claim、delivery_unavailable。诊断不记录候选正文或行动参数。通知发送异常就地吞掉，不影响工具执行和最终回复。
- 允许工具的模型请求不强制最终 JSON schema，以免阻止原生自然台词；无工具调用的输出仍按原主回复完整性契约解码。收尾阶段继续使用原 main_reply schema，FAST 和 Workflow 未迁移。

## 此前失败缺口的正文补修

- 一次补修使用独立 reply_repair 契约，仅要求正文；携带紧凑真实结果、回执、当前图片和完整 character_prompt。不再次要求决策意识元数据，不伪造或记录新的决策。
- 服务忽略 JSON 模式时兼容完整普通正文；截断 JSON、额外续写字段、工具参数信封、内部协议标记及 length/max_tokens/content_filter 结束仍拒绝。
- 一次补修、总轮数、调用 / Token 硬上限、超时、已执行结果保留和失败终态口径沿用上次补丁。补修不能重放工具。

## 验证与边界

模拟 Provider、本地 HTTP 夹具、合成 PNG 回归 **659 项通过**，覆盖 interfaces / core / decision / observability / reliability / cognitive / planner / models 及 Agent 集成。关键验收：

- 原生台词与工具调用同次产生，OpenAI Compatible 的 content 和 calls 均保留，文本协议工具归一化既有测试通过。
- 首步发送早于实际写操作；快速或关闭发送时没有中间气泡；无台词不生成固定兜底。
- Agent 与 Planner 的人格台词原样展示、不写历史、不进入后续请求；调用次数不增加。
- 重复、无新进展、超长、内部协议和提前完成宣告受抑制；抑制不把任务改为失败。
- 中间通知 SSE 失败时，Agent / Planner 仍执行原工具并给出完整最终回复。
- 最终回复的完整性、错误恢复、失败业务终态、取消和工具不重放回归通过。
- 旧中间工具默认退场，显式调试开关可恢复 schema。

未调用生产模型，未改已有日程 / LifeHUD 数据，未重启正式进程。真实人格自然度、发送频率与当天最终回复成功率需加载补丁后继续 Dogfooding；本次不把模拟回归等同于生产验收。
