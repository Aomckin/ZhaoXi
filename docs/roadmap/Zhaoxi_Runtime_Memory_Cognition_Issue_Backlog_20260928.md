# Zhaoxi 待统一收拾问题清单
> 日期：2026-09-28
> 状态：**仅记录问题，不立即开发**
> 用途：继续使用/排查一段时间后，将同类问题补充进来，再统一开新版本处理。

---

## 0. 这份清单解决什么

最近在继续使用朝汐时，逐渐暴露出一批「功能已经存在，但内部行为偏黑箱、运行链路偏重、认知表达不够自然」的问题。

这些问题目前不急着逐个打补丁。

先统一记下来，等再发现一批同类型问题后，一次性开新版本收拾，避免继续：

```text
发现一个问题
→ 打一个补丁
→ 又牵出另一个问题
→ 再改一层
→ 系统继续变胖
```

这一轮主要记录三大类：

1. Memory 检索与生命周期的可解释性问题；
2. Router / Planner / AutoMemory 带来的运行延迟与显式化问题；
3. Current Cognition / 短期认知的定位、文风与数据结构问题。

---

# 1. Memory：设计已演化，但对开发者仍太黑箱

## 1.1 当前实际上已经不是「重要程度 + 活跃程度」二维模型

最初设定的两维：

```text
importance
relevance / activation
```

目前代码实际上已经演化成三类信号：

```text
importance
→ 这条记忆长期有多重要

activation
→ 这条记忆最近有多活跃 / 多“热”

contextual relevance
→ 这条记忆与当前输入有多相关
```

当前检索综合分大致为：

```text
text_score        0.48
semantic_score    0.27
graph_score       0.08
time_score        0.07
activation        0.06
importance        0.04
```

因此：

- importance / activation 并非主要“召回信号”；
- 它们更像长期保留与二次排序因子；
- 当前输入与 Memory 的匹配程度，才是召回主体。

这个设计本身是合理的，但**现在没有一个直观位置能看懂它到底为什么召回某条记忆**。

---

## 1.2 当前 semantic_score 并不是真正语义向量检索

目前存在：

```text
LocalHashEmbeddingProvider
```

会把词法特征映射到固定维度，再计算 cosine。

因此严格来说：

```text
有“向量”
但不是神经网络语义 Embedding
```

它可以处理：

```text
相同 / 相近关键词
中文 bigram
词法重叠
```

但对：

```text
“最近找工作好累”
≈
“秋招推进不顺”
```

这类真正语义近似，理解能力有限。

后续接真实 Embedding 时，可保留当前混合 rerank 思路：

```text
ANN / 向量 Top-K
        ↓
关键词 + 语义 + 图关系 + 时间
        + activation + importance
        ↓
最终排序
```

---

## 1.3 COLD 的实际行为与早期设计发生漂移

早期设计：

```text
高重要 + 低活跃
→ COLD
→ 默认不主动进入普通上下文
→ 有相关主题时再重新激活
```

当前实际普通检索会搜索：

```text
ACTIVE + COLD
```

且 COLD 没有明显额外降权。

需要后续重新确认：

- COLD 是否应该进入普通自动召回；
- 如果允许进入，是否应该有状态惩罚；
- “高重要但长期沉睡”的记忆应该如何重新唤醒。

---

## 1.4 存在“配置有旋钮、实际没接齿轮”的遗留项

例如：

```text
importance_forget_threshold
```

配置仍然存在，但当前 lifecycle 逻辑里没有真正参与判定。

需要统一审计：

```text
配置字段
→ 是否实际生效
→ 是否与文档一致
→ 是否只是兼容遗留
```

避免继续保留“看起来可以调，实际上不影响任何行为”的参数。

---

## 1.5 SQLite FTS 已建立，但主召回链路并未真正使用

当前数据库中存在：

```text
memories_fts
FTS5
```

写入时也会同步。

但主检索实际更接近：

```text
先取大量 ACTIVE / COLD Memory
→ Python 逐条计算文本匹配
→ LocalHash cosine
→ graph / time
→ importance / activation
→ 排序
```

当前规模小还能接受。

长期“广记”后，如果 Memory 规模达到数万级，需要重新评估：

