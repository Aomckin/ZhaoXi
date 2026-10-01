# Zhaoxi v1.4.3 · Memory 3.0 / Broad Memory, Careful Recall
## 长期记忆、AutoMemory、Cluster Recall 与认知数据链路大重构任务书

> 项目：**Zhaoxi / 朝汐**\
> 版本：**v1.4.3**\
> 类型：**大型重构版本 / Memory & Cognition Data Cleanup**\
> 前置版本：
>
> - v1.4.0：Runtime Observatory / Visibility / Post-turn Maintenance
> - v1.4.1：Fast Dialogue Lane
> - v1.4.2：Current Cognition 2.0 / Fast Gate 2.0 收口
>
> 本版核心原则：
>
> > **广记，慎想。**
>
> 写入可以宽，召回必须谨慎；\
> 记忆可以多，进入上下文的必须少而准；\
> “记住”与“想起来”是两回事；\
> Current Cognition、Long-Term Memory、Archive、Experience 不再互相抢活。
>
> 本版不是再补一层 Prompt，而是一次真正的 Memory Runtime 重构。

---

# 0. v1.4.3 为什么要做成大版本

目前 Memory 相关模块已经不是“功能少”，而是：

```text
历史版本长期叠加
+
旧字段兼容
+
聚类语义漂移
+
检索路径与原设计分叉
+
AutoMemory 过重
+
数据存储重复
+
激活值饱和
+
召回机制缺乏层级
```

已经形成典型的：

> **功能都有，但边界不清、语义打架、运行时越来越黑。**

本版目标不是“再修一个 bug”，而是把 Memory 子系统重新收成：

```text
Experience
→ AutoMemory
→ Long-Term Memory
→ Cluster / Index
→ Recall
→ Context Injection
```

每层职责清楚、可观测、可迁移、可回滚。

---

# 1. 当前真实数据基线

以下为当前真实数据库体检结果，用作 v1.4.3 的迁移和验收基线。

## 1.1 Long-Term Memory

当前约：

```text
Memory 总数：1022
已进入 Cluster：999（97.7%）
未聚类：23
有 Embedding：1011（98.9%）
```

状态分布：

```text
ACTIVE      1006（98.4%）
COLD          11（1.1%）
FORGOTTEN      5（0.5%）
```

类型分布：

```text
Episodic      411
State         228
Intent        179
Semantic      169
Relationship   35
```

来源：

```text
conversation  863（84.4%）
user          159（15.6%）
```

---

## 1.2 Cluster 分布

当前：

```text
Cluster 总数：67
已聚类 Memory：999
```

最大两个：

```text
Zhaoxi开发    629
求职          214
```

两者合计：

```text
843 / 999
≈ 84.4%
```

同时：

```text
单例 Cluster：49
占全部 Cluster 的约 73%
```

即当前结构更像：

```text
两个超级黑洞
+
大量单条碎岛
```

而不是稳定的中粒度语义簇。

---

## 1.3 Cluster Membership 异常

当前 999 条 membership 中：

```text
score = 1.0：973
```

约：

```text
97.4%
```

这不是聚类质量特别高，而是当前逻辑：

```text
exact topic match
→ membership_score = 1.0
```

导致 Topic Bucket 吞并过度。

---

## 1.4 Activation 饱和

当前：

```text
activation >= 0.9：962
activation = 1.0：891
平均 activation ≈ 0.978
```

即：

> **87.2% 的全部 Memory 已经顶到 1.0。**

Activation 几乎失去区分度。

---

# 2. 其他数据库体检结果

## 2.1 ExperienceStream

当前约：

```text
experience.db ≈ 179 MB
事件总量 ≈ 1540
```

体积异常大的主要原因：

```text
图片 base64 直接存入 JSON payload
```

单条事件可超过：

```text
10 MB
```

---

## 2.2 Perception

当前约：

```text
perception.db ≈ 139 MB
Observation ≈ 1487
```

大量外部图片 / payload 同样直接进入数据库。

并且至少有大量 Perception Observation 又被投射进入 ExperienceStream。

可能形成：

```text
同一图片
→ perception.db 一份
→ experience.db 又一份
```

---

## 2.3 Session

