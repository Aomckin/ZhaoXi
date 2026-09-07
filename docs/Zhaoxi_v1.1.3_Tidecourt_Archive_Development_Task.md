# Zhaoxi v1.1.3 Development Task
# 潮庭书库（Tidecourt Archive）

> 版本：v1.1.3  
> 主题：Local Document Archive / Retrieval / Self-Knowledge  
> 核心目标：为朝汐建立一个本地、可人工维护、可按需检索的长期文档库，让她可以主动查阅自己的正式设定、暗苟手动保存的资料、项目文档与其他长期参考资料，而不是把所有内容永久塞进 System Prompt。

---

## 0. 背景

Zhaoxi 当前已经具备：

- Personality YAML：定义“朝汐是谁”
- Memory：记录长期经历与动态记忆
- Session Timeline：记录最近对话及其时间
- LifeHUD：提供现实生活状态
- Proactive / Tidal Heartbeat：持续观察生活状态并主动行动

但目前仍缺少一类非常重要的信息载体：

> **正式、较长、人工维护、需要时可以回去翻阅的资料。**

典型内容包括：

- `朝汐_Zhaoxi_角色身世设定_v1.2.md`
- 朝汐外貌设定与角色设定图说明
- 暗苟手动整理的长期资料
- 个人理念、阶段总结
- LifeHUD / MemeVault / Zhaoxi 项目说明
- 其他用户希望长期交给朝汐查阅的 Markdown 文档

当前人格设定文档已经包含潮庭、命名、生日、真挚与热诚、向日葵发卡、怕黑、怕灵异、喜欢夏末、外貌与成长主题等正式设定。详细内容不适合永久全部塞进 System Prompt。

因此 v1.1.3 新增：

# Tidecourt Archive

即：

> **朝汐自己的书库。**

---

# 1. 信息分层

必须明确区分四类信息。

## 1.1 Personality

回答：

> “朝汐是谁？”

特点：

- 短
- 稳定
- 每轮 System Prompt 注入
- 控制人格、关系与表达方式

来源：

```text
src/zhaoxi/personality/zhaoxi_v1.yaml
```

## 1.2 Archive

回答：

> “有哪些正式资料可以回去查？”

特点：

- 长
- 人工维护
- 本地文件
- 按需检索
- 不默认全部注入 Prompt
- 有来源与权威等级

## 1.3 Memory

回答：

> “我们真正经历过什么？”

特点：

- 动态产生
- 可演化
- 可遗忘
- 带生命周期
- 不等同于正式设定

## 1.4 Conversation / Session

回答：

> “我们刚刚聊了什么？”

特点：

- 短期
- 时间连续
- 近期上下文

---

# 2. Archive 目录

建议：

```text
archive/
├── zhaoxi/
│   ├── 朝汐_Zhaoxi_角色身世设定_v1.2.md
│   ├── 朝汐_外貌设定.md
│   └── ...
├── user/
│   ├── 暗苟_长期资料.md
│   ├── 2026_暑假总结.md
│   └── ...
├── projects/
│   ├── LifeHUD.md
│   ├── Zhaoxi.md
│   └── MemeVault.md
└── reference/
    └── ...
```

至少支持：

```text
zhaoxi
user
projects
reference
```

---

# 3. 首批正式文档

将现有：

```text
朝汐_Zhaoxi_角色身世设定_v1.2.md
```

作为首批 canonical 文档放入：

```text
archive/zhaoxi/
```

它是朝汐正式角色设定来源之一。

不要把整份文档复制进 Personality YAML。

Personality 只保留必要核心，详细身世按需检索。

---

# 4. Markdown Front Matter

建议支持：

```yaml
---
id: zhaoxi-lore-v1.2
title: 朝汐角色身世设定
scope: zhaoxi
type: lore
authority: canonical
updated_at: 2026-09-04
tags:
  - 朝汐
  - 潮庭
  - 身世
  - 人格
---
```

至少支持：

```text
id
title
scope
type
authority
updated_at
tags
```

字段缺失时允许合理默认。

---

