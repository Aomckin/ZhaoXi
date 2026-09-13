# Zhaoxi v1.2.2 开发任务书
## Tool Discovery & Memory Semantics Fix
### 修复“广记”语义冲突，并补齐动态工具路由的能力发现闭环

## 1. 背景

当前版本已推进至 v1.2.1，但在实际使用中发现两个架构级问题。

### 1.1 Memory Tool Description 与“广记”理念冲突

现有 `remember_memory` 相关工具说明仍带有类似：

> 仅在用户明确要求记住长期信息时使用

的约束。

这与朝汐既定记忆策略直接冲突。朝汐当前的 Memory 设计是“广记”：

- 用户不必显式说“记住”；
- 日常小事、偏好、变化、阶段性事件也允许记录；
- 是否值得记，由朝汐结合上下文自主判断；
- Memory 是朝汐长期连续存在的一部分，不是单纯命令式存储功能。

因此必须修正 tool description、相关确认文案和运行规则中仍残留的“只有用户明确要求才记”逻辑。

### 1.2 Tool Context Router 缺少“动态发现”闭环

当前 Tool Context Router 已能按需暴露工具，避免所有 Tool Schema 全量常驻。

但实际出现以下问题：

```text
用户：比如你试试找下搜索记忆的那把？
```

朝汐知道自己“应该有”搜索记忆能力，但当前轮次没有暴露 `search_memories`，导致：

```text
知道能力存在
≠
当前可以调用
```

最终只能返回“这次没有实际完成工具查询”。

这说明当前 Router 只有“预先猜测当前需要哪些工具”，但缺少：

```text
模型发现当前工具不够
→ 主动请求额外工具
→ Core 临时挂载
→ 继续当前任务
```

这一闭环。

## 2. 本版本目标

v1.2.2 重点修复：

1. Memory “广记”语义；
2. 动态工具发现；
3. “当前携带工具”与“朝汐总能力”概念混淆；
4. Tool Router 缺少二次扩展能力的问题。

最终目标：

```text
朝汐平时不需要把所有钥匙挂在腰上，
但必须知道钥匙柜里有哪些钥匙，
并且需要时能自己去拿。
```

## 3. Memory 语义修复

### 3.1 修正 remember_memory

彻底删除类似：

```text
仅在用户明确要求记住时使用
```

的旧规则。

建议语义：

```text
用于记录值得长期保留的信息。

朝汐可以根据对话自行判断是否记录，
无需等待用户明确说“记住”。

允许记录：
- 日常小事
- 偏好
- 近期变化
- 阶段性事件
- 用户习惯
- 与朝汐长期关系有关的信息

不要因为信息看似琐碎就默认忽略。
```

### 3.2 修正 update_memory

建议语义：

```text
当用户自然地修正、补充或改变已有信息时，
可直接更新相关 Memory。

不要求用户明确说“更新记忆”。
```

典型：

```text
“那个岗位现在已经不能去了”
“我现在不想继续用之前的方案”
“其实我更喜欢另一种”
```

### 3.3 检查全部 Memory 规则来源

必须搜索以下内容是否仍有旧逻辑：

```text
仅在用户明确要求
只有用户要求记住
必须明确提出保存
仅保存长期重要信息
不要记录琐事
```

检查范围至少包括：

- Memory tool descriptions
- system prompt
- runtime rules
- memory prompt
- confirmation / approval text
- tests
- README / config 中实际会参与运行的部分

目标：

```text
所有运行时规则统一为“广记”
```

## 4. Tool Discovery 机制

### 4.1 新增常驻 Discovery Tool

建议新增：

```text
request_tool_group
```

该工具必须：

- schema 很小；
- 默认长期暴露；
- 不直接执行业务；
- 只负责请求加载新的工具组。

### 4.2 建议 Schema

```yaml
request_tool_group:
  description: >
    当当前可用工具不足以完成用户请求时，
    请求加载额外工具能力，然后继续当前任务。

  parameters:
    group:
      enum:
        - memory_search
        - memory_admin
        - archive
        - local_search
        - filesystem_read
        - filesystem_write
        - web
        - time
        - calculator
        - lifehud
```

不要把每个具体 Tool 全部写入 description。

Discovery 层只需要知道有哪些能力域，不需要知道每个 Tool 的完整 schema。

## 5. Capability Catalog

