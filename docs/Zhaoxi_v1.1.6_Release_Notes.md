# v1.1.6 Desktop Activity Awareness 开发报告

开发分支：`v1.1.6`。版本元数据已更新。用户原有 `docs/old/` 文档迁移保留，未提交 Git commit。

## 实现与修改文件

| 文件 | 职责 |
| --- | --- |
| `src/zhaoxi/desktop/presence.py` | Win32 前台采样、DesktopSnapshot、独立异步采样循环、退出清理 |
| `src/zhaoxi/desktop/input_hooks.py` | 独立消息循环线程，键鼠低级 hook 安装和卸载 |
| `src/zhaoxi/desktop/activity.py` | 秒桶计数、标题缓冲、Context / Inference / Transition、限频语义推测 |
| `src/zhaoxi/desktop/app.py` | 按开关装配；关闭后继续使用基础 Presence |
| `src/zhaoxi/proactive/interaction.py` | 标准输入信号降低打扰、Continuation 暂缓、标题脱敏 |
| `src/zhaoxi/proactive/heartbeat.py` | 活动结束候选、BackgroundIntent 准备、全屏降噪 |
| `src/zhaoxi/proactive/decision.py` | AmbientContextSnapshot，融合近期对话、活动假设、Intent、Tool Signals、近期主动消息 |
| `src/zhaoxi/cli.py` | 给主动决策注入现有 Conversation / Continuation |
| `src/zhaoxi/web/app.py` | 采样任务生命周期、diagnostics、inspect |
| `src/zhaoxi/config/settings.py`、`.env.example` | 采样、标题、输入开关、频率阈值和持续时间配置 |
| `src/zhaoxi/__init__.py`、`pyproject.toml` | 1.1.6 版本号 |
| `tests/desktop/test_activity.py`、`tests/proactive/test_tidal.py` | 新增回归验证 |
| `README.md`、`docs/README.md`、`docs/CODEBASE_STATUS.md` | 文档与实现状态 |

## 前台与输入

- 使用 `GetForegroundWindow`，只读取这个窗口；`GetWindowThreadProcessId → OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION) → QueryFullProcessImageNameW` 获取可执行文件 basename。所有进程句柄都关闭。
- `GetWindowTextW` 使用 513 个 wchar 的固定缓冲，最多保留 512 字符；标题关闭时不调用它。不扫描后台窗口。锁屏或不可见桌面不读取前台。
- `WH_KEYBOARD_LL` / `WH_MOUSE_LL` 在独立 Windows 消息循环线程中运行。callback 仅计数并原样转交 `CallNextHookEx`，不解引用输入 payload，不保存 key code、文本、鼠标坐标、按钮类型或轨迹。
- 键盘单位是 hook 事件/分钟，包含按下、释放及系统重复事件，不等于字数；鼠标单位包含移动等鼠标事件，不等于点击数。阈值可按设备调整。
- 每类最多 301 个秒桶，仅存秒数和计数。1m 为过去 60 秒事件数，5m 为过去 300 秒事件数除以 5。不会保存逐条事件。
- 根据前台 HWND 变化统计窗口切换；同一窗口仅改标题会更新标题缓冲，但不会虚增窗口切换频率。采样之间极短切换可能漏计。

## 数据结构与保留

`InputShape` 包含 keyboard / mouse / window_switch 的 1m、5m 频率和 idle_seconds。

`DesktopActivityContext` 包含 observed_at、foreground_process、foreground_title、foreground_since、foreground_duration、recent_windows、input_shape、fullscreen、idle_seconds、desktop_available、activity_intensity、activity_duration、interaction_state、interruptibility、recent_conversation_summary、current_intents、tool_signals。

`ActivityInference` 包含 primary_activity、confidence（0..1）、alternative_hypotheses、reason_summary、activity_mode。activity_mode 仅允许 text_production / reading / browsing / mixed_work / media_consumption / gaming / idle / unknown；不维护 App Mapping。