# 5. authority：权威等级

建议：

```text
canonical
reference
personal
draft
```

## canonical

正式设定 / 正式事实。

若与普通 Memory 冲突：

> 优先 canonical。

## reference

稳定参考资料。

## personal

用户手动塞入的个人资料。

## draft

草稿 / 未确认内容。

模型必须知道：

> draft 不应被当成绝对事实。

---

# 6. 冲突优先级

推荐：

```text
当前用户明确指令
↓
canonical Archive
↓
reference / personal Archive
↓
长期 Memory
↓
模型推断
```

要求：

- 当前用户明确说的话永远优先
- 正式设定优先于动态 Memory
- Memory 不允许悄悄覆盖 canonical
- 多个 canonical 冲突时，应说明冲突并请求确认
- 不得自行猜哪个是真的

---

# 7. Document Index

需要建立本地索引。

v1.1.3 不要求一开始引入向量数据库。

优先：

```text
SQLite FTS5 / BM25 / 关键词与标题加权
```

目标：

- 本地
- 免费
- 不调用模型
- 文档几十到几百份时足够
- 文件变更后可快速重建或增量更新

---

# 8. Chunking

Markdown 优先按结构切分：

```text
文档
↓
heading
↓
section chunk
```

chunk 建议保存：

```text
document_id
title
scope
type
authority
tags
heading_path
content
updated_at
source_path
```

不要仅按固定字符数粗暴切。

若 section 过长，可二次字符切块，并保留适度 overlap。

---

# 9. 中文检索

需要考虑中文检索效果。

可采用：

- FTS5 trigram
- 简单中文 token 化
- title / heading / tags 额外权重
- exact phrase / substring fallback

目标不是造搜索引擎。

目标是：

> 用户问“朝汐为什么怕黑”，可以稳定找到“怕黑”章节。

---

# 10. Archive Tools

至少提供三个 Tool。

## 10.1 list_documents

用途：

> 查看书库里有哪些文档。

参数建议：

```text
scope?
type?
authority?
limit?
```

返回：

```text
document_id
title
scope
type
authority
updated_at
```

## 10.2 search_documents

用途：

> 根据 query 搜索相关文档片段。

参数建议：

```text
query
scope?
type?
authority?
top_k?
```

返回：

```text
document_id
title
heading_path
snippet
score
authority
source_path
```

单次返回必须有长度限制。

## 10.3 read_document

用途：

> 找到正确文档后继续阅读。

参数建议：

```text
document_id
section?
max_chars?
```

支持：

- 受限全文读取
- 指定 heading
- 指定 section

---

# 11. Agent 行为规则

需要给朝汐补一条明确规则：

> **当用户询问关于朝汐自身、暗苟、项目或其他长期资料的具体事实，而当前上下文无法可靠回答时，优先查询 Tidecourt Archive，而不是猜测。**

例如：

```text
用户：
朝汐，你为什么怕黑？
```

允许：

```text
search_documents("朝汐 怕黑")
```

然后再回答。

---

# 12. 不能假装知道

若 Archive 没有记录具体事实，必须明确说明：

> 文档里没有写。

例如用户问：

```text
我具体哪一天把向日葵发卡送给你的？
```

若文档只写“暗苟赠送向日葵发卡”，却没有日期，则禁止编造日期。

---

# 13. Tool Use 与人格

Archive Tool 不应破坏人格。

允许自然表达：

```text
“等等哦，这个朝汐记得设定里有写，我去翻一下。”
```

然后真的调用 Tool。

继续遵守：

> 说要查，就真的查。

---

# 14. Prompt 注入策略

严禁：

```text
启动时把整个 archive/ 全部塞进 System Prompt
```

正确方式：

```text
常驻：
Personality

按需：
Archive Retrieval
```

检索结果只在需要时注入当前轮。

---

# 15. Archive 与 Memory 的边界

示例：

```text
Archive:
朝汐怕黑，因为最初独自在潮庭生活。

Memory:
2026-09-07 晚上和暗苟一起看了恐怖片，最后还是抱着尾巴缩到旁边。
```