当前文件约：

```text
session.db ≈ 59 MB
```

但实际活数据仅约：

```text
3~4 MB
```

绝大多数为：

```text
SQLite freelist / 已释放但未 VACUUM 的页
```

同时图片仍可能直接占据 session JSON。

---

## 2.4 Post-turn Maintenance

当前观测：

```text
任务约 67
completed 51
failed    15
running    1
```

失败约：

```text
22%
```

主要失败集中在：

```text
AutoMemory phase
```

AutoMemory 模型调用约：

```text
65 次
平均耗时 ~17s
平均输出 ~1300 tokens
```

其中大量：

```text
finish_reason = length
```

说明当前 AutoMemory Prompt / Output Contract 明显过重。

---

# 3. v1.4.3 总体架构目标

最终链路：

```text
ExperienceStream
↓
Memory Candidate Gate
↓
AutoMemory Extraction
↓
Memory Normalization
↓
Long-Term Memory Store
↓
Cluster / Index Maintenance
↓
Retrieval Mode
↓
Cluster-first Candidate Retrieval
↓
Global Escape Candidates
↓
Hybrid Rerank
↓
Context Injection
```

并明确：

```text
Current Cognition
≠ Long-Term Memory
≠ Archive
≠ Experience
```

---

# 4. P0 · Memory Semantic Contract

Memory 运行时统一为三轴：

## 4.1 importance

定义：

> 这条记忆长期有多值得保存。

性质：

```text
稳定
变化慢
由内容价值决定
```

---

## 4.2 activation

定义：

> 这条记忆当前有多“热”，多容易自然浮上来。

性质：

```text
动态
随时间衰减
被访问 / 被关联后上升
```

---

## 4.3 contextual_relevance

定义：

> 这一次 Query 与这条 Memory 有多相关。

性质：

```text
query-scoped
不写回 Memory
```

---

# 5. 清理 legacy relevance

当前旧代码仍存在：

```text
relevance
→ 实际映射 activation
```

v1.4.3：

```text
运行时彻底禁用 relevance 旧语义
```

允许：

```text
数据库 migration compatibility
```

但新代码 / Debug / Prompt / API 只允许：

```text
importance
activation
contextual_relevance
```

---

# 6. P0 · Memory Lifecycle 重构

推荐正式生命周期：

```text
ACTIVE
↓
COLD
↓
DORMANT
↓
ARCHIVED
```

另有：

```text
FORGOTTEN
SUPERSEDED
```

---

## 6.1 ACTIVE

近期自然容易想到。

---

## 6.2 COLD

值得保留，但不应主动浮现。

---

## 6.3 DORMANT

长期没有激活，需要明确 Recall 才检索。

---

## 6.4 ARCHIVED

更深层历史。

仅在：

```text
explicit recall
broad search
```

中出现。

---

## 6.5 FORGOTTEN

只表示：

```text
用户明确要求忘记 / 禁止召回
```

不要把低 activation 自动等同 FORGOTTEN。

---

# 7. 删除“假旋钮”

当前存在但未真正参与逻辑的配置需要清理。

例如：

```text
importance_forget_threshold
activation_dormant_threshold
```

处理原则：

```text
要么真正接入
要么删除
```

禁止继续保留：

```text
看起来可调
实际不生效
```

的配置。

---

# 8. P0 · 修复 Activation 饱和

当前核心问题：

```text
召回 +0.12
邻居 +0.03
二跳 +0.008
每日衰减仅 0.01
```

导致：

```text
大量 Memory 很快顶到 1.0
```

---

## 8.1 改为非线性激活

建议：

```text
boost = base_boost * (1 - activation)
```

例如：

```text
0.3 → 提升明显
0.8 → 提升有限
0.95 → 几乎不再增长
```

避免“越热越容易永久焊死”。

---

## 8.2 Access Boost 分层

建议：

```text
直接命中 selected
> cluster sibling
> graph neighbor
```

而不是所有邻居都持续大幅增温。

---

## 8.3 Decay 改为可解释策略

建议按：

```text
状态
importance
访问间隔
```

共同决定。

例如：

```text
高 importance
→ decay 慢

普通生活碎片
→ decay 快

连续未访问
→ decay 加速
```

