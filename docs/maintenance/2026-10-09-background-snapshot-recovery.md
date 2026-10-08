# 2026-10-09 后台摘要预算与失败队列修复

对应 [近一周失败日志审计](2026-10-08-weekly-failure-log-audit.md) 的 **B01 / B02**：后台摘要认知固定使用 6,000 Token，同时携带完整对话上下文；异常返回 0 被活动适配器解释成 NO_CHANGE，最旧摘要长期反复失败，后续摘要无法推进。

现在摘要认知使用专用预算与精简输入；失败会如实进入活动失败状态，并按每条摘要的持久化重试状态调度。默认失败三次后隔离，后面的到期摘要可以继续处理。

## 预算与输入

- `ActivitySpec.max_total_tokens` 定义活动自己的 Token 上限。摘要认知默认 **12,000**；其他现有活动继续使用原来的 6,000。日模型次数、每 Tick 次数等调度限制仍然有效。
- Ambient Planner 只接收自身规则、当前群聊摘要、来源 / 群会话、时间范围、消息数量及 snapshot 引用，不再调用完整对话 ContextBuilder。摘要发送最多 1,200 字符，超长输入带 `summary_truncated` 标记；数据库里的原摘要不修改。
- Ambient 模型输出设为 `max_tokens=1024`，另预留 `reasoning_budget_tokens=2048`，请求关闭 thinking。现有兼容网关可能仍产生推理，预算仍以实际 usage 记账，超过硬额度仍报失败。
- 这些选项只用于 Ambient Snapshot，不改变直接 QQ 消息的 Planner 输入 / 参数，也不赋予摘要工具执行、外部发言或 Owner 私有记忆写入权限。

新配置在 `.env.example` 中说明：

```dotenv
ZHAOXI_PERCEPTION_COGNITION_MAX_TOTAL_TOKENS=12000
ZHAOXI_PERCEPTION_COGNITION_MAX_ATTEMPTS=3
ZHAOXI_PERCEPTION_COGNITION_RETRY_SECONDS=300
```

预算包括输入和输出，不是仅输出预算。默认重试间隔为第一次失败后 5 分钟、第二次失败后 10 分钟；实际执行还受活动启用状态、Presence、正常调度间隔和每日 / Tick 配额约束。

## 失败队列语义

`snapshot_cognition` 兼容增加三列：`attempt_count`、`next_retry_at`、`last_error`。已有记录默认尝试数 0，保留 PENDING / PROCESSED 状态；迁移可以重复执行。

| 结果 | 摘要状态 | 活动状态 | 后续行为 |
| --- | --- | --- | --- |
| 没有到期摘要 | 不修改 | NO_CHANGE | 不调用模型 |
| 摘要处理成功 | PROCESSED | UPDATE | 结束该项 |
| 第一次 / 第二次失败 | PENDING，记录下次重试时间 | FAILED | 到期前跳过该项，继续选择其他到期项 |
| 第三次失败 | FAILED，隔离 | FAILED | 停止自动重试该项，保留摘要与失败信息 |
| 前台打断 / 取消 | 保留原状态 | 按原抢占规则处理 | 不增加摘要失败次数 |

- `process_pending_snapshot()` 记录安全错误码 / 异常类型后重新抛出，避免错误被映射成 NO_CHANGE。失败日志增加 snapshot ID、次数、状态和下次重试时间，不记录摘要正文。
- 选择时过滤尚未到重试时间及已隔离项；活动整体不再对摘要队列做指数失败退避，每条摘要自行退避，正常活动间隔继续生效。
- 同一 PerceptionRuntime 使用摘要处理锁，避免并发调用重复处理同一项。
- 全部失败项隔离后清除该活动不可执行的待处理标记，同时保留失败次数和失败收据，避免维护债继续挡住其他活动。
- 运行诊断按数据库汇总返回 PENDING / PROCESSED / FAILED 数量，PENDING 数量包含退避中的项，不再受读取 100 条或仅到期项的限制。
- 原摘要、引用不因失败而删除；原有 TTL / 证据保留清理政策仍然适用。修正原因后，内部接口 `set_snapshot_cognition(id, "PENDING")` 可以显式重新入队并清空重试状态；本轮没有增加自动循环重置或新的 UI 按钮。

## 验证

最终相关回归 **153 项通过，0 失败、0 错误、0 跳过**，包括 11 项新增摘要恢复用例：

- 旧 schema 迁移及重复初始化；重试状态跨重启保留。
- 失败队首跳过、5 / 10 分钟退避、第三次隔离及显式重入队。
- 实际 ResilientProvider usage 记账接受超过旧 6,000、低于新 12,000 的返回；超过新预算仍失败。
- 无完整私有对话上下文；发送摘要受限，数据库原文保留。
- 异常上报 FAILED、失败后后续项成功、Debug 强制运行不能绕过单项退避。
- 超时 / 无效协议失败传播；取消不消耗尝试；并发不重复处理。
- 全部隔离后清除不可运行维护债，同时保留失败收据和状态。

覆盖范围为 `tests/perception`、`tests/internal_activity`、感知 Inspector、模型预算集成及预算策略。另通过 Python AST、证据 JSON 与文档链接校验、`git diff --check`。有一条现有 Starlette/httpx 弃用警告，不影响通过。

实际生产数据库以 SQLite `mode=ro` 读取并备份到 `.pytest_cache/background-repair/`，**迁移只应用于副本**。副本迁移前后均为 **PENDING 281 / PROCESSED 144**，摘要 payload SHA-256 完全一致。按这 281 条构造出的精简请求最大 **3,508 字节**，队首请求为 **2,094 字节**；这是消息与部分参数的 JSON UTF-8 大小，不是模型 Token 数，实际 HTTP 包还会包含模型名和少量参数。

[完整验证证据](evidence/2026-10-09-background-snapshot-recovery.json) 保存用例结果、配置默认值、源码哈希及副本迁移检查。

## 加载与验收边界

需要完整退出托盘中的 Core 并正常重启，加载代码和新配置；生产表迁移会在正常启动时自动执行。已有积压摘要会在满足调度条件时按队列推进，不会在本次代码修改时直接批量处理。

本轮未重启实际 Core、未调用真实模型，也未迁移实际生产数据库。因此目前确认的是代码行为、隔离回归与数据库副本兼容，尚未确认线上积压清空或真实服务失败率下降。审计中的 B03 空内容计数、B04 指标误报及其他待查问题不在本轮修复范围。

后续：B03 / B04 修复及 434 项扩展回归见 [空内容计数与失败指标记录](2026-10-09-cognition-count-and-result-metrics.md)。扩展回归补回了精简摘要中的 SocialTrace 标签，输入边界与队列策略保持不变；本记录的源码哈希和请求字节数对应最初验收快照。
