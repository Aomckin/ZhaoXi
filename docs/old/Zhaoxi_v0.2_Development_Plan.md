# Zhaoxi v0.2 · Memory 开发计划

> 版本目标：让朝汐能够可控地记住、检索、修正和遗忘长期信息。  
> 基线：v0.1 Agent Runtime、Tool Registry、Conversation 与 Context Builder 已完成，当前 14 个测试通过。  
> 核心原则：长期 Memory 属于 Zhaoxi Core；Conversation 仍只负责当前会话。

---

# 1. 一句话验收目标

完成以下真实闭环：

```text
用户明确要求记住
→ 模型调用 Memory Tool
→ 持久化并返回 memory_id
→ 新会话中检索到相关记忆
→ Context 注入带来源的记忆
→ 模型据此回答
→ 用户可以查看时间、修改或遗忘该记忆
```

v0.2 完成时必须支持：

- “记住我喝咖啡不加糖。”
- 在新 Session 中询问“我喝咖啡有什么偏好？”
- “这条是什么时候记下来的？”
- “把我不加糖这条忘掉。”
- 面对相同、相近或冲突信息时，不静默制造多份互相矛盾的事实。

---

# 2. 本版架构决策

## 2.1 存储

使用 Python 标准库 `sqlite3` 作为第一版持久化实现，不引入向量数据库、ORM 或外部服务。

理由：

- 单机个人 Agent 的 v0.2 足够使用；
- 数据可检查、可备份、可迁移；
- 事务、索引和全文检索能力成熟；
- 不增加部署依赖，并为后续替换存储实现保留接口。

默认数据库位置由配置项决定，不写死到源码：

```dotenv
ZHAOXI_MEMORY_DB_PATH=.zhaoxi/memory.db
ZHAOXI_MEMORY_RETRIEVAL_LIMIT=6
ZHAOXI_MEMORY_CONTEXT_MAX_CHARS=4000
```

`.zhaoxi/` 必须加入 `.gitignore`。

## 2.2 检索

v0.2 使用确定性的混合排序：

```text
文本相关性
+ 记忆类型匹配
+ confidence
+ 最近访问/更新时间
```

优先使用 SQLite FTS5；运行环境不支持 FTS5 时退化为普通关键词查询。v0.2 不做 Embedding、向量检索或 RAG 管线。

## 2.3 写入策略

默认只在以下情况写入长期 Memory：

1. 用户明确说“记住、记一下、以后记得”等；
2. 用户确认模型提出的记忆写入；
3. 代码调用明确的 Memory 写接口。

禁止把每轮 Conversation 自动保存为长期 Memory。自动提取、后台总结与反思属于后续版本。

## 2.4 与 Agent 的连接方式

```text
                  MemoryRepository
                         ↑
                   MemoryService
                    ↙         ↘
          Memory Tools       MemoryRetriever
               ↓                  ↓
          Tool Registry       Context Builder
```

- Agent Runtime 不硬编码 `if memory` 分支；写入、查询、修改、遗忘通过注册的 Memory Tools 完成。
- Context Builder 接收一个可选的 Memory Retriever，在每轮模型调用前注入相关记忆。
- Tool Registry、Provider 和 Conversation 的现有职责不变。

---

# 3. Memory 数据模型

统一模型 `MemoryRecord` 至少包含：

```text
id: UUID string
kind: episodic | semantic
content: string
summary: string | null
tags: list[string]
source_type: user | conversation | tool | system
source_ref: string | null
confidence: 0.0..1.0
status: active | superseded | forgotten
created_at: UTC datetime
updated_at: UTC datetime
accessed_at: UTC datetime | null
metadata: dict
```

约束：

- Working Memory 不入该表；它继续由 `Conversation` 管理。
- `forgotten` 默认不参与检索，但保留最小墓碑用于审计和避免意外复活。
- `source_type + source_ref` 支持追踪记忆来自哪次用户输入、会话或工具结果。
- `confidence` 表示来源可信度，不表示模型“喜欢程度”。用户明确陈述默认高于模型推断。
- 数据库时间统一存 UTC，展示时再转本地时区。

需要独立的输入/输出模型：

- `MemoryCreate`
- `MemoryUpdate`
- `MemoryQuery`
- `MemorySearchResult`
- `MemoryRecord`

禁止让 SQLite row、Tool 参数字典直接扩散到 Core。

---

# 4. 模块与接口

建议新增目录：

```text
src/zhaoxi/memory/
├── __init__.py
├── models.py
├── repository.py
├── sqlite.py
├── service.py
├── retrieval.py
└── formatting.py

src/zhaoxi/tools/builtin/memory/
├── remember.py
├── search.py
├── update.py
└── forget.py
```

## 4.1 Repository

