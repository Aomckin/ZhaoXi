# Zhaoxi v1.2.6 开发与验收报告

## 交付结果

v1.2.6 增加两层独立、持久化的近期 Context：

- Agenda 支持 Event、Window、Deadline、Focus/Mainline、Expectation，提供 planned/active/done/missed/cancelled/rescheduled 生命周期。
- Zhaoxi Working Notes 支持 Working、TODO、Question、Decision、Hypothesis、Temp，并保留 user/assistant/system/tool 来源及 confirmed/working/tentative 可信度。
- 两个模块使用独立 SQLite 数据库，跨程序重启与会话继续存在，不写入或自动晋升长期 Memory。
- ContextBuilder 每轮直接注入短 Snapshot；模块关闭或读取失败时，普通对话继续运行。
- 新增 12 个 Tool，覆盖任务书要求的新增、修改、完成/解决、取消/删除、查询和 Snapshot。
- `/api/debug/recent-context` 可查看结构化数据、最终 Snapshot，并可在运行时独立启停两个 Context 模块。
- Agenda 与 Working Notes 数据已纳入现有备份和健康检查。

## 安全与边界

- assistant 写入的 confirmed 会被降为 working；assistant hypothesis 强制为 tentative，避免模型推测自我强化成用户事实。
- 过期 Event/Window/Deadline 会转为 missed，不再出现在 Upcoming。
- 相同标题的活动 Agenda、同 Topic 或高度相似的活动 Note 优先更新；Working Notes 按类型执行容量淘汰。
- 本版本没有加入日历 UI、提醒、主动通知、复杂自然时间解析、Decision System、重复日程或 Notes → Memory 自动晋升。

## 配置与调试

`.env.example` 新增 Agenda/Working Notes 的数据库路径、Context 开关和条目上限。运行时调试接口的开关只影响 Context 注入，不删除数据。

## 验收

新增自动化覆盖五类 Agenda 持久化、状态变化、过期排除、Snapshot；Working Notes CRUD、过期、容量、防重与来源可信度；Context 常驻注入、独立关闭和故障降级。

- Python：631 passed、1 skipped。
- Node 单元测试：35 passed。
- Desktop Shell：20 次模式往返及四档尺寸验收通过。
- Phase 3 浏览器验收：8 档尺寸、通知/可见性、头像与 Debug 等场景通过。
- Core 1.2.6 与 LifeHUD Tool 1.1.1 wheel 构建、版本/内容/哈希校验通过。

真实模型对自然语言时间的参数转换、桌面 UI 长时体验与跨自然日人工场景仍需实机验收；自动化测试不替代这些体验验证。

## 2026-09-22 Tool Transcript 稳定性补丁

日志审计确认，能力发现连续调用 `inspect_tool_catalog`、`request_tool_group` 后，文本协议生成的控制调用曾被错误重放成正式 `assistant.tool_calls → tool` transcript。CommandCode/DeepSeek 在下一请求以 HTTP 400 拒绝该消息序列，导致真正的 `agenda_add` 尚未执行就中断。

控制工具现在只把有界结果写入本轮内部 system context，不再进入 provider 工具回执。原生业务工具继续使用标准 tool transcript；由 DSML/Qwen 等文本协议归一化出的业务调用，则以明确标注的内部调用/结果消息安全回放，不再伪造原生 `tool_calls`。新增端到端测试覆盖“检查目录 → 加载 Agenda → 执行 agenda_add → 最终回复”，并验证控制阶段和文本业务调用都不会产生孤立的 tool 消息。
