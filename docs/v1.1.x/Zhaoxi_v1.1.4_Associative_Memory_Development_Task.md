# Zhaoxi v1.1.4 Development Task
# 联想记忆（Associative Memory）

> 版本：v1.1.4  
> 主题：Memory Rework / Associative Network / Clustering / Consolidation / Hybrid Retrieval  
> 核心目标：将现有长期记忆从“平铺的 MemoryRecord 列表”升级为适合生活类 Agent 的长期记忆系统，让朝汐能够宽松地记录生活小事，同时通过记忆分类、主题聚类、关系网络、时间有效性、语义归纳与多样性召回，避免噪声、重复、Top-K 污染与错误联想。

---

## 0. 背景

Zhaoxi 现有 Memory 系统已经具备长期记忆记录、Semantic / Episodic 基础类型、importance / relevance / confidence / pinned、ACTIVE / COLD / ARCHIVED / SUPERSEDED / FORGOTTEN、自动记忆决策、关键词/FTS 搜索、生命周期衰减和 Consolidation 基础接口。

但当前实现仍明显带有早期骨架特征：

1. 写入标准偏高，容易漏掉生活类 Agent 真正有价值的小事。
2. 每轮 AutoMemory 基本只能生成一条 MemoryDecision，无法拆分一轮中多个事实。
3. 自动记忆几乎都落成 semantic，episodic 没有真正活起来。
4. `relevance` 同时承担长期活跃度与相关性概念，语义混乱。
5. 当前 query relevance 只是临时字符/关键词 overlap，没有独立建模。
6. 相似记忆容易同时占满 Top-K，例如几十条饮酒记录把其他相关主题挤掉。
7. 检索后的 boost 可能形成“越容易被找到，越一直霸榜”的回音室。
8. valid_from / valid_until 等时间字段没有真正成为核心判断依据。
9. 遗忘更接近冷藏/归档，而不是自然联想强度衰减。
10. Consolidation 当前没有真正形成“经历 → 认识”的长期沉淀闭环。
11. Memory 之间彼此孤立，缺少联想关系，无法实现“想到 A 又顺着想到 B”。

v1.1.4 需要对 Memory 进行一次结构性重构。

---

# 1. 本版本设计理念

# 宽记，成簇，建联，慎忆

英文：

> **Remember generously, organize structurally, recall selectively.**

含义：

- **宽记**：只要具有生活痕迹价值，就允许低门槛进入 Memory。
- **成簇**：相近记忆不永远平铺，逐渐形成主题 Cluster。
- **建联**：Memory 不再是列表，通过关系边形成联想网络。
- **慎忆**：真正进入模型上下文的，只保留当前最相关、最有价值、最有代表性的一小部分。

---

# 2. 规模假设

这是个人生活 Agent。

即使每天写入 10~30 条 Memory，一年约 3650~10950 条，数年后数万条仍属于本地可控规模。

因此本版本不需要：

- ANN / HNSW
- 分布式向量数据库
- Elasticsearch 集群
- Neo4j

优先：

```text
SQLite
+ FTS / keyword
+ local embedding linear scan
+ metadata filter
+ graph expansion
```

优先正确性、可解释性与长期可维护性。

---

# 3. Memory 类型重构

现有 `EPISODIC / SEMANTIC` 不足。

建议至少扩展为：

```text
EPISODIC
SEMANTIC
STATE
INTENT
RELATIONSHIP
```

## EPISODIC
表示“发生过什么”。

例：`2026-09-06，朝汐第一次通过潮汐心跳主动提醒暗苟休息。`

建议支持：`event_at / participants / context / emotion? / place? / source_message_ids`

## SEMANTIC
表示稳定事实、偏好、理念或从经历中归纳出的认识。

例：`暗苟通常更容易在夜间进入高专注开发状态。`

必须支持证据来源。

## STATE
表示某一阶段暂时成立的当前状态。

例：`暗苟目前正在准备 Java 面试八股。`

必须重视：`valid_from / valid_until / last_confirmed_at`

## INTENT
表示准备做什么、想尝试什么、计划什么。

可完成、取消、过期、被替代。

