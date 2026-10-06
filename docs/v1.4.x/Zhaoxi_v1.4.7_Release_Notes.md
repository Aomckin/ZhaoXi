# Zhaoxi v1.4.7 · Decision Learning

2026-10-04。按 [开发任务书](Zhaoxi_v1.4.7_Decision_Learning_Decision_Journal_开发任务书.md) 实现决策反馈、判断日记与低频回访。

- Choice History 升级 schema v3；兼容旧 v1/v2，反馈、回访、反思与日记链接继续追加事件。
- 结果反馈支持 GOOD / BAD / NEUTRAL / MIXED / NO_DIFFERENCE / UNKNOWN，保留用户原话、最终选择和覆盖记录。
- User Principles 独立只读索引，保留《决策协议》来源与原文段落；《先声》标为朝汐的理解稿。
- 后台 Reflection 可形成、支持、修正、削弱、标记冲突或退役 Decision Journal。人工锁定保留正文，单次置信度变化最多 0.15；不自动修改用户准则。
- 回访、反思与日记维护复用 Internal Activity，遵守 Presence、前台让路、预算与冷却。默认回访最多 2 次/日、至少间隔 6 小时，同一选择最多主动问一次。
- `read_decision_context` 按需查询 user_principles / decision_journal，principles 保留兼容别名；普通 PICK 保持一次主模型调用。
- 管理面板新增“判断与成长”，可录反馈、取消/立即回访、查看反思、编辑/锁定/退役日记及展开原始依据。
- 回复分组修复：表情 DSL 的正文与图片分段共用同一次回复，实时输出、历史恢复和重新生成按整组处理；工具完成后的重试保留结果，图片末段也可重试。

验收按阶段保留，以下数字不表示最终补丁后重新运行了全部 Python 测试：

| 验证阶段 | 结果 |
| --- | --- |
| Decision Learning 开发期全量 Python | 1298 通过，1 跳过 |
| Decision Learning 最终专项 | 130 通过 |
| 回复分组补丁 Python 回归 | 95 通过 |
| 最新前端 Node 测试 | 94 通过 |
| 判断与成长 / 回复分组浏览器检查 | 分别 9 项 / 5 项通过 |
| 真实模型隔离合成场景 | 5 项通过，早期失败尝试保留 |

安装包已重新生成，293 个源码与静态资源逐字节核对通过。验证范围见 [开发记录](Zhaoxi_v1.4.7_开发记录.md)、[自动验收汇总](evidence/decision_v147_acceptance.json) 和 [回复分组修复证据](evidence/reply_group_v147_patch.json)。

退出并重新启动整个朝汐进程，刷新管理面板后加载。默认启用；`ZHAOXI_DECISION_LEARNING_ENABLED=false` 可关闭学习与相关活动，`ZHAOXI_DECISION_MODE=legacy` 仍可回滚旧决策路径。第一版用户准则只读；变更明确原则应由 Owner 修改结构化索引并保留来源，不由模型代写。

自动测试、浏览器和模型测试使用隔离资料。真实日常长期效果、QQ 私聊回访、跨设备交互及任务书 A–F 的长期 Dogfooding 仍需实际使用观察。

## 2026-10-06 运行维护补丁

版本仍为 v1.4.7。补齐 FAST 升级工具额度、安全的明确重试、启动事务恢复与健康显示、群图工具结果批次及当前多图模型视图。历史图片数量限制已取消；Token / Planner 预算控件仅放 Web Dashboard。pytest 临时文件统一归入 `.pytest_cache/`。

逐项行为、隔离验收和正式加载边界见 [维护总览](../maintenance/2026-10-06-runtime-repair-summary.md)。上述 10 月 4 日安装包与测试数字保留为历史证据；此次未重新生成安装包、发布或执行真实业务复验。
