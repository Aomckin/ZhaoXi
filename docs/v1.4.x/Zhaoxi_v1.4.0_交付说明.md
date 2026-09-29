# Zhaoxi v1.4.0 开发交付说明

交付日期：2026-09-29。运行时、包元数据和文档版本统一为 `1.4.0`。本版本已完成代码开发与自动回归；真实模型桌面端的长任务时序、自然中间回复质量和端到端延迟仍需重启 Core 后人工验收。

## 本版结果

- 请求级运行观测覆盖 Routing、Memory、Decision、Planner、Workflow、模型、工具、会话持久化、回复封装和后台维护，记录 TTFR、逐次调用、阶段耗时及统一时间线。
- Planner 的计划、步骤、重规划和完成事件进入 ActionTrace；普通 Agent 明确显示本轮未启用 Planner。
- 运行观测直接展示本轮实际进入上下文的记忆候选及 Final、Text、Semantic、Graph、Time、Activation、Importance 和命中原因，不为展示重复检索或激活记忆。
- Agent / Planner 可按真实进展发送独立中间回复。中间回复不终结 turn，不进入 Conversation、AutoMemory 或 Current Cognition；固定超时气泡已按试用反馈移除。
- 用户可见消息使用持久化 visibility 分类，工具内部轮次不会在实时输出、历史恢复或认知摄取中变成“幽灵回复”。
- Final 在必要会话持久化后交付；AutoMemory 与 Current Cognition 由有界、可恢复、单消费者的后台队列处理。显式 LifeHUD 与记忆写入仍保持同步结果语义。
- 工具发现按规范化查询和目录版本去重，无进展循环有界收口，并保留控制调用诊断。
- 正式回复的分段节奏覆盖整个 `output_messages` 图文序列；延迟只服从“分段回复间隔”，设为 0 时立即展示。服务端交付时间与浏览器完整渲染回执分别记录。
- 维护抽屉及运行观测常用界面完成简体中文化。

## 文档入口

- [原始开发任务书](Zhaoxi_v1.4.0_Runtime_Observatory_Progressive_Response_Task.md)
- [回复交付、可见性与长任务收口补丁任务书](Zhaoxi_v1.4.0_Progressive_Response_Visibility_Patch_Task.md)
- [开发记录](Zhaoxi_v1.4.0_开发记录.md)

## 验证

- Python 全量回归：775 项通过，1 项跳过。
- Node Web 回归：50 项通过。

同时通过 `python -m compileall -q src/zhaoxi` 与 `git diff --check`。

## 人工验收边界

自动测试不能替代真实模型与桌面 UI 验收。重新启动 Core 后需重点观察：

1. LifeHUD、记忆和权限操作的真实写入结果与最终回复是否一致；
2. 长任务是否只在存在真实进展时产生自然中间回复；
3. 点击发送、请求 dispatch、Final 就绪、浏览器首显与完整展示的端到端时间；
4. 后台维护积压、失败和重启恢复是否在日常长时间运行中保持稳定。
