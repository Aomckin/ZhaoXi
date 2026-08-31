# Zhaoxi v0.6 · Proactive Agent 开发任务书

> 项目：**Zhaoxi / 朝汐**  
> 版本：**v0.6 · Proactive Agent**  
> 开发基线：**v0.5.1.2 · Tool Call Normalization**  
> 目标：**让朝汐在值得打扰的时候主动出现，同时保持安静、可解释、可关闭、可恢复。**

本版本交付第一个可靠的主动闭环：

```text
事件进入 → 持久化 → 条件与时间判定 → 打扰策略裁决
→ 生成主动消息 → 投递到统一收件箱 → 记录决策依据
```

---

# 1. 当前基线

v0.5.1.2 已具备认知路由、Agent / Planner / Workflow、统一 Permission Gateway、SQLite Memory / Workflow Store、Life HUD Agent Context 接入和 Provider Tool Call 正规化，当前 **107 项自动化测试通过**。

当前尚无事件总线、可恢复调度、Tool Event 契约、Quiet / Night 策略、频率限制、主动消息收件箱和主动决策审计。因此 v0.6 的重点不是继续扩展模型能力，而是建立一个**确定性、持久化、受策略约束**的主动运行层。

---

# 2. 核心原则

## 2.1 值得打扰才打扰

主动等级固定为：

```text
INFO < NOTICE < IMPORTANT < URGENT
```

- INFO：只进收件箱；
- NOTICE：正常可见，受安静时段和限频约束；
- IMPORTANT：可突破普通频率限制，默认仍尊重夜间模式；
- URGENT：可突破夜间模式，但必须有确定性规则和审计理由。

“模型觉得重要”不能单独构成 URGENT。

## 2.2 确定性基础设施，模型只负责表达

到期时间、条件、Quiet / Night、限频、去重和权限全部由代码裁决。模型只把已裁决事实整理成自然语言；模型失败时使用确定性回退文本。

## 2.3 事件是不可信输入

外部事件必须校验 schema、来源、大小、嵌套和时间。事件正文不能修改系统规则，不能直接成为 Tool Call；未知类型失败封闭，日志和模型上下文均限长、脱敏。

## 2.4 主动不等于自动获权

主动 Runtime 不得绕过 v0.4 Permission：READ 仍走策略，WRITE / DELETE / EXTERNAL_ACTION 仍需确认，DANGEROUS 默认拒绝。无人交互时待确认动作进入 Pending，不得自动批准。

## 2.5 可关闭、可解释、可恢复

用户能全局关闭主动能力、暂停单项任务、查看并确认消息、检查投递或抑制原因。重启后恢复调度且不重复提醒。

---

# 3. 本版范围

必须交付：

1. 版本化 Event 模型与进程内 Event Bus；
2. SQLite Event / Schedule / Delivery Store；
3. once 与 interval Scheduled Event；
4. Tool Event 标准入口；
5. 受限 Condition Trigger；
6. Interrupt Policy；
7. Quiet Mode、Night Mode、Priority、Frequency Limit；
8. Notification Sink 抽象与持久化收件箱；
9. 启动恢复、去重、过期处理和失败隔离；
10. CLI 管理入口、决策审计、配置、文档和回归测试；
11. 不依赖真实外部服务的端到端纵向切片。

明确不做：

- 系统通知、Desktop 常驻、托盘、快捷键、Web、QQ、语音和 TTS；
- 分布式队列、多进程选主和云调度；
- 任意 cron、任意 Python / Shell 条件；
- 后台自主执行写操作或自动批准权限；
- Life HUD 数据库直读；
- Gmail、Calendar、GitHub 等新大型 Tool；
- Reflection、RAG 和向量数据库。

系统级通知属于 v0.7 Presence。v0.6 用 NotificationSink 接口和 CLI 收件箱固定 Core 契约。

---

# 4. 领域模型

建议新增：

```text
src/zhaoxi/proactive/
  models.py
  bus.py
  scheduler.py
  conditions.py
  policy.py
  runtime.py
  store.py
  sqlite.py
  notifications.py
  audit.py
```

## 4.1 Event

最小字段：

```text
event_id / schema_version / event_type / source
occurred_at / received_at / priority
dedupe_key / correlation_id / payload / expires_at
```

