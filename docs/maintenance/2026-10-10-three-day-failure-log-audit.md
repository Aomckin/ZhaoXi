# 2026-10-10 近三天失败日志与 v1.4.8 清债审计

审计窗口：**2026-10-07 00:00:00 至 2026-10-10 00:00:00（Asia/Shanghai）**，即 10 月 7–9 日三个完整自然日。本轮只读生产日志和当前源码，仅写文档及隔离分析文件；未改源码、配置或生产数据，未启动应用、调用模型、重启或发送消息。

## 统计与口径

扫描 `.zhaoxi/logs/zhaoxi.log` 及 `.1`—`.5`，窗口内 104,869 条带时间戳记录，WARNING 6,103 条、ERROR 12 条。文件覆盖整个窗口；[结构化证据](evidence/2026-10-10-three-day-failure-log-audit.json) 保存文件哈希、请求 ID、时间、行号、分类和原方法隔离复核结果，不复制聊天正文、图片或密钥。

前台以 request_started 的 request_id 去重，共 **153 个请求，30 个终态失败、123 个 runtime 成功终态，终态失败率 19.61%**。终态失败依据 Web 失败事件或 runtime_finished=failed，不使用旧 completed 指标作为成功依据。重新生成是独立请求。该分母不包括所有 QQ 请求或后台尝试。

| 日期 | 前台请求 | 终态失败 |
| --- | ---: | ---: |
| 10-07 | 65 | 17 |
| 10-08 | 40 | 8 |
| 10-09 | 48 | 5 |

| 终态失败码 | 请求数 |
| --- | ---: |
| empty_model_reply | 11 |
| invalid_reply_protocol | 7 |
| provider_http_400 | 4 |
| agent_timeout | 3 |
| agent_loop_error | 3 |
| provider_protocol_error | 1 |
| provider_transport_error | 1 |

空回复与主回复协议失败占 **18 / 30（60%）**。另外 **25 个请求**发生 response_generation_failed 后仍以 runtime success 结束；其中可能有恢复，也有工具完成后的确定性保底，不能全当完全恢复。另有 **13 个 runtime success 请求的最终 result_status=failed**，这包括已完成操作但回复失败，以及工具失败后正常交付失败说明；不能将 success 事件单独用作业务成功率，也不能把这 13 个简单相加为新的终态失败。

窗口跨多个代码 / 配置状态，没有逐条构建标识。历史失败不证明当前补丁无效；阶段错误、后台活动错误和 Provider 错误可能重复描述同一次尝试。

## 新确认的代码问题

### V148-10 · P2 · 直接回复与回复重生成超时被归为 agent_loop_error

[Agent](../../src/zhaoxi/core/agent.py) run_direct 的超时分支（643 行）与 resume_current_turn 的超时分支（762 行）抛 AgentLoopError 时未设置 code；[异常类型](../../src/zhaoxi/errors.py) 默认 code=agent_loop_error。普通 Agent 运行的超时分支（599 行）却显式设置 agent_timeout，导致同类超时因入口不同被错误分类。

提取 resume_current_turn 的原 TimeoutError handler 及 AgentLoopError 类，以内存 self(timeout_seconds=120) 触发，确实得到 agent_loop_error。没有实例化 Agent 或访问服务。

日志关联：10-09 17:48:35 至 17:50:35 的重新生成请求 `63a53ca9-b6ee-48ab-b16d-e586b4379569`，总耗时 120,726 毫秒，唯一 Agent response_generation 调用耗时 119,974 毫秒，最终在 `zhaoxi.log:22917` 记录 regenerate_failed / agent_loop_error。这与该分支一致，但日志没有完整异常链，不能把三个泛化错误全部认定为此根因。

修复目标：统一超时错误码、失败阶段及保留操作语义；覆盖普通运行、直接回复、重生成、确认后继续等入口。不能仅凭错误码或长耗时把所有失败都解释为上游慢。

### V148-11 · P2 · 记忆维护把正常跳过误判为归纳失败，且丢失细分原因

[活动适配器](../../src/zhaoxi/internal_activity/activities/legacy.py:101) memory 先执行本地 maintain，再调用 AutoConsolidator.maybe_run，并以 last_consolidation_check_at 是否变化决定失败；不变化即抛 RuntimeError(memory_consolidation_failed)。

[AutoConsolidator](../../src/zhaoxi/memory/consolidation.py:65) 在关闭或尚未到期时合法返回 False，不更新该时间戳；Provider / JSON / 校验失败也返回 False / None 且不推进时间戳。适配器由此不能区分正常跳过与实际失败，也无法保留实际失败类别。

提取这两个原方法，用纯内存 Repository / Service 复核三种情况：关闭归纳、启用但未到期、未到期且本地维护已经有变化，均被错误抛为 memory_consolidation_failed。自动候选检查通常会预先排除关闭 / 未到期，所以不能推断每轮自动调度必然触发；手动强制或候选检查后状态变化仍需覆盖。

