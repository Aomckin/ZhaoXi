# Zhaoxi v1.1.9 开发任务书（修订版）
## Tool Context Router：保留“广记”核心记忆能力，按需暴露其余工具

> 历史任务书：本文保留 v1.1.9 的原始设计。当前 v1.2.2 已将 `search_memories` 改为常驻，并将记忆新增与更新改为默认允许；现行行为见 [v1.2.2 开发报告](../v1.2.x/Zhaoxi_v1.2.2_Release_Notes.md)。

### 1. 背景

当前朝汐普通对话请求的基础输入约为：

- System 静态部分：4,534 字符
- 当前时间：55 字符
- Presence：784 字符
- 桌面状态：486 字符
- Conversation history：8,099 字符
- Memory recall：1,992 字符
- JSON/message 包装：469 字符
- 普通直答完整请求：约 15,399 字符

进入 Function Calling 后，当前 34 个工具 schema 合计约 22,329 字符，使完整请求增长到约 37,737 字符，其中 tools 占约 59.2%。

目前最大 Prompt 膨胀来源已经不是人格提示词，而是工具 schema 长期全量暴露。

但是需要特别注意：

**朝汐的 Memory 并不是普通“按需功能”，而是人格与连续存在感的一部分。**

当前记忆理念为“广记”：

- 不只记录用户明确要求“记住”的信息；
- 日常小事、偏好、变化、近期事件等，也允许朝汐自行判断是否值得记忆；
- 记忆行为应该自然发生，而不是只在出现“记住”“保存”关键词时才启用。

因此 v1.1.9 不能采用“普通闲聊 = 0 tools”的简单策略。

正确目标应为：

> **普通对话始终保留少量核心长期工具，其余工具根据当前意图动态暴露。**

---

# 2. 本版本目标

实现一层轻量 **Tool Context Router**，减少无关工具 schema 长期占用，同时不破坏朝汐的广记机制。

核心目标：

1. 将工具划分为：
   - Persistent Core Tools
   - Dynamic Tools

2. 普通对话始终保留广记所需的核心 Memory 工具；

3. 文件、网页、时间、Life HUD、Archive 等能力按需挂载；

4. 不改变现有 ToolRegistry、Function Calling、MCP 工具实现；

5. 增加完整可观察性，能够明确看到：
   - 本轮暴露了哪些工具；
   - 为什么暴露；
   - tools schema 实际占多少字符 / token；

6. 保留快速回滚到“全工具模式”的能力。

---

# 3. 核心设计原则

## 3.1 Tool 不全是同一种东西

当前工具应区分为两类：

### A. Persistent Core Tools

这类工具不是“偶尔使用的能力”，而更接近朝汐长期存在的一部分。

当前建议至少包括：

```text
remember_memory
update_memory
```

原因：

- `remember_memory`
  - 支撑“广记”
  - 朝汐应该能在普通聊天里自行判断是否记录一件小事
  - 不应该等用户明确说“记住”后才获得写入能力

- `update_memory`
  - 日常对话中用户可能自然修正旧信息
  - 例如：
    - “我现在不打算去那个岗位了”
    - “那个保底岗其实已经不能去了”
    - “我最近不再用这个方案了”
  - 如果已有相关记忆，朝汐应能直接修正，而不是只能新增一条重复记忆

这两个工具默认始终暴露。

---

### B. Dynamic Tools

仅在当前场景可能需要时暴露，例如：

```text
search_memories
pin_memory
forget_memory
archive_memory
reactivate_memory
consolidate_memories

archive_*
filesystem_*
everything-search_*
fetch
lifehud
time
calculator
```

这些工具不需要在每次闲聊时常驻。

---

# 4. Memory 工具策略

Memory 必须单独处理，不能简单作为一个动态工具组整体裁剪。

## 4.1 常驻工具

默认：

```yaml
persistent_memory_tools:
  - remember_memory
  - update_memory
```

---

## 4.2 动态记忆工具

```yaml
dynamic_memory_tools:
  - search_memories
  - pin_memory
  - forget_memory
  - archive_memory
  - reactivate_memory
  - consolidate_memories
```

### `search_memories`

若系统已有自动 Memory Recall：

- 普通对话不必常驻 `search_memories`
- 当用户明显要求主动回忆、查找旧信息时再暴露

典型场景：

```text
你还记得……
我们之前聊过……
上次那个……
帮我找一下以前记过的……
```

### 管理类记忆工具