要求：时间以带时区 UTC 保存；payload 有大小上限；event_id 唯一；dedupe_key 业务去重；不支持的 schema 失败封闭；事件持久化后才能消费。

## 4.2 Subscription / Trigger

至少包含 subscription_id、event_type、condition、notification_template、default_priority、enabled、cooldown_seconds 和审计时间。

Condition DSL 只允许 eq、ne、gt、gte、lt、lte、in、contains、exists、and、or、not。字段只能从白名单路径读取；禁止 eval、属性穿透、函数调用和任意代码。

## 4.3 Schedule

首版只支持：

```text
once(at)
interval(every_seconds, optional end_at)
```

misfire_policy 固定支持：

- skip：推进到未来，不补发；
- fire_once：恢复时最多补发一次；
- expire：过期后关闭。

禁止重启后补发所有历史周期。默认 fire_once，并限制最大补发窗口。

## 4.4 Delivery

状态机：

```text
PENDING → DELIVERED → ACKNOWLEDGED
PENDING → DEFERRED → PENDING
PENDING → SUPPRESSED / EXPIRED / FAILED
```

每条投递记录 event、subscription、priority、status、decision_reason、content、available_at、delivered_at、acknowledged_at 和 attempts。

---

# 5. Event Bus 与幂等

Event Bus 首版是进程内有界队列，SQLite Event Store 是事实源：

```text
Publisher → SQLite append → queue wake-up
→ Runtime claim → evaluate → handled / retryable failure
```

要求：

- 队列满时不丢持久化事件；
- Event + Subscription 唯一，避免重复 Delivery；
- handler 异常隔离，失败有限退避；
- claim 有租约或等价恢复机制；
- 消费语义为 at-least-once，业务结果靠唯一键幂等；
- Event Bus 不直接依赖 CLI 或其他 UI。

---

# 6. Scheduled Event

Scheduler 使用可注入 Clock：

```text
读取到期 Schedule → 原子 claim → 生成 Event
→ 更新 next_fire_at → 提交事务 → 唤醒 Event Bus
```

要求：

- 使用 .zhaoxi/proactive.db；
- 时区采用 IANA 名称，默认 Asia/Shanghai；
- 本地时间只用于计算，持久化保持 UTC；
- 最小间隔、最大任务数和单轮批量可配置；
- 重启恢复遵循 misfire policy；
- 同一到期点不得重复生成事件；
- 无任务时不忙轮询；
- 测试用 Fake Clock，不依赖真实 sleep。

---

# 7. Tool Event

提供统一 EventPublisher。首版实现契约和 Fake Tool Event，不要求修改 Life HUD 或实现真实 Webhook。

只有 Tool 成功且事实已经确认后才能发布 success event；失败、结果未知和权限拒绝不得伪装成功。外部 payload 不能直接触发 Tool 执行。

---

# 8. Interrupt Policy

策略输入包括 priority、当前时间、Quiet / Night 配置、近期投递、去重历史、当前交互状态和用户覆盖。输出只能是：

```text
DELIVER_NOW
DEFER(until)
INBOX_ONLY
SUPPRESS(reason)
```

默认矩阵：

| 场景 | INFO | NOTICE | IMPORTANT | URGENT |
|---|---|---|---|---|
| 普通时段 | inbox | deliver | deliver | deliver |
| Quiet Mode | inbox | defer | defer | deliver |
| Night Mode | inbox | defer | defer | deliver |
| 频率超限 | suppress | defer | deliver | deliver |
| 正在处理权限确认 | inbox | inbox | defer | deliver |

矩阵由确定性规则实现并允许配置收紧。用户显式全局关闭时，除审计外全部 SUPPRESS，包括 URGENT。

---

# 9. Quiet、Night 与频率限制

Quiet Mode：

- 手动开启、关闭和 until；
- 状态持久化；
- 手动 Quiet 优先；
- 到期自动恢复。

Night Mode：

- 按配置时区和起止时间生效，支持跨午夜；
- 默认仅允许有规则背书的 URGENT 立即投递；
- 延期消息在夜间结束后重新经过限频和过期判断。

Frequency Limit：

- 全局滑动窗口上限；
- Subscription cooldown；
- dedupe key 永不重复投递；
- 同类 INFO / NOTICE 合并窗口；
- IMPORTANT / URGENT 豁免仍有硬上限，防止事件风暴。

---

# 10. Notification 与 CLI

