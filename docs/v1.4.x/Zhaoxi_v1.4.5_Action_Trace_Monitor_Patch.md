# v1.4.5 行动记录侧边栏与 Web 观测修复

2026-10-03，基于 `06e4878` 的源码补丁，保留此前调试入口和感知图片检查补丁。

## 原因

原 `renderAgentEvent()` 只接受当前页面 `beginActionTrace()` 创建的请求 ID。Dashboard 工程 iframe 自己不发起 Desktop 对话，`activeTraceId` 一直为空，收到的行动事件被过滤。打开页面时也未把已有运行时间线填入行动记录。

## 修复

- Desktop 小桌边新增行动记录，展示步骤、Planner 状态、耗时与通道指标，并提供折叠的原始事件。
- 工程页标记为观测页面，跟随最新请求的开始事件；Desktop 正在发送自己的对话时仍只接收该请求，避免其他请求覆盖本轮记录。
- 请求结束事件直接更新完成、失败或等待确认状态；恢复历史时不改变输入框上方的录音或发送提示。
- EventBroadcaster 保存本进程最近一轮的有界快照，最多 300 条，保留开始事件和最近 299 条。旧请求的延迟事件不进入新请求快照，后台维护状态按请求关联。
- `/api/debug/runtime` 增加 `live_action_trace`，原完整指标接口保持有效。页面打开、重新聚焦、SSE 重连和周期刷新读取快照，可恢复进行中的请求；无实时缓存时回读已有 `runtime_metrics.timeline`。
- HTTP 回读期间若已有更新的 SSE 事件，丢弃旧响应，避免旧快照覆盖最新步骤。回读按原鉴权边界执行，不重新调用模型或重放工具。

## 验证与生效

Web / Desktop Python 158 项、Node 83 项通过。新增回归覆盖最新请求关联、延迟旧事件、缓存上限、业务请求独占、快照恢复、HTTP / SSE 竞争、已有指标时间线回读及接口鉴权。

隔离 Edge、真实 HTTP / SSE 与延迟假 Agent 的八项验收通过：Desktop 实时步骤、Web 跟随 Desktop 请求、请求进行中刷新恢复、两侧完成状态、指标显示和切页回看等。两侧均显示同一轮的八条事件，无脚本错误。之前常用调试的十项浏览器回归也通过；没有真实模型调用或社交发送。

证据见 [验收汇总](evidence/action_trace_monitor_patch.json)。截图保存在本地 `.zhaoxi/action-trace-desktop.png` 和 `.zhaoxi/action-trace-web.png`。正式进程未重启；需退出并重新启动整个朝汐进程，再刷新 Dashboard。本次未自动提交或重建安装包。