以下工具默认不常驻：

```text
pin_memory
forget_memory
archive_memory
reactivate_memory
consolidate_memories
```

它们属于记忆管理或维护能力，不应因为“广记”而永久暴露。

---

# 5. Router 输出模型

Router 不再返回“是否有工具”，而应返回：

```text
Persistent Core Tools
+
本轮 Dynamic Tool Groups
```

例如：

### 普通闲聊

用户：

```text
周六早上了呀
```

暴露：

```text
remember_memory
update_memory
```

---

### 用户自然分享一件小事

```text
我刚发现楼下那家店的炸串涨价了
```

仍然只需要：

```text
remember_memory
update_memory
```

是否真的写入 Memory 由模型自行判断。

---

### 找文件

```text
帮我找一下桌面上的亚信面试复盘
```

暴露：

```text
remember_memory
update_memory
+
search
filesystem_read
```

---

### 查旧记忆

```text
你还记得我之前怎么定义铁幕的吗？
```

暴露：

```text
remember_memory
update_memory
+
search_memories
```

如果现有语义同时可能命中 Archive，再允许增加：

```text
archive
```

---

### 修改本地文件

```text
把这个配置文件改一下
```

暴露：

```text
remember_memory
update_memory
+
filesystem_read
filesystem_write
```

---

# 6. Tool Group 建议

具体工具名以现有 ToolRegistry 为准。

```yaml
persistent_core:
  - remember_memory
  - update_memory

memory_search:
  - search_memories

memory_admin:
  - pin_memory
  - forget_memory
  - archive_memory
  - reactivate_memory
  - consolidate_memories

archive:
  - archive_search
  - archive_list_documents
  - archive_read

search:
  - mcp_everything-search_search
  - mcp_everything-search_get_file_info

filesystem_read:
  - mcp_filesystem_read_text_file
  - mcp_filesystem_read_file
  - mcp_filesystem_read_multiple_files
  - mcp_filesystem_read_media_file
  - mcp_filesystem_get_file_info
  - mcp_filesystem_list_directory
  - mcp_filesystem_list_directory_with_sizes
  - mcp_filesystem_directory_tree
  - mcp_filesystem_search_files
  - mcp_filesystem_list_allowed_directories

filesystem_write:
  - mcp_filesystem_write_file
  - mcp_filesystem_edit_file
  - mcp_filesystem_create_directory
  - mcp_filesystem_move_file

web:
  - mcp_fetch_fetch

time:
  - current_time
  - mcp_time_get_current_time
  - mcp_time_convert_time

calculator:
  - calculator

lifehud:
  - lifehud
```

---

# 7. 第一阶段路由方式

v1.1.9 先使用轻量、确定性的路由方式。

不要额外调用一次大模型专门做 Tool Routing。

建议：

```text
用户当前输入
+ 最近少量上下文
+ 已知场景状态
→ 规则/意图匹配
→ Dynamic Tool Groups
```

但注意：

**不要只做简单关键词命中。**

例如：

```text
“今天没跑铁幕”
```

这里提到了“铁幕”，但只是聊天，不代表需要调用 Life HUD。

因此判断逻辑应优先区分：

```text
提到某对象
≠
请求读取 / 操作该对象
```

例如：

```text
“今天铁幕做得好累”
→ 不加载 lifehud

“帮我看看今天铁幕记录”
→ 加载 lifehud
```

---

# 8. Router 建议结构

建议新增：

```text
src/zhaoxi/tools/router.py
```

职责保持单一：

```text
resolve_tool_context(
    user_message,
    recent_context,
    registry
) -> ToolContext
```

例如：

```python
ToolContext(
    persistent_tools=[...],
    dynamic_groups=[...],
    exposed_tools=[...],
    reason_tags=[...],
)
```

Router：

- 不执行工具；
- 不修改工具注册；
- 不负责模型调用；
- 只决定“本轮哪些 schema 可以被模型看到”。

---

# 9. 不要让 Router 干预“广记”判断

Router 只负责：

> 朝汐有没有 `remember_memory` 的能力。

Router 不负责：

> 这句话到底值不值得记。

是否记忆仍由 LLM 根据：

- 当前内容
- 人格
- Memory 规则
- 上下文

自行决定。

例如：

```text
暗苟酱：今天楼下的无糖可乐又涨了一块。
```

Router 不应该判断：

```text
“这件事不重要，所以不给 remember_memory。”
```

