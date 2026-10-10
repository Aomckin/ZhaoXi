# User Principles 自主摘要与原文优先

2026-10-06，根据用户要求，将 v1.4.7 首版只读 User Principles 改为朝汐可整理和写入的准则摘要索引。此记录取代旧发布说明中的“用户准则只读”限制；历史验收记录保留原版本事实。

## 当前行为

- 朝汐可在实际阅读用户资料后，用 `write_user_principle` 自己抽象总结并保存或更新摘要。稳定 ID 对应同一条索引，保留逐次修订。不增加独立总结模型，不按关键词自动决定用户偏好，也不在每次启动时全量重建摘要。
- `read_decision_context` 新增 `sources=["user_archive"]`，动态发现 `archive_directory/user` 下的 Markdown 和 TXT；默认目录为 `data/archive/user`。新增、修改或替换版本的文本资料，下次查询即可读取，原配置中的补充 archive 路径仍保留。
- `user_principles` / `principles` 查询优先返回当前用户原文，再提供少量摘要索引；`limit=1` 时优先原文。摘要是检索线索，不等于用户逐字表达或明确确认。用户当前表达和原文优先于摘要及判断经验。
- 保存时验证 `archive:user/...:L行号` 和指定片段内的逐字引文，保留原文摘要哈希。越界路径、朝汐 archive、虚构引文、无效行号均不能写入。朝汐写入标记 `zhaoxi_summary`，Owner 管理页修订标记 `owner`。
- 原始资料变化或消失时，管理页显示需要复查，按需查询不继续使用该旧摘要；后台反思同样回查所引用的当前原文。读取后可重新整理对应 ID，不修改原始 archive 文件。

## 对应入口和存储

“判断与成长”中的 **User Principles · 准则摘要索引** 支持查询用户原文、用原文填写摘要依据、新增或修订摘要、回查原文和查看修订记录。朝汐摘要与 Owner 索引分别显示作者。

`POST /api/decision/user-principles` 保存索引，`GET /api/decision/user-principles/{id}/revisions` 查看修订，沿用本地认证和 Owner 私密边界。工具默认允许本地摘要写入，公开或群聊上下文仍不可读写个人决策资料。

数据继续位于 `decision_user_principles_directory`（默认 `data/decisions/user_principles`）。`revisions.jsonl` 是新写入的权威记录，每条 `{id}.json` 是原子替换的索引；索引写入失败或丢失后仍能由已提交修订读取。旧 JSON 无需迁移。整目录仍由既有 Backup Registry 备份，朝汐新生成的私密索引和修订日志沿用 Git 忽略规则。

## 验证与加载

新增回归覆盖原文验证、路径和私密边界、修订恢复、重复保存幂等、新版资料发现、原文优先、原文改变/丢失后的旧摘要排除、主模型读取后写入的完整工具链，以及认证 API。管理页使用真实 HTTP 与 headless Edge 检查摘要标识、原文回查、保存、修订和刷新恢复。

相关 Python 回归 **249 项通过**；最后原文路径归属边界调整后新增专项 **14 项通过**；最新 Node **98 项通过**，浏览器 **7 项通过**。上述范围不表示重跑了整个仓库的全部测试，未调用真实模型。结果与范围见 [验收证据](evidence/2026-10-06-user-principle-summaries.json)。仅使用隔离合成资料，没有让模型改写真实用户 archive 或现有准则；未重启正式实例。退出并重新启动整个朝汐进程，再刷新管理面板后加载新增工具和入口。
