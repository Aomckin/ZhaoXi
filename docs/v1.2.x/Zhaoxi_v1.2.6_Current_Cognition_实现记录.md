# Current Cognition 二次重构实现记录

本轮只改后端。`CurrentCognitionState.narrative` 是主数据，`ongoing_threads`、`attention` 和近期主题观察仅辅助维护。新状态单独持久化到 `.zhaoxi/current-cognition.db`；旧 `.zhaoxi/short-term-memory.db` 保留为备份，首次初始化时只作为有噪声的参考，不直接迁移。

每轮完成后，维护器读取未处理的用户/助手消息，要求模型返回 `NO_CHANGE` 或定点 Patch。服务层校验用户证据、容量、旧片段匹配、主题重复次数，并拒绝一次性饮食/消费、路径/数据库/工具细节、精确金额时间及无证据心理解释。失败保留旧叙事，不影响主回复；Debug 记录决定、原因、拒绝原因和前后差异。

正常推理常驻注入 `[Current Cognition]`，仍保留最近 40 条原始消息与按需长期记忆。现有前端不改视觉，`/api/recent-context` 的 `short_term_memory` 字段仅作为兼容映射；`/api/debug/recent-context` 输出新的 `current_cognition` 诊断。旧 STM 代码路径已移除。

自动测试覆盖持久化、突破 40 条窗口、无变化、状态改写、用户纠正、单次小事及噪声拒绝、趋势计数、旧数据库只读引用和维护失败隔离。任务书要求的 30–50 轮真实连续对话验收需要在实际模型与日常使用环境中另行执行，不能由单元测试代替。
