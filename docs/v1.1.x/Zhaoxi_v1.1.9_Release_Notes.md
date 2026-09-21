# Zhaoxi v1.1.9 发布说明

> 历史版本说明：本文记录 v1.1.9 当时行为。当前 v1.2.2 已将 `search_memories` 纳入 Memory Core，并将记忆新增与更新改为默认允许；现行行为见 [v1.2.2 开发报告](../v1.2.x/Zhaoxi_v1.2.2_Release_Notes.md)。

## Tool Context Router

本版本在 Agent 与 ToolRegistry 之间加入只负责 schema 可见性的确定性 Router。Registry 注册、工具权限与执行路径保持不变。

- 普通对话常驻 `remember_memory`、`update_memory`，保留“广记”能力。
- 记忆检索与管理、潮庭、文件搜索/读写、网页、时间、计算器和 Life HUD 按当前意图组合暴露。
- “提到对象”不会自动等同于“请求操作对象”；例如“今天铁幕做得累死了”不会加载 Life HUD。
- `ZHAOXI_TOOL_ROUTER_MODE=dynamic` 为默认行为；设为 `all` 可恢复全工具 schema。
- Router 异常时降级到已注册的 persistent core，不返回意外空列表。
- 每次模型调用重新基于当前 Registry 生成 schema，兼容 Provider 动态刷新和多步 Function Calling。

## 可观察性

DEBUG Prompt Diagnostics 新增 router mode、常驻工具数、命中动态组、注册/暴露/过滤工具数、路由原因标签及筛选前 schema 字符数。日志仍只记录名称和长度，不记录用户原文、Memory 内容、schema 正文或参数正文。API 返回的 prompt token 用量继续单独记录。

## 验证

- Router、配置、Prompt Diagnostics、Agent、Cognitive、Memory 与 Life HUD 相关测试通过。
- 完整测试通过，1 项按环境条件跳过。
- Few-shot 测试以当前保留场景为数据源，不再硬编码已主动删减前的数量。
- 自启动可从全局 Python 启动环境稳定解析项目 `.venv\\Scripts\\pythonw.exe`。
- 本地真实 Memory Tool schema 实测结果见开发交付回复；未在自动测试中发起付费真实模型请求。

## Desktop 修复

- Core 原地重启为 Uvicorn graceful shutdown 设置有界超时，避免浏览器 EventSource 长连接让旧服务线程固定等待到“Core 停止超时”。
- 设置页的输入合并与分段回复间隔由 Core 原子写入 `.zhaoxi/interface-settings.json`；浏览器 `localStorage` 仅保留为兼容回退。
- 模型思考开关继续持久化到 `.zhaoxi/model-settings.json`。
