# Zhaoxi v0.3.2 · Memory Lifecycle 任务书

> 项目：**Zhaoxi / 朝汐**  
> 版本：**v0.3.2 · Memory Lifecycle**  
> 目标：在 v0.3.1 Auto Memory 基础上，补齐**记忆生命周期、遗忘机制、记忆压缩与外部事实源边界**。
>
> 核心原则：
>
> **重要的事情，即使很久没提，也不应该轻易遗忘。**  
> **经常与当前生活发生联系的事情，即使本身普通，也应该保持活跃。**  
> **只有当重要程度和关联程度都降低时，一段记忆才真正开始走向遗忘。**

> 实现状态：已完成。SQLite schema v2、生命周期策略、用户控制、Consolidation 与 Tool Source of Truth 边界均已接入，并保留 v1 数据库兼容迁移。

---

# 1. 本版本核心目标

v0.3.1 解决：

> 什么值得记住？

v0.3.2 解决：

> 记住以后，什么该一直保留？  
> 什么该逐渐淡化？  
> 什么该压缩？  
> 什么最终可以遗忘？

同时明确：

> **能从 Life HUD / GitHub / Calendar / Files 等 Tool 重新查询得到的结构化事实，不应默认长期复制进 Zhaoxi Memory。**

Zhaoxi Memory 主要保存：

- 长期偏好
- 稳定习惯
- 认知结论
- 人物关系
- 项目语义上下文
- 长期目标
- 对用户的抽象理解
- Tool 难以直接重新查询出的语义信息

---

# 2. Memory 与 Tool 的边界

## 2.1 Source of Truth 原则

优先级：

```text
Life HUD
→ 生活事实

GitHub
→ 代码 / 项目事实

Calendar
→ 日程事实

Files
→ 文档事实

Zhaoxi Memory
→ 认知、偏好、语义关系与长期印象
```

示例：

```text
Life HUD：
过去 20 个晚上，算法 Focus 较少，项目开发较多。

Zhaoxi Memory：
暗苟晚上通常更愿意开发项目，而不是刷算法。
```

前者是事实证据。

后者是朝汐形成的认知。

---

## 2.2 可重新查询事实默认不长期复制

例如：

```text
“今天 Focus 3h20min”
“昨晚睡了 7h”
“今天吃了辣椒炒肉”
“当前任务还有 4 个”
```

如果可以稳定从 Life HUD 查询：

```text
→ 不默认创建长期 Memory
```

除非该事实本身具有明显长期意义，例如：

```text
“这是第一次完成 Zhaoxi v1.0”
```

此时可以保存为长期事件或认知。

---

# 3. 记忆二维模型

每条长期 Memory 至少增加：

```text
importance
relevance
```

建议范围：

```text
0.0 ~ 1.0
```

---

## 3.1 Importance · 重要程度

表示：

> 这件事本身对长期认知有多重要。

特点：

- 变化较慢
- 不因为长时间没提就快速下降
- 显式要求“记住”的内容应有较高初始值
- 长期目标、核心偏好、重要人物关系通常较高

示例：

```text
“朝汐的拼音统一写 Zhaoxi”
importance = 0.95

“最近在调一个按钮布局”
importance = 0.20
```

---

## 3.2 Relevance · 关联 / 活跃程度

表示：

> 当前这段记忆与最近生活、对话和任务有多强的联系。

特点：

- 变化较快
- 会随时间衰减
- 被再次提到、检索、使用时会上升
- 与近期高活跃 Memory 强关联时也可提升

可增加 relevance 的事件：

```text
用户再次提到
Memory 检索命中
Planner 使用
Tool 结果重新验证
与近期事件产生关联
与其他高活跃 Memory 共同出现
```

可降低 relevance 的因素：

```text
长期未访问
项目结束
上下文切换
相关主题长期沉寂
```

---

# 4. 四象限行为

```text
                    Importance
                         ↑

       高重要 / 低关联  │  高重要 / 高关联
       COLD / KEEP      │  CORE / ACTIVE
                        │
────────────────────────┼────────────────────→ Relevance
                        │
       低重要 / 低关联  │  低重要 / 高关联
       FORGET CANDIDATE │  TEMP ACTIVE
```