- FTS 是否进入 candidate retrieval；
- 真实 Embedding 是否取代 O(N) 扫描；
- 当前 Python 全量评分是否还能接受。

---

## 1.6 importance / activation 的生成标尺不够明确

AutoMemory Prompt 会要求模型生成：

```text
importance
activation
```

但目前缺少明确量表：

```text
0.2 是什么
0.5 是什么
0.8 是什么
0.95 又是什么
```

导致普通自动记忆中，这两个值存在一定“模型凭感觉打分”的成分。

后续需要补：

- 清晰分档；
- few-shot；
- 默认值策略；
- 显式“记住 / 别忘了”与普通自动记忆的区别；
- episodic / semantic / relationship 不同类型是否采用不同初始值。

---

## 1.7 Memory 最需要先补的是「可观察性」

仓库已有：

```text
MemoryService.inspect_retrieval()
```

可以输出：

```text
score
contextual_relevance
text_score
semantic_score
graph_score
time_score
activation_score
importance_score
why_selected
```

后续应该优先做：

### Memory Retrieval Observatory

Debug 页面输入一句话后，直接展示：

```text
#1 某条记忆

final        0.73
text         0.72
semantic     0.61
graph        0.34
time         0.51
activation   0.82
importance   0.43

why:
keyword + semantic + graph
```

目标：

> 让 Memory 从“能工作”变成“我知道它为什么这样工作”。

---

# 2. Runtime 延迟：普通回复存在明显固定税

当前感知：

```text
普通回复经常 30s 起步
```

进一步排查后发现：

## 2.1 不是 Planner 每轮都介入

当前每轮真正固定介入的是：

```text
CognitiveRouter
```

Planner 仅在 Router 输出：

```text
PLAN
```

时启动。

侧边栏里：

```text
第1轮 · 正在思考下一步
第2轮 · 正在思考下一步
```

属于普通 Agent loop 的 model step，不等价于 Planner。

这个显示目前容易造成误解。

---

## 2.2 普通对话可能至少经历 3 次 LLM 调用

当前大致链路：

```text
用户输入
  ↓
CognitiveRouter LLM
  ↓
Memory Retrieval（本地）
  ↓
主 Agent LLM
  ↓
生成回复
  ↓
AutoMemory LLM
  ↓
最终返回
```

因此普通聊天也可能承担：

```text
Router LLM
Main LLM
AutoMemory LLM
```

三次模型请求。

这很可能是 30s 起步的核心来源之一。

---

## 2.3 Router 的本地规则放置顺序不够理想

当前有不少本地能力：

```text
_hint_decision()
_archive_decision()
_is_emoji_reply_request()
_is_emoji_save_request()
_contextual_tool_followup()
simple request guard
```

但不少逻辑发生在：

```text
Router LLM 调用之后
```

这意味着本来可以本地确定的简单请求，也先支付了一次 LLM 延迟。

后续方向：

```text
Local Fast Route
    ↓
能确定
→ 直接 DIRECT / TOOL / WORKFLOW

无法确定 / 有歧义
→ Router LLM
```

Router 应该成为：

> 不确定时才调用的认知分类器。

而不是每轮固定前置税。

---

## 2.4 AutoMemory 当前阻塞主回复

当前逻辑大致是：

```text
主回复已经生成
↓
等待 AutoMemory.process()
↓
Memory 整理完成
↓
才真正返回给用户
```

这意味着：

> 用户在等朝汐“写完日记”之后，才能看到她已经说完的话。

后续应考虑：

```text
主回复先交付
↓
AutoMemory 后置 / 异步执行
```

至少不应该让长期记忆整理位于主交互关键路径上。

需要注意：

- 不得破坏消息顺序；
- 不得出现上一轮 Memory 维护晚到后覆盖新状态；
- 失败时不能影响已经生成的回复；
- 后台维护状态要可观测。

---

## 2.5 Decision System 并非每轮都真正调用模型

`DecisionService.evaluate()` 每轮会经过入口，但存在：

```text
should_evaluate()
```

本地门控。

只有检测到类似：

```text
要不要
该不该
选哪个
值不值得
帮我决定
岗位 / offer 明显取舍冲突
```