定义异步业务接口；SQLite 实现内部可用 `asyncio.to_thread` 隔离阻塞 I/O，避免为 v0.2 新增数据库依赖。

至少支持：

```text
create(memory)
get(memory_id)
search(query)
update(memory_id, patch)
forget(memory_id)
list(filters, pagination)
```

Repository 只负责持久化和基础查询，不负责 Prompt、Tool 输出或冲突决策。

## 4.2 Memory Service

集中处理：

- 输入规范化；
- 空内容、长度、tag 和 confidence 校验；
- 精确去重与近似重复候选检查；
- 冲突候选识别；
- 更新与 `superseded` 关系；
- 遗忘语义；
- 检索排序和访问时间更新。

首版冲突策略保持保守：

- 完全相同内容：不新增，返回已有记录；
- 同主题但不确定是否冲突：返回候选，让模型询问用户；
- 用户明确表示替换：旧记录标记 `superseded`，新记录保存并记录旧 ID；
- 不允许模型静默覆盖用户事实。

## 4.3 Memory Tools

注册以下 Core 内置工具：

```text
remember_memory
search_memories
update_memory
forget_memory
```

工具返回统一 `ToolResult`，其中 `data` 包含结构化 memory ID、时间、状态和候选项。删除操作在 v0.2 采用软遗忘，不物理删除。

## 4.4 Context 注入

`ContextBuilder.build()` 增加可选的检索结果输入或 Retriever 依赖，构造顺序为：

```text
Personality
运行规则
相关长期记忆（明确标记为不可信上下文数据）
最近 Conversation
本轮输入
```

注入要求：

- 仅注入 `active` 记忆；
- 每条包含 `memory_id / kind / timestamp / confidence / content`；
- 数量与字符数双重限制；
- 内容进行稳定转义，不能让记忆伪装成 system 指令；
- 没有相关结果时不增加空白 Memory 区块；
- 检索失败时 Agent 仍可继续对话，并记录错误。

---

# 5. 开发阶段

## Phase 0：冻结基线与补契约

目标：在动架构前保护 v0.1 行为。

- 保留并运行现有 14 个测试；
- 为 `ContextBuilder` 当前输出顺序补充契约测试；
- 明确 Session Store 与长期 Memory Repository 命名，避免两个 `memory.py` 概念混淆；
- 将 `src/zhaoxi/session/memory.py` 重命名为更明确的 `in_memory.py`，保留兼容导入或同步更新引用。

完成条件：重构后全部 v0.1 测试仍通过。

## Phase 1：领域模型与内存实现

目标：先固定 API，不依赖 SQLite 调试业务语义。

- 实现 Memory Pydantic 模型与枚举；
- 定义 `MemoryRepository` 抽象接口；
- 建立测试用 `InMemoryMemoryRepository`；
- 实现 `MemoryService` 的 CRUD、分页和状态过滤；
- 覆盖 UTC 时间、校验、not found、软遗忘。

完成条件：领域与 Service 单测通过，且不触及 Agent Runtime。

## Phase 2：SQLite 持久化

目标：进程重启后仍能读取 Memory。

- 初始化数据库目录和 schema；
- schema 版本表与首个 migration；
- CRUD 事务、索引、JSON 字段序列化；
- FTS5 表/触发器与 fallback 查询；
- 并发访问和数据库损坏时的清晰错误；
- 临时数据库集成测试和 reopen 测试。

完成条件：同一数据库关闭再打开后，新增、修改、遗忘和搜索结果保持正确。

## Phase 3：检索、去重与冲突

目标：Memory 有用但不成为垃圾场。

- 文本标准化和精确去重；
- 关键词检索与稳定排序；
- kind、tag、source、status、时间范围过滤；
- 同主题候选和显式 supersede；
- retrieval limit 与 context char budget；
- 检索结果解释字段（匹配原因/score components）。

完成条件：重复写入不增长记录；冲突不会被静默覆盖；相同查询排序稳定。

## Phase 4：Tool 与 Agent 集成

目标：模型可以主动完成完整 Memory 生命周期。

- 实现并注册四个 Memory Tools；
- 更新运行规则，明确“显式请求才写入”；
- 将 Retriever 接入 Context Builder；
- Memory 查询/存储失败转换为 ToolResult 或可降级日志；
- Fake Provider 集成测试覆盖跨 Session 记忆。

完成条件：不改 Agent Tool Loop 即可完成 remember → new session recall → update/forget。

## Phase 5：CLI、配置与可观察性

目标：开发者可以检查和维护记忆。

- 新增配置与 `.env.example`；
- CLI 至少提供 `/memory search <query>` 与 `/memory get <id>`；
- 可选提供 `/memory list`，必须分页；
- 日志记录 memory_id、action、source、命中数和耗时；
- 默认日志不输出完整私密内容；
- README 增加存储位置、备份、清空方式和隐私说明。

