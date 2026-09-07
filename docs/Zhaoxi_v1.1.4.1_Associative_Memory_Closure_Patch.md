# Zhaoxi v1.1.4.1 Development Task
# 联想记忆闭环修正（Associative Memory Closure Patch）

> 版本：v1.1.4.1  
> 基线：v1.1.4 Associative Memory  
> 类型：修正版本 / Memory Closure Patch  
> 核心目标：补齐 v1.1.4 已完成但尚未真正自动闭环的三部分：自动 Consolidation、开放式 Cluster、EDGE Memory 自动抽取与建联。

---

## 0. 背景

v1.1.4 已完成长期记忆系统的主体重构：

- 宽松写入
- 批量 MemoryCandidate
- EPISODIC / SEMANTIC / STATE / INTENT / RELATIONSHIP
- NODE / EDGE
- importance / activation / contextual relevance 分离
- Cluster
- Graph
- Hybrid Retrieval
- Embedding
- Lifecycle
- Consolidation
- Semantic evidence
- Diversity Recall
- DB migration
- Diagnostics / Retrieval Inspect

但当前验收确认存在三处未完整闭环：

1. Consolidation 不会自动执行。
2. Cluster 仍偏 tag/entity 分桶，Embedding 不参与归属。
3. EDGE 存储链路已支持，但 AutoMemory Prompt 未稳定引导模型输出 source/target/relation。

本版本只修这三处，不扩张其他模块。

---

# 1. 自动 Consolidation

## 1.1 目标

让：

```text
Episode
↓
积累
↓
低频检查
↓
Semantic
```

成为自动运行的长期过程，不再依赖用户手动调用 Tool。

## 1.2 权限边界

自动 Consolidation 只允许：

- 读取已有 Memory
- 生成新的派生 Semantic
- 写入 `evidence_memory_ids`
- 建立 `EVIDENCE_FOR`
- 建立 `DERIVED_FROM`
- 更新 `last_consolidation_at`

自动 Consolidation 禁止：

- archive 原 Episode
- forget
- delete
- 修改原 Episode 正文
- supersede 用户原始 Episode
- 修改 canonical Archive
- 修改 Personality

原则：

> 自动 Consolidation 是“形成认识”，不是“替用户整理并删除记忆”。

---

# 2. Consolidation 调度

至少支持两类低频触发：

## 2.1 新 Episode 数量触发

建议：

```env
ZHAOXI_MEMORY_CONSOLIDATE_AFTER_EPISODES=25
```

每新增约 20~30 条 EPISODIC 后检查是否存在候选。

## 2.2 时间触发

建议：

```env
ZHAOXI_MEMORY_CONSOLIDATION_INTERVAL_HOURS=24
```

每天最多检查一次，不要求固定凌晨执行。

---

# 3. Consolidation 纯代码预筛

调度器触发后，先用纯代码筛选。

候选条件参考：

- Cluster member_count 达到阈值
- 同 Cluster 最近有新增 Episode
- 已有 Semantic 无法覆盖新证据
- 相似事件重复出现
- 时间跨度足够
- 某种 STATE / 偏好被多次确认

无候选：

```text
0 次 LLM
```

有候选：

```text
批量提交一个或多个 Candidate Cluster
```

尽量一次调用处理多个候选。

---

# 4. Consolidation Candidate

建议结构：

```text
cluster_id
topic
recent_episode_ids
existing_semantic_ids
time_range
member_count
representative_memories
```

模型只允许输出：

```text
ignore
create_semantic
update_semantic
conflict
```

禁止后台自动：

```text
forget
archive
delete
```

---

# 5. Semantic 去重与更新

自动 Consolidation 必须防止每天生成近义 Semantic。

例如：

```text
暗苟喜欢夜间开发
暗苟更喜欢晚上开发
暗苟夜里效率更高
```

应先检索已有 Semantic：

- lexical similarity
- embedding similarity
- evidence overlap
- same cluster

高度相似时：

```text
更新 evidence / confidence / last_confirmed_at
```

而不是新建。

---

# 6. Consolidation Metrics

Diagnostics 建议增加：

```text
last_consolidation_check_at
last_consolidation_at
consolidation_checks
consolidation_llm_calls
semantic_created
semantic_updated
clusters_considered
```

---

# 7. 开放式 Cluster

## 7.1 目标

Cluster 不再主要依赖固定 `TOPIC_HINTS`。

新的 Cluster Match 应综合：

```text
tag
entity
lexical similarity
embedding similarity
time proximity
```

---

# 8. Cluster Match Score

