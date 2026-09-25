# Zhaoxi v1.2.8 开发任务书
## Internal Activity Runtime / 内部活动运行层

> 版本定位：把现有“半活跃模式”从单纯的主动消息机会，升级为朝汐的轻量后台活动心跳。
>
> 核心原则：**Activity ≠ Message**
>
> 朝汐获得一次活动机会，不代表一定要主动说话。她也可以在不打扰用户的情况下，整理 Current Cognition、维护 Memory、结算 Agenda 状态，或执行其他内部认知工作。

---

# 一、版本目标

当前半活跃模式主要用于：

```text
Semi-Active Tick
    ↓
判断是否主动发消息
```

v1.2.8 将其升级为：

```text
Semi-Active Tick
        ↓
Activity Scheduler
        │
        ├── Current Cognition Consolidation
        ├── Memory Maintenance
        ├── Agenda Maintenance
        ├── Proactive Check
        └── Future Internal Activities
```

本版本重点不是“让朝汐更爱说话”，而是：

> **让朝汐在不说话的时候，也能做必要的后台认知整理。**

---

# 二、核心架构

建议新增：

```text
internal_activity/
├── models.py
├── scheduler.py
├── registry.py
├── runtime.py
├── policies.py
└── diagnostics.py
```

实际目录根据现有工程结构调整，不要为了目录形式强行重构已有模块。

核心职责：

```text
Presence / Semi-Active Tick
        ↓
InternalActivityRuntime
        ↓
ActivityScheduler
        ↓
选择本轮值得执行的 Activity
        ↓
执行
        ↓
记录结果
```

---

# 三、Activity 类型

v1.2.8 第一版只实现以下活动。

## 1. Current Cognition Consolidation

职责：

- 空状态 Bootstrap
- 周期性重新俯瞰近期上下文
- 消化 Observation Buffer
- 识别缓慢形成的近期趋势
- 淡化已经失效的认知
- 对之前维护失败的内容进行后台自愈
- 必要时更新 Current Cognition

## 2. Memory Maintenance

职责：

- 合并明显重复记忆
- 清理低风险冗余
- 处理明显冲突
- 补充已有记忆之间的关联
- 必要时调整分类 / 状态

禁止：

```text
重新扫描全部聊天疯狂提取新 Memory
```

原则：

> 前台负责发现新 Memory，后台负责整理已有 Memory。

## 3. Agenda Maintenance

优先处理可以本地规则完成的状态维护：

- Event 是否已经过去
- Window 是否结束
- Deadline 是否过期
- 状态是否应从 PLANNED → ACTIVE / MISSED
- 清理明显失效的近期展示状态

尽量不要为了简单时间判断调用 LLM。

## 4. Proactive Check

保留当前半活跃主动消息能力，但重新定位为：

> Internal Activity 的一种，而不是 Semi-Active Tick 本身。

---

# 四、Semi-Active Tick 改造

当前：

```text
Semi-Active Tick
→ Proactive
```

改为：

```text
Semi-Active Tick
→ InternalActivityRuntime.run_tick()
```

然后由 Runtime 判断本轮是否有 Activity 值得执行。

默认不要每次 Tick 全部执行。

---

# 五、Activity Scheduler

新增轻量调度器。

每个 Activity 至少包含：

```yaml
name:
enabled:
dirty:
last_run_at:
last_success_at:
min_interval:
priority:
pending_signal_count:
failure_count:
```

可根据模块需要扩展。

---

# 六、Activity 调度条件

Scheduler 至少考虑：

```text
是否启用
是否 dirty
距离上次执行多久
是否达到最小间隔
是否存在未处理信号
当前优先级
最近是否失败
本轮预算
```

不要让所有 Activity 每次 Tick 都执行。

---

# 七、Current Cognition 双轨更新

v1.2.8 正式建立两条 Cognition 更新路径。

## A. Immediate Update

每轮对话结束后：

```text
Conversation
    ↓
Current Cognition Maintainer
    ↓
强变化判断
    ↓
UPDATE / NO_CHANGE
```

适合：

- 用户明确改变决定
- 主线突然变化
- 明确开始 / 结束某件持续事项
- 重要状态变化