## 高重要 + 高关联

```text
→ ACTIVE
→ 优先检索
→ 不参与普通遗忘
```

## 高重要 + 低关联

```text
→ COLD
→ 默认不主动注入 Context
→ 保留长期存储
→ 有相关主题时可以重新激活
```

## 低重要 + 高关联

```text
→ ACTIVE / TEMP ACTIVE
→ 当前阶段继续保留
→ 等 relevance 自然衰减后重新判断
```

## 低重要 + 低关联

```text
→ FORGET_CANDIDATE
```

但不要直接物理删除。

---

# 5. Memory Lifecycle

建议状态：

```text
ACTIVE
↓
COLD
↓
ARCHIVED
↓
FORGOTTEN
```

### ACTIVE
- 正常参与 Memory 检索
- 可以进入 Context
- relevance 正常变化

### COLD
- 默认降低检索权重
- 不主动进入普通上下文
- 相关主题出现时可以重新激活

### ARCHIVED
- 普通检索基本不返回
- 明确查询历史时仍可找到
- 等待压缩、合并或遗忘

### FORGOTTEN
第一版建议不要立即物理删除，可采用：

```text
status = forgotten
```

必要时后续再加入真正清理，避免阈值设计错误导致永久损失。

---

# 6. 遗忘规则

第一版保持简单，不做复杂模型。

例如：

```text
if pinned:
    KEEP

elif importance >= 0.75:
    KEEP_OR_COLD

elif relevance >= 0.60:
    ACTIVE

elif importance < 0.30 and relevance < 0.20:
    FORGET_CANDIDATE
```

具体阈值全部配置化，不硬编码散落在代码里。

---

# 7. Relevance 衰减与激活

## 衰减

不要求实时不断更新。

可以在以下时机计算：

```text
Memory 检索前
Memory consolidation 时
Session 结束时
定期 maintenance 时
```

第一版可采用简单时间衰减，不要为了 v0.3.2 引入复杂数学模型。

## 激活

当 Memory：

- 被检索
- 被用户再次提及
- 被 Planner 使用
- 被 Tool 结果证明仍然相关

则提高 relevance。

---

# 8. Memory Consolidation

加入基础记忆压缩 / 固化能力。

示例：

```text
A：今晚不想刷算法
B：晚上刷算法很难受
C：晚上还是开发舒服
D：今晚又去开发了
```

可以合并成：

```text
“暗苟通常更喜欢在晚上进行项目开发，而不是算法练习。”
```

处理后：

```text
新 Semantic Memory
importance ↑

旧 Episodic Memories
→ COLD / ARCHIVED / FORGOTTEN
```

---

# 9. Memory Decision 扩展

v0.3.1 已有：

```text
IGNORE
CREATE
UPDATE
MERGE
CONFLICT
```

v0.3.2 建议增加：

```text
ARCHIVE
FORGET
REACTIVATE
CONSOLIDATE
```

形成完整生命周期动作：

```text
IGNORE
CREATE
UPDATE
MERGE
CONFLICT
REACTIVATE
ARCHIVE
FORGET
CONSOLIDATE
```

---

# 10. Memory 数据字段建议

在现有模型基础上补充：

```text
id
content
kind
tags

importance
relevance

status
pinned

source
source_message_id
evidence

created_at
updated_at
last_accessed_at
access_count

valid_from
valid_until
```

不要求一次全部做复杂逻辑，但 schema 尽量留好。

---

# 11. Pinned Memory

用户显式要求长期保留的关键内容支持：

```text
pinned = true
```

Pinned Memory：

- 不参与自动遗忘
- 不因为 relevance 低而清理
- 仍可由用户显式删除

---

# 12. 用户控制权

必须继续保证用户显式意图最高优先级。

支持：

```text
“别忘了这个”
→ 提高 importance / 可 pin

“这个以后不用记了”
→ archive / forget

“彻底忘掉这个”
→ explicit delete / hard forget

“你为什么记得这个？”
→ 返回 source / evidence
```

