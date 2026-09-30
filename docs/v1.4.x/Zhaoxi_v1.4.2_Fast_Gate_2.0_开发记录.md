# v1.4.2 Fast Gate 2.0 轻量补丁开发记录

日期：2026-09-30。实施依据：[轻量补丁任务书](Zhaoxi_v1.4.2_Fast_Gate_2.0_Lightweight_Patch_Task.md)。版本继续为 1.4.2。

## 实施结果

现有 `FastDialogueGate` 改为三态置信度门控：

| 判定 | 运行路径 |
| --- | --- |
| FAST_CONFIDENT | 跳过 Router，单次无工具 Fast Chat |
| AMBIGUOUS | 调用 Cognitive Router，可选 FAST_CHAT / DIRECT / TOOL / PLAN / WORKFLOW |
| HEAVY_CONFIDENT | 明确动作、资源、历史请求直接 TOOL；多步目标 PLAN；需要进一步判断的决策或权限状态进入现有标准流程 |

Gate 只读取有界历史对话、Current Cognition 快照与 active thread 标题、既有 Semantic Capability Routing / Manifest、已有资源引用元数据和本地权限状态。它不调用 LLM、不查长期 Memory、不执行 Tool。阈值与正向票数经 Settings 注入。

- 近期对话排除当前 trigger、内部工具消息及 Tool Result，避免当前输入充当自己的证据；范围与 Fast Chat 的历史条数、字符预算一致。
- Current Cognition 可成为正向证据，但明确动作、具体历史和资源请求优先升级。能力索引或状态读取失败被记录为 signal_errors；弱证据不会默认 FAST。
- Tool 名称只是匹配线索。能力匹配还需当前请求的动作或事实查询形态；LifeHUD 界面评价可以 FAST。
- 句式识别区分聊天、请求、指代、资源版本、历史精确性和多步选择；无法消歧的指代及未识别输入进入 AMBIGUOUS。个人陈述中的“还是”不自动触发决策；“我想了解那个文件”等信息请求不被当作普通个人陈述。
- Router 原有 FAST_CHAT 输出不再被强制改为 DIRECT；真实副作用契约与工具包路由守卫继续有效。Router 判回 FAST 后仍执行能力升级检查；发现 Tool / Recall / Decision 需求后丢弃草稿、单向转入 STANDARD，不再次调用 Router 或 FAST。
- 图片和待授权状态禁止 FAST；Debug 强制 FAST 及 Router 判回 FAST 都不能覆盖这些硬条件。保留原有人工强制 FAST 的诊断功能：可覆盖普通 Gate 判定，但明确显示 debug_force_fast；仍执行能力升级及草稿丢弃检查。
- Owner QQ 私聊的既有 FAST 入口也消费多信号与快照，诊断保存完整三态结果；未进入 FAST 的 QQ 请求继续走外部认知及受限回复流程。

## 配置与 Debug

`.env.example` 已增加 JSON 配置示例，未指定字段使用默认值：

```dotenv
ZHAOXI_FAST_GATE={"strong_threshold":0.8,"conversation_threshold":0.75,"relevance_threshold":0.35,"sufficiency_threshold":0.55,"risk_ceiling":0.3,"fast_min_score":0.75,"fast_min_positive_votes":4}
```

继续使用现有 Runtime Observatory / Debug，新增 `fast_gate_version`、`fast_gate_decision`、所有信号、`fast_score` / `heavy_score`、FAST 正向依据、HEAVY 依据、`router_required` / `router_override` / `router_final_lane` / `router_to_fast_count`。前端以安全文本显示，不增加业务面板。

分数是本地规则的置信度指标，不是经统计校准的概率。该补丁优先将不确定输入交给 Router，后续可依据真实反馈调阈值。

## Fast Chat 单向能力升级

根据后续需求，Fast Chat 可在同一轮发现真实能力需求后放弃尚未交付的草稿。正常闲聊仍为一次无工具 LLM；升级轮多一次草稿判断，随后使用 STANDARD 的现有能力和权限流程。