---

# 9. P0 · AutoMemory Calibration

当前问题：

LLM 会直接输出：

```text
importance
activation
```

但没有明确标尺。

---

## 9.1 importance 评分标尺

建议：

```text
0.1~0.25
普通生活碎片，只提供生活质感

0.3~0.45
一般经历、小事件、小偏好

0.5~0.65
明显阶段事实 / 项目事实 / 有持续意义的状态

0.7~0.85
长期偏好、目标、关系、原则、重要经历

0.9~1.0
明确要求长期记住 / 核心身份 / 极关键事实
```

---

## 9.2 activation 尽量 Runtime 决定

避免让 LLM 自由评分。

建议初始值：

```text
刚发生的一般事件       0.65
近期持续状态           0.75
当前重点主线           0.80
显式“记住”             0.90
历史导入                0.25~0.40
Archive 派生事实        0.30~0.50
```

后续由：

```text
时间
召回
关联
```

动态变化。

---

# 10. P0 · AutoMemory 输出收口

当前大量 AutoMemory：

```text
finish_reason = length
```

说明输出合同过重。

v1.4.3 必须：

```text
缩短 Prompt
限制候选数量
限制每个 candidate 字段长度
Structured Output
禁止长 explanation
```

例如：

```json
{
  "candidates": [
    {
      "type": "semantic",
      "content": "...",
      "importance": 0.72,
      "tags": ["..."],
      "evidence_refs": ["..."]
    }
  ]
}
```

---

# 11. AutoMemory Candidate 数量上限

建议：

```text
普通一轮：0~3 条
复杂长轮：最多 5 条
```

不要：

```text
一轮对话拆 10+ 条 Memory
```

---

# 12. P0 · Maintenance Phase Failure Isolation

当前：

```text
AutoMemory fail
→ 整个 post-turn maintenance failed
→ Current Cognition 不再执行
```

必须改。

推荐：

```text
AutoMemory phase
try
↓
记录 success / failure
↓
Current Cognition phase
继续执行
```

每阶段独立：

```text
status
error
duration
metrics
```

---

# 13. Memory Evidence 强约束

新 Memory 必须尽量保留：

```text
source_event_id
evidence_reference
source_message_id
```

目标：

```text
Memory
↓
AutoMemory Candidate
↓
Experience Event
↓
原始 User / Assistant Turn
```

Debug 可以完整追溯。

---

# 14. 旧数据 Evidence 不强行伪造

旧 Memory 没有 evidence：

```text
保持 unknown / legacy
```

不要通过时间猜测后强行补一个“看起来差不多”的来源。

---

# 15. P0 · Cluster 语义重构

当前 Cluster 实际更像：

```text
Topic Bucket
```

而不是：

```text
Semantic Cluster
```

需要彻底改。

---

# 16. Domain 与 Semantic Cluster 分层

推荐两层：

```text
Domain
↓
Semantic Cluster
```

例如：

```text
求职
├─ 亚信
├─ 丘脑智能
├─ 简历
├─ 秋招策略
└─ 面试状态

朝汐
├─ Runtime
├─ Memory
├─ Current Cognition
├─ Persona
├─ QQ
└─ LifeHUD
```

---

# 17. 禁止 exact topic = membership 1.0

当前：

```text
topic 相同
→ score = 1.0
```

必须移除。

Topic 只能作为：

```text
domain prior
```

不能直接代表：

```text
semantic identity
```

---

# 18. Cluster Membership 新评分

建议：

```text
semantic similarity
+ tag overlap
+ entity overlap
+ temporal affinity
+ type compatibility
```

其中：

```text
semantic similarity
```

必须是主信号。

---

# 19. 大 Cluster 自动 Split

当满足：

```text
member_count > threshold
且
内部平均 similarity 下降
```

自动触发：

```text
split candidate
```

例如：

```text
Zhaoxi开发 629
```

必须拆。

---

# 20. Singleton Cluster 清理

对于单例：

```text
长期无法找到相关成员
```

可以：

```text
保持 orphan
或
挂到 Domain，不强制建 Cluster
```

不要：

```text
每条 Memory 都生成一个名义 Cluster
```