自动机制不能覆盖显式用户决定。

---

# 13. 与 Life HUD 的未来协作接口

v0.3.2 不要求真正接入 Life HUD。

但 Memory 层要预留：

```text
source_type = tool
source_name = lifehud
evidence_reference = ...
```

未来朝汐可以：

```text
Memory：
“暗苟晚上更偏好开发。”

source：
lifehud_analysis

evidence：
过去 30 天 Focus 数据
```

如果 Memory relevance 降低甚至被遗忘，未来仍可以重新查询 Life HUD 再推导。

因此：

> **遗忘认知，不等于删除事实。**

---

# 14. 本版本不做

本版不扩业务能力。

不做：

- Life HUD 正式 Tool 接入
- GitHub Tool 接入
- 新 Planner 能力
- Workflow
- Proactive Agent
- RAG
- 向量数据库大重构
- 复杂知识图谱
- 神经网络遗忘模型
- 真正后台定时任务系统
- 大规模 UI

只补：

> **Memory 生命周期。**

---

# 15. 必测场景

## Case A：高重要低关联

```text
Memory：
“项目名拼音必须写 Zhaoxi。”

长期未提及。
```

要求：

```text
relevance 可以下降
importance 保持高
→ 不遗忘
```

## Case B：低重要高关联

```text
“最近正在开发 Zhaoxi v0.3.2。”
```

近期频繁出现：

```text
→ relevance 高
→ ACTIVE
```

项目结束并长期不再提：

```text
→ relevance 下降
→ 可进入 ARCHIVED
```

## Case C：低重要低关联

一次性开发小细节长期未提：

```text
importance 低
relevance 低
→ FORGET_CANDIDATE
```

## Case D：重新激活

一条 COLD Memory 被重新讨论：

```text
→ Memory 被检索
→ relevance 提升
→ REACTIVATE
```

## Case E：Consolidation

多条重复：

```text
晚上不喜欢刷算法
晚上更喜欢开发
晚上又选择开发
```

要求：

```text
→ CONSOLIDATE
→ 形成稳定 semantic memory
→ 旧细节降级
```

## Case F：Tool 可查询事实

未来模拟：

```text
“昨晚睡了 7h。”
```

如果标记为来自可重复查询 Tool：

```text
→ 默认不长期复制为 Memory
```

---

# 16. 完成标准

v0.3.2 完成后，朝汐的 Memory 不再只是：

```text
CREATE
READ
UPDATE
DELETE
```

而应该具备：

```text
记住
↓
被使用
↓
保持活跃
↓
逐渐变冷
↓
重新唤醒
或
压缩 / 合并
↓
最终遗忘
```

同时明确做到：

> **事实尽量留在事实系统。**  
> **Memory 保存朝汐对世界和用户形成的认知。**

## 验收结果

- [x] importance 与 relevance 进入持久化 schema；
- [x] 阈值、衰减速度和访问提升幅度全部配置化；
- [x] 高重要低关联记忆只变冷、不自动遗忘；
- [x] 低重要低关联记忆逐步进入 COLD 与 ARCHIVED；
- [x] COLD 记忆被相关查询命中后自动 REACTIVATE；
- [x] Pinned 记忆不参与自动归档，但允许用户显式遗忘；
- [x] 多条记忆可以 CONSOLIDATE 为 Semantic Memory；
- [x] 普通检索隐藏历史状态，明确历史查询仍可返回；
- [x] 标记为可重复查询的 Tool 事实默认不复制；
- [x] v1 SQLite 数据库原地迁移至 v2 且保留旧记录；
- [x] v0.1 至 v0.3.1 回归测试保持通过。

---

# 17. 版本总结

```text
v0.2
让朝汐拥有长期记忆。

v0.3.1
让朝汐知道什么时候应该记。

v0.3.2
让朝汐知道什么应该一直记着，
什么可以慢慢淡去。
```

最终目标不是：

> 建一个永远只增不减的数据库。

而是：

> **让 Zhaoxi Memory 真正拥有“记忆”的生命周期。**
