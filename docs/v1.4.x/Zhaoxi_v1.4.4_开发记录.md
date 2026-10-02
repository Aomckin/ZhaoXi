# Zhaoxi v1.4.4 · Presence 2.0 开发记录

日期：2026-10-02。依据 [开发任务书](Zhaoxi_v1.4.4_Presence_2.0_A_Life_Between_Conversations_Task.md)。
代码阶段覆盖 Phase 1–7；Phase 8 的 5–7 天真实使用观察待完成。没有将自动化测试等同于真实 QQ / 桌面长期验收。

## 实现与兼容

保留 v1.2.8 的 internal-activity.db、activity_state、dirty / cooldown / failure backoff、手动触发和 Proactive 回调。旧活动由 activities/legacy.py 适配，Runtime 按 Registry 调用 handler 与 candidate；注册新 ActivitySpec 即可扩展。新模型包括 Category、六种 CostClass、PresenceStates、消息权限和统一 ActivityResult。

Presence 支持 ACTIVE / SEMI_ACTIVE / IDLE / AWAY / SLEEP。Owner 网关（含重新生成和权限续跑）以及明确的外部 Direct Trigger 在入口抢占可取消的后台活动。实际前台处理中暂停后台；AWAY / SLEEP 只进行本地日程核对和允许的重要提醒。Sleep 可在 Debug 强制，自动睡眠时段需单独开启。

每 tick 分别限制 LLM light / heavy、总 LLM、本地活动、外部读取及写入。复合社交活动提前预留读取、模型和写入资源。Debug 不绕过资源上限、社交开关、白名单、每日写入预算或渠道冷却。失败会留 dirty 并递增退避；维护债务未消化时阻止 Leisure / Social。选择疲劳按活动的连续 tick 降权，维护债务判断使用原始优先级。

## FAST 与认知整理

前台仅在交付后给原 ExperienceStream Owner event 标记 dialogue_lane，不增加模型调用或重复数据库。fast_digest_cursor 和 pending_fast_signal_count 保存在既有 activity_state。

Digest 分批读取可信 Owner 的 FAST 消息，寒暄或没有跨轮重复信号时本地 NO_CHANGE 并提交游标；值得消化时最多一次有界模型调用，复用 CurrentCognitionPatch 的 Owner 证据与来源校验。拒绝/失败不提交游标。Digest 不移动正常 Maintainer 的游标，不调用 AutoMemory，不重新抽取全部 FAST 对话。

Cognition Gardening 使用本地结构规则合并同 key Thread、清除 resolved/stale、降低 salience、整理 changes/watch 和缺失 event 证据。它处理已有结构，与 Maintainer 处理新输入分开。

## Memory / Cluster / Reminiscence

Memory Gardening 有界处理既有记录：复用 lifecycle 与精确语义去重、SUPERSEDES 修复；标记缺失证据、过热、冲突、低价值噪声，生成近重复/矛盾复核候选。候选不当作确定事实，整理不会新建 Memory。后台维护关闭旧的自动全量 split 与组织流程。

Cluster Gardening 用已有兼容向量归簇孤儿、刷新 dirty Cluster 的 summary / centroid / representatives，生成 merge / split / drift 候选。每批最多 10 个孤儿和 10 个簇；不发 Embedding API 请求，也不执行全量 recluster。缺向量只标记 repair candidate，留给显式维护。簇合并候选采用有界索引查询，后台不调用原有全簇合并循环。

Reminiscence 优先 COLD / DORMANT、中高 importance、至少 30 天未创建/访问的记忆；默认每 4 小时最多一次、每日 2 次，同一 Memory 至少 14 天冷却。可新增轻量 RELATED_TO；没有可靠关系就 NO_CHANGE。重温信息原子合并到 Memory metadata，保存 last_reminisced_at / count / result，activation、access_count、accessed_at、updated_at 均不增加。没有把重温当作外界重新确认。

## Social

Social Lurk / Wander 默认均关闭，只使用明确配置的 QQ 群白名单。第一版从 Perception 已接收缓存中读取当前授权群近一小时最多 20 条 Observation；不主动调用 NapCat 拉全群历史、不枚举群、不私聊。SQL 在 LIMIT 前限定 plugin / group / conversation_kind。

