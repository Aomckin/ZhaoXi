# Zhaoxi v1.4.1 开发记录

> 日期：2026-09-29
> 主题：Fast Dialogue Lane & Standard Tool Short-Circuit

## 交付结果

v1.4.1 已按修订任务书完成代码开发。普通 Owner 桌面 / Web 对话及 Owner QQ 私聊文本先经过本地 Fast Dialogue Gate；安全闲聊进入独立 FAST_CHAT，不再复用 `run_direct()`。明确动作、长期回忆、实时查询、决策和多步请求由本地禁入原因直接升级，只有需要结合上下文判断的承接进入 Cognitive Router。

## 主要实现

- 新增 `FastDialogueGate` 与 `FastDialogueDecision`，覆盖图片、权限、动作、回忆、决策、实时查询、多步请求和显式承接边界。
- 新增独立 `FastChatRuntime`：只注入 Persona、Current Cognition、当前时间、最近 Owner 对话和当前消息；单次调用 `provider.generate(..., tools=None)`。
- FAST 不执行长期 Memory Retrieval、Tool Discovery、Decision、Planner 或 Agent while-loop。
- FAST 输出若承诺真实查询、写入、更新或发送，拒绝该草稿并最多升级一次，不形成 FAST / Agent 循环。
- 明确动作、回忆、查询与计算直接进入 STANDARD；明确多步任务直接进入 DEEP / PLAN；Router 保留给歧义承接和复杂边界。
- STANDARD 业务工具成功后，下一轮强制 `final_only`，清空 Tool Schema 与 Discovery 目录；权限恢复后的成功工具同样直接收口。
- Runtime Observatory 增加 `runtime_lane`、`route_source`、前后台与各 owner 的 LLM 次数、`memory_search_count`、`tool_rounds`、`catalog_inspections`、`fast_gate_reason`、`escalation_reason` 和 `extra_round_reason`。
- Owner QQ 私聊文本复用 FAST_CHAT：命中时跳过 External Cognition Planner 与长期 Memory Retrieval，同时保留 QQ 表达策略和外部频道隐私边界；群聊、第三方、图片和待授权流程不进入该捷径。
- Debug 面板新增持久化“强制使用 FAST_CHAT”选项，仅作用于 Desktop / Web 与 Owner QQ 私聊；强制状态下仍不会覆盖图片、待授权及非 Owner 边界。
- 新增 FAST 上下文条数与字符预算配置，并更新版本号、README、当前状态和环境变量示例。

## 自动验收

专项测试覆盖：

- “小金毛？”、“今天真热啊”、“我刚吃完饭”、“在吗？”等进入 FAST_CHAT。
- Recent Tool 上下文不会把“在吗？”拉回旧任务。
- “刚刚那两条继续”退出 FAST 并进入 Router。
- 动作、Recall、Decision、实时查询与多步请求不会误进 FAST。
- FAST 仅一次无工具模型调用，不携带 Tool Schema。
- FAST 真实动作承诺只升级一次。
- 明确单 Tool 请求跳过 Router，业务 Tool 成功后的 Finalization 不再携带任何 Tool Schema 或目录。
- 权限恢复后成功的 Tool 直接进入 Finalization。
- Owner QQ 普通私聊只做一次无工具模型调用并跳过外部 Planner，Debug 强制选项可覆盖动作类 Gate；第三方与群聊不受强制选项影响。
- Debug FAST 设置可持久化并在 Core 重建后恢复。

验证结果：

```text
Python full suite: 798 passed, 1 skipped
Node frontend suite: 50 passed
Python compileall: passed
git diff --check: passed
```

## 待实机验收

- 使用真实 Provider 验证 10 条普通闲聊与 5 条短社交承接的自然措辞和 P50 / P95 Final Latency。
- 使用真实 LifeHUD 验证 5 条单 Tool 请求均在业务 Tool 后直接 Finalization。
- 重启桌面端检查 Runtime Observatory 的 FAST / STANDARD / DEEP 字段显示与后台维护不阻塞 Final Delivery。
- 使用真实 NapCat 验证 Owner QQ 私聊的自然 FAST 命中、跨频道上下文与 Debug 强制开关；第三方与群聊继续遵守现有 Perception 边界。