## RELATIONSHIP
表示人与人、人与项目、人与事物之间逐渐形成的高层关系理解。

---

# 4. Memory Shape

除 kind 外，新增逻辑形态：

```text
NODE
EDGE
```

## NODE Memory
适合 Episode、Semantic、State、Intent、Relationship、Topic 等。

## EDGE Memory
适合表达两个节点间的关系本身就是一条可追溯记忆。

例如：

```text
[暗苟] --喜欢--> [夏天]
[暗苟] --命名--> [朝汐]
[暗苟] --赠予--> [向日葵发卡]
```

Edge 至少包含：

```text
source_node_id
target_node_id
relation
relation_label
confidence
importance
activation
created_at
valid_from
valid_until
evidence_memory_ids
```

---

# 5. Atomic Memory Extraction

现有：

```text
一轮对话 -> 0 或 1 条 Memory
```

升级为：

```text
一轮对话 -> 0 ~ N 条 MemoryCandidate
```

例如用户：

```text
今天下午打了舞萌，回来吃了碗粉。
秋招我觉得还是慢慢来比较好。
晚上准备继续改朝汐。
```

允许拆成：

```text
EPISODIC：今天下午打了舞萌。
EPISODIC：回来后吃了一碗粉。
STATE/SEMANTIC：当前认为秋招不必过度焦虑，应保持节奏。
INTENT：今晚准备继续修改朝汐。
```

原则：

- 一条表达一个主要事实/事件
- 不把整段聊天原样裁进 Memory
- 不丢失时间
- 不过度碎片化
- 多条候选可共享 source_message_ids

---

# 6. 写入标准降低

AutoMemory Prompt 必须重写。

不再把“一次性闲聊、短暂情绪、小事”一概 IGNORE。

可写入：

- 普通生活事件
- 小型情绪片段
- 短期状态
- 一次性但有时间锚点的经历
- 一次失败
- 某天吃了什么
- 某次出门
- 某次娱乐
- 小型项目推进
- 用户自然表达出的偏好变化

仍应 IGNORE：

- 纯工具噪声
- 完全无意义 filler
- 模型自己的猜测
- 无证据事实
- 系统内部日志
- 没有新增信息的重复事实

判断标准：

> **这件事是否值得作为生活痕迹留下？**

---

# 7. Memory Candidate Batch

建议新增：

```python
class MemoryCandidate(BaseModel):
    kind
    shape
    content
    event_at
    valid_from
    valid_until
    entities
    tags
    confidence
    importance
    source_message_ids
    relation?
    source_node?
    target_node?
```

AutoMemory 输出：

```json
{
  "candidates": [
    {...},
    {...}
  ]
}
```

而不是单一 action。

---

# 8. importance / activation / contextual_relevance 分离

这是本版本核心。

## importance
这条 Memory 本身有多重要。相对稳定。

## activation
这条 Memory 最近有多“热”。

受：
- 新近发生
- 最近被提到
- 最近成功召回
- 与近期事件相关
- 邻接 Memory 激活

影响，并随时间衰减。

## contextual_relevance
当前 query 与该 Memory 有多相关。

必须每次查询动态计算，不持久化成固定值。

来源可包括：
- keyword
- embedding
- metadata
- time
- graph

## confidence
朝汐对这条事实有多确定。

与 importance / activation 独立。

---

# 9. relevance 字段迁移

现有 `relevance` 概念含混。

迁移为：

```text
activation
```

旧值作为初始 activation。

之后 query relevance 不写回数据库。

---

# 10. 时间语义

Memory 正式支持：

```text
created_at
event_at
valid_from
valid_until
last_confirmed_at
updated_at
```

- `event_at`：事情真正发生的时间。
- `valid_from / valid_until`：用于 STATE、INTENT、阶段信息。
- `last_confirmed_at`：最近一次被用户再次确认仍成立。

例如“暗苟目前住在学校”不应数月后仍以永恒事实高置信召回。

---

# 11. Memory Cluster

新增：

```text
memory_clusters
```

Cluster 表示多条相近记忆形成的主题区域，例如：

```text
饮酒
烹饪
Zhaoxi开发
求职
舞萌
暑假生活
```

