# Zhaoxi v1.4.2 开发记录

日期：2026-09-29 至 2026-09-30。代码版本：1.4.2。

## 范围与依据

本版包含 Current Cognition 2.0、图片输入与历史缩略图修复、Fast Gate 2.0，以及 Fast Chat 单向能力升级。

- [Current Cognition 2.0 / Living Journal 任务书](Zhaoxi_v1.4.2_Current_Cognition_2.0_Living_Journal_Task.md)
- [Fast Gate 2.0 轻量补丁任务书](Zhaoxi_v1.4.2_Fast_Gate_2.0_Lightweight_Patch_Task.md)
- [Fast Gate 与单向能力升级开发记录](Zhaoxi_v1.4.2_Fast_Gate_2.0_开发记录.md)

## Current Cognition 2.0

- 近期认知改为 Overview、带稳定 key 与证据引用的 Threads、Recent Changes、Watch Items；存储不再维护全文 narrative。
- 维护模型只返回结构化操作。运行时做可信 Owner 证据校验、语义 key 合并、数量限制、明确移除、3 天降温和 7 天退出。Changes 最多保留 3 天，Watch Items 最多保留 7 天。
- 本地 gate 跳过玩笑、寒暄和单次情绪等无状态变化消息。维护继续运行在 Final 交付后的持久化后台队列。
- FAST 专用快照默认预算 350 字；按 Overview、Active Threads、Changes、Watch Items、Cooling Threads 排序，Resolved 不进入上下文。小桌边展示自然语言，Debug 提供完整结构、证据、最后维护原因和操作统计。
- 旧 SQLite 状态首次读取时一次性迁移，原始 JSON 写入只读备份表。迁移只保留近期 Overview 与最多 3 条旧主线，不复制旧 attention 或长篇 narrative。旧 STM 仍仅作为不可信 bootstrap 参考。
- Runtime Observatory 增加 gate、triggered、skipped、模型耗时、操作数量及 Thread 增改删指标。

## 图片输入与历史缩略图

### 当前行为

- 图片独立输入直接执行一次无工具视觉调用；带文字或工具的图片请求在收尾阶段保留视觉证据。
- FAST_CHAT 历史保留长边不超过 512 像素的 JPEG 缩略图；视觉追问在短回复较多时补入最近的带图消息，并提示模型区分缩略图、原图与旧文字描述。
- Agent 收尾阶段取消自动清图，历史图片继续由 ContextBuilder 缩略化。是否保留图片不再依赖当前用户措辞；既有跨渠道明确追问取原图的能力保留。

### 排查证据

| 复现 | 根因与处理 |
| --- | --- |
| 首轮图片输入 | Web 已存储并送达图片；工具调用后的收尾误删当前图片。保留当前视觉输入，并为纯图片提供无工具视觉调用。 |
| 2026-09-30 00:03–00:04 的“上一张图” | 发图轮有图，FAST 追问图片数为 0；构造 FAST 历史时清空图片字段。改为输入历史缩略图并补齐带图消息。 |
| 2026-09-30 01:01 的“如龙里的人物” | 首轮有 2 张历史缩略图，工具后变为 0 张；措辞未命中清图豁免规则。取消自动清图。 |

第三次复现的真实事件记录已离线重放：人物图片缩略图在首轮、最终轮均存在（2 → 2）。重放未调用外部模型或修改原始事件库。回归测试覆盖 Web 输入、缩略图尺寸、历史数据不变、新旧图片同轮输入、自然追问及工具前后图片内容一致。

## Fast Gate 与能力升级

Fast Gate 2.0 综合有界近期对话、Current Cognition、能力索引、资源引用、动作与历史需求。FAST_CONFIDENT 跳过 Router，AMBIGUOUS 交给 Router 并允许判回 FAST，HEAVY_CONFIDENT 进入既有标准能力流程。图片和待授权条件禁止 FAST；配置及判定依据可在 Debug 查看。

Fast Chat 在交付前发现真实 Tool / Recall / Decision 需求时，丢弃整段草稿并单向接管到 STANDARD。每轮最多一次，不再调用 Router 或 FAST；未通过检查的草稿、内部标记和工具参数不进入用户回复、会话持久化或记忆整理。QQ 接管继续遵守外部渠道边界。正常闲聊仍为一次无工具前台模型调用。

## 验证结果

截至 2026-09-30，最终代码回归结果：

| 验证 | 结果与边界 |
| --- | --- |
| Python 全量 | 849 项通过、1 项跳过；现有 FastAPI / httpx 弃用提示 1 条。 |
| 前端 Node | 52 项通过，覆盖小桌边安全渲染、Gate 解释与能力升级展示。 |
| Fast Gate 真实模型 | [25 条隔离 Runtime 验收](evidence/fast_gate_v2_real_provider.json)，Gate、路由及调用契约均通过。 |
| 能力升级真实模型 | [Tool / Recall / Decision 三类隔离验收](evidence/fast_escalation_real_provider.json)均通过，每类升级 1 次、Router 0 次、内部标记未泄漏。 |
| 图片链路 | 自动回归与真实事件离线重放通过；修复后桌面真实模型复测待完成。 |

自动回归还覆盖结构化持久化、key 合并、结束退出、降温与淡出、证据拒绝、迁移备份、本地跳过模型及现有外部输入流程。真实模型验收使用本机配置的 `deepseek/deepseek-v4-flash` 和合成数据、临时工具文件，不读写真实个人会话或资料。详细场景与复跑方式见 [补丁开发记录](Zhaoxi_v1.4.2_Fast_Gate_2.0_开发记录.md)。

## 加载与剩余验收

重启 Core / 桌面进程后加载 Python 改动，刷新或重开窗口后加载前端改动。

Current Cognition 任务书要求连续 3–7 天 dogfooding，尚未完成。仍需在真实桌面会话中观察近期认知内容膨胀、过度分析、旧状态退出、FAST 连续性、能力升级自然措辞及历史图片追问。隔离模型验收和图片离线重放分别证明对应链路，不能替代这些持续使用结果。