Lurk 总是 NO_MESSAGE。Wander 大部分保持 LURK / LEAVE，少量机会以单次轻模型提出 REACT / CHAT。Public Social Context 使用独立的公开 persona、显式公开兴趣与当前群经筛选的第三方文本；不读取私有 Current Cognition、Memory、Agenda 或 Owner 消息。群文本是不可信数据。

外发走 Privacy Gate 的 ALLOW / REWRITE / REJECT，保守阻止 Owner 代言、求职/家庭/私聊/跨群/时间/联系方式/密钥等内容。它是上下文隔离与本地规则组成的防线，不声称能识别任意表达方式的全部隐私；真实社交仍需要持续验收。

消息经既有 PluginRuntime.send，target 与 ExperienceStream 都记录 source_plugin=qq_napcat、channel=qq、conversation_id、conversation_kind=group、actor_role=SELF。不会伪装 Owner。默认群写入 cooldown 45 分钟、每日 6 条；没有回复和重复话题进一步降频。发送前先持久化预算与 cooldown，失败或结果不确定也消耗一次机会，避免重启重复发言。

手动 Wander 有二次确认；拒绝确认或手动 tick 未确认时只读/生成候选，不发消息。Direct @ / 明确回复继续走原 External Trigger。前台可取消读取与生成，已经开始的外部发送作为提交边界完成并记录，避免把已发送内容误记成取消。

## Debug 与界面

维护抽屉加入所有新活动手动入口以及 IDLE / SLEEP；现有认证仍生效。Debug 展示当前 Presence / activity、last activity、候选与选择/跳过原因、next eligible、tick 与 daily budget、FAST cursor、重温统计、社交 cooldown/action/privacy trace。ACTIVITY_* 日志持久保留最近 200 条，Debug 返回最近 80 条。

小桌边/陪伴窗口只显示自然活动文字，经 SSE 实时更新并由原 30 秒状态轮询恢复；预算、优先级与 activity ID 留在 Debug。

## 配置与上线

所有配置使用项目既有 ZHAOXI_ 前缀，完整示例见 .env.example。无需新增 Memory schema 或离线重抽记忆；activity_events 为既有内部活动库的增量表，重温字段使用既有 Memory metadata。

关闭 ZHAOXI_PRESENCE_V2_ENABLED 可回退到旧活动集合。保持两个 Social 开关为 false 可先只验收内部生活；开启社交需要同时配置白名单与启用的 QQ 插件。睡眠自动时段默认关闭，避免改变现有夜间行为。

本版代码与文档整理为本地版本提交，未推送或外部发布；没有重启用户已有桌面实例，没有修改生产记忆库或实际向群发送测试消息。源码更新后需重启 Core 才能加载，静态页面需刷新。

## 验收证据

测试使用独立临时库和合成 Provider / SendResult。新增覆盖寒暄 NO_CHANGE、跨轮日语 Thread、游标失败恢复、证据身份、结构整理、精确去重、簇 split candidate、重温无热度膨胀、每日限额恢复、社交白名单与来源隔离、Privacy Gate、手动确认、渠道冷却、前台取消以及发送提交边界。

开发验收（2026-10-02）：Python 全量 **1035 通过、1 跳过**；Node **64 通过**；编译检查与 git diff --check 通过。最终 wheel 构建通过，247 个 Python 源文件与开发验收时的源码逐一一致。证据见 [自动验收汇总](evidence/presence_v144_acceptance.json)。

兼容验证覆盖旧小桌边无 Runtime 时的响应结构；仅在 Runtime 存在时附加 Presence 字段。全量回归使用独立临时目录，现有 Starlette/httpx 弃用提示不影响结果。venv 没有 setuptools，打包使用本机已有 Python 3.13 / setuptools 75.5，无安装依赖或网络下载。

构建产物为 .zhaoxi/v144-dist/zhaoxi-1.4.4-py3-none-any.whl，SHA-256：b975f1bc9338898b6e2ee9c03c5cf49991d3a7ff437b8d0c90d4bd86126ccf9a。

待真实验收：当前桌面视觉与 Core 重启加载、授权 QQ 群真实只读/发言、5–7 天 token 开销/噪声/热度/隐私/自然性观察。此阶段保持 Social 默认关闭。