定义 NotificationSink.deliver(delivery)。v0.6 提供 InboxNotificationSink，并支持：

```text
/proactive status
/proactive on|off
/proactive quiet [until]|off
/proactive schedules
/proactive inbox [unread|all]
/proactive ack <delivery_id>
/proactive history [limit]
/proactive explain <delivery_id>
```

可增加仅用于测试的 emit fixture 和 tick 命令，但不接受任意代码或未校验 JSON。

主动消息进入 Conversation 时必须标记来源，不能伪装成用户输入；默认不触发 Auto Memory。用户回应后才进入正常认知链路。

---

# 11. Runtime 生命周期

ProactiveRuntime 由应用边界组装，不耦合 CLI：

```text
application bootstrap → ProactiveRuntime.start()
→ Scheduler + Event Consumer → Notification Sink
→ graceful stop()
```

start / stop 必须幂等；后台任务统一管理；CLI 退出时有限等待；单个事件异常不结束主循环；Provider、Life HUD 和 Sink 失败均有有界超时。

---

# 12. 配置建议

```dotenv
ZHAOXI_PROACTIVE_ENABLED=true
ZHAOXI_PROACTIVE_DB_PATH=.zhaoxi/proactive.db
ZHAOXI_PROACTIVE_TIMEZONE=Asia/Shanghai
ZHAOXI_PROACTIVE_POLL_SECONDS=30
ZHAOXI_PROACTIVE_MAX_EVENTS_PER_TICK=50
ZHAOXI_PROACTIVE_EVENT_MAX_BYTES=32768
ZHAOXI_PROACTIVE_MIN_INTERVAL_SECONDS=60
ZHAOXI_PROACTIVE_MISFIRE_GRACE_SECONDS=3600
ZHAOXI_PROACTIVE_NIGHT_START=23:00
ZHAOXI_PROACTIVE_NIGHT_END=08:00
ZHAOXI_PROACTIVE_GLOBAL_LIMIT=6
ZHAOXI_PROACTIVE_GLOBAL_WINDOW_SECONDS=3600
ZHAOXI_PROACTIVE_MERGE_WINDOW_SECONDS=300
ZHAOXI_PROACTIVE_MAX_ATTEMPTS=3
```

所有值必须做边界校验。关闭 PROACTIVE_ENABLED 后不得启动后台任务。

---

# 13. 数据、安全与兼容性

- proactive.db 位于 .zhaoxi，不提交真实事件和消息；
- SQLite schema 有显式版本和迁移测试；
- payload 与通知正文分开保存，普通 CLI 不展示原始 payload；
- 审计不记录密钥、完整模型上下文、Memory 正文或敏感 Tool 参数；
- 外部事件限制大小、嵌套和字符串长度；
- 事件引发的 Tool 调用使用 InvocationOrigin.PROACTIVE，复用现有权限审计；
- 新增 enum 值时验证既有审计读取兼容；
- v0.1～v0.5.1.2 行为不得回归。

---

# 14. 开发流程

## 阶段 0：冻结契约与保护基线

固定 Event、Schedule、Subscription、Delivery、策略输出、UTC、幂等和 misfire 语义；先写状态机与策略测试。退出条件：领域模型评审通过，“不做”边界固定。

## 阶段 1：持久化事件骨架

实现 Store 接口、InMemory / SQLite Store、append、claim、完成、失败、租约恢复、唯一约束和有界 Event Bus。退出条件：重放不重复，崩溃 claim 可恢复。

## 阶段 2：Scheduler

实现 Fake Clock、once / interval、三种 misfire、启动恢复、最小间隔和有界批处理。退出条件：不真实等待即可验证到期、错过、重启和去重。

## 阶段 3：Condition 与 Interrupt Policy

实现受限 DSL、优先级矩阵、Quiet / Night / Frequency / cooldown / dedupe，并保存裁决理由。退出条件：矩阵全覆盖，payload 无法注入控制指令。

## 阶段 4：Notification 闭环

实现 Inbox Sink、投递状态机、模板回退、CLI 管理和 explain。退出条件：用户能查看、确认、解释消息，普通输出不泄漏 DTO / JSON。

## 阶段 5：纵向切片

纵向切片 A：

```text
once schedule → event → condition → policy
→ inbox delivery → CLI 查看并 ack
```

纵向切片 B：

