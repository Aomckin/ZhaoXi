# ACTIVE Beat 未投递排查与修复（2026-09-09）

> 当前配置、界面行为与最新限制见 [当前状态](../current/CURRENT_STATUS.md)。下文保留分阶段实现与验收记录；其中旧预算和测试数量不代表当前值。

## 已确认的压制路径

截图中键盘 8 次/分钟、鼠标 5999 次/分钟。用户确认有时启用连点器。原实现使用 **1 分钟**窗口，鼠标达到 180 次/分钟即可独立判定 HIGH，继而产生 desktop.input_active、interruptibility=LOW，最终被 Beat Gate 以 desktop_busy 拦截。5 分钟统计不是此处的判定依据。

修复后，鼠标频率仅保留为活动统计，不独立触发 HIGH。键盘必须同时满足 1 分钟频率阈值及最近 15 秒有键盘输入；停止打字后，即使连点器继续工作，也会在后续采样解除键盘 busy。原生朝汐窗口通过前台 PID 与当前进程 PID 匹配，排除自身窗口输入造成的 HIGH。全屏、有效专注信号及显式禁止打扰仍生效，diagnostics 用 interruptibility_reason 区分来源。

## 历史计数的含义

- beat_count 是单个 ACTIVE 会话计数，会话更换会重置。
- proactive.beat_decisions 是进程累计 Beat 决策次数。
- proactive.llm_decisions 是普通主动事件决策次数，不包含 Beat。
- 原先 Beat 投递只增加 proactive.beat_deliveries，遗漏总计 proactive.deliveries；现已补齐。
- last_beat_result 是上次模型决策记录，last_silent_reason 可能被后续 Gate 覆盖。旧字段无法证明历史 SILENT 一定来自模型；模型失败也曾回退为 SILENT/reaction。

## 新增可观测性

INFO 日志 `[BEAT]` 使用同一个 id 关联每次检查及其后续阶段，记录 scheduled、gated、gate_reason、llm_called、llm_action、model_error、suppressed、suppression_reason、delivered，并附数值型桌面指标及 interruptibility_reason。scheduled=false 表示尚未到期的检查。真正的模型 SILENT 使用 model_silent；模型失败不冒充模型 action；发送前拦截使用 suppressed=true。

`/api/diagnostics` 的 presence.active.last_beat_trace 提供最近记录；受鉴权保护的 `/api/proactive/active/inspect` 中 recent_beats 保留最近 64 条检查记录，跨 ACTIVE 会话保留、进程重启清空。sensor_health 记录传感器或信号提供方名称、异常类型、次数及下一次重试时间。

## 传感器错误

外层采样 8 秒超时取消会抛出 CancelledError，原 LifeHUD 采样仅捕获 Exception，绕过失败退避，导致共享传感器在事件和信号采样阶段反复重试。现在取消也设置退避并继续向上传播；新增测试验证超时后不会紧接着重复访问。此故障能够增加采样延迟与错误计数，但现有证据不足以将本次 desktop_busy 或历史 SILENT 归因于 Focus 502。sensor_events=0 不代表 Beat 没有执行。

## 验证与生效

Python 全量测试 454 通过、1 跳过；前端 24 通过。新增回归覆盖连点器、停止键盘输入、朝汐自身窗口、Gate 与模型静默区分、投递总计以及取消后的传感器退避。

需要重启朝汐加载修改。当前验证为自动测试，尚未取得重启后实机的主动投递日志。

## 自适应键盘 busy 调整

默认绝对阈值由 60 提高到 120 次/分钟；已有环境配置显式指定的阈值继续生效。启动后收集不重叠的有效输入分钟，20 个样本后采用 max(配置阈值, 个人 P80)。P50/P80/P95 使用线性插值，最多保留 1440 个输入分钟，仅在进程内存保存，重启重新校准。空闲零值、包含自身窗口或不可用状态的采样分钟不参与学习。此处统计的是输入分钟分位数，不是全天包含空闲的分位数。

