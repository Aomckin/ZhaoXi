# Zhaoxi v1.1.4.1 开发报告：联想记忆闭环修正

## 结果

本补丁补齐 v1.1.4 的三个自动化断点：Episode 可低频沉淀为 Semantic；陌生主题可通过多因子匹配形成和合并 Cluster；关系事实可从 AutoMemory 的实体名称候选落成 Concept 与 Graph Edge。

## 自动 Consolidation

- `AutoConsolidator` 在 AutoMemory 完成后检查，不增加每轮固定模型调用。
- 数量触发：默认累计 25 条新 EPISODIC。
- 时间触发：默认距上次检查 24 小时；没有对话时不启动额外常驻线程，在下一轮对话后检查。
- 纯代码预筛要求活跃 Cluster 内存在足够未覆盖 Episode；无候选时 0 次 LLM。
- 多个 Candidate Cluster 在一次请求中批量提交；模型动作限制为 ignore/create_semantic/update_semantic/conflict。
- 自动行为只创建派生 Semantic，或更新已有 Semantic 的 evidence、confidence、last_confirmed_at；原 Episode 不 archive/delete/supersede，也不触碰 Archive/Personality。
- 相同 Cluster、证据覆盖与已有 Semantic ID参与去重；更新时只补证据和双向 evidence edges，不每日生成近义 Semantic。

## 开放式 Cluster

Cluster Match Score 分别计算 tag、entity、lexical、embedding centroid 和 time proximity：

- `local-hash-v1`：35% tag、35% entity、20% lexical、5% embedding、5% time。
- 非 hash Provider：20% tag、20% entity、15% lexical、40% embedding、5% time。
- 默认 match threshold 0.38，merge threshold 0.84；`TOPIC_HINTS` 只作 alias/bootstrap。
- 新成员写入后按成员数增量更新 centroid，过程确定且可从 Memory Embedding 重建。
- 高置信 Cluster 合并会迁移 membership 和 Memory 的 cluster_id；旧 Cluster 保留 metadata 并标记 inactive、merged_into_id，原 Memory 正文不变。
- 低于阈值且无 tag/entity bootstrap 的记录保持 unclustered。

## EDGE 与 Entity Resolution

- AutoMemory Prompt 明确使用 `source_entity`、`target_entity`、`relation_label`，并禁止输出 source_node_id/target_node_id。
- Entity Resolution 顺序为 canonical alias、normalized exact/alias、创建新 Concept Node。
- 内置 canonical alias 首批包含 `朝汐` / `Zhaoxi`；结构支持继续增加 aliases。
- 合法 EDGE Candidate 保存 EDGE MemoryRecord、实体关系 Edge，以及 Memory 到两个 Concept 的 ABOUT Edge；Graph evidence 指向 EDGE Memory ID。
- 缺 source/target/relation_label 或关闭 EDGE extraction 时，稳定降级为 NODE Memory，不产生坏 Graph Edge。
- EDGE 的 valid_from/valid_until 同步进入 Graph Edge，过期 Edge 不参与扩展。

## Diagnostics 与 Inspect

Diagnostics 新增：auto_consolidation_enabled、last_consolidation_check_at、consolidation_checks、consolidation_llm_calls、semantic_created、semantic_updated、clusters_considered、cluster_merge_count、edge_memories、graph_edges、entity_nodes、edge_extraction_success、edge_extraction_fallback。

Retrieval Inspect 的图扩展结果新增 seed_memory_id、edge_relation、relation_label、graph_hop，并在 why_selected 中展示 graph contribution 与路径。

## 配置

```dotenv
ZHAOXI_MEMORY_AUTO_CONSOLIDATION_ENABLED=true
ZHAOXI_MEMORY_CONSOLIDATE_AFTER_EPISODES=25
ZHAOXI_MEMORY_CONSOLIDATION_INTERVAL_HOURS=24
ZHAOXI_MEMORY_CONSOLIDATION_MIN_EVIDENCE=3
ZHAOXI_MEMORY_CLUSTER_EMBEDDING_ENABLED=true
ZHAOXI_MEMORY_CLUSTER_MATCH_THRESHOLD=0.38
ZHAOXI_MEMORY_CLUSTER_MERGE_THRESHOLD=0.84
ZHAOXI_MEMORY_EDGE_EXTRACTION_ENABLED=true
```

Memory DB schema 升至 v4，新增 Cluster centroid/merge 状态和 `memory_entities`；v1-v3 继续增量无损迁移。

## 自动测试

- 自动数量触发、单次批量 LLM、无候选零调用。
- 已有 Semantic 补 evidence，不重复创建；原 Episode 保持 ACTIVE。
- 完全不在 Topic Hints 的摄影主题通过不同 tag + 共享 entity 成簇并生成 centroid。
- Bridge Memory 驱动 Cluster merge，成员与正文不丢失。
- AutoMemory EDGE Prompt、Concept Resolution、朝汐/Zhaoxi alias、Graph 持久化与 2-hop 召回。
- malformed EDGE 降级且不产生坏边。
- 最终验证：379 项 Python 通过、1 项 symlink 权限相关测试跳过；17 项 Node 通过；compileall 通过。保留 1 项既有 Starlette/httpx 弃用警告。

## 手动验收

1. 将 consolidate-after 临时设为 4，连续输入四条同主题夜间开发经历；下一轮结束后检查 Semantic evidence，确认四条 Episode 仍存在。
2. 连续输入晚霞、相机、拍照、长焦镜头，并让 AutoMemory 生成相关 tag/entity；检查它们进入同一非内置 Cluster。
3. 输入“我给朝汐取了朝汐这个名字”；检查 EDGE Memory、暗苟/朝汐 Concept 和带“命名” relation_label 的 Edge。
4. 再问“这个名字是谁取的”；在 retrieval inspect 中检查 seed、relation、hop 与 graph contribution。

## 已知限制

- 时间触发依赖下一次对话唤醒，不是独立定时守护进程。
- `local-hash-v1` 不具备真正同义词理解；无共享 tag/entity/lexical 线索的陌生主题可能暂时保持 unclustered。
- Entity Resolution 当前只做 canonical/exact alias，不进行自动全局模糊实体合并。
- Consolidation 的归纳质量仍取决于兼容模型对受限 JSON schema 的遵循程度；无效响应安全地不写入。
