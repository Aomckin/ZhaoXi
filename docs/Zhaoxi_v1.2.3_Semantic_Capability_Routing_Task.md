# Zhaoxi v1.2.3 轻量任务书
## Semantic Capability Routing

### 背景
v1.2.2 已完成 Tool Manifest、动态取钥匙和 Discovery，但真实对话中仍出现：
用户自然提出任务时，朝汐没有先想到对应 Tool，于是直接凭上下文回答，甚至在提醒后仍没完成查询。

典型：
```text
用户：你觉得我今天一天吃得如何？
```

正确链路应为：
```text
自然语言任务
→ 轻量语义能力匹配
→ 命中 Tool Group
→ 预挂 Tool
→ 朝汐基于真实数据回答
```

## 1. 核心改动
在现有 Tool Router 前补一层轻量 `Semantic Capability Routing`。

不新增额外 LLM 调用，优先基于：
- Capability Manifest
- group summary
- aliases
- intents
- 少量关键词 / 规则

将自然语言需求映射到 Tool Group。

## 2. 补全 Life HUD 能力语义
不要只依赖 `Life HUD / 铁幕 / 任务` 等内部词。

为 `lifehud` 补充 intents：
- 查看今天吃了什么
- 评价今天饮食
- 查询饮食记录
- 查看今天做过什么
- 查询睡眠记录
- 查询任务完成情况
- 查询 FocusSession
- 查询铁幕记录
- 查看能量 / 经验
- 查看近期生活状态

目标：用户不需要知道内部 Tool 名称。

## 3. 行动型请求预路由
示例：

```text
“我今天吃得怎么样？”
→ lifehud

“帮我找一下昨天那个复盘”
→ local_search + filesystem_read

“之前那个岗位我怎么说的？”
→ memory_search
```

命中后提前暴露对应 Tool Group。
未命中则继续走 v1.2.2 已有 Discovery。

## 4. Router 与 Discovery 分工
```text
Semantic Router = 提前猜中常见自然语言任务
Discovery = Router 没猜中时兜底
```

不要重写 v1.2.2。

## 5. 禁止失败模式
新增规则：

> 当用户明确要求查询、判断或执行依赖真实数据的任务时，如果系统中存在相关能力，不要直接凭聊天上下文猜测，也不要要求用户说出内部 Tool 名称。

禁止直接出现：
- “请换一种更明确的说法”
- “我没有对应工具”
- “你要明确说 Life HUD”

除非已确认 Manifest 中确实没有对应能力，或该能力 disabled / unavailable。

## 6. 回归测试

### Case A：饮食
```text
用户：你觉得我今天一天吃得如何？
```
预期：
```text
自动命中 lifehud
→ 实际查询
→ 基于真实记录回答
```

### Case B：文件
```text
用户：帮我找一下昨天那个面试复盘
```
预期：
```text
local_search + filesystem_read
```

### Case C：记忆
```text
用户：之前我怎么说暑假结束来着？
```
预期：
```text
memory_search 可直接使用
```

### Case D：避免误触发
```text
用户：今天铁幕做得累死了
```
预期：
```text
不要仅因出现“铁幕”就强制查询 Life HUD
```

## 7. Diagnostics
增加：
```text
semantic_route_matched
semantic_route_groups
semantic_route_reason
```

示例：
```text
matched = true
groups = [lifehud]
reason = daily_diet_query
```

## 8. 本版本不做
- 不新增 LLM Router
- 不重构 Tool Manifest
- 不重构 Discovery
- 不合并 Tool Schema
- 不修改 Memory 架构
- 不扩展 Debug Tool Control
- 不引入复杂向量分类器

只补：
```text
自然语言任务 → 能力域
```

## 9. 完成标准
- [ ] 增加轻量 Semantic Capability Routing
- [ ] 补全 Life HUD intents
- [ ] 常见行动型请求可自动预挂 Tool
- [ ] 用户无需说出内部 Tool 名称
- [ ] Router 未命中时仍能走现有 Discovery
- [ ] 普通聊天不会被关键词误触发
- [ ] 新增至少 4 组回归测试
- [ ] Diagnostics 可看到语义路由结果
- [ ] 不破坏 v1.2.2 现有 Tool 系统

## 一句话总结
**别让朝汐非得先听见“Life HUD”三个字，才想起自己能查生活。**
