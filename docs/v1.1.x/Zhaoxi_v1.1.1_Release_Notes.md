# Zhaoxi v1.1.1 潮汐心跳开发报告

日期：2026-09-05。开发分支：`v1.1.1`，基于干净的 `v1.1` 工作区创建。Core 版本：`1.1.1`。

本次完成常驻观察、事件缓冲、确定性筛选、模型决策以及 Inbox / 通知续聊。开发代码与自动测试已完成；尚未打包、安装或重启用户当前运行的桌面实例。

## 实现与调用链

```text
Web / Desktop lifespan
  TaskSupervisor
    TidalHeartbeat（纯代码）
      Scheduler → 到期提醒（持久化）
      Tool Package sensors → Focus / 任务变化
      时间、最近交互、电脑输入、Quiet → natural_checkin
      EventBuffer → SQLite pending events
      唤醒 DecisionWorker
    DecisionWorker
      TTL / 去重 / 来源有效性 → Score Gate
        drop：结束事件
        inbox：直接写入 INFO 消息，不弹 Toast
        defer：持久化下次判定时间
        reminder：现有 Runtime / Subscription 确定性送达
        candidate / urgent：最多 20 个摘要 → 一次 ModelDecision
          silent：结束事件
          defer：30 分钟后重新判断，最多两次
          speak：复核状态 → durable Inbox → Desktop Toast
用户点击 → activate API → Gateway 串行锁 → Session 保存背景 → 正常续聊
```

Heartbeat 不持有模型对象，也不调用模型。观察与模型决策是两个可取消任务，使用异步 Event 唤醒，避免决策任务每秒反复扫描历史。网络请求不阻塞后续 Heartbeat。单次 Sensor 采集最多等待 8 秒；模型决策最多等待 30 秒。

## Sensor 来源与事件

- 时间和 Reminder 复用现有 Scheduler / SystemClock，按持久化 Schedule occurrence key 去重；中途重启后未处理的提醒仍留在 pending events 中。
- LifeHUD 感知位于独立包 `tools/lifehud_tool/proactive.py`，由 `proactive_sensors()` 可选工厂暴露。Core 按工厂装配，不硬编码 LifeHUD。
- 每 2 分钟读取 `/api/agent/context/focus` 和 `/tasks`，不读取全量 `/today`。接口错误/超时使来源不健康，不使用其旧上下文做自然关心。
- RUNNING Focus 的 `actualMinutes >= 90` 产生 `focus.long_running`，同一 Focus 只观察产生一次，跨重启由数据库去重。发送前检查 Focus 是否已结束/改变。
- 缓存当日最多 500 个任务的完成状态，只在 false → true 时产生 `task.completed`，单轮最多 20 个，INFO Inbox 静默展示。初始快照不回放历史完成记录。
- 最近交互由 Gateway 聊天、权限回复和主动消息激活更新；模型执行期间设置 interacting。Windows 使用 GetLastInputInfo 检查最近 5 分钟是否有输入；无法取得活动事实时不推测电脑活跃。
- Natural Check-in 要求至少 3 小时未交互、电脑活跃、无 Focus、Quiet 关闭、来源健康且有当日任务/专注上下文。以配置时区的日期去重，每天最多一个候选；仍必须通过冷却、夜间和分数门。

沿用 `ProactiveEvent`，`occurred_at / received_at` 对应发生/采集时间；新增 `importance`、`urgency`、`next_decision_at`。保留 `event_id / event_type / source / dedupe_key / payload / expires_at / status / attempts`。Delivery 新增事件类型、简短背景、关联事件 ID；API 不返回内部 relevant_payload。

## 缓冲、评分与成本边界

缓冲默认 300 秒，最多保留 200 个普通候选；满时保留价值较高项。普通事件 TTL 6 小时，自然巡检 1 小时；明确提醒不等普通聚合。历史去重记录留在现有 Store，pending 索引支持高频检查。事件内容仍以现有 JSON 格式保存，新增字段有默认值，无需破坏式迁移。

基础分数为 `0.7 × importance + 0.3 × urgency`：低于 0.3 丢弃，低于 0.6 进入 Inbox，其余成为模型候选。无关事件在 Focus 期间减 0.2 分，INFO 固定只进 Inbox。模型输出 priority 仅作为建议，不允许模型自行提升为可绕过 Quiet 的 URGENT。