才真正进入 Decision LLM。

因此 Decision 不是普通每轮固定税。

但如果命中 Decision，一次对话可能出现：

```text
Router LLM
Decision Memory Retrieval
Decision LLM
Persona Expression LLM
AutoMemory LLM
```

需要后续单独统计真实耗时。

---

## 2.6 必须补阶段耗时统计

目前对延迟更多还是“根据代码推测”。

后续 Debug 应直接显示：

```text
routing_ms
memory_retrieval_ms
decision_ms
planner_ms
model_ms[]
tool_ms[]
response_finalize_ms
auto_memory_ms
current_cognition_ms
total_ms
```

最好同时记录：

```text
LLM call count
prompt tokens
output tokens
tool call count
```

目标：

> 不再猜“30 秒去哪了”。

---

# 3. Planner：不是每轮都跑，但进入后很重，需要真正显式化

Planner 当前是完整多轮 Agent Runtime。

典型链路：

```text
Goal 创建
↓
Memory Retrieval
↓
Planner LLM
↓
create_plan
↓
工具执行
↓
Planner LLM
↓
下一步 / replan
↓
...
↓
Finalization LLM
```

当前限制包括：

```text
max_steps = 12
max_replans = 3
max_attempts_per_step = 2
total_timeout ≈ 180s
```

Planner 本身“重”不是问题。

前提是：

> 只有真正复杂任务才进去。

---

## 3.1 Planner 当前已有完整 Trace，但没进入主 ActionTrace

Planner 内部已有：

```text
goal_created
plan_created
plan_revised

step_started
tool_called
observation_received
step_retried
fallback_selected
step_completed

input_requested
permission_requested

task_completed
task_failed
task_cancelled
```

这意味着 Planner 显式化并不缺数据。

真正缺的是：

```text
Planner Trace
→ 主 ActionTrace
→ 前端侧栏
```

---

## 3.2 不建议前端单独再接一套 Planner Trace

后续更合理的是：

```text
Planner Trace
    ↓
Planner → ActionTrace Adapter
    ↓
统一 agent_event
    ↓
现有 Web Event
    ↓
侧边栏
```

例如：

```text
plan_created
→ planner_plan_created

step_started
→ planner_step_started

step_completed
→ planner_step_completed

plan_revised
→ planner_replanned
```

长期看：

```text
Memory
Planner
Workflow
Decision
Tool
```

都应该逐渐统一到同一套 Runtime Observability。

---

## 3.3 Planner UI 应与普通 Agent loop 区分

当前侧栏：

```text
第1轮 · 正在思考下一步
第1轮 · 已确定下一步
第2轮 · 正在思考下一步
...
```

信息是透明的，但非常像底层日志。

Planner 后续更适合展示：

```text
▾ 规划任务

目标
更新今天的 LifeHUD 并整理结果

计划 v1
✓ 读取当前状态
✓ 写入饮食记录
● 核对日程
○ 整理结果
```

发生重规划时：

```text
↻ 已重新规划
原因：原方案缺少对应能力

计划 v2
✓ 检查工具目录
● 使用替代接口
○ 整理结果
```

分层原则：

```text
输入框上方
→ 朝汐现在正在干嘛

侧边栏
→ 她正在怎么干

Debug
→ Runtime 到底发生了什么
```

---

# 4. Current Cognition：当前更像“分析报告”，不像朝汐自己的临时日记

当前最明显问题：

```text
不像朝汐自己写给自己看的东西
```

而更像：

```text
后台模块对“用户”进行观察后生成的分析报告
```

典型表现：

- 大量使用“用户……”；
- 第三人称观察视角很重；
- 喜欢解释、归纳、分析动机；
- 多条主线混成一整段；
- 信息层级不清晰；
- 旧内容容易不断黏在 narrative 里；
- 最终读起来像“近期形势分析报告”。

---

## 4.1 当前 Prompt 本身就在诱导这种文风

当前 Prompt 同时写了：

```text
Current Cognition 是实时日记
```

但又写：

```text
不扮演朝汐
俯瞰近期用户消息
整体局势概括
不做文学润色
```

这几个条件叠加后，模型自然会写成：

