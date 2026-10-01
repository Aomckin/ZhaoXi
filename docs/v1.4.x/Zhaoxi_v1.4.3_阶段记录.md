# v1.4.3 早期阶段记录

归档日期：2026-10-01。本页保留正式迁移之前的副本预演与开发证据；旧测试数量、思考预算和未启用状态仅代表当时阶段。当前版本以 [版本说明](Zhaoxi_v1.4.3_Release_Notes.md)、[最终开发记录](Zhaoxi_v1.4.3_开发记录.md)及 [任务书核对](Zhaoxi_v1.4.3_任务书核对.md)为准。

以下保留最初副本验收与开发过程，旧测试数字、2000 token 预留和“原库未迁移”均仅代表当时状态；当前以上方收尾为准。


2026-10-01：已恢复开发。代码未提交或发布，原业务数据库未执行离线迁移，现有应用保持运行状态。需求依据：[Memory 3.0 开发任务](Zhaoxi_v1.4.3_Memory_3.0_Broad_Memory_Careful_Recall_Task.md)。

## 实现与本次修正

- importance、activation、contextual_relevance 分离，删除运行时旧 relevance。ACTIVE / COLD / DORMANT / ARCHIVED 自然衰减；FORGOTTEN 保留给明确遗忘。三种召回模式分别限制状态、热度与上下文。
- 簇优先检索与有界 FTS / 语义 / 实体 / 近期逃逸候选联合召回。SQL 先过滤状态再截断候选，避免被已遗忘记录占用名额；选中簇共享候选预算，各全局通道保留名额；维度 postings 与 Memory 状态过滤使用覆盖索引，避免逐特征回表；全局命中记录展示其实际簇；空查询不沿用旧 Inspector 轨迹。
- 聚类以语义为主要信号，领域作为软先验。朝汐、开发等泛词不再决定领域，ASCII 关键词有词边界；成员、合并与迁移降温后重新计算簇的质心、领域、类型及热度，单条无相似同伴的记忆保持孤立。正文中的明确主题优先于无关旧 tags；不同已知领域软降权，未知的任意 tags 不当作领域冲突。
- AutoMemory 普通批次最多 3 条，长输入最多 5 条，每条 240 字；运行时控制热度、来源、证据与 pinned，丢弃模型伪造的运行时字段。无法可靠解析的相对事件时间置空，保留正文事实；Memory 与 Current Cognition 的维护失败分别记录。
- 记忆上下文只注入被选记录，不复制簇摘要或标签，避免带入未选或已遗忘事实。XML 属性转义、完整标签和字符预算已覆盖。书库按标题 / 路径 / tags 提供引用线索，正文读取进入工具流程。
- 版本化语义提供者固定 model / version / dimensions，空间不一致时不比较向量；服务失败降级为词法检索并记录错误类别。离线 Embedding 每批最多 10 条，按返回 index 恢复顺序，验证维度与非零有限值，已兼容的向量复用。
- 离线审计、快照预演、备份、取消和恢复；图片共享内容寻址 blob、旧图片迁移与会话 VACUUM；Experience 过期清理只读列元数据，旧因果迁移通过 blob 编解码读写，避免将 blob 字典当作图片 URL 导致启动失败；Inspector 展示簇、候选、排除理由、漏斗和数据库指标。

主要新增模块：`memory/candidate_index.py`、`memory/search.py`、`memory/clustering.py`、`memory/migration.py`、`reliability/media.py`、`reliability/sqlite.py`。版本号为 1.4.3。

## 百炼接入

用户已填入独立密钥并授权使用真实记忆文本在数据库副本上验收。当前配置为 `text-embedding-v4` / version `1` / 1024 维，北京地域兼容 URL `https://dashscope.aliyuncs.com/compatible-mode/v1`。密钥保留在被忽略的 `.env`，不写入报告或提交。