因为这会破坏“广记”。

正确做法是：

```text
remember_memory 始终存在
→ 朝汐自己决定记不记
```

---

# 10. Fallback 设计

动态工具筛选的风险不是“多花一点 token”，而是：

> 明明有能力，却因为 Router 没挂工具而表现得像不会。

因此必须保留 fallback。

## 10.1 配置模式

建议支持：

```env
ZHAOXI_TOOL_ROUTER_MODE=dynamic
```

可选：

```text
dynamic
all
```

### dynamic

默认新行为：

```text
persistent_core + dynamic groups
```

### all

恢复旧行为：

```text
全部已注册工具
```

便于 Debug 和快速回滚。

---

## 10.2 安全降级

如果 Router 出错：

- 不应导致模型请求失败；
- 至少保留 `persistent_core`；
- 日志记录 Router error；
- 可按配置选择：
  - fallback 到 persistent_core
  - 或 fallback 到 all

建议默认优先稳定：

```text
Router 异常 → persistent_core + safe_default
```

不要静默返回空工具列表。

---

# 11. Prompt Diagnostics 扩展

现有 diagnostics 已能统计 Prompt 与 tools 长度。

v1.1.9 增加 Tool Router 信息：

```text
router_mode
persistent_tools_count
matched_dynamic_groups
dynamic_tools_count
total_exposed_tools_count
total_registered_tools_count
filtered_tools_count
tool_schema_chars
tool_schema_prompt_tokens（若 API 可得）
```

示例：

```text
[PromptDiagnostics]

Tool Router mode: dynamic

Persistent tools:
- remember_memory
- update_memory

Matched dynamic groups:
- search
- filesystem_read

Registered tools: 34
Exposed tools: 8
Filtered tools: 26

Tool schema chars:
22,329 -> 5,184
```

不要在日志中打印：

- 用户原文
- Memory 内容
- Tool schema 正文
- 参数内容
- Prompt 正文

只记录模块名和长度。

---

# 12. 性能目标

当前 baseline：

```text
Registered tools: 34
Tool schemas: 22,329 chars
Function Calling request: 37,737 chars
```

## 普通聊天

预期：

```text
remember_memory
update_memory
```

不追求 0 tools。

目标：

```text
Tool schema chars ≈ 2,000 左右
```

以当前 schema 为参考：

```text
remember_memory ≈ 962
update_memory ≈ 1,105
```

两者合计约：

```text
2,067 chars
```

即普通对话工具上下文可从：

```text
22,329
```

降至约：

```text
2,067
```

下降约 90%。

---

## 常见单域场景

例如：

```text
time
calculator
lifehud
```

目标：

```text
persistent_core
+
少量目标工具
```

整体 schema 尽量控制在：

```text
4,000 chars 内
```

---

## 文件搜索场景

允许相对更大：

```text
persistent_core
+
search
+
filesystem_read
```

但仍不得无脑带上：

```text
memory_admin
archive
web
lifehud
filesystem_write
```

目标：

```text
明显低于当前 22,329 chars
```

---

# 13. 当前不做的事情

为了避免 v1.1.9 再次扩大范围，本版本暂不做以下重构。

## 13.1 不合并 filesystem tools

暂不改造成：

```text
filesystem(action=read|write|edit|...)
```

虽然未来值得做，但这是下一层 schema consolidation。

---

## 13.2 不合并 Memory tools

暂不把：

```text
remember
update
search
pin
forget
archive
...
```

重构为单一 `memory(action=...)`。

当前 Memory 行为已经较稳定，本版本只调整暴露策略。

---

## 13.3 不修改 Memory 自动召回机制

现有 Memory recall：

- 继续正常工作；
- 不因为 Router 改动而改变召回策略；
- Router 只影响 Function Calling schema 暴露。

---

## 13.4 不引入 LLM Router

先观察确定性路由是否足够。

如果后续发现：

- 规则过多；
- 语义误判严重；
- 工具域继续快速增加；

再考虑单独的小型分类器或 LLM Tool Router。

---

# 14. 测试要求

## Persistent Core Tests

必须验证：

### 普通闲聊

```text
“周六早上了呀”
```

应始终暴露：

```text
remember_memory
update_memory
```

---

### 普通小事分享

```text
“今天楼下可乐涨价了”
```

仍应拥有：

```text
remember_memory
update_memory
```

不得因为没有“记住”关键词而移除记忆能力。

---

## Dynamic Router Tests

