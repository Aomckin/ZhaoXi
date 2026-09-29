# Zhaoxi v1.4.0 开发记录

## 本次交付

- ActionTrace 增加请求开始/结束、TTFR、阶段耗时、LLM/Tool 调用明细、Memory 命中数及统一时间线。模型调用在 ResilientProvider 实际尝试边界计时；重试会分别记录。Router、Agent、Planner、Decision、AutoMemory、Current Cognition 与 Workflow Finalization 设置归属。
- Planner TraceRecorder 通过 PlannerActionTraceAdapter 将 goal、plan、step、replan 和完成事件映射到请求 ActionTrace。Planner Tool 调用复用 ActionTrace 的 Tool 记录。
- 本地 Web 增加 Runtime Observatory，展示 Request Summary、Timeline 和默认折叠的 Raw Detail。Memory Retrieval Inspector 显示所选候选的评分、状态、重要度、激活度与选择原因；调试查询不会激活记忆。
- emit_interim_reply 是 Agent/Planner 的 Runtime 控制能力。模型只能在运行超过阈值并仍有后续步骤时使用；默认普通 Agent 最多一次，Planner 最多两次，第二次需有新的 Planner 进展。消息通过独立 SSE interim_reply 事件发送，不写入 Conversation，不进入 AutoMemory 或 Current Cognition，也不终止 turn。
- Web 收到中间回复后立即显示，继续保持请求运行；最终 HTTP 回复或失败响应到达后才结束本轮。中间回复在页面刷新后消失。Runtime 在异常路径仍发出终止 Trace，Web 显示最终错误。
- 配置沿用 ZHAOXI_ 环境变量前缀：RUNTIME_METRICS_ENABLED、INTERIM_REPLY_ENABLED、INTERIM_REPLY_THRESHOLD_SECONDS、INTERIM_REPLY_MAX_COUNT、PLANNER_INTERIM_REPLY_MAX_COUNT、MEMORY_RETRIEVAL_DEBUG_ENABLED。

## 验证

- Python 全量回归：765 项通过、1 项跳过；Node Web 回归：43 项通过。新增 Runtime 指标、中间回复隔离、次数/进展限制、Planner Trace 桥接、失败收尾与 Debug API 测试。
- 前端内联脚本通过 Node 语法检查；Python 源码通过 compileall，Git diff 通过空白检查。

## 实机边界

本轮未连接真实模型服务，也未运行桌面 UI 的长任务实机时序。中间回复由模型在后续 Agent/Planner 调用中主动触发；若单次模型调用一直阻塞直到直接产出最终回复，本版不会在该调用内部强制插入角色发言。当前指标用于建立基线，后续再按真实数据优化延迟。


## 2026-09-29 运行时展示补齐

- 行动记录直接展示模型、工具和阶段结束事件的 duration_ms；请求完成事件携带有界指标快照，侧栏展示全部阶段与逐次调用耗时。阶段时间可能相互包含，不应直接相加。
- Planner 事件增加计划步骤描述、状态、当前步骤及步骤耗时；普通 Agent 路径明确标识本轮未启用 Planner。
- 增加请求作用域的中间回复计时兜底：超过配置阈值、尚未生成回复时发送一次独立事件；结束或离开作用域时取消计时，沿用原有开关及次数限制，不写入对话历史。
- 验证：Observability、Planner、Web 相关 Python 测试 68 项通过；前端 Node 测试 46 项通过。包含慢模型未主动调用中间回复工具、Planner 步骤信息及耗时、前端指标渲染测试。未进行真实模型的桌面端交互验收。


## 2026-09-29 定时兜底撤销与补丁任务书审阅

按用户实际试用反馈，撤销上一节的请求计时中间回复兜底：删除 delayed_reply/runtime_wait 自动任务与固定气泡，保留 Agent/Planner 主动中间回复及次数限制。慢模型回归现验证超过阈值仍不会自动产生气泡，相关 20 项测试通过。运行中的 Core 需重启以加载删除。

已复核当日 00:02 至 10:01 日志，将样本耗时、重复工具目录调用、可见性落盘信息丢失、前后台交付边界及指标口径写入 `Zhaoxi_v1.4.0_Progressive_Response_Visibility_Patch_Task.md`。

## 2026-09-29 回复交付与可见性补丁实施

- 消息增加持久化可见性分类；工具内部轮次不进入实时输出、历史恢复或认知摄取，磁盘重启后仍保持分类。工具轮正式结果带 `tool_turn`，重新生成只继续整理，不重放已确认写入。
- Final 在必要会话持久化后立即返回；AutoMemory 与 Current Cognition 改为有界、持久化、单消费者的后台队列。队列冻结每轮快照、逐阶段 checkpoint，进程中断的写入标记 uncertain，清空会话会撤销积压。自动记忆写入缺少可证明的幂等重放契约，因此重试上限明确为一次，不盲目重放。
- 工具发现按规范化查询与目录版本去重，连续无进展会提示收口并切换最终整理；日志增加安全指纹、缓存命中和控制调用耗时。
- Final 保留按段落拆分；段间延迟继续由“分段回复间隔”设置控制，设为 0 时立即完整展示。节奏状态覆盖整次 `output_messages`，包括 Reply DSL 拆出的正文、表情和后续正文，避免只对单条消息内部段落生效。服务端 `response_sent_at` 与浏览器完整渲染回执分开记录，普通聊天、重生成、权限续跑及语音确认共用回执。
- Runtime 补齐 context build、session persist、tool discovery、post-turn enqueue、response packaging 等阶段，并将嵌套阶段按区间并集计算 Other。侧栏区分 Planner、前台任务、回复和后台维护状态。本轮实际进入上下文的 Memory 候选随请求快照保存，Runtime Observatory 自动展示 Final、Context、Text、Semantic、Graph、Time、Activation、Importance 与命中原因；不为展示重复检索或激活记忆。
- 自动验证：Python 全量回归通过；Node Web 回归通过；`compileall` 与 `git diff --check` 通过。真实模型桌面端的延迟变化和视觉交互仍需重启 Core 后实机验收。

## 2026-09-29 前端与文档收口

- 维护抽屉的表情、近期状态、内部活动、外部来源、感知、认知流、决策、预算、运行观测和通用调试标题及常用控件完成简体中文化，内部协议值与 Debug 原始字段保持不变。
- Runtime Observatory 改为“运行观测”，本轮实际 Memory 候选直接显示为“本轮记忆候选”；前端构建标识更新为 `v1.4.0-zh-ui-20260929`。
- 原任务书实施清单已按实际交付勾选；定时气泡撤销、后台维护队列和分段节奏的实施修订均在任务书与当前状态页明确记录。
- 自动测试和静态检查结果见 [v1.4.0 开发交付说明](Zhaoxi_v1.4.0_交付说明.md)。桌面真实模型长任务、自然中间回复质量和端到端延迟仍属于人工验收边界。
