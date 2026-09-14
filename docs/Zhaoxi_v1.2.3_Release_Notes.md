# Zhaoxi v1.2.3 开发报告

本版本以 [Semantic Capability Routing 任务书](Zhaoxi_v1.2.3_Semantic_Capability_Routing_Task.md) 为验收依据。开发分支与 Core 运行时版本均为 `v1.2.3`；独立 Life HUD Tool 包版本为 `1.1.1`。

## 实现

- 复用现有 Tool Router，在模型调用前以确定性规则、实时 Capability Manifest、group、aliases 和 intents 做轻量语义匹配，不新增 LLM 调用。
- Life HUD Tool 补充饮食、睡眠、任务、FocusSession、铁幕记录、能量、经验和近期生活状态等自然语言 intents，用户无需知道内部 Tool 名称。
- 饮食等生活事实询问预挂 `lifehud`；带复盘、笔记、报告等对象的行动型查找预挂 `local_search + filesystem_read`；“之前怎么说”类历史表达询问直接路由记忆检索。
- 语义命中只保留当前 enabled 且 available 的组；不可用能力不会伪装成已预挂。
- 未命中时保留 v1.2.2 的 `inspect_tool_catalog` / `request_tool_group` Discovery 兜底与每轮扩展限制。
- Runtime 规则明确要求：依赖真实数据的查询、判断或执行不得仅凭聊天上下文猜测，也不得要求用户说出内部 Tool 名称。

## 防误触发与 Diagnostics

自然生活陈述需要同时满足能力域和查询/行动语气才会预挂 Life HUD；例如“今天铁幕做得累死了”不会仅因出现“铁幕”触发查询。

Tool diagnostics 新增：

- `semantic_route_matched`
- `semantic_route_groups`
- `semantic_route_reason`

诊断只记录能力组与稳定 reason tag，不记录用户原文。

## 验证

- 任务书四类回归已覆盖：饮食查询、昨天的面试复盘、历史表达检索、铁幕普通陈述不误触发。
- 覆盖 disabled Life HUD 不预挂、Manifest intents 可见、diagnostics 不包含用户原文。
- 全量 Python：`549 passed, 1 skipped`；唯一 warning 为既有 Starlette/httpx 弃用提示。
- Node Web：`32 passed`。
- `compileall` 与 `git diff --check` 通过。

## 保留边界

语义路由部分没有新增 LLM Router、没有重构 Manifest 或 Discovery，也没有引入向量分类器。规则只负责“自然语言任务 → 能力域”，业务事实仍必须由实际 Tool 调用取得。下述时间语义修复独立升级了 Memory 时间来源字段。

## 时间上下文语义修复

- 普通 Conversation History 不再把 user/assistant 正文包装为 `[timestamp · role]`；角色继续由结构化 message role 表达，消息 timestamp 只保留为数据库元数据。
- 只有当前用户请求明确涉及日期、时点、时长、先后或跨天推理时才注入独立 `[Temporal Context]`。其中聊天时间标记为 `point` observation，明确禁止由两点推断中间持续清醒、工作、游戏、睡眠或其他 interval/state。
- 时间硬约束区分事件发生、记录与获知：Memory schema v5 新增 `recorded_at`、`known_at`、`source`，保留独立 `event_at`；旧记录的 `created_at` 只迁移为记录/获知时间，不反填事件时间。Proactive Event 对应区分 `event_at/occurred_at`、`recorded_at/known_at/received_at` 与 `source`。
- Memory 检索上下文不再输出含糊的 `time=event_at or created_at`，改为分别输出 `event_at`、`recorded_at`、`known_at` 和 `source`。缺少 `event_at` 时不得用导入或获知时间推断事件时间，也不得推断朝汐当时存在、在场或亲历。
- Memory 聚类、时间相似度与 Consolidation 时间范围也不再回退使用 `created_at`；缺少 `event_at` 时不制造事件区间，时间评分保持中性。
- assistant 输出在 Conversation、AgentResponse、Quick Suggestions、Interface Response 与 Session 保存/读取边界清理精确匹配的内部 ISO timeline header；正文中间的类似文本不受影响。
- Session schema v2 启动迁移会清理历史污染记录；迁移后的迟到污染也会在历史读取时幂等修复并回写。

专项回归覆盖普通历史无时间头、23:00 与次日 14:00 只能作为离散观察、旧日记不产生 Agent presence、`[ISO_TIME · 朝汐]` 不可发送或持久化，以及旧 Session 数据迁移。