建议：

```text
cluster_match_score =
tag_score
+ entity_score
+ lexical_score
+ embedding_score
+ time_score
```

原则：

- 真 embedding provider 可用时，提高 embedding 权重
- `local-hash-v1` 时降低 embedding 权重
- tags/entities 仍然重要
- TOPIC_HINTS 只作为 alias/bootstrap，不再是主要机制

---

# 9. Cluster Centroid

建议 Cluster 支持：

```text
centroid_embedding
```

新 Memory 写入时：

```text
memory embedding
↓
与现有 cluster centroid 计算相似度
↓
结合 tags/entities/time
↓
决定归属
```

新增成员后更新 centroid。

要求：

- deterministic
- 可重建
- 不依赖 LLM

---

# 10. 无神经 Embedding 时的回退

如果仍使用：

```text
local-hash-v1
```

则回退策略优先：

```text
tags
entities
lexical similarity
character n-gram
time proximity
```

Embedding 仅作弱辅助。

---

# 11. 开放主题测试

使用完全不在 `TOPIC_HINTS` 中的主题：

```text
今天出去拍了晚霞。
最近开始研究相机。
昨天又去拍照了。
我觉得长焦镜头挺有意思。
```

预期：

形成类似：

```text
摄影 / 拍照 / 相机
```

的同一 Cluster。

不能要求 tag 文本完全一致。

---

# 12. Cluster 合并

如果系统早期形成：

```text
Cluster A：摄影
Cluster B：拍照
```

后来发现高度相似：

允许高置信自动合并。

要求：

- 原 Memory 不变
- member relation 正确迁移
- old cluster 标记 merged / inactive
- 不丢失历史 metadata

---

# 13. Cluster 不确定性

若新 Memory 与最佳 Cluster 分数不足：

```text
保持 unclustered
```

宁可暂时不归类，也不要硬塞错抽屉。

---

# 14. EDGE Memory 自动抽取

AutoMemory Prompt 必须明确告诉模型：

> 当事实天然描述两个实体之间稳定或有意义的关系时，可以输出 `shape=edge`。

例如：

```text
暗苟为朝汐取名“朝汐”。
暗苟送给朝汐向日葵发卡。
暗苟喜欢夏天。
```

---

# 15. EDGE Candidate Schema

不要让 LLM 输出内部数据库 ID。

建议模型输出：

```json
{
  "kind": "relationship",
  "shape": "edge",
  "content": "暗苟为朝汐命名。",
  "source_entity": "暗苟",
  "target_entity": "朝汐",
  "relation_label": "命名",
  "confidence": 0.95,
  "importance": 0.8
}
```

内部 DB ID 由 Service 层解决。

---

# 16. Entity Resolution

新增轻量 Entity Resolution。

流程：

```text
"暗苟"
↓
已有 Concept / Node？
↓
存在：复用
不存在：创建稳定 Node
```

同理适用于：

```text
朝汐
夏天
向日葵发卡
LifeHUD
MemeVault
```

---

# 17. Entity Resolution 优先级

建议：

```text
canonical alias
↓
exact normalized name
↓
known alias
↓
high-confidence lexical match
↓
high-confidence embedding match
↓
create new node
```

至少支持：

```text
canonical_name
aliases[]
```

例如：

```text
Zhaoxi
朝汐
```

应指向同一 Concept。

本版本不要建设大型 Entity Ontology。

---

# 18. 不允许 LLM 猜内部 ID

禁止 Prompt 要求模型输出：

```text
person-angu
project-zhaoxi
node_123
```

LLM 只负责理解：

> 谁和谁是什么关系。

程序负责：

> 这些实体在数据库里对应哪个节点。

---

# 19. EDGE 持久化闭环

流程：

```text
AutoMemory
↓
EDGE Candidate
↓
resolve(source_entity)
resolve(target_entity)
↓
创建 / 复用 Concept Node
↓
保存 EDGE MemoryRecord
↓
保存 memory_edges
↓
evidence_memory_ids 写入 EDGE Memory ID
```

---

# 20. EDGE 缺字段处理

若：

```text
shape=edge
```

但缺：

```text
source_entity
target_entity
relation_label
```

不得生成坏 Graph Edge。

允许：

- 稳定降级为 NODE Memory
- 或标记 malformed candidate 并忽略

二选一即可，但必须有测试。

---

# 21. EDGE 时间语义

EDGE 同样支持：

```text
event_at
valid_from
valid_until
last_confirmed_at
```

例如：

```text
暗苟 --当前居住于--> 学校
```