标题切换历史默认保留约 20 分钟（可配置 10–30），最多 600 条；每条为 timestamp、process_name、window_title、duration。当前标题可实时存在。模型最多收到最后 12 条历史及当前窗口。锁屏/采样失败清空标题历史；退出清除 Context、假设和当前快照。重启不恢复。

原始标题、输入桶、ActivityInference 不接入任何数据库、Session、Memory 或日志。持久化的高层活动事件仅说明“持续高输入后停止”，不包含标题或进程路径。未新增自动桌面 Memory 写入链，不把概率推测自动固化为事实；普通对话仍沿用既有 AutoMemory。

## 推测与状态联动

- 原始桌面采样默认每 2 秒，通过 `asyncio.to_thread` 执行 Win32 读取，不阻塞 UI。计数钩子另有线程。
- 只有进入已有 ACTIVE continuation 或普通主动决策候选时才尝试语义推测；前台需稳定至少 10 秒，数据需在 15 秒内，尝试间隔默认至少 60 秒（配置 30–120 秒）。失败也占用间隔，不每次切换调用模型。
- 每次推测仅一次 provider 尝试、30 秒超时、4000 token scope，无工具调用。失败为 unknown；前台改变丢弃旧假设，网络请求结束后再次检查前台是否仍有效。
- 融合标题、进程、输入形状、时间、最近四条对话的有限摘录、准备中的 BackgroundIntent 和当前标准 Tool Signals。Ambient 还带近期主动消息及活动变化。近期 Memory clusters 字段预留为空，本版本不额外扫描长期 Memory。
- 强度 LOW / MEDIUM / HIGH 由输入频率和 idle 计算；activity_duration 为当前强度阶段的持续秒数，foreground_duration 为当前前台语义片段的持续时间，不声称已经准确测量某个语义活动总时长。
- 产生 activity.started / stopped / intensity_changed、经模型置信度约束的 context_switched，以及默认连续高输入至少 20 分钟后停止的 deep_work_ended。
- 高输入发布 `desktop.input_active`，保留 ACTIVE 状态并设 LOW，Continuation 不再机械追问；停止后发布 false，可重新评估未结束话题。锁屏/AWAY/Quiet 的 BLOCKED 优先。
- 长时间高输入停止使非 ACTIVE 用户进入 SEMI_ACTIVE 并产生高层候选；可准备 `BackgroundIntent(send=false)`，实际发送仍经过原有冷却、夜间、Quiet 和模型裁决。
- fullscreen.entered/exited 仍作为低权重状态事件存在，全屏退出不再单独进入高权重普通主动队列。全屏仍保守降低可打扰度。
- StateSignal 输出 foreground_process、activity_mode、activity_intensity、input_active、activity_transition，15 秒过期；State Machine 仅消费标准 Signal。原始标题放在独立短期 Context，避免进入通用 Signal 日志/序列化链。
- Core 无 LifeHUD 依赖；没有启用任何 Tool Package 也可工作。

## Diagnostics / Inspect

`GET /api/diagnostics` 新增 desktop_activity：开关、前台进程名、活动模式/强度/时长、频率、上次高层变化、采样健康度和 hook 健康度。普通 presence diagnostics 不含标题或 HWND。

`GET /api/desktop/activity/inspect` 显式返回当前标题、近期缓冲、输入频率、推测、confidence、reason 与推测时间。复用 Desktop API 的随机本地令牌保护；未装配桌面活动模块时返回 enabled=false。该接口不会触发模型调用。

## 验证与性能

- 全量 Python 回归见本报告末尾最终结果。
- 自动测试覆盖 Win32 process/title API 契约、标题关闭与锁屏不读前台、计数内容边界、1m/5m、切换计数、缓冲过期、脱敏、退出清理、ACTIVE 暂缓与恢复、SEMI_ACTIVE 活动结束候选、全屏降噪、模型假设/置信度/错误降级/限频。
- 五种场景的语义测试使用假模型，验证模型输出接入与数据传递，不冒充真实模型分类准确率测试。
- Windows 实际冒烟：20 次 Presence 调用平均约 0.31 ms，Python tracemalloc 峰值约 546 KiB；两种 hook 安装成功，线程退出成功。这次环境没有可读前台进程/标题，因此该数字仅代表当前不可读前台路径，不代表完整正常桌面性能。
- 输入秒桶最多 903 条、标题最多 600 条、待处理 transition 最多 32 条；内存有界，无持续原始磁盘写入。尚未做正常交互桌面的长时间 CPU profile。