选型依据：[百炼文本检索与聚类模型 / 维度建议](https://help.aliyun.com/zh/model-studio/embedding-rerank-model)、[兼容接口及业务空间域名迁移说明](https://help.aliyun.com/zh/model-studio/embedding-interfaces-compatible-with-openai)。短文本记忆先使用默认 1024 维；支持替换成与密钥对应地域的业务空间域名。

三条合成文本接口检查通过，均返回 1024 维：近义句 cosine 0.7198，无关句 0.3585，总耗时 7437 ms。该结果只是连接与向量格式检查，不代表质量验收。报告：`.zhaoxi/memory-v143-semantic-probe.json`。真实库副本对照已经完成多轮；最终结果与质量边界见下文。

## 真实 AutoMemory 请求

使用现有 `deepseek/deepseek-v4-flash`，经 CommandCode 网关，三组合成会话分别覆盖普通生活、项目进展、明确记住。没有发送真实用户对话，也没有写业务库。

此前网关忽略关闭 thinking，导致输出预算被 reasoning 用尽；`reasoning_effort=none` 被接口拒绝。叶子提供者现在兼容 DeepSeek 的 JSON object，后台请求使用 low 与最多 2000 token 的有界 reasoning 预留；普通前台请求不启用该预留。参考：[DeepSeek JSON](https://api-docs.deepseek.com/guides/json_mode/)、[CommandCode 设置](https://commandcode.ai/docs/settings)。

最终三次均 `finish_reason=stop`，生成并写入 2 / 3 / 2 条；耗时 10.54 / 7.21 / 9.64 秒，completion tokens 993 / 624 / 650。正文输出分别 329 / 548 / 335 字符。普通提取请求的正文预算为 1000，网关有效 max_tokens 为 3000；不能把 reasoning 预留误记为正文长度上限失效。报告：`.zhaoxi/memory-v143-llm-validation.json`。长时间稳定性仍需观察。

## 自动验证

- 最终工作区完整回归：889 passed、1 skipped、1 dependency warning，209.44 秒，包含候选预算、覆盖索引、领域先验与 blob 过期清理的最后修改。
- v1.4.3 专项文件最新 33 项通过，覆盖向量分批 / 复用、实际查询计划与通道预算；相邻 Cognitive Stream 与备份装配专项通过。
- Web Node：52 passed；实际可执行内联脚本语法检查通过，已排除 application/json 数据脚本块。
- wheel 已构建：`.zhaoxi/v143-wheel-check/zhaoxi-1.4.3-py3-none-any.whl`，SHA-256 `a9a97a712b14cafc0468876cd9258c8baa63133e3a073680fca6bf34bb2b32aa`。未安装或发布。
- 真实百炼查询向量预先缓存后，独立本地测速 10 条查询：候选 42–70 条，候选生成最高 80.202 ms，重排最高 22.923 ms，达到任务书的本地性能目标。此计时排除接口调用，不应当作端到端响应时间。报告：`.zhaoxi/memory-v143-local-retrieval-probe.json`。

## 真实库快照对照

最终候选预算与覆盖索引版本：真实库独立副本，1025 条记忆、10 个固定查询、K=6。真实 text-embedding-v4 向量来自百炼；最后一轮复测复用本地副本与缓存查询向量，没有重新发送整库正文。

| 指标 | 旧实现 | v1.4.3 hash | v1.4.3 百炼 |
| --- | ---: | ---: | ---: |
| Recall@6 | 0.8000 | 0.8750 | 0.8250 |
| Precision@6 | 0.2833 | 0.3333 | 0.3000 |
| Returned precision | 0.2833 | 0.4500 | 0.3750 |
| MRR | 0.9000 | 0.9000 | 0.8250 |
| Forbidden hits | 0.0000 | 0.0000 | 0.0000 |
| Cluster hit rate | 0.5000 | 0.6000 | 0.9000 |
| Wrong cluster rate | 0.6167 | 0.2750 | 0.1167 |
| Cluster expected coverage | 0.9500 | 0.6250 | 1.0000 |

已修正 Precision@K 分母为 K，另保留 Returned precision；暂停记录的 0.4167 使用了实际返回条数，不能作为 Precision@6 使用。标签是开发者选定的固定 ID，待用户审查，其他相关记忆未完整标注。新算法允许孤立记忆；hash 模式簇覆盖率变化不能直接等同于召回失败。

百炼 Recall / Precision / Cluster hit / Wrong cluster 均有改善，但 MRR 从 0.90 降至 0.825。下降来自 QQ 接入查询：被标记的首条排到第四，前面包括未完整标注的接入原则 / 尚未接入状态。必须完成同口径人工审查，当前不能宣称“召回质量不得低于迁移前”已通过。未修改标签来掩盖下降。

最终 hash 报告：`.zhaoxi/memory-v143-hash-acceptance/benchmark.json`；最终语义报告：`.zhaoxi/memory-v143-semantic-acceptance/benchmark.json`。各目录的 `benchmark.private.json` 与 `after.db` 含原始记忆，只留本地且被 Git 忽略。报告记录旧提交号。

## 验收边界与续接

1. 最后候选预算版本的副本复测与完整自动回归已完成。固定标签下 QQ 接入的 MRR 下降仍需人工审查；实际首条包含相关的接入原则 / 状态，现有标签未完整覆盖这些记录。不能通过事后扩张标签或调权偏爱固定 ID 来宣称验收通过。
2. 正式迁移须停止所有运行入口、验证备份后使用离线命令。本轮只验证副本，不发布原库。
3. 完成任务要求的 5–7 天持续使用，观察提取成功率 / 正文长度 / token、热度分布、关联召回与拒绝噪声。
4. 原有 LifeHUD 工具目录中的其他工作区改动属于并行用户工作，不回退、覆盖或归入本轮核心开发。

可复用命令：

```powershell
python -m pytest -o addopts='' -q --basetemp=.pytest-tmp-v143-final-full
node --test tests/web/*.test.cjs
python scripts/check_memory_embedding_v143.py
python scripts/benchmark_memory_v143.py --semantic --output .zhaoxi/memory-v143-semantic-benchmark --baseline-ref <旧提交号>
python main.py --memory-maintenance audit
python main.py --memory-maintenance all --output-dir .zhaoxi/memory-v143-preview
```

配置真实语义服务后，迁移预演也会将记忆正文发送给该服务；默认不写原库。实际发布与回滚命令见根 README。

本次旧基线固定为 `937ae4481de7db3bcca1f4d90d77d69d8ba62914`。复用语义副本与已缓存查询向量复测时不会重新发送整库正文。命令支持 `--after-snapshot <after.db>`；修改 embedding model / version / dimensions 后兼容检查仍会要求重建。

当前所有本轮验证进程均已结束；代码和文档保留为未提交状态，wheel 未安装或发布。
