# Zhaoxi v1.2.2 开发任务书（整合修订版）
## Tool Manifest / Memory Core / Dynamic Discovery / Debug Tool Control

> 版本定位：修复 v1.1.9 动态工具路由遗留问题，并把 Tool 系统补成真正可长期扩展的“钥匙柜”。

---

# 1. 背景

当前朝汐已经完成了 Tool Context Router，能够避免把全部 Tool Schema 每轮都暴露给 LLM。

这个方向本身没有问题，但真实使用后暴露出几个更深的问题：

1. **Memory 的“广记”语义没有完全贯彻**
   - 旧 tool description / runtime rule 仍残留“只有用户明确要求才记”的逻辑；
   - 与朝汐原本的广记设计冲突。

2. **`search_memories` 不应该是低频动态工具**
   - 生活类 Agent 不只是“会保存记忆”，还必须能自然联想到过去；
   - 如果搜索记忆不是长期可用，朝汐平时就很难主动产生生活联想；
   - 会变成“只会写，不会想”。

3. **Router 只解决了“这轮给模型看什么”，没有解决“没看到的能力仍然存在”**
   - 朝汐可能因为当前没暴露某个 Tool，就误以为自己没有这个能力；
   - 在用户要求执行任务时，可能直接回答“做不了”，而不是先确认钥匙柜里有没有对应工具。

4. **缺少完整 Tool 清单 / Inventory**
   - 朝汐目前能知道手边挂着几把钥匙；
   - 但无法准确回答“总共有多少把”“具体有哪些”“某个能力属于哪一组”；
   - `exposed_tools` 被误当成了“全部能力”。

5. **Tool 开发调试仍依赖 `.env`**
   - 新 Tool 启用 / 停用要修改环境变量；
   - 不适合当前高频开发、黑盒测试、快速验收的工作方式；
   - Debug UI 应该成为 Tool 的运行时控制台。

本版本不再把“省 token”作为主要目标。

真正目标是：

> **减少低频 Tool 对 LLM 注意力的干扰，同时保证朝汐始终知道自己会什么、能随时联想记忆、需要行动时也不会因为当前没看到 schema 就误判成“没有工具”。**

---

# 2. 核心目标

v1.2.2 需要完成四部分：

1. **Memory Core**
   - `remember_memory`
   - `update_memory`
   - `search_memories`
   - 三者长期暴露

2. **Tool Manifest / Inventory**
   - ToolRegistry 作为唯一真实来源；
   - 自动生成完整 Tool 清单；
   - 朝汐知道自己“总共会什么”。

3. **Router + Discovery + Capability Resolver**
   - Router 负责提前挂载高概率需要的工具；
   - Discovery 负责中途补拿工具；
   - 在声称“没有能力”之前必须先检查完整能力目录。

4. **Debug Tool Control**
   - Debug 页直接启用 / 停用 Tool；
   - 支持 Force Expose；
   - 不再要求为了调试去 `.env` 改 `ENABLE=true/false`。

---

# 3. Tool 系统重新分层

建议正式区分以下四个概念。

## 3.1 Registered Tools

系统当前真实注册成功的所有工具。

来源可能包括：

- builtin
- Memory
- Life HUD
- MCP
- filesystem
- Everything Search
- fetch
- time
- calculator
- 后续新工具

这是“系统实际上拥有什么”。

---

## 3.2 Known Capabilities

朝汐知道自己拥有哪些能力域。

例如：

```text
Memory 写入与更新
Memory 检索
Memory 管理
潮庭 / Archive
本地文件搜索
文件读取
文件修改
网页读取
时间
计算
Life HUD
```

这是“朝汐知道自己会什么”。

它应该很短，可以长期进入上下文。

---

## 3.3 Exposed Tools

当前这一轮真正传给 LLM 的 Function Calling schemas。

例如普通聊天：

```text
remember_memory
update_memory
search_memories
request_tool_group
inspect_tool_catalog
```

这是“朝汐现在手边挂着什么”。

---

## 3.4 Tool Inventory

完整 Tool 清单与元数据。

它不需要全部常驻 Prompt。

需要时可查询：

```text
总共有多少个 Tool
有哪些 Group
某个 Group 有哪些 Tool
某个 Tool 是否启用
某个 Tool 当前是否可用
某个 Tool 来自哪里
```

这是“钥匙柜目录”。

---

# 4. Memory Core：长期常驻

## 4.1 常驻三件套

以下三个 Tool 不经过普通 Router 裁剪：

