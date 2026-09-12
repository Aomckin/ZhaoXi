# Zhaoxi v1.1.5 Release Notes

## 本体主权

Zhaoxi Core 不导入任何 Life HUD 实现。LifeHUD-Tool 1.1.0 作为可选能力包存在；禁用、未安装、不可达或 schema 异常都不会阻断聊天、Memory、Archive、State、Proactive、Reflection、Planner、Workflow 或 Desktop Presence。

## Tool Package 生命周期

加载流程为 discover → enabled → SDK compatibility → configure → declared capability registration → optional health。

通用总开关：

```env
ZHAOXI_TOOL_LIFEHUD_ENABLED=true
```

分项开关：

```env
ZHAOXI_TOOL_LIFEHUD_TOOL_ENABLED=true
ZHAOXI_TOOL_LIFEHUD_WORKFLOW_ENABLED=true
ZHAOXI_TOOL_LIFEHUD_ROUTER_HINTS_ENABLED=true
ZHAOXI_TOOL_LIFEHUD_PROACTIVE_ENABLED=true
ZHAOXI_TOOL_LIFEHUD_REFLECTION_ENABLED=true
ZHAOXI_TOOL_LIFEHUD_STATE_SIGNALS_ENABLED=true
```

包默认只发现、不启用；只有显式配置 `ENABLED=true` 才装配。禁用包不会构造 Client、注册任何能力或访问网络。Diagnostics 分别公开 installed、enabled、configured、reachable、healthy、capabilities、requires_sdk 和 backoff_until。

## 公共 SDK 与 Capability

新增 `zhaoxi.sdk` 1.0，公开 Tool/Result、Permission、CapabilityDeclaration、Package/Provider Protocol、StateSignal、SignalAggregator、Reflection/Proactive 数据契约和包侧 Retry。LifeHUD-Tool 只从该公共入口导入。

CapabilityDeclaration 字段：tool、workflow、router_hints、proactive_provider、reflection_provider、state_signal_provider。未声明或被配置关闭的能力不会装配。

## State 与主动性

StateSignal 包含 type、value、observed_at、expires_at、confidence、priority、source 和 metadata。Aggregator 按 TTL、priority、confidence 与观察时间解析冲突。

Interaction State 保留 ACTIVE、SEMI_ACTIVE、IDLE、AWAY；Interruptibility 独立为 HIGH、NORMAL、LOW、BLOCKED。Life HUD Focus 只报告 `attention.focus=active`：`ACTIVE + Focus` 的结果是 ACTIVE + LOW。

ACTIVE 现在表示持续对话。存在 open thread 时，沉默 3 分钟后可进入独立 Conversation Continuation 判断；默认冷却 5 分钟、每个 ACTIVE window 最多 3 次。SEMI_ACTIVE 继续承载普通 Heartbeat 与可暂存但不自动发送的 BackgroundIntent。AWAY 返回仍先进入 SEMI_ACTIVE。

## Life HUD 边界

- 现有 10 个 Agent Context 读操作与 Focus start/complete HTTP 契约不变。
- Focus 写入标记为 `EXTERNAL_SERVICE_WRITE`，不再伪装为 Core 的 LOCAL_STATE。
- 后台采样失败使用 2、5、15、30 分钟渐进退避，成功后自动恢复两分钟正常采样。
- Proactive、Reflection、State Signal 和 Workflow provider 分别隔离异常。
- 删除重复的 `capabilities()` 实现。
- 铁幕路由要求明确命令；普通文本中的“开幕/落幕”不再强制触发 Workflow。
- 认知路由读取有界的最近对话用于解析短句指代；“你明明可以查到的”等承接语在最近上下文命中 Tool Hint 时强制进入 TOOL，模型只口头承诺查询时会纠正重试，不能直接结束回复。

## 双事实源

新增统一 provenance 模型：source、domain、observed_at、valid_at、confidence、authority、external_ref。结构化生活事实优先当前可用的 Life HUD；经历、感受和对话语境优先 Memory；正式设定继续遵循当前用户指令 > canonical Archive > Memory。解析只选择回答依据，不删除或覆盖另一来源。

## 人格与表达方式分层

人格 Prompt 与表达方式 Prompt 改为两个独立、版本化的 YAML 输入。`zhaoxi_v1.yaml` 只维护身份、关系、性格与长期设定；`expression_v1.yaml` 独立维护语气、节奏、情绪表达、格式偏好和角色表达克制。`ContextBuilder` 以人格 → 表达方式 → 运行规则的固定顺序组合，普通对话、Tool/Workflow 最终回复与主动消息共用同一组合结果。

## 验证

- 覆盖包缺失、禁用零网络、服务不可达、恢复采样、分项开关、SDK 边界、StateSignal 聚合、ACTIVE + Focus、Continuation 冷却/预算、双事实源、人格/表达方式分层及路由误劫持。
- 397 项 Python 测试通过、1 项 Windows symlink 权限测试按预期跳过；19 项 Node 前端测试通过。
- 现有 Life HUD、Memory、Archive、Proactive、Desktop、Workflow 与发布测试保持兼容。

手动验收确认：禁用时 doctor 显示 installed=true、enabled=false、无 Tool/Capability 且不执行 health 请求；显式启用后，当前本机 Life HUD 返回 reachable=true、healthy=true；“那个电影节今天开幕了”保持 DIRECT，“朝汐，开幕，完成 v1.1.5”进入既有铁幕 Workflow。

## 已知限制

- Health 为短超时同步诊断或后台采样结果，不提供持续连接。
- Conversation open-thread detection 是低成本启发式，不是完整意图图谱。
- BackgroundIntent 仅提供最小可存候选接口，本版本不自动制造或推送 surprise。
