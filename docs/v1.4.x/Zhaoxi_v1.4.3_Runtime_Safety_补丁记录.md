# Zhaoxi v1.4.3 Runtime Safety 补丁记录

2026-10-01。对应 [Fast Escalation / Tool Repair / Budget Safety 任务书](Zhaoxi_v1.4.3_Fast_Escalation_and_Tool_Repair_Safety_Patch.md)。包与运行时版本保持 `1.4.3`，本补丁不需要数据库迁移，也不重构 Fast Gate、Planner 或 LifeHUD API。

## 行为与约束

### FAST 当前消息校验

Fast LLM 输出结构化内部申请 `kind / reason / trigger_span`。Runtime 验证种类、非空原因、原话片段及当前消息的相应行动 / 回忆 / 决策意图；历史对话不参与校验，引用和否定行动不授予执行意图。旧的短标记仍可兼容，但同样必须通过当前消息的证据检查。

“台账先挂着”之后只说“小金毛”，不会因为旧任务而接受升级；“那就把台账补一下吧”可以通过。拒绝时丢弃整份草稿，最多补一次无工具 FAST 回复；补答若继续申请升级、调用工具或承诺执行，使用固定聊天回复。草稿和内部标记不交付、不持久化。升级单向、每轮最多一次，已接受的升级不会重入 Router 或 FAST。

### STANDARD 请求内限制

| 约束 | 普通 STANDARD | 经 FAST 升级 |
| --- | --- | --- |
| 模型轮数，含收尾 | 3 | 2 |
| 含业务工具调用的模型轮数 | 2 | 1 |
| 修复轮数 | 1 | 1，同时受左侧模型 / 工具限制 |
| 同一错误重试 | 最多 1 次 | 同左，但可能先触及更严格轮数上限 |
| 同一工具失败 | 最多 2 次 | 同左 |

`ZHAOXI_STANDARD_MODEL_ROUND_LIMIT / TOOL_ROUND_LIMIT / REPAIR_ROUND_LIMIT` 在 `.env.example` 有说明。限制和成功 / 失败记录存在请求内状态，不依赖 Observatory 是否启用；权限暂停与恢复共用状态，不重置轮数或锁。

错误指纹结合工具名、稳定错误码、归一化错误和参数形状；改变参数值或动态数字不能无限绕开上限。同类错误第二次出现或同工具第二次失败后锁定该工具并进入收尾。结果未知的写入与拒绝授权不会自动重放。

已经调用的工具仅发生参数错误时，不再重新查目录或加载能力组；真实缺失 / 不可用能力仍可查询。同请求内 `search_memories` 的相同和高字面相似查询复用成功或失败结果，非 query 参数必须一致。这是保守的文本归一化与相似度检查，不声称识别任意语义同义句。

连续两轮没有新事实、成功操作、错误解决或状态变化时强制收尾。目录首次返回的新信息算进展，重复目录返回不算进展。最后模型轮移除工具；即使模型仍产生工具调用，也不执行。

默认上限意味着“读取 → 更新 → 再读取验证”不能无限续跑：前两轮已完成操作会保留，但第三次验证不执行，不能据此声称已核验。明确需要更长链路的调用者可配置轮数；现有多轮能力加载测试使用显式较高配置，生产默认值保持上述约束。

### 预算收尾和真实结果

- NORMAL：执行原任务。
- WARNING：保留已知主任务能力，禁止额外 Recall、能力发现和无关新支线。
- DANGER：停止新工具、修复和 Planner 步骤，只允许无工具收尾；每个同批调用前重新检查状态。
- EXHAUSTED：直接生成确定性回复，包含已完成、未完成、未执行和结果未知的操作；即使没有任何工具结果，也给出明确正文。

确定性回复不依赖模型；预算或模型调用上限异常也进入这条路径。部分成功不回滚、不抹除；修正成功的参数校验错误标记为已解决。冻结的授权批次及剩余调用也受运行时限制，未执行项不算完成；同批用户批准的项目仍按原权限合同处理。

