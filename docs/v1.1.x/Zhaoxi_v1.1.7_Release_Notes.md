# v1.1.7 ACTIVE Conversation Closure 开发报告

> 当前配置、界面行为与最新限制见 [当前状态](CURRENT_STATUS.md)。下文保留分阶段实现与验收记录；其中旧预算和测试数量不代表当前值。

基线已在 `v1.1.6` 提交为 `6fbe423`（v1.1.6.1 桌面感知、普通上下文注入、查询承诺与 Memory 时区修复、原有历史文档迁移）。之后创建 `v1.1.7` 分支开发本版。本版代码尚未另行提交。

## 实现

- 新增 `ConversationBeatLoop`、`ConversationSession`、`ConversationBeatReason`、`BeatDecision`。生产装配使用 Beat Loop；原 Continuation 类保留给兼容调用和已有测试，生产环境不会重复运行两条主动路径。
- ACTIVE 下不要求 world event 或 open_thread；独立会话调度默认沉默 180 秒后首次判断，后续至少间隔 300 秒。利用原有每 30 秒 Heartbeat 唤醒 worker，所以实际判断允许约一个 heartbeat 周期的调度误差。
- 会话维护 started_at、last_user_at、last_assistant_at、last_initiative_at、initiative_budget、beat_count、momentum、next/last Beat 和结果。初始预算 2、上限 3；成功主动发送扣 1，待回应主动消息得到非空用户回复后补 1，同一主动消息不重复补预算。
- 普通回复完成时间刷新 ACTIVE TTL；用户有效回应继续同一会话。Beat 本身不续 TTL，无回应最终在有效互动后约 20 分钟进入 SEMI_ACTIVE，清除会话与临时状态。新会话重新初始化预算。
- momentum 是轻量规则值：用户继续发言与消息长度提升，对话结束表达降低，主动发送后降低；作为模型特征，不作为硬门槛。
- Gate 检查 ACTIVE、静默/冷却、预算、Quiet、夜间、interacting、未解决的权限、BLOCKED、LOW、高输入与近期主动投递。无桌面、无 LifeHUD 仍能仅基于对话判断；高输入信号过期/解除后可重新评估。
- 模型只输出 SILENT / CONTINUE / COMMENT / ASK / CALLBACK；单次有界请求，无 tools，拒绝模型返回的 tool_calls；错误或无效 JSON 降级为 SILENT 并记录 model_failed_or_invalid。SILENT 更新冷却，不消耗发送预算。
- 上下文含最近 12 条有限长度对话、最近四条的有限摘录概览、最后双方消息与时间间隔、现有 Desktop Runtime Context 和推测缓存、互动状态、打扰程度、近期主动历史、BackgroundIntent、预算、momentum 与上次 Beat 结果。不增加独立 ActivityInference LLM。
- Prompt 允许自然评论/回调/好奇，并禁止工具、编造进度、催促、重复、连续问问题、机械关心和固定叫用户名；默认不问“做完了吗/还在吗”。自然程度仍需真实模型验收。

## 发送与竞态

Beat 与普通 Proactive 使用同一 DecisionWorker 串行处理，并共享持久投递历史。普通 Proactive 看见 Beat 后沿用既有普通冷却；Beat 在其他主动发送后遵守 Beat 冷却。延期普通消息 flush 也检查冷却，显式提醒/URGENT 保留优先级；存在待处理显式提醒时先处理提醒。

模型请求后重查用户、会话、Quiet、夜间和桌面打扰状态。用户在模型运行期间发言会使旧 Beat 失效。Beat 最终投递阶段复用 Gateway 会话锁，模型请求期间不持有此锁，因此用户可以随时继续聊天。成功发送通过既有 NotificationSink / Inbox / SSE 路径进入主动消息，且加入当前对话供下一轮引用。

## Diagnostics / Inspect

`/api/diagnostics` 新增顶层 active，presence.active 也可查看：session_started_at、last_user_at、last_assistant_at、last_initiative_at、beat_count、next_beat_at、last_beat_at、last_beat_result、last_beat_reason、last_silent_reason、initiative_budget、conversation_momentum。