为朝汐提供一个极小的“能力目录”。

例如：

```text
当前可按需取得的能力：
- 记忆检索
- 记忆管理
- 潮庭/档案
- 本地文件搜索
- 文件读取
- 文件修改
- 网页读取
- 时间
- 计算
- Life HUD
```

目的：让模型知道自己“拥有”这些能力，即使当前轮次尚未暴露对应 Tool Schema。

## 6. 区分三个概念

### A. registered_tools

系统当前实际注册的全部工具，例如 34 个。

### B. known_capabilities

朝汐知道自己拥有哪些能力域，例如：

```text
memory
archive
filesystem
web
lifehud
time
calculator
```

### C. exposed_tools

当前轮真正传给 LLM 的 Function Calling schema，例如：

```text
remember_memory
update_memory
request_tool_group
```

用户问“你现在有多少钥匙？”时，不能再把 `exposed_tools` 数量直接当成“朝汐总共只有这些能力”。

## 7. 动态工具加载流程

目标流程：

```text
用户请求
↓
Tool Context Router 首次筛选
↓
模型看到：
- persistent core tools
- 当前 dynamic tools
- request_tool_group
- capability catalog
↓
模型发现当前工具不足
↓
调用 request_tool_group
↓
Core 加载对应工具组
↓
重新发起模型调用
↓
模型继续执行原任务
```

## 8. 示例

### Case A：普通聊天

用户：

```text
周六早上了呀
```

当前暴露：

```text
remember_memory
update_memory
request_tool_group
```

无需额外加载。

### Case B：用户要求查旧记忆

用户：

```text
你试试找下搜索记忆的那把？
```

如果 Router 首轮未命中：

```text
模型调用：
request_tool_group(memory_search)
```

Core：

```text
追加 search_memories
```

模型继续：

```text
调用 search_memories
```

而不是告诉用户“我现在没有这把钥匙”。

### Case C：本地文件搜索

用户：

```text
帮我找一下桌面上的面试复盘
```

若 Router 已命中：

```text
local_search + filesystem_read
```

则不需要 discovery。

若未命中：

```text
request_tool_group(local_search)
```

之后继续。

## 9. Tool Discovery 重试限制

避免模型无限请求工具组。

建议每个用户轮次最多允许：

```text
2 次 capability expansion
```

例如：

```text
第一次：request memory_search
第二次：request archive
超过次数：停止扩展，按现有能力回答或明确说明无法完成
```

同时禁止：

```text
request_tool_group(all)
```

不要允许模型直接恢复全量工具。

## 10. Tool Group 加载后的行为

一旦请求某个 Tool Group：

```text
当前 Function Calling loop 内保持可用
```

不要每次 Tool Result 返回后重新丢失。

例如：

```text
request memory_search
→ search_memories
→ 得到结果
→ 后续模型继续看到 search_memories
```

当前用户轮结束后：

```text
下一轮重新计算 Tool Context
```

不要永久挂载。

## 11. Persistent Core Tools 调整

默认长期暴露：

```text
remember_memory
update_memory
request_tool_group
```

如后续证明某些 Tool 极高频且 schema 很小，可另行评估。

当前不要继续扩大 persistent core。

## 12. Router 与 Discovery 的关系

两者职责不同。

### Router

负责提前猜中大概率需要的工具。

目标：

- 减少额外 round-trip
- 提升常见操作速度

### Discovery

负责 Router 没猜中时兜底。

目标：

- 不因为工具裁剪导致能力缺失
- 允许模型自己补足工具

因此 Router 不需要百分百准确，只要：

```text
Router + Discovery
```

整体闭环可靠即可。

## 13. 不要让 Discovery 变成 Tool Schema 复读机

Capability Catalog 只描述能力域。

错误：

```text
filesystem_read_text_file:
  path...
  head...
  tail...
filesystem_read_multiple_files:
  paths...
...
```

正确：

```text
filesystem_read:
  读取本地文件、目录和媒体文件
```

只有真正请求该能力后，才把详细 schemas 发给 LLM。

## 14. UI / 文案修正

当前出现：

```text
是否允许朝汐执行：
仅在用户明确要求记住长期信息时使用？
```

这类确认文本必须修改。

如果 Memory 写入仍需要 UI 确认，建议：

```text
朝汐想记录一条长期记忆，是否允许？
```

