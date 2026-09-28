# Zhaoxi v1.3.2 开发记录

2026-09-27：按《Unified Cognitive Timeline 开发任务书》接入统一事件流。本记录按开发时间保留阶段结论；截至 2026-09-28，群聊首答与防循环已实测，最终收口任务书 A–E 尚未全部实机验收。

## 已实现

- 新增 `cognitive_stream` 一级领域：`CognitiveEvent`、`EventPart`、`ExperienceStream`、`CognitiveIngress`、`AttentionRetriever` 和 `SessionProjector`。事件保留来源、信任级别、隐私级别、父引用与原始引用。
- `.zhaoxi/experience.db` 持久化全局事件，按来源引用去重，按发生与接收时间稳定排序；维护游标按实际写入顺序读取。支持按 Session、频道、发言者、时间与引用查询，并按来源设置 Raw Event TTL。数据库进入备份清单。
- Desktop / CLI / Web 的用户输入和回复，QQ Direct / Ambient 输入、群聊 Snapshot、QQ 回复，Tool Action / Observation、Planner / Workflow 高层结果、QQ 连接状态变化和已投递的 Proactive 消息进入同一条 Stream。旧 Conversation、QQ Session 与 Interaction Ledger 暂时双写，Runtime Self State 继续独立保存。
- Desktop 的 ContextBuilder、Router、Planner 和 Decision，QQ 的 Planner / Reply 上下文以及 Proactive 判断都可读取有界 Attention Context。检索保留频道和发言人标签，并限制条数、字符数、时间范围和每来源配额。QQ Owner 可召回 Desktop 对话；本地 Tool / Workflow 等私有内容不注入 QQ。群聊不能读取 Owner 私有事件。
- Current Cognition 后台与对话后维护改读 Stream 中可信 Owner 事件。QQ Owner 的维护与长期记忆整理通过同一事件源与 Desktop 共用实现；第三方消息不能升级为 Owner 事实。旧 QQ Planner 的候选写入在新运行时停止，旧接口保留兼容。
- 新增维护抽屉中的 Cognitive Stream Debug 与对应 API：统计、最近事件与过滤、Attention 结果、Session 投影、待维护 Owner 事件和写入错误。

## 验证与待验收

- 自动测试包括全局顺序、去重、跨频道召回、QQ 隐私边界、第三方认知隔离与 TTL；完整 pytest 套件通过。
- QQ / NapCat 的 Desktop → QQ → Desktop、QQ → Desktop Planner、第三方群聊和跨频道 Tool 场景仍需在真实连接下人工冒烟。本次开发没有自动完成这些实机验收项。
- 当前保留 External Planner 与旧 Session 作为迁移兼容层；完整移除旧认知读取、Episode 自动整理和独立时间轴 UI 均不在本轮范围。

## 2026-09-27 跨频道同步回归修复

实机记录显示事件已双向写入 `experience.db`：QQ Owner 发言与回复、Desktop Owner 发言与回复均在同一时间线。实际回复仍否认跨频道内容。复盘定位到 Attention 渲染先按时间正序拼接，再从开头截断字符，导致最新 Desktop 回复被截掉；无关群摘要占用了上下文预算。QQ 的隐私提示也过于笼统，模型把已核验 Owner 的普通 Desktop 对话误当不可引用的本地资料。Desktop 一侧还曾转去查书库，忽略了已有的 QQ 原事件。

现改为先为最新事件保留预算、完整保留事件边界，按明确提到的频道提高相关事件权重，并在非群聊问题中排除无关 SocialSnapshot。已核验 Owner QQ 私聊明确允许引用 Desktop/QQ 普通对话，仍不开放本地工具、日程、长期记忆与文件。Router 和回复上下文明确要求对近期跨频道问答优先使用原事件，不因书库未收录而否认它。

使用当晚真实事件顺序在本地重放，修复后的 2000 字符 QQ Attention 包含最新 Desktop 原话；新增运行时测试验证该原话进入 QQ 模型输入。完整 pytest 套件通过。当前运行的 Core 在补丁前启动，需要重启后再进行真实 QQ 收发验证。

## 2026-09-28 最终收口任务书代码进展