例如：

```text
“offer 收到了”
“这个方向不走了”
“秋招结束了”
“今天开始弄 v1.2.8”
```

## B. Background Consolidation

由 Internal Activity 触发。

处理：

```text
弱信号
缓慢趋势
跨多轮形成的状态
过时认知
未成功处理的近期信息
```

输入：

```text
Current Cognition
+
Observation Buffer
+
近期必要上下文
```

输出：

```text
NO_CHANGE
或
UPDATE
```

---

# 八、Current Cognition Bootstrap

当前 Cognition 为空时：

```text
narrative == ""
```

应自动提高 Consolidation 优先级。

条件示例：

```text
存在足够近期对话
或
Observation 已累计到一定程度
```

执行：

```text
BOOTSTRAP
```

Bootstrap 与普通 Incremental Update 分离。

Bootstrap 目标：

> 建立第一份基线 Current Cognition。

不允许简单把空状态当作普通 NO_CHANGE 后永久跳过。

---

# 九、Bootstrap 游标规则

Bootstrap 成功：

```text
保存 Cognition
→ 推进 cursor
```

Bootstrap 失败：

```text
不消费完整初始化窗口
→ 保留待处理状态
→ 下一次 Internal Activity 可再次尝试
```

避免：

```text
第一次失败
→ cursor 前移
→ 永远失去初始化机会
```

---

# 十、Observation Buffer

Current Cognition 继续保留轻量 Observation Buffer。

用途：

> 广泛观察近期弱信号，不直接进入主 Context。

例如：

```yaml
topic: 饮食
count: 4

topic: 动漫
count: 5

topic: Zhaoxi开发
count: 7
```

Observation 本身：

- 不展示给用户
- 不直接注入主 Prompt
- 不等于 Memory
- 不等于 Cognition

它只是 Consolidation 的近期信号源。

---

# 十一、Observation 规范化

避免：

```text
动漫
动画
二次元
番剧
```

被当成完全不同主题。

第一版可采用：

- Prompt 约束稳定 key
- 简单 alias map
- 轻量归一化

不要上复杂 Topic Modeling。

---

# 十二、Periodic Consolidation

除了 dirty 触发，也支持周期综合。

建议：

```text
累计 8~12 个 user turn
```

或：

```text
距离上次 Consolidation 超过一定时间
```

满足任一条件后：

```text
current_cognition_consolidation = due
```

具体阈值配置化。

---

# 十三、Memory Maintenance

后台 Memory Maintenance 与现有 Memory Extractor 严格分工。

## Memory Extractor

```text
Conversation
→ 发现新事实
→ 新增 / 更新 Memory
```

## Memory Maintenance

```text
Existing Memory
→ 去重
→ 归并
→ 冲突整理
→ 低风险清理
```

不要在后台重新跑“广记”。

---

# 十四、Memory Maintenance 触发条件

可包括：

```text
最近新增 Memory 数量达到阈值
重复候选数量增加
检测到冲突
距离上次整理时间较长
```

无明显需要：

```text
SKIP
```

---

# 十五、Agenda Maintenance

Agenda Maintenance 优先使用规则引擎。

例如：

```text
Event.start_at 已过去
且没有完成
→ 根据规则更新状态

Window.end_at 已过去
→ ACTIVE / MISSED 判断

Deadline 已过期
→ overdue / missed
```

不要为这些规则调用 LLM。

---

# 十六、Proactive Check

现有半活跃主动消息逻辑迁移为 Activity。

其执行结果可能是：

```text
NO_MESSAGE
MESSAGE
```

如果 NO_MESSAGE：

> 本轮 Tick 仍然可以有其他内部活动完成。

---

# 十七、Activity Budget

每次 Tick 设置轻量预算。

例如：

```yaml
max_llm_activities_per_tick: 1
max_local_activities_per_tick: 3
```

第一版建议保守。

避免一次半活跃同时调用：

```text
Cognition
Memory
Reflection
Proactive
```

多个模型任务。

---

# 十八、优先级建议

建议默认优先级：