---

# 21. Cluster Merge 真正接通

当前 Merge 几乎没有实际发生。

v1.4.3：

```text
相似 Cluster
→ merge candidate
```

但禁止：

```text
仅凭 Topic 相同就 merge
```

必须看：

```text
centroid similarity
tags
entities
summary
```

---

# 22. P0 · Cluster-first Retrieval

真正实现：

```text
Query
↓
Cluster Retrieval
↓
Top-K Semantic Clusters
↓
Cluster 内 Candidate Memories
↓
Global Escape Candidates
↓
Hybrid Rerank
```

---

# 23. Cluster Retrieval Score

建议：

```text
cluster_semantic
cluster_text
entity_match
tag_match
cluster_activation
cluster_importance
```

输出：

```text
Top 3~5 Clusters
```

---

# 24. Global Escape Candidates

必须保留。

避免：

```text
Memory 当初分错 Cluster
→ 以后永远搜不到
```

建议额外加入：

```text
Global FTS Top-K
Global Semantic Top-K
Recent High-Activation Top-K
Exact Entity Hits
```

再与 Cluster Candidates union。

---

# 25. Retrieval Mode

正式新增：

```text
ASSOCIATIVE
EXPLICIT_RECALL
BROAD_SEARCH
```

---

## 25.1 ASSOCIATIVE

用于自然联想。

候选：

```text
ACTIVE
+
少量高相关 COLD
```

默认不碰：

```text
DORMANT
ARCHIVED
```

---

## 25.2 EXPLICIT_RECALL

用于：

```text
“你还记得……”
“上次……”
“以前……”
```

允许：

```text
ACTIVE
COLD
DORMANT
ARCHIVED
```

---

## 25.3 BROAD_SEARCH

用户明确：

```text
“帮我翻一下记忆”
“都有哪些……”
```

可进一步扩大。

---

# 26. COLD 的语义必须恢复

COLD 应表示：

> **记得，但平时不会自己冒出来。**

只有：

```text
高 contextual relevance
或
explicit recall
```

才能召回。

---

# 27. Candidate Retrieval 两阶段

Stage 1：

```text
FTS
Semantic
Cluster
Entity
Recent / Active
```

做 candidate generation。

Stage 2：

```text
Hybrid Rerank
```

不要继续：

```text
从大池子拿很多 Memory
→ Python 全量评分
```

---

# 28. SQLite FTS5 正式接入

现有：

```text
memories_fts
```

已经存在但主 Search 没真正用。

v1.4.3：

```text
FTS5
→ lexical candidate source
```

不再只是摆设。

---

# 29. Semantic Retrieval

当前：

```text
LocalHashEmbeddingProvider
```

本质：

```text
lexical hashing vector
```

不是真语义 Embedding。

---

# 30. Real Embedding Provider

本版后半段加入可插拔：

```text
local-hash-v1
→ fallback / legacy

semantic provider
→ primary
```

不绑定特定模型。

接口：

```python
EmbeddingProvider.embed(text)
```

保持不变。

---

# 31. Embedding Versioning

每条 Memory / Cluster 记录：

```text
embedding_model
embedding_version
embedding_dim
```

更换模型时：

```text
reindex
```

禁止混用不同 embedding 直接 cosine。

---

# 32. Reindex 工具

新增 CLI / Debug Action：

```text
rebuild_memory_embeddings
rebuild_cluster_centroids
rebuild_memory_fts
recluster_memories
```

必须支持：

```text
dry-run
progress
backup
cancel / rollback
```

---

# 33. Retrieval Hybrid Score

现有 Hybrid 思路可以保留。

但权重需要重新校准。

推荐目标：

```text
semantic
text
cluster
graph
time
activation
importance
```

注意：

```text
importance + activation
不能成为 topical relevance 主角
```

它们只是：

```text
Memory 自身性质
```

---

# 34. Cluster Diversity

继续保留：

```text
per-cluster limit
```

但改成：

```text
根据 retrieval mode / cluster confidence 动态调整
```

例如：

```text
明确锁定单一事件
→ 同 Cluster 可多拿

广泛联想
→ 保持多 Cluster 多样性
```

---

# 35. Graph 的定位

