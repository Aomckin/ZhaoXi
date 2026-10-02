# Zhaoxi v1.4.4 · Presence 2.0

版本：**1.4.4**。开发与整理日期：2026-10-02。任务书 Phase 1–7 的代码已实现，Phase 8 的真实环境 5–7 天 dogfooding 待完成。

## 版本变更

- 既有内部活动 Runtime 升级为 Registry：正式活动类型、成本、Presence 过滤、疲劳、独立 tick 预算与每日限额。
- Presence 支持 ACTIVE / SEMI_ACTIVE / IDLE / AWAY / SLEEP，前台消息抢占可取消的后台活动；空闲允许 NO_ACTIVITY。
- FAST 闲聊在后台按独立游标消化弱趋势；新增 Cognition、Memory 和 Cluster Gardening。
- 低频翻旧记忆，保存重温记录并保持 activation 与 Recall 统计。
- 可选 Social Lurk / Wander：QQ 群白名单、独立 Public Social Context、Privacy Gate、SELF 身份、冷却及每日限额。
- 小桌边显示自然活动文字，Debug 提供活动日志、候选、预算、游标与社交 trace，手动社交发言需要再次确认。

## 自动验收

开发验收时 Python 全量 **1035 通过、1 跳过**（系统不支持创建符号链接），Node **64 通过**；编译与差异检查通过。1.4.4 wheel 构建通过，247 个 Python 源文件完成一致性核验。测试使用临时数据与合成服务，详见 [验收汇总](evidence/presence_v144_acceptance.json)。

## 启用与剩余验收

无需离线记忆迁移。新配置在 [.env.example](../../.env.example)，沿用 ZHAOXI_ 前缀。Social Lurk / Wander 和自动 Sleep 时段默认关闭；社交需要明确群白名单和已启用的 QQ 插件。Social 仅读取现有 Perception 当前授权群缓存，缺失的群历史不会主动回查。

加载新代码需重启 Core 并刷新前端；本次未重启已有桌面实例、修改生产记忆或发送真实 QQ 测试消息。桌面视觉、授权 QQ 群实测及持续使用效果仍待验收。本版整理为本地版本提交，未推送或外部发布。

## 版本文档

- [开发任务书](Zhaoxi_v1.4.4_Presence_2.0_A_Life_Between_Conversations_Task.md)
- [开发记录与验收边界](Zhaoxi_v1.4.4_开发记录.md)
- [逐项任务书核对](Zhaoxi_v1.4.4_任务书核对.md)

## 群聊历史回查增量

补齐按群号、时间和字面关键词搜索已保存原消息，并只读衔接现存 Perception 旧消息与旧摘要。此前 590 条旧消息及 66 条旧摘要已完成只读回查核验；权限和保留期限沿用既有规则。补丁范围、测试与模型调用示例见 [补丁记录](Zhaoxi_v1.4.4_群聊历史搜索_补丁记录.md)。