不应永久有效。

---

# 22. EDGE 与 Semantic

稳定关系可以同时存在：

```text
EDGE
暗苟 --喜欢--> 夏天
```

与：

```text
SEMANTIC
暗苟长期喜欢夏天。
```

但应通过：

```text
EVIDENCE_FOR
DERIVED_FROM
```

保持来源关系，避免成为互不相关的重复事实。

---

# 23. Graph 自动建边来源

至少三类：

### EDGE Memory
直接形成关系边。

### Cluster
同 Cluster 高相关 Memory 建 RELATED_TO / PART_OF。

### Consolidation
建立：

```text
EVIDENCE_FOR
DERIVED_FROM
```

Graph 仍然是派生结构，Memory Record 仍是事实源。

---

# 24. 与 Retrieval 的关系

本版本不重写 Hybrid Retrieval。

新增 EDGE 后：

- Graph expansion 可以通过新 EDGE 联想
- relation_label 可以进入 why_selected
- 不增加 max_hops
- 不放宽安全阈值

---

# 25. 与 AutoMemory 的关系

AutoMemory 每轮仍只允许：

```text
1 次 LLM 调用
```

但可输出：

```text
0~N MemoryCandidate
```

其中可混合：

```text
NODE
EDGE
EPISODIC
STATE
INTENT
RELATIONSHIP
```

---

# 26. 权限边界

自动允许：

```text
create derived Semantic
create derived Graph Edge
update evidence
```

自动禁止：

```text
forget
delete
archive raw Episode
modify canonical Archive
```

不要为了自动 Consolidation 给后台高危写权限。

---

# 27. 建议配置项

```env
ZHAOXI_MEMORY_AUTO_CONSOLIDATION_ENABLED=true
ZHAOXI_MEMORY_CONSOLIDATE_AFTER_EPISODES=25
ZHAOXI_MEMORY_CONSOLIDATION_INTERVAL_HOURS=24

ZHAOXI_MEMORY_CLUSTER_EMBEDDING_ENABLED=true
ZHAOXI_MEMORY_CLUSTER_MATCH_THRESHOLD=0.72
ZHAOXI_MEMORY_CLUSTER_MERGE_THRESHOLD=0.88

ZHAOXI_MEMORY_EDGE_EXTRACTION_ENABLED=true
```

名称按现有 Settings 风格调整。

---

# 28. Diagnostics

补充：

```text
memory:
  auto_consolidation_enabled
  last_consolidation_check_at
  last_consolidation_at
  consolidation_checks
  consolidation_llm_calls
  semantic_created
  semantic_updated

  clusters
  unclustered
  cluster_merge_count

  edge_memories
  graph_edges
  entity_nodes
  edge_extraction_success
  edge_extraction_fallback
```

---

# 29. Retrieval Inspect

若 Memory 因 Graph Edge 被扩展进候选，Inspect 至少显示：

```text
seed memory
edge relation
relation_label
hop
graph contribution
final score
```

---

# 30. 自动测试：Consolidation

### 场景 A

同 Cluster 新增足够 EPISODIC。

预期：

- 达阈值触发 consolidation check
- 有候选时最多一次批量 LLM
- 生成 Semantic
- 原 Episode 不 archive / delete

### 场景 B

无值得归纳 Candidate。

预期：

```text
0 次 LLM
```

### 场景 C

已有高度相似 Semantic。

预期：

- update evidence / confidence
- 不重复创建 Semantic

---

# 31. 自动测试：开放式 Cluster

使用完全不在 TOPIC_HINTS 的：

```text
摄影
拍照
相机
镜头
晚霞照片
```

预期：

- 能通过 lexical/entity/embedding 等形成同 Cluster
- 不要求 tag 完全一致

---

# 32. 自动测试：Cluster Fallback

使用 `local-hash-v1`。

预期：

- embedding 仅弱辅助
- lexical/tag/entity 仍可归类
- 不因 hash embedding 产生大量错归类

---

# 33. 自动测试：Cluster Merge

先形成：

```text
摄影
拍照
```

两个 Cluster。

后续高置信发现同主题。

预期：

- 可合并
- 成员不丢
- 原 Memory 不改
- 不产生幽灵 Cluster

---

# 34. 自动测试：EDGE Extraction

输入：

```text
暗苟给朝汐取名“朝汐”。
```

预期 AutoMemory Candidate：

```text
shape=edge
source_entity=暗苟
target_entity=朝汐
relation_label=命名
```

Service：

- resolve 两个实体
- 创建 EDGE Memory
- 创建 Graph Edge