- 当前输入作为独立 Current Trigger 进入模型，Recent Timeline 不再重复收录当前事件。Desktop、QQ Direct、Planner 与回复通过请求级 `CognitiveTurnContext` 传递触发事件、输出目标、隐私受众、表达策略和图片；移除了共享 `current_trigger_event` / `builder.trigger_event`。QQ 的临时对话视图使用 ContextVar，避免覆盖 Desktop Conversation。
- `CognitiveEvent` 增加 `turn_id`、`reply_to_event_id`、`caused_by_event_id`，SQLite 提供索引和按回合查询。近期时间线按因果回合组织，普通群聊 Raw 按十分钟窗口压为 L1；Attention 只补近期窗口外的事件，多条较早群聊可压为 L2 Episode。L1/L2 保留原事件、父引用和原始引用，可经 `resolve_timeline_unit` 回查。
- Owner 近期图片的已解析原图引用写入 Raw Event；跨频道视觉追问可从近期事件重新送图，原图缺失时上下文明确限制为已有文字描述。最终回复过滤内部来源标签。新增 Current/Recent/Recall 渲染、活动请求、回合与 Unit 回查诊断接口。
- 自动回归覆盖当前锚点、交错问答、并发作用域、群聊 99 条压缩、Raw 图片跨频道复用及原有 QQ 多模态和分段场景。相关测试集已通过。
- 当时运行中的 Core 尚未加载新代码，13:20 左右的 `.zhaoxi/logs/zhaoxi.log` 曾连续记录 `QQ connection failed type=ConnectionRefusedError`。随后 NapCat 恢复连接，桌面程序已完整重启，并完成下述群聊防循环实测；任务书 A–E 的跨频道完整黑盒验收仍待执行。自动测试与单个群聊场景不代替该验收。

## 2026-09-28 非 Owner 外部回复防循环

外部事件继续写入 ExperienceStream。非 Owner 消息仅在私聊或明确指向朝汐、且包含具体求答意图（或图片）时取得首次回复资格；首次合格消息直接进入统一回复链。发出一次非 Owner 回复后，同一 actor 五分钟内、同一会话四十五秒内的后续外部消息不再触发回复。已知 bot 在 Owner 再次发言前，同一会话最多获得一次回复（回看上限 24 小时）。普通寒暄和非定向群消息不回复。最后一次守卫判定可在 Perception Debug 中查看。

## 2026-09-28 夏苟群实机反馈与首答调整

在群 `1043364342`，已核验朝汐、夏苟、Owner 三个成员，并由夏苟发一条定向测试问题。旧规则让 External Planner 返回 `reply=false`，朝汐没有发送群回复。依据 Owner 补充要求，现改为非 Owner 的**首次明确求答消息直接进入统一回复链**；正式发送后，同 actor 五分钟、同会话四十五秒内拦截快速互答。可配置 `ZHAOXI_QQ_EXTERNAL_BOT_USER_IDS`；本机将夏苟账号列入已知 bot，该 bot 在 Owner 再次发言前最多获得一次回复（回看上限 24 小时）。普通寒暄、通知和非定向群消息仍不回复。

完整重启桌面程序后，14:11:49 夏苟在该群 `@朝汐` 询问 `3+5`；朝汐于 14:12:06 发出回复，ExperienceStream 记录 `ASSISTANT_REPLY dc98fc707d394b57a0d83fdc866d0f01`，其 `reply_to_event_id` 指向该输入事件。群历史可见这次回复实际分成三条消息。14:12:28 夏苟立即追问 `5+6`；PerceptionStore 将其标为 `PROCESSED`，ExperienceStream 收录原始事件。至 14:14:11，群历史和 ExperienceStream 均没有该追问的后续回复，证实本轮实机防循环拦截。仅“重启 Core”仍沿用旧 Python 模块，需完整重启桌面程序加载修改。

## 当前验收边界

- 已验证：自动回归；真实 NapCat 群中的首答、追问拦截、原始输入与回复入流及回复因果关联。
- 待验证：最终收口任务书 A–E 的 Desktop ↔ QQ 连续近期经历、并发回复对齐、旧事件召回与图片回查等完整黑盒场景。当前版本号为 `1.3.2`，但尚不据此宣布正式收口。