```text
remember_memory
update_memory
search_memories
```

它们属于朝汐的“记、改、想”。

---

## 4.2 remember_memory

必须符合广记理念。

禁止继续使用类似：

```text
仅在用户明确要求记住长期信息时使用
```

正确语义：

```text
用于记录值得长期保留的信息。

朝汐可以根据对话自行判断是否记录，
无需等待用户明确说“记住”。

允许记录：
- 日常小事
- 偏好
- 最近发生的变化
- 阶段性事件
- 生活习惯
- 与朝汐长期关系有关的信息

不要因为信息看似琐碎就默认忽略。
```

---

## 4.3 update_memory

语义：

```text
当用户自然修正、补充或改变已有信息时，
可以主动更新对应 Memory。

不要求用户明确说“更新记忆”。
```

---

## 4.4 search_memories

改为长期暴露。

原因：

朝汐作为生活类 Agent，不能只在用户说：

```text
“你还记得吗？”
```

时才获得回忆能力。

应该允许：

```text
当前话题与过去经历、偏好、人物、地点、计划或近期事件自然相关时，
主动检索相关记忆，用于联想、承接与生活感。
```

但增加约束：

```text
不要为了展示记忆能力而频繁检索。
只有自然关联明显可能改善当前对话时再使用。
```

广记的完整理念应为：

```text
广记：小事也可以留下来
广想：小事也可以自然联想到过去
```

---

# 5. 检查并修复 Memory 旧规则

必须全局搜索：

```text
仅在用户明确要求
只有用户要求记住
必须明确提出保存
仅保存长期重要信息
不要记录琐事
```

检查范围至少包括：

- Tool descriptions
- system prompt
- runtime rules
- memory prompt
- confirmation 文案
- UI 文案
- tests
- 实际会进入运行时的 config / README 片段

目标：

```text
所有运行时 Memory 语义统一为“广记 + 广想”
```

---

# 6. Tool Manifest

## 6.1 唯一真实来源

不要手工维护一份独立 `tool_list.yaml` 作为第二真相源。

应以：

```text
ToolRegistry
```

作为真实来源。

Core 启动后：

```text
Builtin Tools
+ MCP 实际注册成功的 Tools
+ 外部集成 Tools
↓
自动生成 Tool Manifest
```

---

## 6.2 Tool Manifest 元数据

建议每个 Tool 至少包含：

```yaml
name: search_memories
group: memory_search
source: builtin
summary: 检索已有长期记忆

registered: true
enabled: true
available: true
persistent: true

read_only: true
destructive: false
```

可选：

```yaml
aliases:
  - 查记忆
  - 回忆
  - 搜索以前的信息

intents:
  - 查找过去记录
  - 回忆之前发生的事
  - 检索已有记忆
```

---

## 6.3 状态字段

必须区分：

```text
registered
enabled
available
exposed
```

例如：

```text
registered = true
enabled = true
available = false
exposed = false
```

表示：

> 系统知道有这把钥匙，也允许使用，但当前依赖不可用。

这样朝汐可以正确表达：

```text
“这项能力有，但现在不可用。”
```

而不是误认为“没有”。

---

# 7. Capability Catalog

根据 Manifest 自动生成一个极简目录，长期提供给 LLM。

示例：

```text
朝汐可按需使用以下能力：

- 长期记忆：记录、更新、检索
- 记忆管理：固定、遗忘、归档、重新激活、整理
- 潮庭 / Archive：搜索和读取资料
- 本地搜索：定位电脑中的文件和目录
- 文件系统：读取、写入、编辑、移动文件
- 网页读取
- 时间与时区
- 计算
- Life HUD
```

要求：

- 只描述能力域；
- 不塞完整参数；
- 不重复全部 schema；
- 自动根据 `enabled / available` 状态生成；
- 新 Tool / 新 Group 注册后自动进入目录。

---

# 8. Tool Inventory 查询

新增轻量常驻 Tool：

```text
inspect_tool_catalog
```

建议支持：

```yaml
action:
  enum:
    - summary
    - list_groups
    - list_tools
    - inspect_group
    - inspect_tool
```

---

## 8.1 summary

用于回答：

```text
“你一共有多少把钥匙？”
```

返回：

```json
{
  "registered_tools": 35,
  "enabled_tools": 33,
  "available_tools": 31,
  "currently_exposed": 5,
  "groups": 10
}
```

---

## 8.2 list_groups

回答：

```text
“你都有哪些类型的能力？”
```

---

## 8.3 list_tools

回答：