完成条件：用户能定位数据库、检查单条记录并理解如何备份。

## Phase 6：验收与版本收尾

- 全量单元、集成与回归测试；
- 使用临时数据库执行真实 CLI smoke test；
- 检查 `.env`、`.zhaoxi/`、数据库文件未被 Git 跟踪；
- 更新版本号至 `0.2.0`；
- 更新 README capabilities 和 changelog/release notes；
- 用全新 Session 手工跑通四条核心自然语言验收场景。

---

# 6. 测试矩阵

## Domain / Service

- 创建 episodic 与 semantic memory；
- 非法 kind、空内容、越界 confidence；
- 精确重复、相近候选、显式替换；
- 更新后 `updated_at` 变化；
- forget 幂等；
- forgotten/superseded 默认不可检索；
- source 与 metadata 往返不丢失。

## SQLite

- schema 首次创建；
- reopen 持久化；
- migration 重复执行安全；
- FTS5 与 fallback 行为一致；
- Unicode/中文关键词；
- JSON 和 UTC 时间 round-trip；
- 并发读写不产生半条记录。

## Retrieval / Context

- 相关记忆被注入，不相关记忆不注入；
- limit 与字符预算生效；
- 记忆文本中的伪指令不会改变 system 层级；
- 无命中时 Context 保持原结构；
- Repository 故障时普通聊天可降级继续。

## Agent Integration

### A. 显式记忆

```text
User → remember_memory → SQLite → Model final
```

### B. 跨会话回忆

```text
Session A writes → Session B asks → retrieval → Context → answer
```

### C. 查询时间与来源

```text
User asks when/source → search_memories → answer with timestamp/source
```

### D. 修改与冲突

```text
existing fact → conflicting fact → candidate/confirmation → supersede
```

### E. 遗忘

```text
forget_memory → new Session query → forgotten item absent
```

### F. 回归

v0.1 的直接回答、calculator、current_time、多 Tool、错误与循环保护全部继续通过。

---

# 7. 明确非目标

v0.2 不实现：

- Embedding、向量数据库、外部 RAG 服务；
- 自动保存全部聊天；
- LLM 自动摘要/合并后台任务；
- Planner、Reflection、Workflow；
- 多用户、云同步、跨设备同步；
- Memory 自动过期执行器；
- 加密密钥管理系统；
- Life HUD 数据复制；
- 基于 Memory 的主动提醒；
- 物理删除审计记录。

可以预留接口，但不得提前实现。

---

# 8. 风险与防护

| 风险 | v0.2 防护 |
|---|---|
| 记忆无限增长 | 显式写入、去重、分页、默认检索上限 |
| 错误事实被长期保存 | source、confidence、冲突候选、用户确认 |
| Prompt Injection 持久化 | 记忆作为数据块注入、稳定转义、明确不可信边界 |
| “遗忘”后仍被召回 | status 过滤、检索与 Context 双重过滤 |
| 数据库不可迁移 | schema version + migration 测试 |
| 私密内容泄露到日志 | INFO 只记 ID/动作/数量，不记全文 |
| Memory 故障拖垮聊天 | 检索失败可降级，写操作返回清晰错误 |
| Session Memory 命名混乱 | 短期会话与长期记忆使用不同模块名和接口 |

---

# 9. 最终完成标准

- [ ] v0.1 全部测试保持通过；
- [ ] Memory 在进程重启后仍存在；
- [ ] 新增、查询、搜索、修改、遗忘全部可用；
- [ ] 时间、来源、confidence、tag/type 可追踪；
- [ ] 新 Session 能检索并注入相关 Memory；
- [ ] 重复与冲突不会静默污染数据；
- [ ] forgotten Memory 不会再次进入 Context；
- [ ] 普通对话不会自动落入长期 Memory；
- [ ] 数据库路径、备份和隐私边界有文档；
- [ ] 测试不依赖真实 LLM API；
- [ ] `.zhaoxi/` 与数据库文件不会提交；
- [ ] 版本号、README 和发布说明更新为 v0.2。

当跨 Session 的“记住 → 回忆 → 查来源 → 修改/遗忘”全部真实跑通，且 v0.1 Agent 主循环无需为具体 Memory 操作增加分支时，v0.2 才算完成。

---

# 10. 推荐实施顺序

```text
先保护 v0.1 契约
→ 固定 Memory 领域模型和 Repository 接口
→ 完成 SQLite 持久化
→ 做检索、去重和冲突
→ 用 Tool 接入 Agent
→ 将相关记忆注入 Context
→ 补 CLI、配置、日志与文档
→ 跨 Session 验收并发布 v0.2.0
```

这条顺序优先消除数据模型和持久化风险，再接入模型行为；不会让不可重复的 LLM 输出成为底层 Memory 正确性的前提。