Memory Graph 继续保留。

但明确：

```text
Graph Expansion
= rerank / enrichment
```

不是一级 candidate source 的唯一依赖。

---

# 36. P1 · Memory Retrieval Observatory 2.0

v1.4.0 已有 Inspector。

v1.4.3 扩展：

```text
retrieval_mode

cluster_candidates
cluster_score
cluster_rank

candidate_source:
- cluster
- fts
- semantic
- recent
- entity
- graph
- escape

status_filter

why_included
why_excluded
why_promoted
why_demoted
```

---

# 37. Debug 必须能回答

```text
为什么这条 Memory 被找到？
为什么这条没被找到？
为什么这个 Cluster 被选中？
为什么 COLD 还能出现？
为什么这条 activation 变高？
```

---

# 38. P1 · Archive 与 Memory 边界

Archive：

```text
人工正式资料
版本文档
README
任务书
手册
```

Memory：

```text
经历
认知
状态
偏好
关系
```

禁止：

```text
把整份 Archive chunk 自动抄进 Memory
```

---

# 39. Artifact Resolver

复用 Archive 元数据：

```text
title
source_path
updated_at
tags
```

提供轻量：

```text
artifact_reference_match
```

供：

```text
Fast Gate 2.0
Router
Memory Recall
```

使用。

---

# 40. P1 · Experience / Memory 漏斗观测

新增统计：

```text
Owner turns
↓
AutoMemory triggered
↓
Candidates generated
↓
Candidates accepted
↓
Memory written
↓
Cluster assigned
```

查看：

```text
每 100 条 Owner Turn
最终生成多少长期 Memory
```

---

# 41. 防止 Memory 过度拆分

一轮输入：

```text
同一事实的多个表述
```

应该：

```text
merge / dedup
```

而不是：

```text
拆成多条相似 Memory
```

---

# 42. Memory Dedup

新增：

```text
exact hash
near-duplicate semantic
same-event duplicate
same-entity same-fact
```

候选时先查：

```text
create
update
merge
ignore
```

---

# 43. P1 · Perception / Experience 图片去重

当前：

```text
Base64 图片
```

可能同时存：

```text
perception.db
experience.db
session.db
```

建议新增：

```text
MediaBlobStore
```

---

# 44. MediaBlobStore

结构：

```text
media/
  sha256/...
```

数据库只存：

```text
media_id
hash
mime
size
thumbnail_ref
```

---

# 45. Media 去重

同一内容：

```text
hash 相同
→ 只保存一次
```

Perception / Experience / Session 只引用。

---

# 46. 图片迁移策略

不要在主启动时一次性迁移 300MB。

提供：

```text
offline migration
lazy migration
```

优先新数据先切换。

旧数据可后续后台迁。

---

# 47. P1 · Session SQLite Cleanup

增加：

```text
VACUUM
incremental_vacuum
```

或定期维护入口。

目标：

```text
释放 freelist
```

不是频繁每轮 VACUUM。

---

# 48. DB Maintenance Dashboard

展示：

```text
db size
live pages
freelist pages
last vacuum
media blobs
dedup ratio
```

---

# 49. P1 · AutoMemory 与 Current Cognition 解耦

Post-turn Maintenance：

```text
AutoMemory
Current Cognition
```

应阶段独立。

建议：

```text
PhaseResult:
  status
  error
  duration
  metrics
```

某一阶段失败：

```text
不自动阻止其他独立阶段
```

---

# 50. Maintenance Queue Phase 模型升级

从：

```text
phase int
```

逐步升级成：

```text
named phases
```

例如：

```text
auto_memory
current_cognition
future_reflection
```

便于以后扩展。

---

# 51. P1 · Memory Write Rate / Backpressure

如果短时间大量外部消息进入：

```text
不要无限 AutoMemory
```

加入：

```text
batching
dedup
rate limit
owner priority
```

---

# 52. Migration 总原则

v1.4.3 必须支持：

```text
backup
dry-run
migration report
rollback
```

禁止：

```text
启动一次直接把 1022 条 Memory 全改坏
```

---

# 53. Migration Phase A · 只读体检

输出：