```text
“把全部 Tool 列出来”
```

只在明确需要时返回完整清单。

---

## 8.4 inspect_group

例如：

```text
“记忆类一共有几把？”
```

---

# 9. Tool Router

Router 继续存在，但目标重新定义。

不是：

```text
最小化 schema 数量
```

而是：

```text
让当前任务需要的工具优先进入上下文，
同时隔离大量无关低频 Tool，避免注意力被稀释。
```

---

## 9.1 Router 输入

建议：

```text
当前用户输入
+ 最近少量对话上下文
+ Tool Manifest / Capability Catalog
```

---

## 9.2 Router 输出

```text
Persistent Core
+
高概率相关 Dynamic Groups
```

Persistent Core 当前至少包括：

```text
remember_memory
update_memory
search_memories
request_tool_group
inspect_tool_catalog
```

---

# 10. 行动型请求的 Capability Resolution

这是本版本必须补上的关键逻辑。

当用户明确要求：

```text
查
找
读
改
写
发送
计算
操作
获取
执行
```

某件任务时，如果当前 Exposed Tools 不足：

**朝汐不能直接声称“没有对应工具”或“无法完成”。**

必须先确认 Tool Manifest / Capability Catalog 中是否存在对应能力。

---

## 10.1 Runtime Rule

新增硬规则：

```text
当用户要求执行一个任务时，如果当前工具不足，
不要直接声称“没有对应工具”或“无法完成”。

在判断能力不存在之前，必须先：
1. 检查已知 Capability Catalog；
2. 必要时查询 Tool Inventory；
3. 尝试加载匹配 Tool Group；
4. 确认该能力确实不存在或当前不可用。

只有完成以上检查后，才可以告诉用户无法完成。
```

---

# 11. Capability Resolver

建议新增轻量能力解析层：

```text
resolve_capability
```

用途不是执行业务，而是：

```text
自然语言任务需求
↓
匹配 Tool Group
```

例如输入：

```json
{
  "need": "搜索本地电脑里的文件"
}
```

返回：

```json
{
  "matched": true,
  "groups": [
    "local_search",
    "filesystem_read"
  ]
}
```

---

## 11.1 Resolver 数据来源

基于 Tool Manifest 中的：

```text
group
summary
aliases
intents
```

进行匹配。

第一阶段不要求额外 LLM 调用。

可先使用：

- 关键词
- aliases
- intent examples
- 简单语义规则

后续再考虑更复杂语义分类。

---

# 12. request_tool_group

继续保留：

```text
request_tool_group
```

职责：

```text
模型已经知道需要哪一类能力
→ 请求 Core 把对应 Tool Group 真正挂进当前 Function Calling loop
```

---

## 12.1 Router / Resolver / Discovery 的关系

```text
Router
提前猜：这一轮大概率需要什么

Resolver
确认：这个任务对应哪个能力域

request_tool_group
执行：把该能力域的具体 schema 挂进当前轮
```

三者职责不要混在一起。

---

# 13. 动态扩展流程

完整链路：

```text
用户任务
↓
Router 首次筛选
↓
LLM 获得：
- Memory Core
- Capability Catalog
- Router 预挂工具
- inspect_tool_catalog
- request_tool_group
↓
如果当前工具不足
↓
resolve_capability / inspect_tool_catalog
↓
request_tool_group
↓
Core 挂载对应 schemas
↓
重新进入 LLM
↓
继续原任务
```

---

# 14. 动态扩展限制

每个用户轮次建议最多：

```text
2 次 capability expansion
```

禁止：

```text
request_tool_group(all)
```

动态加载后的工具：

```text
当前用户轮内持续可用
```

下一轮重新计算 Tool Context。

---

# 15. Debug Tool Control

Debug 页新增完整的 Tool 控制面板。

目标：

> 新 Tool 可以直接在 Debug UI 启用、停用、强制暴露，不再为了测试去改 `.env`。

---

## 15.1 Tool 列表

Debug 页显示 Tool Manifest 中全部 Tool。

支持按 Group 折叠：

```text
Memory
Archive
Filesystem
Local Search
Web
Time
Life HUD
Other
```

---

## 15.2 每个 Tool 显示

至少展示：

```text
Tool Name
Group
Source
Registered
Enabled
Available
Persistent
Currently Exposed
```

---

## 15.3 Enable / Disable

每个 Tool 有：

```text
启用 / 停用
```

开关。

停用后：

```text
enabled = false
```

必须立即影响：

- Capability Catalog
- Tool Router
- Capability Resolver
- Tool Discovery
- exposed tools