不要再显示旧的“只有明确要求才记”规则。

如果当前设计中 Memory 写入无需每次确认，则检查该文案是否应该直接移除。

## 15. Prompt Diagnostics 扩展

新增：

```text
known_capabilities
initial_exposed_tools
requested_tool_groups
expanded_tools
capability_expansion_count
final_exposed_tools
```

示例：

```text
Tool Router:
initial groups: persistent_core

Known capabilities:
memory_search
archive
filesystem_read
filesystem_write
web
time
calculator
lifehud

Capability expansion:
1. memory_search

Initial tools: 3
Final tools: 4
```

继续遵循：

```text
只记录模块和数量
不打印用户原文
不打印 Memory 内容
不打印 Tool Schema 正文
```

## 16. 测试要求

### 16.1 Memory Semantics Tests

用户未明确要求：

```text
“今天楼下可乐涨价了”
```

必须保证：

```text
remember_memory
```

仍然可用。

不能因为没有“记住 / 保存 / 记录”而移除。

对于：

```text
“那个岗位现在已经不能去了”
```

必须保证：

```text
update_memory
```

可用。

### 16.2 Discovery Tests

初始：

```text
remember_memory
update_memory
request_tool_group
```

模型请求：

```text
request_tool_group(memory_search)
```

随后：

```text
search_memories
```

必须进入下一次模型调用。

还需覆盖：

- Router 已提前暴露时，不重复 request；
- 非法 group 拒绝但不崩溃；
- 重复 request 自动去重；
- 超过 expansion limit 后停止扩展；
- Tool Result 返回后动态工具仍保持到当前用户轮结束。

## 17. 能力认知测试

用户：

```text
你现在会哪些东西？
```

回答依据应是：

```text
known_capabilities
```

而不是：

```text
当前 exposed_tools
```

不要再出现“我只有四把钥匙”，但实际上只是当前只挂了四把。

## 18. 回归测试

必须确保：

- Tool Router 原功能正常；
- Function Calling 多轮循环正常；
- Memory 自动 recall 不受影响；
- 广记写入逻辑不受 Router 限制；
- Discovery 后 Tool Result 能继续回模型；
- 当前用户轮结束后动态工具不会永久污染下一轮；
- `all` debug 模式仍可用；
- Prompt Diagnostics 正常；
- 现有人格 / few-shot / Presence 不受影响。

## 19. 本版本暂不做

v1.2.2 不做：

- 合并 filesystem tools；
- 合并 memory tools；
- 新增 LLM Router；
- 重写 Memory 系统；
- 修改 Memory recall 算法；
- 重构 MCP Provider；
- 全面改造 Tool Registry。

本版本只补齐：

```text
广记语义
+
能力目录
+
动态工具发现
+
工具扩展闭环
```

## 20. 验收标准

- [ ] `remember_memory` 描述符合广记设计；
- [ ] `update_memory` 描述符合自然修正设计；
- [ ] 删除运行时旧“仅明确要求才记”规则；
- [ ] 新增 `request_tool_group`；
- [ ] `request_tool_group` 长期暴露；
- [ ] 新增 Capability Catalog；
- [ ] 区分 registered / known / exposed；
- [ ] Router 未命中时可动态加载工具；
- [ ] 动态加载后能继续原任务；
- [ ] 单轮最多允许有限次数工具扩展；
- [ ] 不允许直接请求 all tools；
- [ ] 用户轮结束后动态加载状态重置；
- [ ] Memory 广记能力长期保留；
- [ ] 相关 UI 文案修正；
- [ ] Prompt Diagnostics 能记录扩展过程；
- [ ] 新增单元测试与集成测试；
- [ ] 完整测试通过。

## 21. 版本定位

v1.1.9 解决的是：

```text
不要每轮暴露全部工具
```

v1.2.2 要补上的是：

```text
工具不在手边时，
朝汐必须知道自己还有这项能力，
而且能够自己把它拿回来。
```

同时修正一个更早遗留的问题：

```text
Memory 不是“用户明确要求才启动”的功能。
```

对于朝汐而言：

```text
广记是常态，
搜索、管理和外部工具才是按需能力。
```

## 一句话总结

**让朝汐少带钥匙，但不能让她忘记钥匙柜；让她广记生活，也别再等暗苟酱亲口说“请记住”。**