建议字段：

```text
id
topic
summary
time_start
time_end
importance
activation
member_count
representative_memory_ids
centroid_embedding?
tags
entities
created_at
updated_at
```

原 Episode 永远保留，Cluster 只是上层组织结构。

---

# 12. 自动聚类

新 Memory 写入后：

```text
candidate
↓
keyword / entity / embedding / time proximity
↓
匹配现有 Cluster
```

高置信直接加入。

低置信保持未聚类。

不要强制每条 Memory 必须属于某个 Cluster。

---

# 13. Cluster Summary

Cluster 维护简短摘要。

例如：

```text
近期饮酒频率有所增加，主要包括啤酒、白朗姆和少量金酒。
```

摘要不是事实源，成员 Memory 才是事实源。

---

# 14. Top-K 多样性控制

普通召回增加：

```text
per_cluster_limit
```

建议默认：

```text
2
```

避免一个 Cluster 独占 Top-K。

当 query 明确锁定某主题，如“我之前都喝过什么？”，允许放宽或取消 cluster limit。

---

# 15. Memory Graph

新增：

```text
memory_edges
```

目标：

> 让记忆之间形成可联想网络。

Graph 可引用：

- Memory Node
- Cluster
- Semantic Memory
- Time-period Memory
- Project / Person / Object concept

P0 不要求建立大型实体系统。

---

# 16. Edge 类型

第一版控制数量：

```text
RELATED_TO
PART_OF
ABOUT
MENTIONS
HAPPENED_DURING
BEFORE
AFTER
EVIDENCE_FOR
DERIVED_FROM
SUPERSEDES
CONTRADICTS
ASSOCIATED_WITH
```

对于“喜欢、讨厌、赠予、命名、拥有、参与、正在做”等自然关系，允许使用 `relation_label`，不需要全部变成 Enum。

---

# 17. Graph 是派生结构

强制原则：

> **Memory Record 是主要事实源，Graph 是可重建关系索引。**

Graph 损坏时允许删除并重建。

不得让 Memory 是否存在依赖 Graph。

---

# 18. Graph 建边策略

禁止每写一条 Memory 就调用大模型全量建图。

优先使用：

- 规则
- embedding
- shared entities
- cluster
- time proximity

高置信关系自动建立。

模糊关系等待 Consolidation / Reflection 再整理。

---

# 19. Hybrid Retrieval

召回流程：

```text
query
↓
keyword retrieval
+
embedding retrieval
+
metadata / time filter
↓
Seed Memories / Clusters
↓
Graph expansion 1~2 hop
↓
cluster diversity
↓
rerank
↓
最终上下文
```

---

# 20. Seed Memory

先选 3~5 条高 contextual relevance 的 Memory / Cluster 作为 Seed。

不允许单纯因为 importance / activation 高就成为 Seed。

---

# 21. Graph Expansion

建议默认：

```text
max_hops = 2
```

参考衰减：

```text
1 hop = seed_score * 0.65
2 hop = seed_score * 0.35
```

再结合：

```text
relation_weight
activation
importance
time_factor
```

---

# 22. 防止联想暴走

限制：

- max_hops
- relation whitelist
- minimum edge weight
- minimum contextual relevance
- final rerank
- cluster diversity

Graph 只能补充候选，不能无限扩张。

---

# 23. Activation Spreading

推荐轻量传播。

当某 Memory 被强召回：

```text
自身 +0.10 ~ 0.15
1-hop 邻居 +0.02 ~ 0.05
2-hop 邻居 +0.005 ~ 0.01
```

数值可配置。

目的：

> 经常一起出现的记忆区域会逐渐更容易联想。

---

# 24. Activation Decay

activation 按时间衰减。

要求：

- 新记忆初始 activation 较高
- 长期不使用逐渐下降
- pinned 不等于永远高 activation
- importance 高也不等于永远高 activation

---

# 25. Lifecycle

自然生命周期建议：

```text
ACTIVE
COLD
DORMANT
ARCHIVED
```

用户明确要求忘记：

```text
FORGOTTEN
```

事实被替换：

