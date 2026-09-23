# Zhaoxi v1.2.6 交付与验收

> 2026-09-24 更新。初版 [Agenda + Working Notes 任务书](Zhaoxi_v1.2.6_Agenda_Working_Notes.md) 保留为历史需求；实际运行时的近期状态层已从逐条便签改为滚动 Short-Term Memory。后端过程见 [STM 重构说明](Zhaoxi_v1.2.6_Short_Term_Memory_Backend.md)，前端依据 [调整任务书](Zhaoxi_v1.2.6_前端调整任务书.md) 完成。

## 当前交付

- Agenda 独立持久化，支持 Event、Window、Deadline、Focus、Expectation 及计划、进行中、完成、错过等状态；Agenda Tool 仍负责日程增改和查询。它表达未来时间事实，不充当提醒或自动计划系统。
- Short-Term Memory 使用独立 SQLite 滚动状态。主回复完成并保存会话后，Maintainer 检查新消息，返回 `NO_CHANGE` 或结构化 Patch；支持更新、强化、衰减和删除。维护失败不阻断主回复。旧 Working Notes 数据不自动迁移，也不再注入 Context；`notes_*` Tool 已撤出运行时。
- ContextBuilder 每轮直接注入 Agenda 与 STM Snapshot，最近约 40 条原始消息仍保留，长期 Memory 仍按需检索。`/api/debug/recent-context` 可查看 STM 结构化状态、Snapshot、最后处理消息与最近维护结果；只有 Agenda 保留手动 Context 开关。
- 小桌边以日期分组时间线展示 Agenda：五类节点、今日主线、当前时间位置、过去事项弱化，备注默认折叠。STM 是单张近期状态纸页，只展示 Overview 和非空分区。两块读取相互独立，首次空状态与读取失败分别提示；整个桌边统一滚动。
- 桌边入口位于右上方；桌面模式下避开 36px 自绘窗口栏。相同开始时间且标题规范化后完全相同的 Event 与 Window 共用一个视觉节点，关联记录仍可展开查看；不删除数据库记录，也不合并匹配不确定的事项。

## 边界与兼容

旧 `.zhaoxi/working-notes.db` 可保留为历史备份，不作为新 STM 的来源；新状态默认在 `.zhaoxi/short-term-memory.db`。没有长期记忆自动晋升、向量检索、主动提醒、复杂日历 UI 或自动计划生成。旧任务书和旧验收数字是历史切片，不代表当前行为。

同版本 Tool Transcript 稳定性补丁：能力目录检查和钥匙组加载的文本协议控制调用不再伪造成正式 `assistant.tool_calls → tool` 回执；业务 Tool 的标准回执保持不变。此前该错误曾让 Provider 以 HTTP 400 拒绝后续请求，实际 `agenda_add` 尚未执行。回归测试覆盖连续能力发现后调用 Agenda 的路径。

## 验证

- Python 全量测试：654 项收集，653 通过、1 跳过。
- Node 前端单元测试：41 项通过。
- 隔离 Edge 布局检查：桌面与窄屏下确认桌边入口避开窗口栏、时间线和 STM 渲染、折叠详情样式及侧边栏边界。
- `git diff --check` 与 Python `compileall` 在提交前复核。

真实模型的自然语言时间解析、跨自然日状态变化和长期桌面使用体验仍需实机观察；自动化检查不等同于这些人工验收。