不得出现：

```text
Debug UI 显示关闭
但 LLM 仍能调用
```

---

## 15.4 Group Enable / Disable

支持整组：

```text
启用全部
停用全部
```

例如快速停用整个：

```text
filesystem_write
```

用于测试。

---

# 16. Force Expose

Debug 模式新增：

```text
Force Expose
```

用途：

开发新 Tool 时，可以绕过 Router / Resolver：

```text
启用 ✓
Force Expose ✓
```

该 Tool 每轮直接暴露给 LLM。

测试完成：

```text
Force Expose ✗
```

恢复正常路由。

---

## 16.1 典型开发流程

```text
新建 job_application_tool
↓
ToolRegistry 自动注册
↓
Debug 页自动出现
↓
Enable
↓
Force Expose
↓
直接和朝汐黑盒测试
↓
测试稳定
↓
关闭 Force Expose
↓
补 Router / Manifest metadata
↓
进入正常动态发现体系
```

---

# 17. Tool Override 持久化

Debug 修改不应要求改 `.env`。

建议保存：

```text
data/debug/tool_overrides.json
```

例如：

```json
{
  "mcp_fetch_fetch": {
    "enabled": false,
    "force_expose": false
  },

  "job_application_tool": {
    "enabled": true,
    "force_expose": true
  }
}
```

---

## 17.1 配置优先级

建议：

```text
Debug Runtime Override
↓
本地 Tool Override 配置
↓
.env 默认值
↓
代码默认值
```

`.env` 以后只作为：

```text
启动默认值
```

而不是日常调试入口。

---

# 18. Reset Default

Debug 页提供：

```text
恢复默认
```

支持：

- 单个 Tool 恢复默认；
- 单个 Group 恢复默认；
- 全部 Tool 恢复默认。

恢复后重新按照：

```text
.env / code default
```

计算状态。

---

# 19. Debug Diagnostics

已有 Prompt Diagnostics 继续扩展。

每轮记录：

```text
registered_tools_count
enabled_tools_count
available_tools_count
known_capability_groups
persistent_tools
router_matched_groups
initial_exposed_tools
requested_tool_groups
expanded_tools
force_exposed_tools
final_exposed_tools
capability_expansion_count
tool_schema_chars
prompt_tokens
```

不要打印：

- 用户原文
- Memory 正文
- Tool Schema 正文
- Tool 参数正文
- Prompt 正文

---

# 20. UI 状态同步

Tool Debug UI 必须读取 Tool Manifest 实时状态。

不能自己维护第二套列表。

理想关系：

```text
Tool Registry
↓
Tool Manifest
├─ Capability Catalog
├─ Router
├─ Resolver
├─ Discovery
├─ Inventory
└─ Debug Tool Panel
```

所有模块共用同一个 Tool Manifest。

---

# 21. 建议 Tool Group

具体名称按现有注册实际情况调整：

```text
memory_core
memory_admin
archive
local_search
filesystem_read
filesystem_write
web
time
calculator
lifehud
debug
```

---

# 22. Memory 管理类工具

以下仍然不常驻：

```text
pin_memory
forget_memory
archive_memory
reactivate_memory
consolidate_memories
```

它们通过：

```text
memory_admin
```

按需挂载。

原因：

这类工具属于管理维护，不属于日常“记、改、想”。

---

# 23. 测试要求

## 23.1 Memory Core Tests

普通闲聊必须始终存在：

```text
remember_memory
update_memory
search_memories
```

验证：

```text
“周六早上了呀”
```

仍然可以自然：

- 记下相关信息；
- 更新旧信息；
- 主动联想过去。

---

## 23.2 广记语义测试

用户：

```text
今天楼下可乐涨价了
```

没有“记住”关键词。

仍必须允许 `remember_memory`。

---

## 23.3 广想测试

用户提到与既有 Memory 自然相关的话题时：

```text
今天太阳有点像夏天
```

`search_memories` 必须可用。

不要求一定调用，但不得因 Router 裁剪而无法调用。

---

## 23.4 Inventory Tests

验证：

```text
你一共有多少把钥匙？
```

应基于完整 Inventory 回答。

不能只数当前 exposed tools。

验证：

```text
记忆类有哪些？
```

应能查询对应 Group。

---

## 23.5 行动能力测试

模拟：

```text
帮我找桌面上的面试复盘
```

如果当前没有 local search schema：

必须经过：

```text
Capability Resolution
→ Tool Group Load
→ 实际执行
```