二者同时存在。

Archive 是：

> 正式资料。

Memory 是：

> 活过的经历。

---

# 16. Archive 默认只读

v1.1.3 默认：

> **Read-only knowledge source**

朝汐可以：

- list
- search
- read

不可以默认：

- 自动改文档
- 自动覆盖
- 自动删除
- 自动重写 canonical

未来需要编辑时另开明确 Write Tool，并走 Permission。

本版本不做。

---

# 17. 文件变更与索引刷新

必须支持：

```text
用户手动往 archive/ 丢 Markdown
↓
重新索引
↓
朝汐可查询
```

最低要求：

- 启动时索引一次
- 提供 `--reindex-archive`

可选增强：

- 低频检测 mtime / file hash
- 发现变化后增量更新

不要每个 Heartbeat 全量扫描。

---

# 18. 索引数据库

建议：

```text
.zhaoxi/archive.db
```

至少存：

```text
documents
chunks
metadata
index_state
```

原始 Markdown 始终以文件为准。

---

# 19. 文档 ID

document_id 必须稳定。

优先使用：

```text
front matter id
```

若不存在：

根据：

```text
relative_path
```

生成稳定 ID。

不要每次启动随机 UUID。

---

# 20. 文档更新与删除

同一 document_id 更新时：

- 替换旧 chunk
- 更新时间
- 不产生重复文档
- 搜索只返回最新内容

文档删除后重新索引：

- 删除对应索引
- 不影响 Memory
- 不残留幽灵 chunk

---

# 21. 图片 / 设定图支持

当前已有朝汐角色设定图。

v1.1.3 不要求实现：

- 图片 embedding
- OCR
- 自动视觉 caption
- 图像向量检索

优先采用 Sidecar Markdown：

```text
朝汐_角色设定集.png
朝汐_角色设定集.md
```

Sidecar MD 示例：

```markdown
# 朝汐角色设定集

对应图片：朝汐_角色设定集.png

## 内容

- 朝汐三视图
- 浅金长发
- 海绿色眼睛
- 向日葵发卡
- 黑白女仆装
- 钥匙串
- 蓬松尾巴
```

原则：

> 文本负责找到图片，图片负责提供视觉细节。

---

# 22. Attachment Metadata

Sidecar 文档可支持：

```yaml
attachments:
  - type: image
    path: 朝汐_角色设定集.png
```

Archive Tool 可返回：

```text
attachments
```

但 v1.1.3 不要求自动把附件送进视觉模型。

---

# 23. 手动塞用户资料

这是 P0 用法之一。

例如：

```text
archive/user/我的长期想法.md
archive/user/2026夏天.md
archive/user/职业规划.md
```

不需要开发复杂录入 UI。

暗苟手动丢 Markdown 就够。

---

# 24. Scope

至少支持：

```text
zhaoxi
user
projects
reference
```

例如：

```text
search_documents(
  query="为什么怕黑",
  scope="zhaoxi"
)
```

---

# 25. Retrieval Ranking

建议综合：

```text
BM25 / FTS score
+ title exact match
+ heading match
+ tags match
+ canonical boost
+ scope match
```

注意：

> authority 不应完全覆盖 query relevance。

---

# 26. Retrieval Result 结构

建议：

```json
{
  "document_id": "zhaoxi-lore-v1.2",
  "title": "朝汐角色身世设定",
  "scope": "zhaoxi",
  "authority": "canonical",
  "heading_path": "6 > 6.1 怕黑",
  "snippet": "...",
  "score": 0.91,
  "source_path": "archive/zhaoxi/..."
}
```

---

# 27. Source Awareness

模型需要知道：

> 这是 Archive 检索出的正式资料。

建议注入：

```text
潮庭书库检索结果：
[canonical | 朝汐角色身世设定 | 6.1 怕黑]
...
```

不要伪装成 Conversation。

---

# 28. Source Mention

正常聊天时不强制显示技术路径。

但若用户问：

```text
“这个从哪里看到的？”
```

应能回答：