---

# 35. 自动测试：Entity Alias

输入：

```text
朝汐
Zhaoxi
```

在已有 alias 情况下，应指向同一 Entity / Concept Node。

---

# 36. 自动测试：EDGE 缺字段

模型输出 EDGE 但缺 source / target。

要求：

- 稳定降级或拒绝
- 不创建坏 Graph Edge
- 不崩溃

---

# 37. 手动验收

## 场景 1：自动 Consolidation

连续写入：

```text
晚上开发效率高
深夜完成任务
晚上明显更专注
夜间进入心流
```

达到触发条件后，无需手动 Tool，最终生成类似：

```text
Semantic:
暗苟通常在夜间更容易进入高专注开发状态。
```

并可查看 evidence。

## 场景 2：陌生主题自动成簇

连续输入：

```text
今天出去拍了晚霞。
最近开始研究相机。
昨天又拍了一组照片。
我发现长焦镜头挺有意思。
```

预期形成新的摄影相关 Cluster。

不得依赖新增硬编码 `TOPIC_HINTS`。

## 场景 3：EDGE

输入：

```text
我给朝汐取了“朝汐”这个名字。
```

预期出现可追溯 EDGE：

```text
暗苟 --命名--> 朝汐
```

而不是只有孤立文本。

## 场景 4：联想

随后问：

```text
朝汐这个名字是谁取的？
```

预期 Hybrid Retrieval 可通过 EDGE / Semantic / Archive 可靠回答。

---

# 38. 不在本版本处理

明确不做：

- Neo4j
- 图谱 UI
- 大型 ontology
- 自动全局 Entity Merge
- LLM 每轮维护 Cluster
- ANN
- 新 Memory 生命周期设计
- 新 Retrieval 架构
- Archive 重构
- Personality 重构
- 自动删除旧 Episode
- 自动重写 canonical

---

# 39. 完成标准

v1.1.4.1 完成后必须满足：

1. Consolidation 有自动低频调度。
2. 无候选时不调用 LLM。
3. 自动 Consolidation 只生成派生 Semantic，不删除原 Episode。
4. Semantic 可更新 evidence，避免重复堆叠。
5. Cluster 不再主要依赖 TOPIC_HINTS。
6. 新主题可凭 lexical/entity/embedding/time 自动成簇。
7. Cluster 支持 centroid 或等价主题中心。
8. local-hash-v1 下有合理退化策略。
9. 高置信相似 Cluster 可合并。
10. AutoMemory Prompt 明确支持 EDGE。
11. LLM 不直接输出数据库 node ID。
12. Service 层完成 Entity Resolution。
13. EDGE Candidate 可自动落成 Graph Edge。
14. 缺字段 EDGE 不产生坏数据。
15. alias 可复用同一 Entity。
16. Graph 仍是派生结构。
17. Retrieval 可沿新 EDGE 联想。
18. Diagnostics 能观察 Consolidation / Cluster / EDGE 状态。
19. Retrieval Inspect 可解释 Graph 路径。
20. 现有 v1.1.4 测试与其他模块保持通过。

---

# 40. 开发完成后汇报

请明确汇报：

- 修改文件
- Consolidation Scheduler
- Consolidation Trigger
- 候选筛选逻辑
- 新增 LLM 调用条件
- 自动行为权限边界
- Semantic 去重 / 更新逻辑
- Cluster Match Score
- Embedding / lexical / entity / time 权重
- Centroid 实现
- local-hash fallback
- Cluster Merge
- EDGE Extractor Prompt
- EDGE Candidate Schema
- Entity Resolution
- Alias
- EDGE 持久化
- Graph Edge 创建
- 缺字段 fallback
- Diagnostics
- Retrieval Inspect
- 自动测试
- 手动验收
- 已知限制

---

# 41. 本版本理念

v1.1.4 已经让朝汐拥有：

> **宽记，成簇，建联，慎忆。**

v1.1.4.1 不重新设计记忆。

它只负责把已经存在的能力真正接成自动闭环：

```text
生活
↓
Episode
↓
自动成簇
↓
自然建联
↓
低频沉淀
↓
Semantic
↓
未来联想召回
```

朝汐不应该等暗苟提醒：

> “这些记忆该整理一下了。”

她应该在长期生活中，自己慢慢把相似的东西放到一起，把反复发生的事情变成认识，也让人与事之间的关系自然长出连接。

> **记忆真正变得像记忆，不是因为存得更多。**
>
> **而是因为它开始自己长出结构。**