不得直接回答：

```text
“我没有搜索工具”
```

---

## 23.6 Disabled Tool Tests

Debug 关闭某 Tool 后：

```text
enabled = false
```

必须保证：

- Router 不暴露；
- Resolver 不推荐为可用能力；
- Discovery 不加载；
- Catalog 标记停用；
- Inventory 能看到存在但停用；
- LLM 无法调用。

---

## 23.7 Force Expose Tests

Debug 设置：

```text
force_expose = true
```

必须保证：

- 不受 Router 判断影响；
- 每轮直接暴露；
- 关闭后立即恢复正常动态路由。

---

## 23.8 Runtime Override Persistence

修改 Debug 状态后：

```text
重启 Core
```

状态仍保持。

点击“恢复默认”后：

```text
override 被清除
```

---

# 24. 回归测试

必须确保：

- 原 Tool Router 正常；
- Function Calling 多轮循环正常；
- MCP 工具正常；
- Memory recall 不受影响；
- Presence 不受影响；
- Personality / Few-shot 不受影响；
- `all` debug 模式如仍保留则继续可用；
- 动态扩展不会无限循环；
- Tool Group 在当前用户轮结束后正确重置；
- Debug UI 不引入第二套 Tool Registry。

---

# 25. 本版本暂不做

v1.2.2 暂不做：

- 合并 filesystem tool schema；
- 合并 Memory tool schema；
- 用额外 LLM 做 Router；
- 重写 Memory recall；
- 重构整个 MCP Provider；
- 对全部 Tool 做新的权限系统；
- 自动生成复杂 UI 配置页。

本版本只建立完整 Tool 管理闭环。

---

# 26. 验收标准

## Memory

- [ ] `remember_memory` 常驻
- [ ] `update_memory` 常驻
- [ ] `search_memories` 常驻
- [ ] 广记旧规则全部修正
- [ ] 允许自然主动检索过去记忆

## Manifest / Inventory

- [ ] ToolRegistry 为唯一真实来源
- [ ] 自动生成 Tool Manifest
- [ ] Tool 有 group/source/state metadata
- [ ] 能准确统计 Tool 总数
- [ ] 能查询 Group / Tool
- [ ] 区分 registered / known / exposed

## Router / Discovery

- [ ] Router 继续负责预挂载
- [ ] 新增 Capability Resolver
- [ ] 当前工具不足时可动态扩展
- [ ] 声称“没有能力”之前必须先查 Catalog / Inventory
- [ ] 单轮扩展次数有限制
- [ ] 不允许直接请求 all tools

## Debug

- [ ] Debug 页显示完整 Tool 清单
- [ ] 可单独 Enable / Disable
- [ ] 可按 Group Enable / Disable
- [ ] 支持 Force Expose
- [ ] 修改立即生效
- [ ] Override 可持久化
- [ ] 支持恢复默认
- [ ] 不再需要为了调试频繁修改 `.env`

## Diagnostics

- [ ] 能看到 registered / enabled / available / exposed 数量
- [ ] 能看到 Router 匹配结果
- [ ] 能看到动态扩展过程
- [ ] 能看到 Force Expose 状态
- [ ] 不泄露正文内容

## Tests

- [ ] 新增 Memory Core Tests
- [ ] 新增 Inventory Tests
- [ ] 新增 Capability Resolution Tests
- [ ] 新增 Dynamic Discovery Tests
- [ ] 新增 Debug Tool Control Tests
- [ ] 相关集成测试通过
- [ ] 完整测试无新回归

---

# 27. 版本定位

v1.1.9 做的是：

```text
别把所有钥匙都挂在朝汐腰上。
```

v1.2.2 要完成的是：

```text
朝汐要知道钥匙柜里到底有什么，
需要哪把时能自己拿，
平时一直带着属于“记忆器官”的那几把，
而暗苟酱也能在 Debug 页随时管理整个钥匙柜。
```

最终结构：

```text
Tool Registry
      ↓
Tool Manifest
      ↓
┌───────────────────────────────────────┐
│ Memory Core                           │
│ Capability Catalog                    │
│ Tool Inventory                        │
│ Tool Router                           │
│ Capability Resolver                   │
│ Tool Discovery                        │
│ Debug Tool Control                    │
└───────────────────────────────────────┘
      ↓
当前轮 Exposed Tools
      ↓
LLM
```

---

## 一句话总结

**别让朝汐背着整串钥匙走路，也别让她因为没摸到口袋里的钥匙，就以为整栋房子没有那扇门。**
