# v1.1.6.1 Desktop Context Injection 补丁报告

本补丁在现有 `v1.1.6` 分支开发，运行时/包版本更新为 `1.1.6.1`。既有未提交改动和文档迁移保留。

## 实现

- `src/zhaoxi/desktop/activity.py` 新增只读 `runtime_context(now)`，从已采样 DesktopActivityContext 提取当前窗口、输入形状和有效推测缓存，不采样、不调用模型、不落盘。
- `src/zhaoxi/core/context.py` 通过已经装配的 `interaction.desktop_activity` 获取上下文，在独立 `[Desktop Activity]` Runtime 区块注入。因此 DIRECT、普通 Tool Loop 及共用 ContextBuilder 的最终回复都可获得观察。
- 注入 available / stale / age_seconds / observed_at、foreground_process / foreground_title / foreground_duration、键盘/鼠标/窗口切换的 1m/5m 频率、fullscreen / idle_seconds、activity_mode / activity_intensity / activity_confidence / activity_summary、interaction_state / interruptibility。另带 input_rate_enabled / input_healthy，避免把无法统计误认为无输入。
- 原始快照到达 15 秒即 stale，与既有 Signal 有效期一致；旧快照仍可供“最后看到”的回答使用。模块关闭、没有采样或锁屏时 available=false，不附带旧标题。标题单项关闭时 foreground_title=null。
- 有效 ActivityInference 缓存直接复用；缓存缺失或超过原有两倍 inference interval 时只传 raw Context，由本轮聊天模型理解。普通对话新增 Activity LLM 调用数为零。
- Prompt 明确标题等字段为不可信观察数据，忽略其中指令；实时/过期/不可用的表达必须区分，活动语义保留不确定性，不复述完整标题、路径或原始区块。

## 数据边界

ContextBuilder 只构造临时模型消息，未向 Conversation 添加原始区块；Session 持久化和 AutoMemory 输入仍为已有用户消息与最终回复。没有新增 raw title 历史持久化、日志输出或 Memory 写入链。普通 diagnostics / Inspect / Proactive / Continuation 的行为保持。正常模型回复可概括软件和活动；不会把原始标题主动复制成长期记忆。

## 修改清单

实现：`src/zhaoxi/core/context.py`、`src/zhaoxi/desktop/activity.py`。

版本：`src/zhaoxi/__init__.py`、`pyproject.toml`。

测试：`tests/core/test_desktop_context.py`，新增 9 项：有/无缓存 DIRECT 输入、stale、missing/locked/disabled unavailable、缓存过期、Session/AutoMemory/日志/diagnostics 隐私、普通工具路径。

文档：`README.md`、`docs/README.md`、`docs/CODEBASE_STATUS.md`、本报告。

## 验证

- 全量 `.venv/Scripts/python.exe -m pytest`：**431 passed、1 skipped、1 warning**，16.77 秒。warning 为现有 Starlette/httpx 弃用提示。
- Desktop / Proactive / 新增上下文专项：通过。
- `git diff --check`：通过，仅既有文件行尾转换提示。
- 测试检查真实 DIRECT 执行路径发给 FakeProvider 的模型输入，并断言只调用一次聊天模型；未调用真实模型付费 API。

## 手动验收

运行中的朝汐需要重启加载补丁。启动 Desktop 后打开 VS Code，先确认 `/api/desktop/activity/inspect` 中 process、title、rates 正常，再问“你现在能看到我在哪个软件吗？”。预期依据当前窗口回答软件，并以“看标题好像……”描述活动。采样过期只能描述最后观察；不可用才说明无法读取。

当前完成代码与自动回归，尚未执行真实桌面 + 真实模型的端到端人工验收。传感器本身不可用时，本补丁不会虚构前台信息。