`/api/proactive/active/inspect` 返回 current_state、session、desktop_suppression、last_model_decision；复用 Desktop 本地令牌保护。普通 diagnostics 不含模型回复正文或原始桌面标题。

拦截原因包括 not_active、silence_or_cooldown、desktop_busy、blocked、budget_exhausted、request_busy、quiet_mode、night_mode、recent_proactive、priority_message_pending；模型结果包括 model_silent、model_failed_or_invalid。

## 配置

```dotenv
ZHAOXI_ACTIVE_BEAT_MIN_SILENCE_SECONDS=180
ZHAOXI_ACTIVE_BEAT_COOLDOWN_SECONDS=300
ZHAOXI_ACTIVE_BEAT_INITIAL_BUDGET=2
ZHAOXI_ACTIVE_BEAT_MAX_BUDGET=3
```

初始预算高于上限时按上限初始化。旧 continuation 分钟配置不再驱动生产 ACTIVE Beat，改用上述秒级配置。

## 修改文件

- `src/zhaoxi/proactive/beat.py`：会话调度、上下文、模型决策与可观测状态。
- `src/zhaoxi/proactive/worker.py`：Beat 分支、优先消息、发送前复核、投递。
- `src/zhaoxi/proactive/runtime.py`：延期普通消息冷却。
- `src/zhaoxi/proactive/interaction.py`：新会话边界与 active diagnostics。
- `src/zhaoxi/interfaces/gateway.py`：用户/回复/权限事件、共享会话锁、清空会话。
- `src/zhaoxi/cli.py`：生产装配，待权限 Gate。
- `src/zhaoxi/web/app.py`：active diagnostics 与 inspect。
- `src/zhaoxi/config/settings.py`、`.env.example`：配置。
- `src/zhaoxi/__init__.py`、`pyproject.toml`：1.1.7 版本。
- `tests/proactive/test_beat.py`：17 项回归。
- `scripts/smoke_active_beat.py`：显式 --live 才运行的真实模型验收脚本。
- README、文档索引、CODEBASE_STATUS、本报告：实现与验收状态。

## 自动验收

全量 `.venv/Scripts/python.exe -m pytest`：**448 passed、1 skipped、1 warning**，16.53 秒。warning 为既有 Starlette/httpx 弃用提示。`git diff --check` 通过。

覆盖无 open thread、传统 open thread、高输入暂缓/解除恢复、SILENT 不扣预算且冷却、用户回应补预算且不重复补、无回应预算耗尽并超时、新会话重建、quiet/请求忙/权限/disabled/night、模型过程中用户发言或忙碌变化、普通主动与延期消息冷却、模型错误、Inspect 鉴权。测试没有装配 LifeHUD。

## 真实模型隔离验收（2026-09-09）

用户明确授权后，执行 `.venv/Scripts/python.exe scripts/smoke_active_beat.py --live`，使用已配置的 `api.deepseek.com` 和项目人格提示。

结果：**open_thread=false、beat_count=1、action=CONTINUE、failure=null、delivery_count=1**，进程退出码 0。第一次 Beat 成功生成并投递一条自然续聊到隔离内存 Inbox。本次共两次模型调用：一次普通 DIRECT 回复、一次 Beat 决策；未调用第二次 Beat。

测试对话采用任务书的“认可你是我的犬娘了”。正式 Session / Memory 没有修改，未发送桌面通知。终端中文输出存在编码显示问题，因此本报告不引用未能可靠显示的生成正文。

最初真实 API 执行被自动审批拒绝，用户随后明确授权；以上成功结果来自授权后的执行，没有绕过审批。

此结果验证了本机真实模型、普通对话、无 open thread、Beat 决策及投递的完整隔离链路。脚本使用加速的日间时钟，不能等同于任务书要求的真实 Desktop UI 中 3–5 轮闲聊与数分钟静默的完整人工体验验收；该 UI 长时验收仍待完成。运行中的朝汐需重启加载新代码。

本版严格止于 ACTIVE 闭环；v1.1.x 功能范围冻结，后续只允许 bugfix，不新增 Surprise、感官、工具或自治系统。
