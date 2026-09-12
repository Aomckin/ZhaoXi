# Zhaoxi v1.1.3 开发报告：潮庭书库

## 结果

v1.1.3 新增本地、人工维护、按需检索且默认只读的 Tidecourt Archive。Markdown 是唯一事实源，SQLite 是可重建索引；完整书库不会常驻进入 System Prompt。

## 目录与首批资料

默认目录为 `data/archive/`，支持：

```text
data/archive/
├── zhaoxi/
├── user/
├── projects/
└── reference/
```

首批 canonical 文档为 `zhaoxi/朝汐_Zhaoxi_角色身世设定_v1.2.md`。两张现有设定图分别配有 Sidecar Markdown；文本负责检索，图片继续保存视觉细节。

## DB 与索引

默认数据库：`.zhaoxi/archive.db`。

- `documents`：稳定 ID、标题、scope、type、authority、更新时间、tags、attachments、相对源路径、正文、文件哈希。
- `chunks`：文档 ID、章节顺序、heading path、受限正文片段。
- `chunks_fts`：FTS5 索引，优先使用 trigram tokenizer，环境不支持时回退 unicode61。
- `metadata`：最后索引时间与实际 FTS tokenizer。
- `index_state`：逐文件哈希、索引状态和有界错误。

启动时扫描一次 Markdown 并按 SHA-256 增量更新。内容修改会原位替换旧 chunks；文件删除会清理文档与 FTS 行；重复索引不产生重复项。`--reindex-archive` 可执行完整重建。

## Markdown 与 Front Matter

支持字段：`id`、`title`、`scope`、`type`、`authority`、`updated_at`、`tags`，并支持可选 `attachments`。缺省 ID 由相对路径稳定派生；缺省 scope 取一级目录；user 默认 personal，其余默认 reference。YAML 损坏会形成单文件诊断，不阻断其他文档。

authority：

- `canonical`：正式设定或正式事实。
- `reference`：稳定参考资料。
- `personal`：用户人工维护的个人资料。
- `draft`：未确认草稿，不作为绝对事实。

冲突优先级写入 Agent 运行规则：当前用户明确指令 > canonical Archive > reference/personal Archive > 长期 Memory > 模型推断。多个 canonical 冲突时必须说明并请求确认。

## Chunking 与中文检索

Markdown 先按 heading 层级切 section，保留完整 heading path；超长 section 再按字符上限切分并保留 overlap。检索综合：

- FTS5 / BM25 强匹配；
- 中文短语与二元词片 fallback；
- title、heading、tags、content 分级权重；
- 适度 canonical/reference/personal/draft 系数；
- scope/type/authority 硬筛选。

authority 只作适度加成，不覆盖问题相关性。结果受 `top_k`、单片段和总字符预算限制。

## Tool 与上下文

- `archive_list_documents`：列出有界元数据。
- `archive_search`：返回标题、scope、authority、heading、snippet、score、source_path 与 attachments。
- `archive_read`：按 document ID 和可选 section 受限读取。

三个 Tool 均声明 `PermissionLevel.READ`、无副作用，不提供 write/delete/rename。Tool observation 标记 `source_kind=tidecourt_archive`，模型可区分书库、Memory 与 Conversation。

认知路由会把朝汐身世、潮庭、信物、用户长期资料及项目文档的具体事实问题导向 Tool 路径，并要求本轮真实调用。若检索无结果，Tool 与 System Prompt 都要求明确说“文档没有记录”，不得编造。

## Security

- 只扫描配置的 Archive 根目录内 `.md`。
- Tool 不接受文件路径，只接受受控筛选项或稳定 document ID。
- 绝对 attachment 路径与 `../` 越界被拒绝。
- 指向 Archive 外部的符号链接不索引。
- 原始正文不出现在 diagnostics。
- 只有当前查询命中的有限片段进入模型上下文。

## 配置与诊断

配置项见 `.env.example`：

```text
ZHAOXI_ARCHIVE_ENABLED=true
ZHAOXI_ARCHIVE_DIRECTORY=data/archive
ZHAOXI_ARCHIVE_DB_PATH=.zhaoxi/archive.db
ZHAOXI_ARCHIVE_SEARCH_TOP_K=5
ZHAOXI_ARCHIVE_CONTEXT_MAX_CHARS=6000
ZHAOXI_ARCHIVE_MAX_DOCUMENT_CHARS=12000
ZHAOXI_ARCHIVE_CHUNK_MAX_CHARS=3000
ZHAOXI_ARCHIVE_CHUNK_OVERLAP_CHARS=200
```

`GET /api/diagnostics` 新增 `archive`，只返回 enabled、文档/chunk 数、最后索引时间、健康状态、有界错误、数据库与目录位置、FTS tokenizer。

## 自动测试

开发环境结果：`362 passed, 1 skipped`。跳过项是当前 Windows 权限不允许创建测试 symlink；越界 symlink 的拒绝逻辑仍由代码路径和可创建 symlink 的环境测试覆盖。既有 Personality、Memory、Session、Proactive、Planner、Workflow、Web 与 Voice 测试全部通过。

## 手动验收

```powershell
.\.venv\Scripts\python.exe main.py --reindex-archive
.\.venv\Scripts\python.exe main.py --archive-status
```

随后启动朝汐，依次询问：

1. `朝汐，你为什么怕黑？` 应查询 canonical 文档并回答潮庭早期经历。
2. `向日葵发卡是谁送给你的？` 应回答暗苟。
3. `我具体哪一天把向日葵发卡送给你的？` 应明确文档没有记录具体日期。
4. 在 `data/archive/user/test.md` 写入长期资料并重建索引，应能检索。
5. 修改或删除该文档后重建，应只返回新内容或不再返回。

## 已知限制

- 不含向量数据库、Embedding、OCR、图片理解或自动 caption。
- 不提供 Archive 编辑 UI 或写入 Tool。
- 中文检索面向几十至几百份本地文档，不是通用搜索引擎。
- canonical 的语义冲突由模型依据多条检索结果说明；本版本不自动判定自然语言真假。
- 不在每次 Heartbeat 扫描或搜索 Archive；只在启动、显式重建和确有资料需求时使用。