> 第三方系统分析员口吻。

后续应该重新定义认知主体：

```text
Current Cognition 是朝汐写给自己的私人近期认知。
```

不是：

```text
系统写给开发者看的用户分析。
```

---

## 4.2 建议语气

应该是：

```text
朝汐自己的认知视角
```

但不是角色扮演输出。

要求可以是：

- 对暗苟称“暗苟”，或自然省略主语；
- 禁止称“用户”；
- 不需要卖萌；
- 不需要耳朵尾巴舞台描写；
- 不需要面向用户解释；
- 不需要完整文章感；
- 允许自然、不正式、带一点个人认知色彩。

本质：

> 同一个“朝汐”在给未来几轮的自己留便签。

---

# 5. Current Cognition：当前 narrative 太重，容易越滚越乱

当前结构：

```text
narrative
ongoing_threads
attention
observations
```

但实际大部分信息仍然塞入：

```text
narrative（最多 700 字）
```

于是长期维护后容易变成：

```text
求职
+ 项目
+ QQ
+ 面试
+ 暑假回忆
+ 状态分析
+ 开发方式
+ 身份一致性
→ 全黏在一个大段落里
```

虽然结构上有 threads / attention，但 narrative 仍承担过多职责。

---

## 5.1 700 字对于“每轮常驻认知”太重

Current Cognition 每轮都会注入 Context。

因此它应该是：

```text
短
稳定
可快速扫一眼
真正有近期价值
```

而不是：

```text
一篇 600~700 字议论文
```

建议以后控制在：

```text
250~450 中文字
```

信息不足时更短。

---

# 6. Current Cognition 更适合模仿“轻量 Memory Summary”

参考方向不是照搬 ChatGPT Memory Summary，而是借它的：

```text
有组织
有主题
有层级
不是一整块散文
```

但朝汐版本应该更轻、更临时。

示例结构：

```text
【这几天】
暗苟最近还是围着秋招和项目两条线转。
学校和寝室让节奏有些散；这两天注意力开始重新回到朝汐本身，
想把之前 vibe coding 留下的一些黑箱真正弄明白。

【手头还挂着】
· 秋招继续推进，但对低价值宣讲/笔试明显更没耐心了。
· 朝汐当前在收口运行机制，主要是 Memory、Planner、Current Cognition。

【刚发生的变化】
· 开始主动追代码链路，而不是继续堆功能。
· Current Cognition 自己暴露出“系统分析报告”味，需要重做。

【我需要记着】
· 不要把单次情绪和单件小事拔高成趋势。
```

推荐上限：

```text
这几天          ≤ 180 字
手头还挂着      ≤ 3 条
刚发生的变化    ≤ 3 条
我需要记着      ≤ 2 条
```

不要求填满。

---

# 7. Current Cognition 的写入标准应该重新定义

现在容易陷入：

```text
“最近一周发生了什么”
→ 尽量都总结
```

后续更好的判断标准：

> 如果明天朝汐醒来，不知道这件事，会不会明显误解暗苟现在的生活？

只有答案是：

```text
会
```

才值得进入 Current Cognition。

例如：

```text
今天吃了什么
× 不进

单次吐槽寝室
× 通常不进

连续几天寝室严重拖慢效率
✓ 可形成近期环境状态

今天改了一次 Memory
× 不进

连续几轮都在回头理解朝汐底层
✓ 可形成“近期项目重心转向工程理解与收口”

某场面试结束
× 结束就结束

秋招长时间缺少实质进展，并影响当前节奏
✓ 可以留
```

---

# 8. Current Cognition 不适合继续用“大文章精确文本 Patch”

当前更新方式：

```text
找到 narrative 中某一段原文
→ 替换
→ 其余保留
```

问题：

- 容易留下旧阶段化石；
- 删除和结束状态困难；
- narrative 越来越像滚雪球；
- 模型需要持续编辑一篇旧作文。

后续更适合：

```text
稳定 thread key
+ 独立 summary
+ upsert / remove
```

例如内部存：

```json
{
  "key": "zhaoxi_development",
  "summary": "最近在回头梳理 Memory、Planner 等底层机制，重心从继续堆功能转向理解和收口。",
  "last_updated": "...",
  "evidence": []
}
```