键盘 busy 要求有效外部窗口、近期键盘输入、超过自适应阈值、输入没有明显回落共同成立。1m/5m < 0.6 或键盘停止超过宽限时间时标记 just_stopped，即使绝对频率仍高也不压制；1m/5m > 1.2 标记 rising，其余为 steady。鼠标频率不参与 busy 判断。

diagnostics 的 busy_evidence 展示样本数、基线是否就绪、分位数、实际阈值、近期输入证据、1m/5m 比率、趋势及最终 busy。分位数不持久化；跨重启的长期学习仍是后续扩展。新增测试覆盖趋势下降优先解除、高速用户自适应、采样不重复加权及样本排除。

## v1.1.7.1 Gate 微补丁

ACTIVE 不再因 LOW 自动硬阻断。全屏及专注等 LOW 原因进入模型上下文，由模型结合自然续聊内容决定；BLOCKED、请求处理中、quiet/night、预算和冷却仍阻断。

desktop_busy 仅在桌面样本新鲜、外部窗口、自适应多证据 busy 成立，且 1m 和 5m 键盘频率均达到 max(240, 自适应阈值, P95) 时暂缓。普通 HIGH 不自动阻断，趋势回落后恢复。模型上下文新增 busy_evidence，提示词明确 SILENT 不是默认安全选项。

每条 BEAT 日志补齐 beat_scheduled、gate_passed、desktop_busy、keyboard_1m、keyboard_5m、mouse_1m、foreground_process、interruptibility、llm_confidence，并保留已有阶段字段。

本次 Python 全量回归 459 通过、1 跳过。真实模型隔离脚本在受限环境连接失败，申请外部访问被自动审批拒绝（认为缺少向具体外部 API 发送测试对话的授权），未绕过。任务书的本次实机成功投递标准仍未完成；此前 v1.1.7 的隔离成功记录不替代本补丁验收。

### 授权后的真实模型复验

用户随后明确回复“允许运行”，执行 `.venv/Scripts/python.exe scripts/smoke_active_beat.py --live` 成功：open_thread=false、beat_count=1、action=COMMENT、failure=null、delivery_count=1。本次实际两次模型调用（普通回复一次、Beat 决策一次），第一轮 Beat 已投递至隔离内存 Inbox，无需第二轮。

此结果完成了本补丁在本机真实模型下的非 open-thread ACTIVE Beat 隔离投递验证。正式 Session/Memory 未修改、未发送桌面通知；加速日间时钟与隔离 Inbox 不等同于 Desktop UI 场景 A–D 的长时人工体验验收。正式朝汐进程仍需重启加载补丁。终端中文正文编码显示异常，不引用无法可靠显示的消息内容。

## 14:40 后实机失败及响应处理修正

日志确认 14:40:41 重启后加载微补丁。14:45:38、14:50:44、14:55:48、15:00:49 四次 Beat 均 Gate 通过、desktop_busy=false，但结果均为 model_failed_or_invalid，llm_action=null。不是模型选择 SILENT，也没有投递成功。检查记录按 id 去重后共 41 次，其中 36 次为等待静默/冷却、1 次请求处理中、4 次进入模型。旧统一异常处理不足以还原四次失败的具体异常。

现为 Beat 请求启用 JSON object 响应模式，兼容单个完整 JSON 代码块，继续严格验证 action、reason、confidence 和非空内容，不将任意正文当作可投递回复。截断、空响应、意外工具调用、JSON 解析、字段校验、请求失败及超时各有独立错误码。model_diagnostics 包含阶段、异常类型、响应长度、finish_reason、工具调用数量、JSON 错误位置及安全的字段校验类型，不记录正文或异常中的原始输入。失败仍保持有界冷却且不消耗主动预算。

验证：Python 全量 467 通过、1 跳过。沿用明确授权运行相同真实模型隔离脚本，两次模型调用，首次 Beat action=CONTINUE、failure=null、open_thread=false、delivery_count=1，退出码 0。此结果验证新 JSON 模式链路，不证明历史四次失败必然为 JSON 格式问题；实机需重启加载后用新增诊断确认。