### 时间

```text
“现在几点？”
```

结果：

```text
persistent_core + time
```

### 查旧记忆

```text
“你还记得之前那件事吗？”
```

结果：

```text
persistent_core + memory_search
```

### 文件搜索

```text
“帮我找桌面上的复盘”
```

结果：

```text
persistent_core + search + filesystem_read
```

### 文件修改

```text
“把这个 yaml 改一下”
```

结果：

```text
persistent_core + filesystem_read + filesystem_write
```

### Archive

```text
“去潮庭翻一下之前的人设文档”
```

结果：

```text
persistent_core + archive
```

### Life HUD

```text
“帮我读一下今天 Life HUD 的数据”
```

结果：

```text
persistent_core + lifehud
```

### 普通聊天提到 Life HUD

```text
“今天铁幕做得累死了”
```

结果：

```text
persistent_core
```

不得仅因出现“铁幕”就加载 lifehud。

---

# 15. 集成测试

验证完整链路：

```text
Tool Router
→ ToolRegistry
→ Provider
→ Function Calling
→ Tool result
→ 后续模型调用
```

必须保证：

- 动态筛选后的 schema 正确进入 API 请求；
- 工具执行行为不变；
- 多步 Function Calling 不被破坏；
- 工具调用后下一轮仍可根据需要重新计算 Tool Context；
- `all` 模式能恢复当前旧行为；
- Router 出错不会导致 Core 崩溃；
- Persistent Memory tools 永远不会因路由误判消失。

---

# 16. 真实请求验收

完成后至少测试以下真实对话：

## Case A：纯闲聊

```text
周六早上了呀
```

预期：

```text
2 个 persistent memory tools
无其他 dynamic tools
```

---

## Case B：小事自然记忆

```text
今天买到的可乐比上次贵了一块
```

预期：

```text
remember_memory / update_memory 可用
```

是否真正写入由模型自行判断。

---

## Case C：文件搜索

```text
帮我找一下桌面上的亚信面试复盘
```

预期：

```text
persistent_core
+
search
+
filesystem_read
```

---

## Case D：回忆

```text
你还记得我之前怎么说暑假结束的吗？
```

预期：

```text
persistent_core
+
memory_search
```

如自动 recall 已直接命中，则模型也可以不实际调用 search。

---

## Case E：Life HUD

```text
看看今天 Life HUD 里铁幕记录怎么样
```

预期：

```text
persistent_core
+
lifehud
```

---

# 17. 完成标准

v1.1.9 完成需满足：

- [ ] 新增 Tool Context Router；
- [ ] 区分 Persistent Core Tools 与 Dynamic Tools；
- [ ] `remember_memory` 长期暴露；
- [ ] `update_memory` 长期暴露；
- [ ] 广记机制不依赖“记住”等显式关键词；
- [ ] 普通聊天不再携带全部 34 个工具；
- [ ] 支持动态工具组组合；
- [ ] 支持 `dynamic / all` 模式；
- [ ] Router 异常有安全 fallback；
- [ ] Prompt Diagnostics 显示工具路由结果；
- [ ] Memory 自动召回机制不被修改；
- [ ] Function Calling 主循环不回归；
- [ ] 新增 Router 单元测试；
- [ ] 新增 Persistent Memory 测试；
- [ ] 相关集成测试通过；
- [ ] 使用真实 API 请求重新统计 schema 和 prompt_tokens；
- [ ] 普通对话 tools schema 从约 22,329 字符下降至约 2,000～3,000 字符；
- [ ] 常见动态工具场景显著低于全量 schema。

---

# 18. 版本定位

v1.1.9 不是一次“删工具”。

它要解决的是：

> **朝汐已经拥有很多能力，但不应该在每一句话里同时把所有能力说明书摊在桌上。**

与此同时：

> **记忆不是临时能力。**

对当前朝汐而言，广记已经属于长期存在机制，因此必须保留最基础的 Memory 写入与更新能力。

最终目标：

```text
普通聊天：
核心人格
+ 当前上下文
+ Memory recall
+ remember/update
```

需要行动时：

```text
再额外挂载当前任务需要的 tools
```

这样既保留朝汐“会自然记住生活”的特性，又能把 Function Calling 上下文从目前的全量工具模式大幅压缩。

---

## 一句话总结

**不是让朝汐少会东西，而是让她平时只把真正需要的工具放在手边，同时永远保留自己的记忆能力。**
