# Zhaoxi v1.1.4 开发报告：联想记忆

## 结果

v1.1.4 将平铺的长期记忆升级为 SQLite 上可重建的联想网络。Memory Record 仍是事实源；Cluster、Graph 与 Embedding 都是派生索引，不改变 Archive 高于 Memory 的信息边界，也不修改 Personality。

## Schema 与迁移

- schema version：3。
- `memories`：新增 shape、activation、event_at、last_confirmed_at、derived_at、entities、participants、source_message_ids、evidence_memory_ids 与 cluster_id。
- 新表：`memory_clusters`、`memory_cluster_members`、`memory_edges`、`memory_embeddings`、`memory_evidence`、`memory_runtime`。
- v1/v2 数据库使用增量 `ALTER TABLE`；旧 semantic/episodic、状态和正文保留，旧 relevance 复制为初始 activation。兼容列 relevance 暂时保留用于回滚，但不参与动态 query relevance 写回。

## 类型、形态与批量提取

- `MemoryKind`：EPISODIC、SEMANTIC、STATE、INTENT、RELATIONSHIP。
- `MemoryShape`：NODE、EDGE。
- `MemoryCandidate` 支持事件/有效期、实体、参与者、标签、置信度、重要度、activation、来源消息与自然关系标签。
- AutoMemory Prompt 改为一次调用输出 `{candidates:[...]}`；每条候选表达一个主要事实。旧 action JSON 仍兼容。
- 提取标准改为“是否值得留下生活痕迹”，普通饮食、娱乐、情绪、短期状态、小型推进和计划可记录；工具噪声、猜测、日志和纯 filler 仍忽略。

## 权重与时间

- importance：记忆本身的重要性，稳定存储。
- activation：近期热度，可衰减、命中提升并向 1/2-hop 邻居轻量传播。
- contextual_relevance：keyword、embedding、metadata/time 和 graph 的查询时分数，不写回数据库。
- STATE / INTENT 过期后在普通召回中显著降权；event_at、valid_from、valid_until 与 last_confirmed_at 均可参与时间判断。

## Cluster

- 写入后使用主题词、tags 和 entities 做高置信归属；低信息记录允许保持未聚类。
- 第一版内置饮酒、烹饪、Zhaoxi开发、求职和舞萌主题提示，其他明确 tag/entity 可形成主题。
- Cluster 保存时间范围、成员数、代表记忆、importance、activation 与简短可重建摘要。
- 普通召回默认 `per_cluster_limit=2`；明确回忆或单主题查询放宽限制。

## Graph

- 首版关系：RELATED_TO、PART_OF、ABOUT、MENTIONS、HAPPENED_DURING、BEFORE、AFTER、EVIDENCE_FOR、DERIVED_FROM、SUPERSEDES、CONTRADICTS、ASSOCIATED_WITH。
- 同 Cluster 记忆按规则建立 RELATED_TO；替代事实建立 SUPERSEDES / CONTRADICTS；Consolidation 建立双向证据边。
- 自然关系可保存在 relation_label，不扩张 enum。
- 默认最多 2-hop，带最小边权、visited 去环、hop 衰减和最终 rerank；Graph 只补充候选。

## Embedding 与 Hybrid Retrieval

- 默认 `local-hash-v1` 是无额外依赖的本地特征 embedding；Provider 可注入替换。
- 缓存键为 embedding_model + SHA-256 content hash；正文不变不重复计算。
- 个人规模使用 O(n) cosine scan，不引入 ANN。
- 最终分数分别保留 text、semantic、graph、time、activation、importance；text/semantic 占主导。
- `inspect_retrieval` 返回 seed/分量、Cluster、最终分数和 `why_selected`，便于调优。

## Lifecycle 与 Consolidation

- 自然生命周期：ACTIVE → COLD → DORMANT → ARCHIVED；pinned/high-importance 可冷却但不会因低 activation 被自动归档。
- 明确遗忘才进入 FORGOTTEN；事实替换进入 SUPERSEDED，并保留冲突/替代关系。
- Consolidation 生成 Semantic 的 `evidence_memory_ids`、`derived_at` 和 evidence rows；原 EPISODIC 永久保留。
- 为兼容旧 v0.3.2 手工整合语义细节的行为，非 EPISODIC 且未 pinned 的旧输入仍可归档。

## Diagnostics

`GET /api/diagnostics` 的 memory 节点仅暴露：total、by_kind、by_status、clusters、edges、unclustered、embedding_model、embedding_count、last_consolidation_at，不包含用户正文。

## 自动测试

- 原有 Memory、Cognitive、Context、Tool、Web diagnostics 与数据库迁移测试保持兼容。
- 新增：批量生活提取、五种 kind/shape/time、Cluster diversity 与主题展开、带环 2-hop Graph、证据型 Consolidation、过期 State、v2 relevance 迁移，以及 10,000 Memory keyword/embedding 线性扫描。
- 最终验证：372 项 Python 通过、1 项 symlink 权限相关测试跳过、17 项 Node 通过；`compileall` 与 `git diff --check` 通过。既有 Starlette/httpx 弃用警告保持 1 项。

## 手动验收

1. 连续输入“中午吃粉、下午舞萌、晚上改朝汐”，检查数据库产生 2 条 EPISODIC 与 1 条 INTENT，而非整段复制。
2. 连续记录啤酒、白朗姆、金酒，普通混合话题提问时饮酒最多 2 条；问“我都喝过什么”时应展开更多。
3. 记录三次夜间高效率开发，调用 Consolidation 后检查 Semantic 证据 ID、EVIDENCE_FOR / DERIVED_FROM 边，且 Episode 仍为 ACTIVE。
4. 写入带 valid_until 的 STATE，过期后与新 STATE 一起检索，确认旧状态时间分显著降低。
5. 打开 `/api/diagnostics`，确认只出现计数和模型名，不出现记忆正文。

## 已知限制

- 默认本地 hash embedding 是可离线工作的基线，不等价于神经语义模型；可通过注入兼容 Provider 替换。
- Cluster Summary 当前为确定性短摘要，不额外调用 LLM；复杂主题归并仍待 Reflection/低频 Consolidation 改进。
- 自动冲突识别仍以保守文本相似度为主，复杂时序冲突需要模型候选或用户明确 supersedes。
- Graph 当前以 Memory 节点为主，尚未建设大型实体 ontology 或图谱可视化。
- 真实兼容模型的批量 JSON 稳定性、数年真实数据和桌面长时运行仍需人工观察。