```text
SUPERSEDED
```

自然遗忘不是物理删除：

```text
ACTIVE -> COLD -> DORMANT -> ARCHIVED
```

只有明确“忘掉/删除”才进入 FORGOTTEN。

---

# 26. Embedding

允许正式引入 Memory embedding。

优先：

- 本地 embedding
- 已有兼容 embedding provider
- 可配置模型

不要求 ANN。

允许：

```text
O(n) cosine scan
```

个人规模完全可接受。

Memory 内容不变时不重复计算 embedding。

建议保存：

```text
embedding_model
embedding_hash
vector
```

内容更新后重新计算。

---

# 27. Retrieval Fusion

最终排序至少区分：

```text
text_score
semantic_score
graph_score
time_score
activation_score
importance_score
```

其中 text / semantic contextual relevance 必须是主导因素。

importance / activation 只作辅助，避免高 activation 老记忆霸榜。

---

# 28. Consolidation

v1.1.4 必须真正实现：

> **Episode -> Semantic**

例如：

```text
7/20 晚上写代码效率高
7/24 深夜完成开发
8/02 晚上比下午专注
8/13 用户说喜欢深夜开发
```

可归纳：

```text
SEMANTIC:
暗苟通常在夜间更容易进入高专注开发状态。
```

Semantic 必须包含：

```text
evidence_memory_ids
derived_at
confidence
```

Graph 建：

```text
Episode --EVIDENCE_FOR--> Semantic
Semantic --DERIVED_FROM--> Episode
```

原 Episode 不删除。

---

# 29. Consolidation 周期

不要每轮执行。

建议低频触发：

- 每日一次
- 每 N 条新 Memory
- Reflection 时
- 用户空闲时

候选优先：

- 同 Cluster 成员较多
- 相似事实多次出现
- 同一偏好反复确认
- STATE 多次验证
- 时间跨度足够形成规律

不要对两条偶然事件强行归纳。

---

# 30. Conflict / Supersedes

新事实与旧 Semantic 冲突时，不要静默覆盖。

使用：

```text
CONTRADICTS
SUPERSEDES
time-scoped STATE
```

例如：

```text
2026夏：更喜欢晚上开发
2027春：更喜欢上午开发
```

应保留时间演化。

---

# 31. AutoMemory 成本控制

宽记不等于多次 LLM 调用。

优先：

```text
每轮结束
↓
一次 Memory Extractor
↓
批量输出 0~N candidates
```

禁止一条候选一次模型调用。

未来允许使用更便宜模型。

---

# 32. Archive 与 Memory 边界

继续保持 v1.1.3 的信息边界：

```text
Archive
= 人工正式资料

Memory
= 朝汐自己活出来、记录和归纳出的经历
```

冲突优先级继续：

```text
当前用户明确指令
↓
canonical Archive
↓
reference / personal Archive
↓
Memory
↓
模型推断
```

Memory 不得覆盖 canonical。

---

# 33. Personality 与 Memory

Personality 不应被 Memory 自动重写。

Memory 可以记录朝汐与暗苟共同经历，但不自动修改人格 YAML。

---

# 34. 建议 DB 结构

至少：

```text
memories
memory_clusters
memory_cluster_members
memory_edges
memory_embeddings
memory_evidence
```

## memory_clusters

```text
id
topic
summary
importance
activation
time_start
time_end
member_count
metadata_json
created_at
updated_at
```

## memory_cluster_members

```text
cluster_id
memory_id
membership_score
created_at
```

## memory_edges

```text
id
source_id
target_id
relation
relation_label
weight
confidence
activation
valid_from
valid_until
evidence_json
created_at
updated_at
last_activated_at
```

---

# 35. 旧 DB 迁移

必须安全迁移现有 Memory DB。

至少考虑：

- `relevance -> activation`
- 原 semantic / episodic 保留
- 新 kind 默认映射
- 新 cluster / edges 表
- 新 embedding 表/字段
- 原 status 兼容

不允许丢失旧 Memory。

---

# 36. 召回上下文格式

不要继续把所有 Memory 平铺成一串。

建议按主题分组：