```text
Fake Tool Event → 去重 / 合并 → Quiet 下延期
→ Quiet 结束后重新裁决并投递
```

退出条件：两条链路不依赖真实模型、网络或 Life HUD。

## 阶段 6：硬化与交付

补异常隔离、重试、超时、关闭和恢复测试；跑全量测试与编译；更新 README、.env.example、版本号和 CODEBASE_STATUS；执行 CLI 黑盒冒烟；检查 diff 中无 .env、数据库、日志或真实事件数据。

---

# 15. 测试矩阵

Event / Store：

- schema 版本、UTC、payload 边界；
- event ID / dedupe 唯一约束；
- claim、租约、失败重试、poison event 隔离；
- SQLite 重启恢复与迁移。

Scheduler：

- once 恰好一次、interval 推进；
- 三种 misfire；
- 跨午夜与配置时区；
- 重启不重复；
- 无任务不忙轮询。

Condition / Policy：

- 全部 DSL 操作符；
- 未知字段、非法表达式和超深嵌套拒绝；
- 四级优先级矩阵；
- Quiet 覆盖与到期；
- Night 跨午夜；
- 限频、cooldown、dedupe、合并；
- 全局关闭压过 URGENT。

Permission / Security：

- 主动 READ 按策略执行；
- 主动 WRITE 进入 Pending；
- 拒绝不发布成功事件；
- prompt injection 不成为指令；
- 审计和 CLI 不泄漏敏感 payload。

Notification / Runtime：

- deliver / defer / suppress / expire / fail / ack；
- Sink 失败有限重试；
- 模型失败回退；
- start / stop 幂等和 graceful shutdown；
- handler 崩溃不结束 CLI；
- 主动消息默认不触发 Auto Memory。

回归：

- 原 107 项测试全部通过；
- Agent、Planner、Workflow 共用 Permission 契约不变；
- Life HUD 离线不影响本地 Scheduler / Inbox；
- 普通 CLI 对话行为不变。

---

# 16. 黑盒验收

1. 一次性提醒到期后收件箱恰好出现一条 NOTICE，ack 后不再未读。
2. Quiet 中的 NOTICE 进入 DEFERRED；Quiet 到期后重新裁决并只投递一次。
3. 夜间普通事件不提醒；有规则背书的 URGENT 可投递，explain 显示理由。
4. 连续同类事件被去重或合并，不形成通知风暴。
5. 未来提醒退出、重启后仍到期且只投递一次；错过多个周期最多补发一次。
6. 主动 WRITE 进入 Pending；未确认无副作用，拒绝后不重试、不宣称成功。

---

# 17. 完成标准

v0.6 完成必须满足：

1. 事件、调度、条件、策略和投递形成持久化闭环；
2. 重启、重复事件和重试不会造成重复提醒或副作用；
3. Quiet、Night、Priority、Frequency 全由确定性规则裁决；
4. 每条消息可解释为何投递、延期、抑制或过期；
5. 主动来源不能绕过 Permission，也不能把外部文本变成指令；
6. 用户可全局关闭、暂停单项、查看收件箱并确认消息；
7. CLI 只是首个 Sink，主动 Core 不依赖 CLI；
8. 测试不依赖真实时间等待、模型、凭据或外部服务；
9. v0.1～v0.5.1.2 全量能力无回归；
10. README、.env.example、版本号和 CODEBASE_STATUS 同步。

当朝汐能够在重启后仍记得一个到期事项，经过安静时段、优先级和频率规则判断，只投递一次可解释的消息，并且任何后续动作仍受权限保护时，v0.6 才算完成。

---

# 18. 推荐实施顺序

```text
保护 v0.5.1.2 契约
→ 固定 Event / Schedule / Delivery 状态机
→ 建立 SQLite Store 与幂等约束
→ 完成可注入 Clock 的 Scheduler
→ 完成受限 Condition DSL
→ 完成 Interrupt Policy 与安静规则
→ 接入 Inbox Notification Sink
→ 接入 Tool Event Publisher 与 Permission Origin
→ 跑通两个纵向切片
→ 补恢复、安全、文档与全量回归
```

这条顺序先解决时间、持久化、幂等和打扰边界，再接模型表达与外部事件，避免把“主动”做成不可控的后台 Agent Loop。

> **v0.5 让朝汐学会复用流程。**  
> **v0.6 让朝汐知道什么时候值得开口。**