```text
HIGH
- Current Cognition Bootstrap
- Current Cognition recovery
- 重要 Agenda 状态结算

MEDIUM
- Current Cognition Consolidation
- Memory Maintenance
- Proactive Check

LOW
- 普通整理任务
- 非必要 Reflection
```

具体权重可配置。

---

# 十九、Activity 失败策略

Activity 失败：

```text
记录错误
增加 failure_count
保留 dirty
主 Runtime 继续
```

不得：

```text
一个 Cognition 失败
→ 整个 Semi-Active Tick 崩溃
```

---

# 二十、重试与退避

某 Activity 连续失败：

```text
failure_count += 1
```

增加冷却。

例如：

```text
1 次失败 → 正常重试
2 次失败 → 延长 cooldown
3 次以上 → 标记 degraded
```

避免后台无限烧 API。

---

# 二十一、Current Cognition 校验失败修复

本版本顺带修复当前已知问题。

ValidationError 必须记录具体字段。

至少保存：

```text
error_type
field_path
error_message
input_excerpt
attempt
response_chars
finish_reason
```

禁止继续只记录：

```text
ValidationError
```

---

# 二十二、Current Cognition cursor 提交语义

重新明确：

```text
UPDATE 成功
→ advance cursor

正常 NO_CHANGE
→ advance cursor

Validation FAILED
→ 不 advance

Service REJECTED
→ 不直接永久消费
→ 标记 pending / retryable

BOOTSTRAP FAILED
→ 不 advance bootstrap window
```

避免近期上下文被静默吞掉。

---

# 二十三、Internal Activity 不进入用户对话

内部活动默认：

```text
silent = true
```

执行后不要自动发送：

```text
“我刚刚整理了记忆”
```

只有 Proactive Check 决定需要消息时，才允许输出给用户。

---

# 二十四、内部活动日志

至少记录：

```text
ACTIVITY_TICK_START
ACTIVITY_SELECTED
ACTIVITY_SKIPPED
ACTIVITY_SUCCESS
ACTIVITY_FAILED
ACTIVITY_BACKOFF
```

每条包含：

```text
activity_name
reason
started_at
duration
result
```

---

# 二十五、Debug 面板

建议增加：

```text
Internal Activity
```

可查看：

```text
上次 Tick 时间
本轮候选 Activity
实际执行 Activity
Skip 原因

Current Cognition:
- dirty
- pending_turns
- last_run
- last_result

Memory Maintenance:
- dirty
- last_run

Agenda Maintenance:
- last_run

Proactive:
- last_check
- last_result
```

---

# 二十六、Debug 手动触发

允许调试：

```text
Run Activity Tick
Run Cognition Consolidation
Run Memory Maintenance
Run Agenda Maintenance
Run Proactive Check
```

仅用于 Debug。

不要变成普通用户功能入口。

---

# 二十七、配置项

建议增加：

```env
INTERNAL_ACTIVITY_ENABLED=true

CURRENT_COGNITION_CONSOLIDATION_ENABLED=true
CURRENT_COGNITION_CONSOLIDATION_MIN_TURNS=10
CURRENT_COGNITION_CONSOLIDATION_MIN_INTERVAL=...

MEMORY_MAINTENANCE_ENABLED=true
MEMORY_MAINTENANCE_MIN_INTERVAL=...

AGENDA_MAINTENANCE_ENABLED=true
PROACTIVE_ACTIVITY_ENABLED=true

INTERNAL_ACTIVITY_MAX_LLM_PER_TICK=1
```

如已有 Settings 体系，按现有规范接入。

---

# 二十八、与 Presence 的关系

Semi-Active Tick 仍属于 Presence 层。

Internal Activity 不代表：

```text
朝汐当前一定处于 Active 对话状态
```

它更像：

> 后台轻量活动机会。

后续可与 Presence State 联动：

```text
Idle
Semi-Active
Working
Sleeping
```

但本版本不扩展完整 Presence 状态机。

---

# 二十九、与 Decision System 的关系

v1.2.8 不实现完整 Decision System。

当前 Activity Scheduler 使用：

```text
规则
dirty
cooldown
priority
budget
```

未来 Decision System 可以参与：

```text
“这次 Activity Tick 最值得做什么？”
```

