# QQ 普通成员定向回复与 Planner 退场

日期：2026-10-13（Asia/Shanghai）。用户已明确授权“放开对普通成员的自动回复，防 bot 互答规则不动，然后 QQ 回复禁用 Planner”。本记录更新此前 [@ 无回复排查](2026-10-13-qq-mention-no-reply.md) 中暂缓的回复策略边界。

## 行为

- 普通真人群友明确 @ 朝汐、引用朝汐回复，以及普通真人 QQ 私聊进入原回复链；不要求问句/请求关键词，不使用原非 Owner 的 5 分钟同人冷却和 45 秒会话冷却。
- 人格、历史和图片仍由既有回复链处理；非定向群消息继续进入原 Ambient 路径，不因为开放定向聊天而对每条群消息自动发言。
- bot 判断仍来自 sender_is_bot 元数据或已知 bot ID。bot 的明确请求校验、24 小时互答回看、Owner 介入条件与 45 秒会话保护不变，Owner 的原豁免不变。bot 的识别来源和名单不变。
- QQ 定向回复跳过 ExternalCognitionPlanner.decide，且不再提前构建其上下文；通过守卫的 QQ 消息直接进入已有标准回复或符合条件的 Owner 私聊 FAST 路径。实际回复、合法的群历史查询和输出边界继续生效；不把对话消息转成工具执行授权。
- QQ Ambient Snapshot 的后台认知整理保留原流程；本次禁止的是回复前的 Planner 闸门，不改其他来源的 Planner、群聊自主发言或后台认知设置。

## 真实记录回放

读取原生产 Observation 和 Experience 只读副本，对刚才半小时的四条真实 @ 输入运行当前 PerceptionRuntime.ingest，使用既有内存 Session 存储和隔离 Perception 数据库；在真实回复模型入口截停，不编造正文，不调用 Provider 或 QQ 发送。

4 条记录（19:23:29、19:31:04、19:44:46、19:45:54）均到达 channel reply 入口；3 条普通成员原先的 no_explicit_request 变为允许，Owner 继续允许。Planner 入口 0 次，Planner 上下文构建 0 次。

用 10-10 以来实际收到的 7 条 bot 定向消息与修改前函数对照，保留当时可见的回复/Owner 介入上下文，结果一致：6 条 no_explicit_request、1 条允许。原 bot 分支的条件和常量不变；本次真实样本没有覆盖所有冷却分支，不把抽样结果写成线上全情形验收。另核对 1,488 条非定向群消息仍为 not_directed。

证据见 [脱敏回放记录](evidence/2026-10-13-qq-direct-reply-policy.json)。Python AST 和差异检查通过；未以合成测试案例或假模型正文作为日用验收。原始记录和回放脚本留在 `.pytest_cache/qq-direct-reply`，不提交。

## 加载

源码已修改，正式 Core 未重启，没有重放或补发刚才的消息。重启 Core 后新来的 QQ 消息使用新规则；实际速度和模型正文质量需加载后观察，不能把移除 Planner 估算为固定时延保证。