新增整体 `result_status` 为 `completed / partial_success / failed / budget_exhausted`。保留原 ActionTrace 的操作状态与已有取消合同。正常完成后的有界无工具收尾仍可报告 completed；预算耗尽时整体为 budget_exhausted，同时 `partial_success` 和操作记录保留已完成部分。成功生成 fallback 时 `response_status=succeeded` 表示已交付说明，不代表全部业务成功。

每请求最多一次额外预算申请，拒绝也消耗申请次数；只允许已有进展、剩余一步可完成的申请，连续失败不扩容，DANGER 后不扩容。Planner 按现存计划核对剩余步骤。普通 STANDARD 不自动扩容拖长修复链。第二次扩容配置仅为旧配置兼容保留，不授予第二次申请。

## Observatory

复用 runtime_metrics 和 ActionTrace，增加升级 requested / validated / rejected_reason / trigger_span、工具 failure_fingerprint / retry_count / locked、STANDARD model / tool / repair round、budget_state / remaining_ratio、forced_finalization_reason、partial_success、deterministic_fallback_used 及 result_status。网关 activity 同步最终结果状态。可以区分业务没有完成和回复说明已正常生成。

## 自动验收

| 任务书用例 | 自动证据 |
| --- | --- |
| A 旧任务 + 昵称 | 强制三类坏草稿均拒绝升级；拒绝补答不可偷偷执行工具。 |
| B 明确承接 | 当前原话通过，严格升级预算独立于 Trace。 |
| C 首次失败 | 允许一次修复；修正成功后保留结果并解除该次错误的未完成标记。 |
| D 同类第二次失败 | 同指纹和不同错误均受同工具失败上限约束，锁定后收尾。 |
| E 重复检索 | 归一化高相似查询不再次执行，过滤参数不混用。 |
| F 参数错误后查能力 | 主循环及权限续跑冻结尾部均拒绝重新发现。 |
| G DANGER | 无工具收尾；同批第一项消耗至 DANGER 后第二项未执行。 |
| H EXHAUSTED | 无模型调用仍返回非空事实说明；保留成功 / 失败 / 未执行差异。 |

还覆盖 WARNING 主任务 / 新支线、连续无进展、修复后状态、缺失 reason、权限暂停和恢复、未知写入锁、实际缺失工具的目录例外、续跑失败指纹和非 STANDARD 预算指标。主要用例见 `tests/core/test_loop_safety.py`，预算、Planner、入口、权限和旧多轮调用回归同步调整。

最终完整 Python 回归：996 passed、1 skipped，196.06 秒；保留一个 Starlette/httpx 依赖弃用警告。Node 回归：61 passed。测试临时目录统一 `.zhaoxi/test-tmp`，原始输出在 `.zhaoxi/loop-full-final.log` 和 `.zhaoxi/loop-node-final.log`，不进入仓库根目录或版本提交。

## 真实模型验收与运行边界

[真实模型合成证据](evidence/runtime_safety_real_provider.json)：通过真实配置的模型服务和隔离 `InterfaceGateway DESKTOP` 入口执行两例。A 保持 FAST、0 升级 / 0 工具；B 使用 Debug 强制进入 FAST 以覆盖升级路径，升级通过一次，2 STANDARD 模型轮、1 模拟工具轮，result_status=completed。旧上下文坏申请另用确定性注入首草稿、真实模型完成拒绝补答，升级次数与工具次数均为零。

模拟台账仅为内存工具，不访问或改动正式台账，不发送 QQ 消息。早期桌面合成夹具曾遇到断言失败、网络超时和空正文；最终把模拟工具明确设为已在手边，并使用 2400 输出上限后通过，相关情况保留在证据说明。真实模型最终正文仍可能包含夹具中的技术术语；此处验收的是运行时限制，不把夹具回复作为产品话术。

本轮没有重启已运行桌面实例；以上是源码及真实模型网关验收，不等同于本机原生窗口加载补丁后的验收。正式 LifeHUD / NapCat 实机操作和 Dogfooding 不包含在本次合成验收中。重启后现有 editable 安装才会加载更新源码。
