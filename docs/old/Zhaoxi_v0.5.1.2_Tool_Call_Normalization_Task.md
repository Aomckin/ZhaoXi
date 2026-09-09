# Zhaoxi v0.5.1.2 Tool Call Normalization 任务书

## 目标

在模型 Provider 边界统一工具调用语义：标准 structured `tool_calls` 与受支持的 DSML 文本 Tool Call 都正规化为内部 `ToolCall`，再进入同一套 Agent / Planner / Permission / Tool Runtime。

## 开发项

1. 在 OpenAI-compatible Provider 增加 DSML 文本协议解析与参数类型安全转换。
2. 从可展示正文中剥离协议；协议残缺或无法解析时失败封闭，绝不向用户透传。
3. 同时出现 structured 与文本调用时以 structured 为准，避免重复执行。
4. 补齐标准调用、DSML 调用、空参数、去重和畸形协议回归测试。
5. 更新版本标识与代码库状态，并执行全量测试、编译和 diff 检查。
6. Life HUD 原始 Instant 保持 UTC，仅在 Tool observation 层转换为可配置的本地展示时区。

## 验收标准

- 两类协议进入 Runtime 前均为 `zhaoxi.models.types.ToolCall`。
- CLI 最终输出不包含 `DSML`、`tool_calls` 等模型内部协议正文。
- 未知工具与非法参数仍由现有 Tool Runtime 统一校验，不绕过权限边界。
- 畸形文本协议不可执行、不可展示；既有 structured tool call 行为无回归。

## 完成状态

已完成。Provider 单元测试、真实 DeepSeek 空白/双竖线 DSML 变体测试、DSML → Agent Runtime 集成测试、UTC 源数据不变与本地展示转换测试及全量 **107 项测试**均通过。