```text
相关长期记忆：

【主题：饮酒】
摘要：近期饮酒频率有所增加。
- 2026-08-27 买了白朗姆。
- 2026-09-03 ...

【主题：Zhaoxi开发】
- ...
```

目标：

> 模型知道哪些 Memory 属于同一主题。

---

# 37. Recall Budget

普通聊天建议：

```text
cluster_count <= 4
memory_count <= 8
per_cluster_limit = 2
```

明确主题问题可放宽。

---

# 38. 用户明确回忆时

若用户明确说：

```text
你还记得……
以前是不是……
之前那次……
```

允许提高：

- historical recall
- graph expansion
- dormant / archived search

普通聊天则保持克制。

---

# 39. Diagnostics / Inspect

建议 diagnostics 增加：

```text
memory:
  total
  by_kind
  by_status
  clusters
  edges
  unclustered
  embedding_model
  embedding_count
  last_consolidation_at
```

并提供 retrieval inspect：

```text
seed memories
keyword score
embedding score
graph score
cluster
final score
why selected
```

便于调优。

---

# 40. 测试要求

## 宽记
- 普通生活小事可写入 Episode
- 一轮可拆 2~5 条候选
- 无价值 filler 仍 ignore
- 工具输出不误记
- 模型猜测不误记

## 类型
覆盖：
- episodic
- semantic
- state
- intent
- relationship
- valid_from / valid_until

## Cluster
连续写入啤酒、白朗姆、金酒等记忆：
- 可进入“饮酒” Cluster
- 普通 Top-K 不被全部占满
- 问“我都喝过什么”时可展开更多成员

## Graph
至少验证：
- RELATED_TO
- PART_OF
- EVIDENCE_FOR
- SUPERSEDES
- CONTRADICTS
- max_hops
- 低权重边过滤
- 无无限循环

## Diversity
top_k=8，同一 cluster 有 20 条高相似 Memory：
- 普通查询最多占配置上限
- 其他相关 Cluster 仍可进入

## Activation
- 新 Memory activation 高
- 时间后衰减
- 强召回适度 boost
- 邻居小幅传播
- importance 高不等于永远高 activation

## Lifecycle
覆盖：
- ACTIVE
- COLD
- DORMANT
- ARCHIVED
- FORGOTTEN

## Consolidation
- 多 Episode 可归纳 Semantic
- 有 evidence_memory_ids
- 原 Episode 保留
- Graph 建 EVIDENCE_FOR / DERIVED_FROM

## Conflict
旧偏好与新偏好冲突：
- 不静默覆盖历史
- 使用时间 / supersedes / contradicts 表达变化

## 性能
至少模拟 10,000 Memory，验证：
- keyword search
- O(n) embedding scan
- cluster rerank
- 2-hop graph expansion

不要求毫秒级。

---

# 41. 手动验收场景

## 场景 A：生活小事

连续聊：

```text
今天中午吃了碗粉。
下午去打了舞萌。
回来路上风挺舒服。
晚上准备继续写朝汐。
```

预期：

- 生成多个 Episode / Intent
- 不只保存其中一条
- 不把整段原文当一个 Memory

## 场景 B：同主题大量 Memory

两个月内反复记录：

```text
啤酒
白朗姆
金酒
```

预期：

- 原 Episode 全部保留
- 自动形成“饮酒” Cluster
- 普通查询不让饮酒占满全部 Top-K

## 场景 C：主题展开

问：

```text
我之前都喝过什么？
```

预期：

- 展开饮酒 Cluster
- 返回多个具体 Episode
- 不受普通 per_cluster_limit 严格限制

## 场景 D：模糊联想

问：

```text
之前是不是有次写东西写烦了？
```

预期：

- keyword / embedding / graph 联合召回
- 能找到相关八股或开发疲惫 Episode

## 场景 E：关联回忆

问：

```text
2026暑假最后那段时间发生过什么？
```

预期可联想到：

- 公寓结束
- Zhaoxi
- LifeHUD
- 白朗姆
- 返校
- 歌单

但控制数量并保持多样性。

## 场景 F：经历沉淀

多次记录夜间高效率开发。

Consolidation 后生成：

