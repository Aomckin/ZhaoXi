# v1.2.6 Short-Term Memory 后端重构

2026-09-23：Working Notes 的逐条便签模型已由独立的滚动短期记忆取代。旧 `.zhaoxi/working-notes.db` 不迁移、不读取为 Context；保留为历史备份。新状态位于 `.zhaoxi/short-term-memory.db`。

## 运行路径

旧会话首次进入 Gateway 时，若 STM 尚未处理消息，Maintainer 用当前最多 40 条会话消息初始化。正常轮次先从持久化状态渲染 `[Short-Term Memory]` 常驻 Context，主回复和工具动作结束、会话落盘后再检查本轮新增消息。后台专用 Prompt 返回 `NO_CHANGE` 或结构化 `add / update / reinforce / fade / remove` Patch；服务校验消息来源和 ID、合并相似内容、限制每类容量，并按近期话题的强化间隔逐步衰减。维护失败只留下日志与诊断状态，主回复照常返回，旧 STM 保留。

Snapshot 从结构化事实生成，不从自由文本全文重写；单次近期兴趣尚未强化时不会进入 Snapshot。长期 Memory 仍按需检索，Agenda 仍表示未来时间事实，原始最近 40 条消息保持不变。没有任何形成内容时显示“近期上下文尚未形成”。

## Debug 与边界

`/api/debug/recent-context` 返回 `short_term_memory.state`、`snapshot`、`updated_at`、`last_processed_message_id`、`last_maintenance`。日志包含 `STM_MAINTAIN_START`、`STM_NO_CHANGE`、`STM_PATCH_APPLIED`、条目强化/衰减/删除及失败事件，不打印整段私有对话。`notes_*` 不再注册给 Agent，也不再从旧 Notes 注入 Context。小桌边现已使用独立的 STM 只读视图；界面变更见 [v1.2.6 交付与验收](Zhaoxi_v1.2.6_Release_Notes.md)。

本次后端重构没有开发长期记忆晋升、提醒或向量检索；Agenda 前端时间线已在后续前端调整中完成。