```text
cluster size distribution
activation histogram
status distribution
duplicate candidates
orphan memories
missing evidence
embedding versions
```

---

# 54. Migration Phase B · Recluster Dry Run

不写库。

输出：

```text
旧 Cluster
→ 新 Domain
→ 新 Semantic Cluster

split
merge
orphan
```

---

# 55. Migration Phase C · Backup

至少：

```text
memory.db.bak
archive.db.bak
```

必要时：

```text
experience.db metadata backup
```

---

# 56. Migration Phase D · Reindex

执行：

```text
FTS rebuild
embedding rebuild
cluster centroid rebuild
recluster
```

---

# 57. Migration Phase E · Activation Rebalance

不能简单保留当前：

```text
大量 1.0
```

需要重新归一化。

建议基于：

```text
last_access
access_count
created_at
importance
recent evidence
```

重算初始 activation。

---

# 58. Activation Rebalance 目标

迁移后分布不应：

```text
90% > 0.9
```

理想更像：

```text
少量高热
一批中热
大量冷 / dormant
```

具体阈值根据数据调。

---

# 59. Legacy Cluster 迁移

禁止直接把：

```text
Zhaoxi开发 629
```

原样保留。

至少拆成：

```text
Runtime
Memory
Current Cognition
Persona
QQ
LifeHUD
UI
Tool System
```

---

# 60. 求职 Cluster 迁移

至少尝试拆：

```text
公司 / 面试
网申
笔试
岗位偏好
秋招状态
简历
```

---

# 61. 测试集

从真实 Memory 选固定 Benchmark Query。

至少覆盖：

```text
朝汐 Runtime
亚信面试
丘脑智能
LifeHUD 饮食
舞萌
饮酒
寝室状态
秋招
角色设定
QQ 接入
```

---

# 62. Retrieval Benchmark

每个 Query 人工标注：

```text
Expected Relevant Memories
Expected Cluster
Forbidden Distractors
```

统计：

```text
Recall@K
Precision@K
MRR
Cluster Hit Rate
Wrong Cluster Rate
```

---

# 63. 迁移前后对比

必须输出：

```text
旧检索 Top-K
新检索 Top-K
```

人工比较。

不要只看：

```text
速度变快
```

却召回变差。

---

# 64. 性能目标

当前约 1k Memory。

目标：

```text
Candidate Retrieval
< 100ms 本地

Hybrid Rerank
< 100ms~300ms

不计 LLM
```

未来：

```text
10k Memory
```

也不应退化成全量 Python Scan。

---

# 65. 大库扩展目标

设计必须至少能自然扩展到：

```text
10k
50k
100k Memory
```

不要求现在压测 100k，但架构不能默认：

```text
全部 list_records
```

---

# 66. 不把 Memory Retrieval 放回 FAST

即使 v1.4.3 做得很快：

```text
FAST_CHAT
仍默认不查 Long-Term Memory
```

Fast 依赖：

```text
Recent Conversation
Current Cognition
```

只有：

```text
Recall Need
Escalation
```

才进入长期 Memory。

---

# 67. 与 Fast Gate 2.0 联动

Fast Gate 可以消费：

```text
historical_specificity
current_cognition_sufficient
artifact_reference
```

但不要：

```text
为了判断 FAST
先跑完整 Memory Retrieval
```

否则又把性能优化绕回去了。

---

# 68. 本版建议代码模块

可以逐步收成：

```text
src/zhaoxi/memory/
    models.py
    service.py
    lifecycle.py
    retrieval/
        modes.py
        cluster_index.py
        candidate_sources.py
        reranker.py
    clustering/
        domain.py
        semantic.py
        maintenance.py
    embedding/
        base.py
        local_hash.py
        semantic_provider.py
        reindex.py
    migration/
        audit.py
        recluster.py
        rebalance.py
```

不强制一次性移动所有文件。

优先保证职责清楚。

---

# 69. 推荐开发顺序

## Phase 1 · Semantic Contract

- [ ] importance / activation / contextual_relevance
- [ ] 清 legacy relevance
- [ ] FORGOTTEN 语义
- [ ] 配置假旋钮清理

## Phase 2 · AutoMemory