- 文档标题
- section
- 可选相对路径

---

# 29. Security / Privacy

Archive 是本地用户资料。

要求：

- 默认只读取配置目录
- 不允许任意文件系统路径搜索
- 防止 `../` 路径逃逸
- 不读取 archive 外文件
- 不自动上传整座书库
- 只把当前检索到的有限片段发给已配置模型

---

# 30. Context Budget

Archive Tool 必须限制：

```text
top_k
max_chars
max_document_chars
```

避免因为一句问题把整份长文档塞入上下文。

---

# 31. Diagnostics

建议 `/api/diagnostics` 增加：

```text
archive:
  enabled
  documents
  chunks
  last_indexed_at
  index_healthy
  index_errors
  db_path
```

不要暴露完整文档正文。

---

# 32. CLI

建议增加：

```text
python main.py --archive-status
python main.py --reindex-archive
```

输出：

```text
documents
chunks
last_indexed_at
errors
```

---

# 33. 配置项

建议：

```env
ZHAOXI_ARCHIVE_ENABLED=true
ZHAOXI_ARCHIVE_DIRECTORY=archive
ZHAOXI_ARCHIVE_DB_PATH=.zhaoxi/archive.db
ZHAOXI_ARCHIVE_SEARCH_TOP_K=5
ZHAOXI_ARCHIVE_CONTEXT_MAX_CHARS=6000
```

名称按现有 Settings 风格调整。

---

# 34. Tool Registry 与 Permission

Archive Tools 注册进现有 Tool Registry。

不要为 Archive 单独造第二套 Agent 工具体系。

建议 Tool 名：

```text
archive_list_documents
archive_search
archive_read
```

Archive Read 属于本地只读查询，走现有 read 权限级别。

本版本不提供：

```text
write
delete
rename
```

---

# 35. 与 Planner / Workflow

未来 Planner / Workflow 可以调用 Archive。

例如：

```text
“按我的项目规划文档帮我拆任务”
```

可先 search，再规划。

但本版本不要为 Archive 重构 Planner。

---

# 36. 与 Proactive

v1.1.3 不要求 Heartbeat 每轮查 Archive。

禁止：

```text
每个 Heartbeat 自动搜索文档
```

Archive 只在：

- 用户问题需要时
- 主动决策明确需要背景时
- Planner / Reflection 明确需要资料时

按需调用。

---

# 37. 与 Reflection

本版本不要求大改 Reflection。

但架构应允许未来：

```text
Reflection
↓
查询 Archive 中项目目标 / 梦想 / 长期设定
↓
结合 Memory / LifeHUD
```

---

# 38. 初始 Seed

首次运行时：

如果：

```text
archive/zhaoxi/
```

为空：

保持空目录即可。

项目可自带用户明确提供的朝汐角色设定文档。

不要自动生成虚构设定。

---

# 39. 测试要求

## Front Matter

- 正确解析 metadata
- 无 front matter 也可索引
- malformed front matter 有明确错误
- 单文件错误不导致整个 Archive 崩溃

## Index

- 初次构建
- 增量更新
- 文档修改
- 文档删除
- document_id 稳定
- 重复索引不产生重复 chunk

## Search

- “朝汐为什么怕黑”可命中怕黑章节
- “向日葵发卡”可命中信物章节
- “真挚与热诚”可命中核心信念
- scope filter 有效
- authority filter 有效
- top_k 生效
- 总字符限制生效

## Read

- 按 document_id 读取
- 按 heading 读取
- max_chars 生效
- 不存在文档返回明确错误

## Security

- `../` 无法逃逸目录
- 绝对路径无法越权读取
- symlink 越界应拒绝或安全解析
- 只读 Tool 无法修改文件

## Agent

- 用户问朝汐具体身世时能主动搜索
- 有资料时不编造
- 无资料时明确说没有记录
- conflicting canonical 能识别冲突

## Regression

- Personality 正常
- Memory 正常
- Session 正常
- Proactive 正常
- Planner / Workflow 不受影响

---

# 40. 手动验收

## 场景 A：问朝汐自己

