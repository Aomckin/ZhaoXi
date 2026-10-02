# v1.4.4 任务书核对

日期：2026-10-02。此表核对代码与自动化场景；真实环境项仍单独保留，详见 [版本说明](Zhaoxi_v1.4.4_Release_Notes.md)、[开发记录](Zhaoxi_v1.4.4_开发记录.md)与 [自动验收汇总](evidence/presence_v144_acceptance.json)。

| 完成标准 | 代码与证据 | 状态 |
| --- | --- | --- |
| 1 保留旧 Runtime | activity_state 原结构继续使用；legacy adapters 保留五个活动 | 代码已实现 |
| 2 Registry 扩展 | ActivitySpec / ActivityResult / Registry；自定义 slow_lurk 验证注册与运行 | 自动验证通过 |
| 3 Presence 正式关系 | 五态、spec.presence_states、前台入口计数与 Sleep 可选时段 | 自动验证通过 |
| 4 半活跃多活动 | 调度认知、Memory、Cluster、Digest、Reminiscence、可选 Social | 自动验证通过 |
| 5 FAST 后台消化 | 独立持久游标；无趋势零模型；趋势一次模型；失败不前进 | 自动验证通过 |
| 6 Cognition Gardening | 本地合并、冷却、resolved/stale 清理、证据检查 | 自动验证通过 |
| 7 Memory 整理 | 本地生命周期/精确去重/关系修复、冲突与缺失证据复核候选；不建新 Memory | 自动验证通过 |
| 8 Cluster 增量整理 | 兼容向量归簇、dirty refresh、merge/split/drift 候选；禁止后台全量聚类 | 自动验证通过 |
| 9 低频重温 | 旧冷记忆、中高重要性、每日及单条 cooldown | 自动验证通过 |
| 10 无 activation 膨胀 | metadata 原子合并；热度、访问时间/次数均保持 | 自动验证通过 |
| 11 Lurk 只看 | 读取已有授权群缓存，NO_MESSAGE | 自动验证通过 |
| 12 whitelist | 开关与 whitelist 不被手动 force 绕过；按 plugin/group/kind 隔离读取 | 自动验证通过 |
| 13 SELF | ReplyTarget 与 CognitiveEvent 全部 SELF，不注入 Owner 私有上下文 | 自动验证通过 |
| 14 Privacy Gate | 输入过滤与输出 ALLOW/REWRITE/REJECT；拒绝稿不调用 Send | 合成场景通过，真实社交待观察 |
| 15 社交 cooldown/daily | 持久每日写入计数、同群 cooldown、无人回应/重复话题降频 | 自动验证通过 |
| 16 Owner 抢占 | 网关/External Direct 入口取消可中断任务；发送提交边界完成记录 | 自动验证通过 |
| 17 小桌边自然活动 | SSE 与恢复轮询，自然文本清除、literal text 安全展示 | 自动验证通过，真实桌面视觉待验收 |
| 18 Debug 解释 | 候选/理由/预算/游标/社交 trace/next eligible/timeline，认证 HTTP 接口 | 自动验证通过 |
| 19 默认静默 | 无消息活动消息权限为 false；手动 tick 无社交发言授权 | 自动验证通过 |
| 20 自然空闲生活 | clean 可 NO_ACTIVITY；资源约束与疲劳已实现 | 5–7 天 dogfooding 待完成 |

自动验收：Python 1035 通过、1 跳过；Node 64 通过。wheel 构建通过，247 个 Python 源文件一致；[汇总证据](evidence/presence_v144_acceptance.json)。

## 交付边界

- Social 默认关闭，未替用户配置或开启真实群；第一版使用现有 Perception 已接收的授权 QQ 群缓存。
- 未重启正在运行的桌面 Core；源代码版本 1.4.4，旧进程仍可能运行 1.4.3。
- 未迁移生产 Memory，没有通过实际发群消息验证隐私或自然性。
- 不把合成 Provider 验收写成真实模型验收，不把自动回归写成长期使用观察。