然后后台只做：

```text
UPSERT thread
REMOVE thread
UPDATE overview
ADD change
REMOVE stale change
```

Renderer 再把这些结构化块组合成“小日记”。

这样某条主线结束后：

```text
REMOVE thread
```

即可真正消失。

---

# 9. 建议重新确认 Current Cognition 的系统定位

四类信息应该严格分工：

```text
Current Cognition
→ 每轮常驻
→ 极短
→ 最近主线、状态、关注点
→ 朝汐自己的视角

Long-Term Memory
→ 按需召回
→ 大量长期事实、经历、关系、偏好

Conversation
→ 最近真实对话历史

Agenda / LifeHUD / Tool
→ 精确结构化事实
```

一句话定义：

> Current Cognition = 朝汐的易失性自我笔记。

可以理解为：

```text
“这是我此刻脑子里挂着的生活。”
```

而不是：

```text
“这是关于暗苟最近一周的分析报告。”
```

---

# 10. 当前几个系统问题背后的共同症状

这几类问题其实很像：

## Memory

```text
功能已经有了
但看不见它为什么召回
```

## Planner

```text
Runtime 很复杂
但前端只显示“第几轮正在思考”
```

## Current Cognition

```text
状态确实被维护了
但维护出来的东西不像朝汐自己的认知
```

共同问题可以概括为：

> **朝汐已经长出了不少内部机制，但“机制的语义”和“人能理解的表现”之间还没完全对齐。**

下一版本不一定应该继续扩能力。

更应该：

```text
解释
收口
显式化
减负
统一
```

---

# 11. 后续新版本的候选目标

暂不定版本号，继续收集问题。

未来可以考虑统一做成一轮：

```text
Runtime / Cognition Cleanup
```

候选目标：

### P0：先看清

- [ ] 全链路耗时统计；
- [ ] LLM 调用次数统计；
- [ ] Memory retrieval inspector；
- [ ] Planner trace 接 ActionTrace；
- [ ] Debug 页面可查看各模块内部决策。

### P1：砍固定延迟

- [ ] Router Local Fast Path；
- [ ] 简单请求跳过 Router LLM；
- [ ] AutoMemory 移出主响应关键路径；
- [ ] 检查 Current Cognition 维护是否也阻塞主回复；
- [ ] 检查 Decision / Planner / Workflow 的调用边界。

### P1：Current Cognition 重构

- [ ] 改为朝汐自己的认知视角；
- [ ] 禁止“用户”式第三方分析语气；
- [ ] narrative 瘦身；
- [ ] 从大文章 Patch 改为 thread / block 更新；
- [ ] 按近期主线、变化、挂起事项、注意点组织；
- [ ] 自动移除失效状态；
- [ ] 控制总长度；
- [ ] 保持“临时日记”而不是长期 Memory。

### P2：Memory 收口

- [ ] importance / activation 量表；
- [ ] COLD 召回策略；
- [ ] 清理死配置；
- [ ] FTS / 向量检索路线；
- [ ] semantic_score 命名与实现一致；
- [ ] 大规模 Memory 性能设计。

---

# 12. 暂时不要做的事

在正式开新版本前，先不要继续：

- 为每个小问题单独打补丁；
- 再增加新的 Memory 字段；
- 急着上真正 Embedding；
- 继续给 Current Cognition 堆 Prompt；
- 单独再做一套 Planner 前端；
- 为降低延迟盲目删功能；
- 在没有耗时统计前拍脑袋判断谁最慢。

先使用、观察、记录。

---

# 13. 后续继续补充区

后续发现的新问题直接继续加在这里。

建议记录格式：

```text
## 问题名

现象：
...

预期：
...

当前怀疑：
...

是否高频：
...

是否影响交互：
...

相关模块：
...
```

---

# 14. 当前阶段结论

这一批问题暂时不需要马上修。

目前最有价值的是继续正常使用朝汐，让问题继续自然暴露。

等积累到足够多后，再统一开新版本处理：

> **不是继续堆功能，而是把已经长出来的系统真正梳理成“看得懂、跑得快、像朝汐自己”的整体。**
