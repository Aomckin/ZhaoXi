# 朝汐代码现状

更新：2026-10-09。源码版本仍为 v1.4.7，包含结构维护、运行修复与调试设置，没有版本升级。

当前架构以 [架构说明](ARCHITECTURE.md) 为入口；测试范围、隔离约束与统一命令见 [测试指南](../guides/testing.md)。结构维护见 [原维护记录](../maintenance/2026-10-04-architecture-and-tests.md)，最新修复与逐项证据见 [运行维护总览](../maintenance/2026-10-06-runtime-repair-summary.md)。

- `bootstrap/` 负责装配；`ZhaoxiAgent.runtime` 用有类型的字段持有共享服务，旧 `agent.<service>` 访问转发到同一值。
- Web 请求模型、生命周期、设置、感知、表情、记忆 API 已分模块；聊天、会话、诊断及鉴权仍在 `web/app.py`。
- Experience 与模型设置使用显式 Settings 路径，装配和备份共用配置。
- pytest 默认状态重定向到临时目录；Core、Tool Python、前端 Node 和 Career Node 测试通过 `scripts/test.py` 统一运行。

- 多轮调试开启后模型/工具上限分别取总步数/总步数减一，最后一步保留给回复。FAST 升级默认复用完整 STANDARD 额度；未执行/部分完成状态、明确重试上下文和工具后回复恢复按真实执行结果处理。
- 主回复协议拒绝裸 operation/name + arguments 工具封套，进入仅补回复或真实工具结果兜底，避免参数泄露和误执行；见 [维护记录](../maintenance/2026-10-06-tool-arguments-reply.md)。
- 正文后追加重复 reply/awareness 协议时只交付一次正文，冲突或不完整混合协议拒绝；见 [维护记录](../maintenance/2026-10-06-mixed-reply-protocol.md)。
- 请求主回复契约时拒绝缺失 awareness、未知顶层字段与残缺封套；长度耗尽也不作为完整正文交付，保留既有有界回复恢复；见 [维护记录](../maintenance/2026-10-06-incomplete-reply-envelope.md)。
- QQ 群聊 @ 的 Planner 超时可进入受来源权限约束的回复兜底；本地重生成定位最后一条普通回复，失败输入也保留；见 [QQ 修复](../maintenance/2026-10-07-qq-debug-planner-reply.md) 和 [重生成修复](../maintenance/2026-10-07-retry-ghost-delivery.md)。
- 启动先完成 SQLite 正常初始化与事务恢复再检查健康；HTTP/SSE 连接和 Core 就绪状态分开显示。
- 原生工具结果批次在 Provider 出站时保持连续；群图观察保留来源，失败提醒只追加一次。
- 当前模型图片受最长边 1600 / 每张 512 KiB 约束；正式附件与 LifeHUD 原图不变。历史图片继续发送 512 像素缩略图，没有此次新增的数量上限。
- LifeHUD 可用当前上下文提供的明确历史图片引用关联同会话 Owner 原图，确认快照保留引用，当前图片占位符含义不变；见 [修复记录](../maintenance/2026-10-08-lifehud-history-images.md)。
- 纯图片输入不再补写查看图片占位句；旧本地记录加载时兼容清理，主动消息附带近期历史缩略图和来源，重载后保持无文字图片显示；见 [修复记录](../maintenance/2026-10-08-image-only-and-proactive-vision.md)。
- Token / Planner 预算控件仅位于 Web Dashboard，Desktop 侧边栏保留其他常用调试功能；预算覆盖持久化、下一次请求生效，Planner 最多批准一次追加。
- 后台摘要使用默认 12,000 Token 的专用预算与精简摘要输入；单项失败持久化退避，默认第三次失败隔离并允许后续项推进；见 [预算与队列记录](../maintenance/2026-10-09-background-snapshot-recovery.md)。
- 文本认知计数跳过空内容事件；整体失败与已完成操作分别记录，Gateway 与指标采用同一结果推导；见 [计数与指标记录](../maintenance/2026-10-09-cognition-count-and-result-metrics.md)。

[近一周日志审计](../maintenance/2026-10-08-weekly-failure-log-audit.md) 中 B01—B04 已完成代码修复，B03 / B04 扩展相关回归 434 项通过，提交前隔离副本相关回归 580 项及 Node 2 项通过；其余待查项保留原状态。各专项测试范围重叠，不相加作为全量测试数。

本轮未重启正式实例、运行真实模型业务或发布。安装、启动方式见根 README；真实使用验收边界继续以对应版本记录为准。

此前混合了多个版本状态、架构描述及不同年代测试数字的交接文档已完整保存在 [2026-10-04 历史快照](../old/CODEBASE_STATUS_2026-10-04.md)。该快照保留历史事实，不作为当前测试基线。