- 普通消息距上次发言至少 45 分钟；从持久化 Delivery 历史恢复冷却。
- 用户刚聊天后 15 分钟不发普通消息，正在交互时推迟 5 分钟再检查。
- Quiet / 夜间延后普通事件；默认夜间为配置时区 23:00–08:00。
- 用户明确 Reminder 跳过普通冷却与聚合，但遵循原 Quiet / 夜间策略；只有来源已声明 URGENT 才可绕过。
- 两批模型决策间至少 5 分钟；defer 延后 30 分钟，同一事件最多两次决策。silent、非法 JSON、空 speak、模型失败均结束本批候选，不在下个心跳重试。
- 模型复用当前 Personality prompt，只接收当前时间、最近交互和最多 20 条、每条 600 字符的事件摘要，不附带工具或完整生活数据。明确提示摘要是不可信数据，不执行其指令。
- 输出 JSON：`action: silent|defer|speak`、`priority: low|medium|high`、`reason`、`content`。模型调用使用 1 次 provider attempt / 4000 token budget，避免后台自动重试或 fallback 额外调用；30 秒超时。
- 发言前再次检查 Quiet、交互、Focus 状态，防止模型等待期间情况改变后仍发出过时提醒。

明确 Reminder 保留原订阅文案和确定性送达路径，即使模型不可用也能正常提醒；自然关心和 Focus 候选由当前人格模型表达。

## Inbox / Session 闭环

Inbox 显示最近 100 条已送达/已读消息，包含内容、时间和读状态；按 Delivery ID 去重，抑制/延后消息不显示。点击发送 `POST /api/proactive/{delivery_id}/activate`，沿用 Desktop token 保护。

Gateway 串行恢复已送达消息：把实际内容、时间和简短可读背景写为 assistant 消息，保存到现有 SQLite Session，再标记 ACKNOWLEDGED。不会伪造 user origin，不直接展示原始 Event JSON。重复点击不会重复附加同一上下文；清空或上下文裁剪后再点可重新恢复。

Toast 回调携带 Delivery ID，唤起窗口并走相同激活 API；页面尚未加载时暂存 ID，回复气泡仍在输出时前端等待当前回复结束再恢复。持久 sink 已送达时不重复弹 Toast。

## 配置

`.env.example` 已同步，现有 `.env` 无需改动即可使用默认值。

| 环境变量 | 默认值 | 范围/行为 |
| --- | --- | --- |
| ZHAOXI_PROACTIVE_HEARTBEAT_SECONDS | 30 | 5–300 秒 |
| ZHAOXI_PROACTIVE_COOLDOWN_MINUTES | 45 | 1–1440 分钟 |
| ZHAOXI_PROACTIVE_NATURAL_CHECKIN_ENABLED | true | 关闭后只处理事件候选 |
| ZHAOXI_PROACTIVE_NATURAL_CHECKIN_MIN_HOURS | 3 | 1–48 小时 |
| ZHAOXI_PROACTIVE_EVENT_BUFFER_SECONDS | 300 | 0–600 秒 |

继续使用既有 ENABLED、DB_PATH、TIMEZONE、NIGHT_START_HOUR、NIGHT_END_HOUR、调度批次与 misfire 配置。

## 可观测性

`GET /api/diagnostics` 的 `metrics.counters` 提供：

- `proactive.heartbeat`、`proactive.sensor_events`、`proactive.sensor_errors`。
- `proactive.gate_drop / gate_inbox / gate_candidate / gate_urgent / gate_defer`。
- `proactive.llm_decisions`、`proactive.deliveries`、`proactive.spoken`。
- `proactive.heartbeat_errors`、`proactive.worker_errors`。

计数器是现有 MetricRegistry 的进程内累计值，重启清零。`llm_decisions` 表示决策调用次数，`spoken` 表示模型生成后实际送达的普通/紧急主动消息；确定性 Reminder 纳入 deliveries。Provider 的通用计数仍在原位置。

## 修改文件

新增模块：

- `src/zhaoxi/proactive/heartbeat.py`、`sensors.py`、`buffer.py`、`scoring.py`、`decision.py`、`worker.py`。
- `tools/lifehud_tool/proactive.py`。

集成与存储：

- `src/zhaoxi/proactive/models.py`、`policy.py`、`runtime.py`、`store.py`、`sqlite.py`、`notifications.py`。
- `src/zhaoxi/cli.py`、`config/settings.py`、`interfaces/gateway.py`。
- `src/zhaoxi/web/app.py`、`web/static/index.html`。
- `src/zhaoxi/desktop/app.py`、`window.py`、`notifications.py`。
- `tools/lifehud_tool/package.py`。