问：

```text
朝汐，你为什么怕黑？
```

预期：

- 查询 Archive
- 命中角色设定
- 回答与潮庭早期经历一致

## 场景 B：问信物

问：

```text
向日葵发卡是谁送给你的？
```

预期：

- 命中 canonical
- 回答是暗苟赠予

## 场景 C：问未知细节

问：

```text
我具体哪一天把向日葵发卡送给你的？
```

如果文档没有日期：

预期：

```text
明确说明没有记录具体日期
```

禁止编造。

## 场景 D：手动塞资料

创建：

```text
archive/user/test.md
```

写：

```text
暗苟最近想长期研究桌面型生活 Agent。
```

重新索引。

问：

```text
我最近想长期研究什么？
```

预期：

- 可通过 Archive 查到

## 场景 E：更新 / 删除文档

修改后重新索引：

- 返回新内容
- 不返回旧 chunk

删除后重新索引：

- 搜索不到
- 不残留幽灵结果

## 场景 F：图片 Sidecar

放：

```text
archive/zhaoxi/朝汐角色设定集.png
archive/zhaoxi/朝汐角色设定集.md
```

搜索：

```text
朝汐夏装是什么？
```

预期：

- 命中 Sidecar Markdown
- 能知道白色连衣长裙与宽帽檐草帽

---

# 41. 不在本版本处理

明确不做：

- 向量数据库
- Embedding API
- 图片 Embedding
- OCR
- 自动 Caption
- 自动读取整个用户磁盘
- 自动写入 Archive
- Archive 编辑 UI
- Web 文件管理器
- 云同步
- 多用户权限
- 文档版本控制系统
- Git 自动提交
- 自动修改 canonical
- 自动从 Memory 生成正式文档

---

# 42. 完成标准

v1.1.3 完成后必须满足：

1. 存在本地 Tidecourt Archive。
2. Markdown 可直接人工放入。
3. 支持 Front Matter。
4. 支持 scope / type / authority / tags。
5. 支持本地索引。
6. 不依赖大模型完成检索。
7. 支持 list_documents。
8. 支持 search_documents。
9. 支持 read_document。
10. Agent 可主动调用 Archive。
11. 朝汐问自身设定时优先查 canonical 文档。
12. 没有资料时不编造。
13. Archive 与 Memory 保持清晰边界。
14. 不把整个 Archive 常驻注入 Prompt。
15. 支持文档新增 / 修改 / 删除后的重新索引。
16. 防止路径越界。
17. 检索结果受上下文长度限制。
18. Sidecar Markdown 可描述图片。
19. Diagnostics 能查看索引状态。
20. 现有测试保持通过。

---

# 43. 开发完成后汇报

Codex 完成后请明确汇报：

- 修改文件
- 新增模块
- Archive 目录设计
- DB 结构
- Markdown 解析方式
- Front Matter schema
- authority 规则
- Chunking 方式
- 中文搜索实现
- Ranking 策略
- Tool 定义
- Tool permission
- Context 注入格式
- Agent 何时决定搜索 Archive
- Archive 与 Memory 的边界
- 文档更新 / 删除策略
- Sidecar 图片支持方式
- Security / Path Traversal 防护
- 配置项
- Diagnostics
- CLI
- 自动测试结果
- 手动验收步骤
- 已知限制

---

# 44. 本版本理念

Personality 是：

> **朝汐的性格。**

Memory 是：

> **朝汐活过的经历。**

Conversation 是：

> **朝汐刚刚说过的话。**

而 Tidecourt Archive 是：

> **朝汐可以回去翻阅的书。**

她不需要把所有东西永远背在脑子里。

重要的是：

当暗苟问起某件曾被认真写下的事情时，

她知道那本书放在哪里。

她可以走进潮庭的书房，

找到它，

翻开它，

然后回来告诉暗苟：

> “嗯，找到了。这里确实写过。”

这就是：

# Tidecourt Archive

> 有些事情不需要永远悬在意识里。  
> 只要它们被好好放在一个不会丢失的地方。