但本版本不要提前耦合。

---

# 三十、测试场景 1：Cognition Bootstrap

前提：

```text
Current Cognition 为空
已有 20+ 轮有效对话
```

Semi-Active Tick：

```text
→ 发现 bootstrap due
→ 执行
→ 建立首份 narrative
```

不能继续永久为空。

---

# 三十一、测试场景 2：弱趋势形成

连续多轮：

```text
饮食
日常
动漫
朝汐开发
```

单轮 Immediate Update 都 NO_CHANGE。

Observation 累积后：

```text
Periodic Consolidation
```

应能形成类似：

```text
最近日常与娱乐话题有所增加，Zhaoxi 开发仍持续推进。
```

---

# 三十二、测试场景 3：强变化即时更新

用户：

```text
“offer 收到了。”
```

无需等待半活跃 Tick。

Immediate Update 应直接处理。

---

# 三十三、测试场景 4：后台静默

Semi-Active Tick：

```text
Cognition Consolidation 成功
Memory Maintenance 成功
Proactive = NO_MESSAGE
```

用户侧：

```text
无消息
```

Debug 可查看后台已执行。

---

# 三十四、测试场景 5：Activity Budget

同一 Tick：

```text
Cognition due
Memory due
Proactive due
```

若：

```text
max_llm_activities_per_tick = 1
```

只执行最高优先级一个 LLM Activity。

其余保留到后续 Tick。

---

# 三十五、测试场景 6：Validation 失败

Cognition 模型返回非法结构。

预期：

```text
记录具体 field error
cursor 不推进
dirty 保留
后续 Tick 可重试
```

---

# 三十六、测试场景 7：Agenda 本地结算

某 Event 已过期。

Semi-Active Tick：

```text
Agenda Maintenance
→ 本地更新状态
```

不产生 LLM 调用。

---

# 三十七、测试场景 8：Memory Maintenance 无事可做

Memory 状态干净。

```text
Memory Maintenance
→ SKIP
```

不要为了“到点了”强制调模型。

---

# 三十八、测试场景 9：失败隔离

Current Cognition Activity 报错。

同一 Tick 内：

```text
Agenda Maintenance
```

仍应正常完成。

Runtime 不崩溃。

---

# 三十九、人工验收

至少运行一段真实日常使用。

观察：

- 朝汐没有频繁主动打扰
- 后台 Activity 确实在运行
- Current Cognition 不再长期空白
- 弱趋势能够在几轮后被综合出来
- Memory 不会因为后台维护再次疯狂增殖
- Agenda 状态可以自然结算
- API 调用量没有异常上升
- Debug 能解释“为什么这次跑了 / 为什么没跑”

---

# 四十、本版本不做

明确排除：

```text
完整 Decision System
复杂任务优先级 AI
全量 Reflection 系统重构
跨设备后台同步
多实例 Activity Scheduler
复杂 Cron 引擎
自主长期规划
自动资源消费
复杂 Agent 自治
```

v1.2.8 只负责：

> 建立轻量、可控、可观察的 Internal Activity Runtime。

---

# 四十一、完成标准

以下全部满足才算完成：

- Semi-Active Tick 已不再等于 Proactive Check
- 新增 Internal Activity Runtime
- 新增 Activity Scheduler
- Proactive Check 已成为 Activity
- Current Cognition 支持后台 Consolidation
- Current Cognition 支持 Bootstrap 自愈
- Observation Buffer 能被后台综合使用
- Current Cognition cursor 提交语义修正
- ValidationError 可定位具体字段
- Memory Maintenance 可后台运行
- Agenda Maintenance 可后台运行
- 每次 Tick 有预算限制
- Activity 支持 cooldown / dirty / priority
- Activity 失败相互隔离
- 后台活动默认静默
- Debug 可查看 Activity 状态和最近执行结果
- 支持手动 Debug 触发
- 自动测试通过
- 真实环境连续使用验收通过

---

# 四十二、版本一句话

> **Zhaoxi v1.2.8：让朝汐不只会在半活跃时“想要不要说句话”，而是开始拥有真正的内部活动，在安静的时候也能整理自己的认知、记忆与近期状态。**