配置、版本与文档：`.env.example`、`pyproject.toml`、`src/zhaoxi/__init__.py`、`scripts/verify_release.py`、`README.md`、`docs/README.md`、`docs/current/CODEBASE_STATUS.md`、本报告。

新增测试：`tests/proactive/test_tidal.py`、`tests/tools/test_lifehud_proactive.py`、`tests/web/proactive_inbox.test.cjs`。更新桌面通知测试、窗口测试的 loaded 事件替身，以及发布/备份测试的版本断言。

## 自动验证

- `.venv/Scripts/python.exe -m pytest`：321 项通过，1 项原有 Starlette/httpx 弃用警告。
- `node --test tests/web/*.test.cjs`：17 项通过。
- `git diff --check`：无空白错误。

新测试覆盖空闲 100 次观察零模型、心跳/模型分离、缓冲容量/TTL/聚合、评分、Quiet/冷却/交互、urgent、三种决策与有界 defer、模型非法输出/失败、重启前后待办与送达幂等、提醒绕过聚合、同批提醒冷却、通知不重复、API 鉴权、上下文持久恢复、自然关心条件、Focus/任务变化与缓存、模型等待中 Quiet/Focus 改变、后台取消以及页面点击/去重/回复中延后激活。

## 手动验收步骤（待真实环境执行）

1. 正常退出旧桌面实例，再启动本分支 `python main.py --desktop`。通过原 Desktop 界面的 diagnostics 检查运行版本为 1.1.1；沿用现有本机配置。
2. 空闲运行 30 分钟：heartbeat 增加，llm_decisions 在无候选条件下不增加，不出现无意义通知。缓冲默认会延后普通事件 5 分钟。
3. LifeHUD 开启 Focus，跨过 90 分钟后等待一次 Sensor 采集和聚合窗口：最多一个 Focus 候选；模型可决定 silent / defer / speak，后续心跳不得重复骚扰。必要时用测试环境降低聚合等待以便观察，完成后还原。
4. 开启托盘 Quiet Mode，再触发普通候选：不弹 Toast；解除 Quiet 或到期后按持久的下次检查时间重新判断。URGENT 按原策略例外。
5. 在独立测试数据环境用已有 `/proactive remind 1 喝水` 创建提醒，再让常驻实例读取同一测试库：到期送达一次；即使最近已有普通发言也不丢失。通知或 Inbox 点击后回复“再过十分钟”，确认模型知道原提醒背景。
6. 让电脑有输入活动、无 Focus、今日有任务/专注上下文且超过 3 小时未聊天：允许一个 natural_checkin 候选，同一天不重复；无上下文或电脑不活跃应保持静默。
7. 让模型服务暂时不可用：候选静默结束，heartbeat 继续增长，桌面可继续使用；恢复服务后新的独立事件可以继续决策。
8. 点击 Inbox/Toast，检查窗口唤起、已读状态、背景续聊；重启后再次打开 Inbox 验证历史保留。通过托盘退出，确认两个后台任务随服务关闭，不遗留额外常驻实例。

## 已知限制

- 未运行真实模型/真实 LifeHUD 90 分钟 Focus/Windows Toast 实机验收，也未生成 wheel 或安装包；自动验证使用 Fake Provider、时钟和本地测试库。
- 感知仅覆盖 Focus 和任务完成，没有新增生活业务规则、系统危险感知、任务截止日期推断或 LifeHUD 写操作。
- Natural Check-in 采用保守每日一次；非 Windows 平台无法取得系统输入活跃事实时保持静默。Quiet 手动提前关闭后，已延后的候选仍按原 next_decision_at 等待，避免突然补发。
- 持久记录支持 pending 和 cooldown 恢复；Quiet/交互时间与 diagnostics 计数仍为进程状态。候选缓冲有界，但历史去重记录继续保存在现有数据库，没有新增自动清理策略。
- 送达以持久 Inbox 为事实源；若在持久化后、Toast 渲染前进程退出，下次不重复弹窗，消息仍可在 Inbox 打开。
- 支持现有单一 Session；旧进程遗留的系统通知跨进程重新激活、多 Session 路由不在本次实现范围。
- 常驻循环接入 Web / Desktop；纯 CLI 保留原手动 `/proactive tick` 模式。