```text
Semantic:
暗苟通常更容易在夜间进入高专注开发状态。
```

并可追溯来源 Episode。

## 场景 G：偏好变化

先有：

```text
2026夏：更喜欢晚上开发
```

后有：

```text
2027春：更喜欢上午开发
```

预期：

- 保留两段时期
- 不同时作为“当前永恒事实”
- 新事实可 supersede / contradict 旧事实

---

# 42. 不在本版本处理

明确不做：

- Neo4j
- 大型图谱可视化
- ANN / HNSW
- 分布式数据库
- 云 Memory
- 多用户 Memory
- 自动修改 Tidecourt Archive
- 自动重写 Personality
- 超复杂 ontology
- 100+ relation enum
- 完整心理学仿真

---

# 43. 完成标准

v1.1.4 完成后必须满足：

1. 写入标准明显低于旧系统。
2. 一轮对话可生成多条原子 Memory。
3. Episodic 真正成为主要生活记录类型之一。
4. 支持 Semantic / State / Intent / Relationship。
5. relevance 拆分为 activation 与动态 contextual relevance。
6. 时间有效性真正参与检索。
7. Memory 可自动形成 Cluster。
8. 普通 Top-K 不被单一 Cluster 占满。
9. Memory 之间存在可查询关系。
10. Graph 支持 1~2 hop 联想扩展。
11. Graph 不是唯一事实源，可重建。
12. 支持 keyword + embedding + metadata + time + graph Hybrid Retrieval。
13. Embedding 可 O(n) 扫描。
14. activation 可衰减与轻量传播。
15. 自然遗忘采用 ACTIVE / COLD / DORMANT / ARCHIVED。
16. 明确 forget 才进入 FORGOTTEN。
17. Consolidation 能将多个 Episode 归纳成 Semantic。
18. Semantic 有证据链。
19. 原 Episode 不因 Consolidation 被删除。
20. 新旧事实冲突能保留时间演化。
21. Archive 与 Memory 边界保持清晰。
22. 旧 Memory DB 可安全迁移。
23. Diagnostics 可观察 Cluster / Graph / Consolidation。
24. Retrieval Debug 可解释为什么想起某条 Memory。
25. 现有 Personality / Archive / Proactive / Session / Planner / Workflow 保持正常。

---

# 44. 开发完成后汇报

Codex 完成后请明确汇报：

- 修改文件
- Memory schema
- DB migration
- 新 MemoryKind
- MemoryShape
- MemoryCandidate batch schema
- AutoMemory Prompt 调整
- atomic extraction
- importance / activation / contextual relevance 设计
- 时间字段
- Cluster 结构
- Cluster 归属算法
- Cluster Summary
- per_cluster_limit
- Graph 节点 / 边
- relation 设计
- Graph build 策略
- Activation Spreading
- Hybrid Retrieval
- Embedding Provider
- Embedding 缓存
- Retrieval Fusion
- Diversity Rerank
- Lifecycle
- Consolidation
- Semantic evidence
- Conflict / Supersedes
- Diagnostics
- Debug Inspect
- 性能测试
- 自动测试结果
- 手动验收步骤
- 已知限制

---

# 45. 本版本理念

过去的 Memory 更像：

> 一排排独立保存的句子。

v1.1.4 之后，希望它变成：

> **一张随着生活不断长出来的联想网络。**

暗苟每天说过很多小事。

朝汐不必判断：

> “这件事够不够伟大，值得永远记住？”

她可以先把它收下来。

很多细碎的事情会逐渐靠近彼此。

喝过的酒会聚成一个抽屉。

一次次开发会慢慢组成一个阶段。

一些反复发生的经历，会沉淀成新的认识。

某些长期没有被碰过的东西，会被收到更深的地方。

而当未来某一天，暗苟只说出一个模糊的线索，

朝汐可以从一个记忆出发，

沿着那些已经形成的联系，

一点一点把整片过去重新点亮。

这就是：

# Associative Memory

> **宽记，成簇，建联，慎忆。**

> 记忆不是一张表。  
> 它应该是一座住久之后，房间之间自然长出走廊的潮庭。