- Fast Chat 在无 Tool Schema 的同一次调用中输出内部 `[escalate:tool]`、`[escalate:recall]` 或 `[escalate:decision]`。混有台词的结果整段丢弃；格式异常的保留标记也不会提交。
- 原生 Tool Call 及既有动作承诺检测继续触发升级。Debug 强制 FAST 只影响入口选择，不再跳过能力升级检查。
- Tool 进入标准工具链；Recall 使用标准检索和完整上下文，不强制多跑一个工具；Decision 触发现有按需评估服务，经 Guard 后由 Persona 表达。缺少 Decision 服务时继续使用标准上下文回复。
- Gate 直达 FAST 与 Router 判回 FAST 使用同一条接管路径。接管后不再调用 Router 或 FAST，结构上每轮最多一次 FAST → STANDARD。
- Fast 草稿在能力检查通过前不写 Conversation、Session、ExperienceStream、AutoMemory，不发 SSE 回复或中间气泡。升级失败同样不回填草稿；只保留标准流程的最终结果或错误状态。
- QQ 的现有受限标准回复同样丢弃 Fast 草稿；外部渠道的工具、资料和权限边界继续有效。
- Debug 新增 `fast_escalation_count`、`fast_escalation_kind`，并显示能力及升级次数。事件只含类型、原因与计数，不携带草稿正文或被丢弃的 Tool 参数。

## 七组任务书回归

| 输入及上下文 | Gate 结果 |
| --- | --- |
| 小金毛？ | FAST_CONFIDENT |
| 最近秋招真没啥结果；Current Cognition 有秋招主线 | FAST_CONFIDENT，近期认知为正向证据 |
| 书馆里未来开发计划9.21版，自己去看 | HEAVY_CONFIDENT，TOOL |
| 上轮缺 bug 记录文件；去补一份吧，把这个 bug 记录起来，我等下处理 | HEAVY_CONFIDENT，动作及承接证据 |
| LifeHUD 这个界面看着有点怪 | FAST_CONFIDENT，能力需求低 |
| 亚信上次具体问了我哪些题？ | HEAVY_CONFIDENT，精确历史需求 |
| 之前那个你觉得怎么样？；无消歧上下文 | AMBIGUOUS，Router 判断 |

## 验证证据

### 最终自动回归

- Python 全量：849 项通过、1 项跳过；现有 FastAPI / httpx 弃用提示 1 条。
- 前端 Node：52 项通过，包含 Gate 分数、信号、依据、Router 回落和能力升级展示。
- Gate 回归覆盖七组输入、正向 Recent / Current Cognition、配置校验、图片 / 权限守卫、索引失败、当前 trigger 排除、真实工具链及 Router 判回 FAST / 再升级。
- 能力升级回归覆盖草稿与标记混合、格式异常、真实记忆进入标准上下文、Decision Guard 调用、Router 回落后升级、权限确认、失败后不回填草稿、会话持久化、AutoMemory 输入、SSE 和 QQ 输出边界。

### 本机真实模型隔离验收

模型为当前配置的 `deepseek/deepseek-v4-flash`；使用合成近期状态、记忆、文档与面试历史及临时工具文件，不读写真实个人会话、Memory、Agenda 或书库。

| 验收 | 结果 |
| --- | --- |
| [Fast Gate 25 条](evidence/fast_gate_v2_real_provider.json) | 12 条 FAST 均为 Router 0 / 前台模型 1；7 条 HEAVY 均进入 TOOL 并获得成功工具回执；6 条 AMBIGUOUS 调用 Router，其中 5 条判回 FAST、1 条进入 DIRECT。模型、Gate、调用契约均无错误；两条 bug 记录请求实际写入隔离目录的 bug.md。 |
| [Tool / Recall / Decision 三类能力升级](evidence/fast_escalation_real_provider.json) | 强制 Gate 接纳以验证 Fast Chat 能力发现。Tool 3 次前台调用、Recall 2 次、Decision 3 次；三类均升级 1 次、Router 0 次，内部标记未泄漏。 |

### 复跑入口

以下命令使用当前环境；模型验收会调用配置的 Provider 并产生调用费用。报告写入指定路径。

```powershell
python -m pytest
node --test (Get-ChildItem tests/web/*.test.cjs).FullName
python scripts/smoke_fast_gate_v2.py --output fast-gate-report.json
python scripts/smoke_fast_escalation.py --output fast-escalation-report.json
```

## 使用与后续观察

重启 Core / 桌面进程后加载新 Gate，Debug 仍可查看每轮判定。25 条验收属于本机真实模型的隔离 Runtime 验收；用户桌面真实会话的自然措辞、显示效果和持续使用仍需观察。Current Cognition 主线任务要求的 3–7 天长期 dogfooding 尚未完成。

图片修复及其离线重放证据见 [v1.4.2 总开发记录](Zhaoxi_v1.4.2_开发记录.md)；修复后桌面真实模型复测仍待完成。