## 手动验收与已知限制

以下真实场景未在当前自动化桌面会话完成，应启动 `python main.py --desktop` 后验收：

1. 编辑器持续输入、只阅读、浏览器与编辑器切换；inspect 中确认进程、标题、频率及不同假设。
2. 看番/游戏全屏后退出，确认不会仅因为退出全屏主动说话。
3. ACTIVE 说“我去试下修复”后输入，确认状态保持 ACTIVE、LOW 且不追问；停下后候选恢复。
4. 连续操作超过默认 20 分钟再停下，确认 deep_work_ended 与 SEMI_ACTIVE 候选；可临时降低配置到 60 秒进行开发验证。
5. 分别关闭标题/输入/整个模块，测试锁屏解锁、退出重启；确认原始数据不恢复、普通 diagnostics 无标题。
6. 在真实模型配置下评估推测是否自然、是否保留不确定性，检查长时间 CPU 和内存。

限制：没有截图、OCR、剪贴板、DOM、Accessibility 全量树；不读取输入内容。快速窗口切换存在采样误差；媒体/游戏含义依赖模型，hook 失败时频率不可用并暴露 input_healthy=false。全屏打扰策略仍保守；语义活动时长、跨日行为聚合、长期桌面 Memory 自动生成和完整 Surprise System 不在本次实现中。

## 最终自动验证结果

- `.venv/Scripts/python.exe -m pytest`：**412 passed、1 skipped、1 warning**，约 15.79 秒。warning 为现有 Starlette/httpx 弃用提示。
- 标题关闭及推测缓存过期收尾后，专项 `tests/desktop/test_activity.py`：**14 passed**。
- `git diff --check`：通过（仅 Git 行尾转换提示）。
- 未执行真实模型 API 的场景准确率验收；真实前台标题和长时桌面使用仍按上述手动清单验收。

## 2026-09-08：查询承诺后提前结束回复修复

证据：21:35 对话 trace `3b48e6a1-0392-43f0-8b6a-2f6afcc821fd` 返回 chat 200，但无该 trace 的 LifeHUD 请求；最终回复停在“我直接去翻你的LifeHUD记录”。同时 memory retrieval / AutoMemory 出现 naive/aware datetime 异常。

- `core/agent.py`：DIRECT 草稿出现当轮查询承诺时，不展示/持久化未完成草稿，使用同一用户消息转入有界工具循环；普通 TOOL 路径也检查未兑现的查询承诺。继续沿用 PermissionGateway，失败如实反馈。不强制把正常“猜测”变为查工具。
- `cognitive/coordinator.py`：提升后将实际路由标记为 TOOL，完成最终回复后才执行 AutoMemory。
- `memory/models.py`：在解析模型输入与旧记录时统一 datetime 为 aware UTC；没有偏移的历史时间按 Memory UTC 兼容约定解释，已有偏移保留同一时刻。`lifecycle.py` / `consolidation.py` 同步兼容 metadata 与 runtime 中的旧无偏移时间。
- 在真实 Memory 数据库的隔离备份上复现 `_time_score` 减法异常；修复后检索和后续写入通过。原始用户数据库没有被此次验证修改。
- 新增 10 项回归覆盖截图原句、同轮工具结果、用户消息不重复、未完成草稿不保存、反复承诺有界失败、普通猜测、非承诺语句、旧数据库和新输入的混合时区。
- 全量验证：**422 passed、1 skipped、1 warning**；`git diff --check` 通过。未调用真实模型重放用户对话。运行中的进程需重启加载修复。