- [ ] importance 标尺
- [ ] activation Runtime 初始化
- [ ] Structured Output
- [ ] Candidate 上限
- [ ] finish_reason length 修复
- [ ] evidence 强约束
- [ ] phase failure isolation

## Phase 3 · Lifecycle

- [ ] activation 非线性 boost
- [ ] decay
- [ ] ACTIVE / COLD / DORMANT / ARCHIVED
- [ ] migration rebalance

## Phase 4 · Cluster 3.0

- [ ] Domain / Semantic Cluster
- [ ] 删除 exact-topic=1.0
- [ ] Split
- [ ] Merge
- [ ] Singleton policy
- [ ] Cluster migration dry-run

## Phase 5 · Retrieval 3.0

- [ ] Retrieval Mode
- [ ] Cluster-first
- [ ] FTS candidate source
- [ ] Global escape
- [ ] Hybrid reranker
- [ ] Diversity

## Phase 6 · Embedding

- [ ] Provider metadata
- [ ] real semantic provider
- [ ] fallback
- [ ] reindex

## Phase 7 · Observatory

- [ ] Cluster Inspector
- [ ] Candidate Source
- [ ] Retrieval Mode
- [ ] Lifecycle reason
- [ ] Activation history

## Phase 8 · Data Cleanup

- [ ] MediaBlobStore
- [ ] Perception / Experience new data dedup
- [ ] Session vacuum
- [ ] DB metrics

## Phase 9 · Migration

- [ ] audit
- [ ] backup
- [ ] dry run
- [ ] recluster
- [ ] activation rebalance
- [ ] reindex
- [ ] report

## Phase 10 · Dogfooding

至少：

```text
5~7 天
```

观察：

```text
召回是否变准
Memory 是否仍快速膨胀
activation 是否重新饱和
Cluster 是否重新长成黑洞
AutoMemory 是否继续 length
Current Cognition 是否被 Memory 污染
```

---

# 70. 本版不做

暂不做：

```text
Planner UI
Presence 2.0
Dashboard 大改
向日葵视觉
手机端
```

v1.4.3 优先把“脑子深处”收干净。

---

# 71. 完成标准

v1.4.3 完成后必须满足：

```text
1. relevance 旧语义从运行时消失。

2. importance / activation / contextual_relevance 三轴职责明确。

3. activation 不再大面积饱和到 1.0。

4. ACTIVE / COLD / DORMANT / ARCHIVED 真正产生区分。

5. COLD 不再默认等同普通 ACTIVE 参与自然召回。

6. AutoMemory 不再频繁撞输出长度上限。

7. AutoMemory 失败不会拖死 Current Cognition。

8. 新 Memory 尽量具有可追溯 evidence。

9. Zhaoxi开发 / 求职 巨型 Topic Bucket 被拆解。

10. Cluster 不再主要依赖 exact topic。

11. Cluster-first Recall 真正进入主搜索链。

12. 全局 Escape Candidate 防止错聚类导致永远搜不到。

13. SQLite FTS 真正参与 Candidate Retrieval。

14. 真语义 Embedding 可插拔，并具备版本 / reindex 能力。

15. Retrieval 不再依赖大规模 Python 全扫。

16. Fast Chat 仍默认不查长期 Memory。

17. Experience / Perception 新图片不再重复 Base64 存多份。

18. Session DB 可以释放 freelist。

19. Debug 可以解释：
    - 为什么记
    - 为什么热
    - 为什么冷
    - 为什么聚在这个簇
    - 为什么这次被召回
    - 为什么没有被召回

20. 真实 1k Memory benchmark 上，召回质量不得低于迁移前。
```

---

# 72. v1.4.3 的最终目标

现在的长期 Memory 更像：

```text
东西都记下来了
但所有东西都在脑门前挥手
而且 Zhaoxi开发 这个抽屉里塞了半个世界
```

v1.4.3 要变成：

```text
该记的仍然记
↓
自然形成中粒度语义簇
↓
近期热记忆容易自然联想
↓
旧记忆逐渐冷却
↓
明确回忆时仍然能找回来
↓
真正相关的少数内容才进入上下文
```

也就是：

> **不是少记，而是终于学会怎么放、怎么找、什么时候想起来。**