日志中 memory_maintenance 有 **6 次 RuntimeError**，其中两次在 10-09 08:23、16:24；现有日志没有更细原因，**不能证明六次都是正常跳过误报**。实际模型归纳失败被泛化的情况也应处理。

修复目标：用明确结果区分未到期、关闭、无变化、更新与失败，保留本地已完成维护；实际失败保留安全错误码 / 阶段，不用时间戳变化推断执行结果。与 V148-01 的正确 no-op 语义共同验收。

## 现有问题补强与仍待定位的失败

| 方向 | 本窗口证据 | 判断与下一步 |
| --- | --- | --- |
| 前台回复交付不稳定 | 41 次主回复协议拒绝：empty 23、json 9、truncated_json 4、mixed_json 3、tool_arguments 2；另有 5 条工具参数损坏日志 | 高优先级可靠性问题；日志无法独立定位模型输出、截断、协议转换或解析器。需对当前构建有界复核，保持已完成工具不重放 |
| V148-07 领域误路由 | 10-08 19:14 请求 `b8411f12-6bbf-4ac7-9763-f83fec0365ff` 在 `zhaoxi.log.1:51701 / 51717` 连续两次 LifeHUD 调用失败，分别 lifehud_invalid_argument / validation_error | 补强截图里购买记录误写 LifeHUD 的执行证据；参数错误本身不是工具实现 bug，Domain Map 仍须动态生成 |
| 岗位录入失败且诊断不足 | add_job 4 次失败、2 个请求（10-09 14:55、16:26）；最终 result_code 仅为 failed | 不能判断字段、重复、服务状态或适配器缺陷；需保留业务安全错误码和失败字段类别，不能盲目放宽校验 |
| 摘要结构输出 / 校验失败 | 新失败日志中 ValidationError 4 次；snapshot `d31380bc2e7b4e7984d80d5ed4ab8aa2` 在 20:55 第三次失败后隔离 | 退避隔离已有生效证据，但模型输出结构、解析、候选提交阶段未区分，仍需定位字段错误；不将所有 ValidationError 都当同一 bug |
| 上游不可用与重试 | 10-09 15:13 provider_transport_error；15:20 多次工具后保底及重生成仍遇到传输失败；Beat 9 次模型失败，其中 3 次调用预算耗尽、5 次 HTTP 400、1 次传输错误 | 上游故障不自动归为代码 bug；核查重试预算、保底说明和恢复路径，首次失败原因需保留 |
| 退出收尾 | 2 次 graceful shutdown 超时，随后共 4 条 ASGI CancelledError | 均集中于退出时的流取消；不算 4 个独立聊天 bug。需检查 SSE / 长连接退出与任务取消顺序，尚未确认数据或回复丢失 |

## 历史已修复问题与环境噪声

- 后台摘要失败 **1,659 次尝试**、预算超限 **1,383 条**（6,000 上限 1,375 条、4,000 上限 8 条），大量属于旧预算 / 队列状态，不能把它们逐条登记为新 bug。B01 / B02 已有 [摘要预算与队列修复](2026-10-09-background-snapshot-recovery.md)。
- 新格式摘要失败日志共 **47 次、37 个 snapshot ID**，其中 ProviderError 43、ValidationError 4；44 次保持 PENDING 并有下次时间，3 次第三次失败进入 FAILED。两个旧队首在 10-09 09:00 / 09:01 因 provider_call_budget_exhausted 隔离，20:55 又隔离一项校验失败。这说明失败已能显式记录和隔离，不代表队列已清空、所有预算合理或根因已消失。
- current_cognition candidate_check TypeError **10 次**，最后在 10-08 21:59；B03 已有 [空内容计数修复](2026-10-09-cognition-count-and-result-metrics.md)。不能用历史数量宣布当前修复失败。旧失败指标 completed 的 B04 同样保留历史状态，不重复立项。
- `unsupported_model` HTTP 400 **208 次**全部对应历史 `deepseek-flash` 配置，最后发生在 10-08 10:09:34；属于已确认配置不兼容及永久错误反复调用的防护债，不证明当前配置仍错。
- QQ 连接拒绝 **2,692 次尝试**、LifeHUD 健康失败 **17 条**、Sensor 失败 **36 条**。存在服务不可用与分层重复记录，不能相加为用户失败数。重连退避与按状态聚合继续纳入清债。
- Current Cognition 后台维护失败 7 次（JSONDecodeError 5、ValueError 2），Perception planner 失败 3 条、direct 失败 1 条；没有完整业务请求分母，不给这些路径计算失败率。

## 处理建议与验收边界

优先处理有效回复交付和超时分类，其次修正记忆维护 no-op / 失败语义、摘要校验诊断、工具领域路由和岗位录入错误码。已登记 V148-01—V148-09 继续保留各自证据边界；本次失败日志不能单独证明决策误判、历史消息丢失、选错图片或重生成重复投影已定位。

本次仅完成日志审计与两个源方法隔离复核；未做修复，未做真实模型 / 桌面交互验收。新增问题纳入 [v1.4.8 清债记录](../v1.4.x/Zhaoxi_v1.4.8_Reliability_已知问题与清债记录.md)。
