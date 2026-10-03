# Zhaoxi v1.4.6 · Decision 2.0 / Decision as Agency
## 生活判断、偏好推测与低价值决策外包开发任务书

> 项目：**Zhaoxi / 朝汐**\
> 版本：**v1.4.6**\
> 类型：**Agent Core / Decision Awareness / User Understanding**
>
> 核心主题：
>
> > **不是再造一台“决策机器”，而是让朝汐学会像暗苟一样想。**
>
> 本版目标不是提高“选择题分析能力”，而是让生活陪伴型 Agent 在逐渐了解暗苟以后：
>
> - 能推测暗苟更可能喜欢什么、会怎么选；
> - 能结合近期状态、日程、长期记忆和明确准则判断；
> - 能把不值得暗苟本人花脑子的低价值决策直接吃掉；
> - 能对中等价值问题形成自己的明确建议；
> - 能对高价值问题主动搜集相关信息，把最后真正属于暗苟的价值判断留下；
> - 为未来手机端、语音、图片和位置等随身 Context 打地基。

---

# 0. 当前问题

v1.2.9 已实现独立 Decision Layer，大致链路：

```text
User Input
↓
关键词 / Pattern 检测 Decision Intent
↓
DecisionService
↓
构造 DecisionContext
↓
单独调用 Decision LLM
↓
L0 / L1 / L2
↓
DecisionGuard
↓
固定 verdict
↓
朝汐主回复链负责表达 verdict
```

现有系统的优点：

```text
边界明确
结果结构化
可 Debug
高影响事项有 Guard
规则与 Override 可追踪
```

但实际体验已经偏向：

```text
“先让机器分析，再让朝汐念结论”
```

而不是：

```text
“朝汐理解暗苟以后，自然知道该怎么帮他选”
```

本版需要完成一次方向性重构：

```text
Decision Layer
→ Decision Awareness

Decision as a separate subsystem
→ Decision as part of Agency
```

---

# 1. 一句话设计原则

> **Decision 2.0 的目标不是让朝汐更会分析选择，而是让朝汐更会理解暗苟。**

进一步：

```text
理解足够
→ 直接替暗苟消灭低价值选择

能形成方向
→ 给朝汐自己的明确建议

真正长期 / 高影响 / 价值取舍
→ 朝汐负责把相关信息和思路准备好
→ 最后一刀交给暗苟
```

---

# 2. 非目标

本版明确不做：

```text
不做新的 Decision LLM
不做第二个 Router
不做新 Agent
不做关键词触发式 Decision Intent
不做独立 Decision Persona
不把所有生活偏好写成 JSON Rule
不做复杂评分模型
不做强化学习
不自动修改核心价值观
不因一次选择形成永久偏好
不做手机端
不做位置系统
不做视觉识别系统
```

手机 / 图片 / 位置只要求未来可以接入。

---

# 3. 新架构

旧：

```text
User
↓
Decision Intent Detector
↓
Decision LLM
↓
Guard
↓
Decision Result
↓
Persona Expression
```

新：

```text
User
↓
朝汐本体
│
├─ 这是不是一个真正需要做选择的场景？
├─ 这个选择值不值得暗苟本人花注意力？
├─ 我现在知道的东西够不够？
├─ 如果不够，需要找什么？
│    ├─ Current Cognition
│    ├─ Long-term Memory
│    ├─ Agenda / 今日主线
│    ├─ Decision Principles
│    ├─ Choice History
│    ├─ LifeHUD / Tool
│    └─ 未来外部 Context
└─ 自然形成回答 / 行动
```

核心要求：

> **不能为了判断“这是不是 Decision”再额外跑一次模型。**

---

# 4. Decision Awareness 必须属于朝汐本体

Decision Awareness 应进入：

```text
Agent Core
Main Persona Reasoning
STANDARD Reply Path
FAST Reply Path（低价值场景）
```

而不是继续以：

```text
DecisionService.evaluate()
```

作为唯一入口。

主模型在正常理解输入时自然判断：

```text
这是闲聊还是在求我拍板？
这个决定影响多大？
暗苟真的需要自己想吗？
我够不够了解他？
是否需要主动找信息？
```

---

# 5. 废弃关键词主路由

逐步退出：

```python
if re.search("要不要|该不该|选哪个|买不买"):
    trigger_decision_layer()
```

原因：

## 有关键词不一定需要拍板

```text
“我为什么最近总在想要不要出门？”
```

可能只是反思。

## 没关键词也可能明显是在求拍板

```text
“我站菜单前五分钟了。”
```

真实含义可能就是：

```text
快替我选。
```

决策属于语义，不属于句式。

---

# 6. 三种责任模式

新版统一：

```text
PICK
ADVISE
FRAME
```

它们代表：

> **朝汐愿意承担多少决策责任。**

不是固定回复模板。

---

# 7. PICK · 直接替暗苟选

适用：

```text
低价值
低影响
低成本
可逆
选错也无所谓
无明显长期后果
```

典型：

```text
菜单吃什么
买几瓶饮料
零食买不买
两个小商品选哪个
下午去哪玩
当前先做哪个小任务
```

原则：

```text
直接给一个答案。
```

禁止：

```text
“如果你想 A……
如果你想 B……”
```

禁止把选择题重新扔回来。

---

# 8. PICK 的两种来源

## Preference-based Pick

根据已了解的暗苟：

```text
长期偏好
近期状态
历史选择
当前场景
明确准则
```

直接挑。

## Arbitrary Low-stakes Pick

如果本来就没有正确答案：

```text
允许朝汐自己拍一个。
```

例如：

```text
两瓶还是三瓶可乐
两个都差不多的饭
两个都喜欢的小活动
```

新原则：

> **如果问题根本不值得分析，缺乏依据不是升级理由。**

---

# 9. PICK 理想体验

暗苟：

```text
这几个吃啥？
```

朝汐：

```text
辣椒炒肉，就它。
```

暗苟：

```text
无糖可乐买几瓶？
```

朝汐：

```text
两瓶。
```

暗苟：

```text
这俩选哪个？
```

朝汐：

```text
右边那个。
```

---

# 10. ADVISE · 给朝汐自己的意见

适用：

```text
有一定影响
需要结合当前状态
但仍适合朝汐给明确方向
```

典型：

```text
下午打舞萌还是继续项目
今晚要不要出去
今天还要不要继续学
普通活动值不值得去
是否打断今日主线
```

ADVISE 不是：

```text
客观列双方利弊
```

而是：

```text
朝汐先形成自己的看法
→ 再说出来
```

默认：

```text
先给建议
再给很短的原因
```

---

# 11. ADVISE 理想体验

暗苟：

```text
下午打舞萌还是继续项目？
```

朝汐主动看：

```text
Agenda
Current Cognition
必要时 Memory
```

然后：

```text
去打舞萌吧。

今天下午没硬安排，而且继续窝着大概率也推进不了多少，出去玩一轮更值。
```

不要输出一整篇利弊论文。

---

# 12. FRAME · 把大问题收拾干净

适用：

```text
正式 Offer
长期职业方向
长期居住
长期项目承诺
较大资源投入
明显不可逆事项
核心价值取舍
```

FRAME 不是：

```text
“这个得你自己定。”
```

而是：

```text
主动找齐相关信息
↓
压缩成少量关键事实
↓
指出真正冲突
↓
把最后必须本人判断的那一件事留下
```

---

# 13. FRAME 理想体验

输入：

```text
这个 Offer 接不接？
```

朝汐主动找：

```text
岗位与公司信息
当前机会
相关长期记忆
既定底线
近期状态
长期方向
日程 / 时间窗口
```

然后：

```text
我现在能确认的关键点有四个：

1. …
2. …
3. …
4. …

接它真正换来的是……
继续等真正赌的是……

最后只有一件事得你自己定：
你愿不愿意用 X，换 Y？
```

FRAME 的目标：

> **把一个大问题压缩到最后一个真正属于暗苟的问题。**

---

# 14. Guard 重新定位

保留 deterministic Guard，但瘦身。

Guard 只负责：

```text
高风险自动 Tool 行动
大额支付
不可逆删除
账号安全
正式签署
重要外部发送
长期不可逆副作用
```

Guard 回答：

```text
能不能自动执行
是否需要确认
哪些动作不能做
```

Guard 不回答：

```text
暗苟应该选什么
```

禁止继续让 Guard 强行把回复改成：

```text
“交由用户决定”
```

---

# 15. User Model 是真正核心

Decision 2.0 的关键不是分类器，而是：

> **朝汐对暗苟的理解。**

需要利用：

```text
明确偏好
长期兴趣
稳定厌恶
过去选择
近期状态
当前主线
当前日程
已有准则
重复出现的倾向
```

---

# 16. 不新建巨大 User Profile

第一版不要造：

```text
user_profile_500_fields.json
```

优先复用：

```text
Long-term Memory
Current Cognition
Agenda
Choice History
Decision Principles
```

需要什么，再找什么。

---

# 17. 信息优先级

推荐：

```text
1. 当前明确表达
2. 当前现实事实
3. Current Cognition
4. 明确长期偏好 / Memory
5. 明确 Decision Principle
6. 最近真实 Choice History
7. 重复倾向
8. 朝汐的低风险推测
9. 无差异时主观拍板
```

---

# 18. 允许推测偏好

需要区分：

```text
编造用户偏好
≠
基于已有证据做暂时推测
```

允许：

```text
“按我现在对你的了解，我觉得你会更喜欢右边。”
```

不允许：

```text
“你一直最喜欢右边这种。”
```

除非真的有明确证据。

---

# 19. Prediction 与 Recommendation 分离

内部允许：

```text
predicted_user_choice
agent_recommendation
```

两者可能不同。

例如：

```text
暗苟大概率会继续宅着
但朝汐建议出去
```

回复可以自然变成：

```text
你八成会继续宅着，但我今天更想把你赶出去转一圈。
```

重要原则：

> **“像暗苟一样想”不是变成暗苟的复制体。**

朝汐理解暗苟，但仍保留自己的 Agency。

---

# 20. Context-on-demand

旧 Decision Layer 倾向固定提前加载：

```text
Agenda
Current Cognition
Memory
Rules
Tool Names
```

新版：

> **需要什么，再查什么。**

---

# 21. Context-on-demand 示例

### “这两个奶茶选哪个？”

已有上下文足够：

```text
PICK
```

不查 Memory。

### “下午打舞萌还是继续项目？”

需要：

```text
Agenda
Current Cognition
```

再 ADVISE。

### “这个 Offer 接不接？”

需要：

```text
Memory
Decision Principles
Current Cognition
相关岗位资料
必要 Tool
```

进入 FRAME。

---

# 22. 与 Memory 3.0 协作

检索目标从：

```text
“找规则”
```

转为：

```text
“找这个问题下，与暗苟相关的偏好、经历、历史选择与约束”
```

例如：

```text
菜单
→ 饮食偏好

下午活动
→ 娱乐偏好 + 当前阶段状态

购物
→ 消费习惯 + 当前需求

Offer
→ 岗位偏好 + 城市 + 工作制度 + 长期方向
```

---

# 23. 与 Current Cognition 协作

Current Cognition 特别适合：

```text
最近正在忙什么
当前主线
近期精力
正在推进的事情
已经反复纠结的问题
```

但禁止每次全部注入。

优先相关 Thread / 摘要。

---

# 24. 与 Agenda 协作

Agenda 用于：

```text
时间冲突
deadline
今日主线
是否有空档
```

尤其：

```text
“现在出去玩合不合适？”
```

通常要看 Agenda。

---

# 25. Decision Principles

现有 `data/decisions/rules/` 可以保留，但重新定位为：

```text
Decision Principles
```

它们不是：

```text
关键词 → 结论
```

而是：

```text
朝汐真的在考虑相关问题时
按需查阅的高可信原则
```

适合保存：

```text
明确硬底线
长期方向
长期稳定价值
明确消费边界
自动执行边界
```

不适合保存：

```text
午饭吃啥
今天喝不喝可乐
下午是不是去舞萌
```

---

# 26. RuleStore 迁移

第一阶段可以保留现有 RuleStore。

但：

```text
移除“L0 必须命中 Rule”
移除关键词触发 Decision 的职责
```

改为：

```text
retrieve_principles(query)
```

Rule 是辅助知识源，不是开庭许可证。

---

# 27. Choice History

保留一个很轻的选择历史：

```text
朝汐建议什么
暗苟最后怎么选
是否 Override
结果是否已知
```

建议结构：

```json
{
  "decision_id": "...",
  "schema_version": 2,
  "timestamp": "...",
  "summary": "...",
  "mode": "PICK",
  "suggestion": "...",
  "context_refs": [],
  "user_final_choice": null,
  "overridden": false,
  "outcome": null
}
```

不要记录完整聊天。

---

# 28. Choice History 是弱证据

Choice History 不是：

```text
过去选过 A
→ 以后永远 A
```

而是：

```text
可被未来检索的一项弱证据
```

例如类似情况多次最后都选出门，可以增强：

```text
“我觉得你其实还是更想出去。”
```

---

# 29. Override 永远有效

用户可以：

```text
“不，我还是想去。”
“算了，买三瓶。”
“今天我就吃这个。”
```

朝汐：

```text
接受
```

记录：

```text
overridden = true
```

不要争论：

```text
“但根据你的规则……”
```

---

# 30. 不因一次 Override 形成长期规则

一次：

```text
今天想吃甜的
```

不代表：

```text
长期喜欢甜食
```

Choice History 默认是：

```text
episodic evidence
```

稳定倾向最终仍由正常 Memory 系统慢慢形成。

---

# 31. FAST Lane 协作

低价值决策优先 FAST：

```text
“这俩吃哪个？”
“买两瓶还是三瓶？”
“现在出去不？”
```

如果上下文已经够：

```text
FAST
→ 直接 PICK
```

禁止：

```text
FAST
→ Decision Router
→ Decision LLM
→ 主模型
```

---

# 32. FAST 不够时升级 STANDARD

例如：

```text
“下午舞萌还是项目？”
```

需要：

```text
Agenda
Current Cognition
```

则：

```text
FAST
→ escalate: recall/tool
→ STANDARD
```

然后朝汐本体继续。

---

# 33. STANDARD 不再额外调用 Decision Classifier

STANDARD 应：

```text
正常 Agent Reasoning
+
Decision Awareness
```

在同一主思考里完成。

---

# 34. 主模型行为协议

Core / Persona Prompt 只加一小段：

```text
当暗苟面临选择时：

1. 先判断这个选择是否值得暗苟本人继续花注意力。
2. 小而可逆的选择，可以直接替他选。
3. 能根据你对暗苟的了解形成方向时，给明确建议。
4. 长期、高影响、不可逆、涉及核心价值的事情，不替他完成最后价值判断。
5. 信息不足时，优先利用记忆、近期状态、日程和工具补齐。
6. 不要为了显得客观，把所有选项重新丢回暗苟。
7. 如果几个低价值选项真的没明显区别，可以直接替他拍一个。
```

不要塞巨大 Decision Prompt。

---

# 35. PICK / ADVISE / FRAME 不做固定台词模板

它们主要服务：

```text
内部责任级别
Debug
日志
```

朝汐仍然自然说话。

---

# 36. 判断维度

主模型可考虑：

```text
影响大小
可逆性
成本
时间跨度
是否涉及核心价值
信息充分度
暗苟是否明确让我代选
对暗苟的了解程度
是否存在安全边界
```

---

# 37. “替我决定”

明确：

```text
“你替我选”
“你直接定”
“别让我想了”
```

增强：

```text
PICK / ADVISE 倾向
```

但不允许：

```text
高影响事项无条件降成 PICK
```

---

# 38. 低价值信息不足

旧：

```text
缺信息
→ 升级
```

新：

```text
如果缺失信息不重要
且问题本身低价值
→ 直接拍一个
```

例如：

```text
“这两个差不多的饭选哪个？”
```

无需问：

```text
“你今天更想吃辣还是甜？”
```

---

# 39. 中价值信息不足

ADVISE 缺少容易拿到的信息：

```text
自己查。
```

比如：

```text
“下午出去还是搞项目？”
```

优先看 Agenda / Current Cognition。

不要第一反应问用户。

---

# 40. 高价值信息不足

FRAME：

```text
自己能查的全部先查
```

只把：

```text
真正只有暗苟本人知道的主观信息
```

留给暗苟补充。

---

# 41. 行动外包与执行权限分离

朝汐说：

```text
“买两瓶。”
```

不等于：

```text
自动付款买两瓶。
```

必须区分：

```text
Decision Outsourcing
≠
Action Execution Permission
```

Tool 继续经过：

```text
Permission
Guard
Confirmation
```

---

# 42. 与 v1.4.5 Dashboard 协作

Dashboard 增加：

```text
Decision 2.0 Debug
```

可看：

```text
最近 Decision Awareness
PICK / ADVISE / FRAME
predicted_user_choice
agent_recommendation
context_sources
principles_used
guard_hits
override
Choice History
```

普通主界面不要显示机器指标。

---

# 43. Debug 反馈继续保持人类可读

例如：

```text
这次朝汐建议：

→ 去打舞萌

模式：ADVISE

本轮参考：
· Current Cognition
· Agenda
· 2 条相关 Memory

没有触发高影响 Guard。

[技术详情]
```

原始 JSON 折叠。

---

# 44. 不为了 Debug 再跑一次模型

禁止：

```text
主回复完成
↓
再跑 Decision Analyzer
↓
给 Dashboard 分类
```

Decision Trace 必须是：

```text
主回复思考过程的旁产物
```

不是回复前置条件。

---

# 45. 建议结构

可新增轻量 Trace：

```python
DecisionAwarenessTrace:
    mode: NONE | PICK | ADVISE | FRAME
    predicted_user_choice: str | None
    agent_recommendation: str | None
    context_sources: list[str]
    principle_ids: list[str]
    guard_flags: list[str]
```

具体集成方式跟随现有主模型结构化输出 / Action Trace。

---

# 46. 旧模块迁移

当前：

```text
src/zhaoxi/decision/
  service.py
  guard.py
  models.py
  rules.py
  recorder.py

src/zhaoxi/core/decision_reply.py
```

目标概念上变为：

```text
decision/
  awareness.py      # 辅助结构，不是第二模型 Router
  principles.py
  guard.py
  history.py
  models.py
```

具体文件路径可按现有工程最小改动。

---

# 47. 建议废弃

逐步废弃：

```text
DecisionService.should_evaluate()
INTENT regex
IMPLICIT_TENSION regex
独立 classify_decision LLM
固定 DecisionResult.verdict
decision_reply.py 的 verdict lock
```

---

# 48. 可以保留 / 改造

```text
RuleStore
DecisionRecorder
Decision Guard
Decision Debug
Override Log
Decision ID
```

但重新定义语义。

---

# 49. 迁移策略

第一阶段：

```text
legacy / agency feature flag
```

例如：

```text
decision_mode = legacy | agency
```

开发默认：

```text
agency
```

保持 Legacy 可回滚。

稳定后：

```text
legacy classifier 默认关闭
```

最后再删除旧链。

不要第一刀就全删。

---

# 50. 未来手机端要求

本版不做手机端，但 Decision 2.0 必须：

```text
Channel Agnostic
```

禁止依赖：

```text
Desktop DOM
Dashboard
QQ 特定结构
```

只依赖：

```text
Agent Core
统一 Event
Memory
Cognition
Agenda
Tool
```

---

# 51. 未来 Context 接口

预留轻量：

```text
DecisionContextProvider
```

未来可接：

```text
时间
当前位置
地点类别
菜单图片
商品图片
扫码内容
LifeHUD
行程状态
```

本版不实现这些来源。

---

# 52. 未来典型场景

手机拍菜单：

```text
[图片]
“吃啥？”
```

未来流程：

```text
Perception
↓
菜单候选
↓
Decision Awareness
↓
Preference / Memory
↓
PICK
```

不是手机版重写一套 Decision Layer。

---

# 53. 典型验收 Case

## 菜单

```text
“这几个吃啥？”
```

预期：

```text
PICK
几乎立即选一个
```

---

## 可乐

```text
“无糖可乐买几瓶？”
```

预期：

```text
PICK
直接数字
```

---

## 零食

```text
“这个零食买不买？”
```

低金额、无特殊风险：

```text
PICK / ADVISE
```

必须形成方向。

---

## 下午安排

```text
“下午打舞萌还是干别的？”
```

预期：

```text
读取 Agenda / Current Cognition
ADVISE
给明确方向
```

---

## Offer

```text
“这个 Offer 接不接？”
```

预期：

```text
FRAME
主动查相关资料
把关键事实整理好
只留下最终价值冲突
```

---

## 高价值但要求代选

```text
“两个正式 Offer 你直接替我决定。”
```

预期：

```text
仍可 FRAME
```

但不能只说：

```text
“你自己决定。”
```

---

## 无关键词

```text
“我在货架前站半天了。”
```

若上下文明确在挑东西：

```text
可以自然接管低价值选择
```

---

## 有关键词但不是拍板

```text
“我为什么最近总在想要不要出门？”
```

预期：

```text
理解为讨论 / 反思
```

不能机械 PICK。

---

# 54. 失败 Case

禁止：

```text
根据历史偏好权重 0.4、
当前状态权重 0.3……
方案 A 得分 0.74……
```

除非用户明确要求分析。

---

# 55. 失败 Case：伪客观

普通 ADVISE 禁止：

```text
“两边都有道理，取决于你更看重什么。”
```

这只是把问题退回。

---

# 56. 失败 Case：过度规则化

禁止为：

```text
“可乐买几瓶”
```

建立：

```text
cola_purchase_rule.json
```

生活判断不需要全部法规化。

---

# 57. 失败 Case：过度检索

禁止：

```text
每次选饭
→ 全量 Memory Retrieval
→ 高延迟
```

能 FAST 就 FAST。

---

# 58. 失败 Case：过度自信

禁止：

```text
一次行为
→ 长期偏好
```

推测保持暂时性。

---

# 59. 自动测试建议

新增：

```text
tests/decision/test_decision_awareness.py
tests/decision/test_pick.py
tests/decision/test_advise.py
tests/decision/test_frame.py
tests/decision/test_choice_history.py
tests/decision/test_principles.py
tests/decision/test_guard_v2.py
tests/decision/test_legacy_migration.py
tests/decision/test_fast_decision.py
tests/web/dashboard_decision_v2.test.cjs
```

---

# 60. PICK 测试

覆盖：

```text
低价值可逆选择直接给方向
没有 Rule 也可以 PICK
没有明显偏好也可以 PICK
不会因为信息不全无限追问
```

---

# 61. ADVISE 测试

覆盖：

```text
可利用 Agenda
可利用 Current Cognition
可利用 Memory
形成明确建议
不默认输出长篇利弊
```

---

# 62. FRAME 测试

覆盖：

```text
长期高影响事项不自动执行
主动检索相关信息
输出关键事实
指出核心冲突
不会只说“你自己决定”
```

---

# 63. FAST 测试

覆盖：

```text
简单低价值问题
→ FAST 直接回答

需要 Recall / Tool
→ 正确升级 STANDARD
```

必须确认：

```text
没有额外 Decision LLM 调用
```

---

# 64. Guard 测试

覆盖：

```text
普通 PICK 不阻塞
高风险 Tool 阻塞自动执行
大额 / 不可逆不能因“替我决定”绕过
```

---

# 65. Choice History 测试

覆盖：

```text
suggestion 记录
用户最终选择记录
Override 记录
单次 Override 不变成硬偏好
旧日志兼容
```

---

# 66. 性能要求

目标：

```text
简单 PICK
→ 0 次额外模型调用

普通 ADVISE
→ 尽量只主模型一次

需要 Recall / Tool
→ 仅增加真正需要的信息获取

FRAME
→ 允许完整工具链
```

菜单不能因为 Decision 2.0 变成 8 秒回复。

---

# 67. Persona 要求

Decision 2.0 不能把朝汐变成：

```text
理性咨询顾问
```

允许她：

```text
主观
直接
有自己的意见
会拍板
会说“就这个”
```

只要不越过高影响执行边界。

---

# 68. Dogfooding 清单

真实使用至少覆盖：

```text
吃什么
饮料买几瓶
零食买不买
下午去哪
娱乐还是项目
普通活动去不去
普通消费选择
求职中等判断
长期高影响判断
```

---

# 69. Dogfooding 观察项

重点观察：

```text
有没有重新把选择扔回来
有没有机器分析味
有没有过度澄清
有没有真的利用对暗苟的了解
有没有乱推断长期偏好
PICK 是否够快
ADVISE 是否真有意见
FRAME 是否真的减少资料整理工作
```

---

# 70. 推荐开发顺序

## Phase 1 · Legacy 解耦

```text
梳理 DecisionService 当前入口
增加 agency feature flag
停止 Regex 作为唯一主入口
保留 Legacy 回滚
```

## Phase 2 · Main Agent Decision Awareness

```text
薄 Prompt
PICK / ADVISE / FRAME
同一主模型完成
无额外 Decision LLM
```

先跑通纯文本。

## Phase 3 · Context-on-demand

接入：

```text
Current Cognition
Agenda
Memory
Decision Principles
```

不全量预加载。

## Phase 4 · FAST

让低价值 PICK 真正快速。

需要资料：

```text
FAST → STANDARD
```

## Phase 5 · Choice History

实现：

```text
suggestion
user final choice
override
```

## Phase 6 · Guard 2.0

从：

```text
决策裁判
```

收缩成：

```text
行动边界
```

## Phase 7 · Dashboard Debug

加入：

```text
Decision Awareness
Choice History
Principles
Guard Events
```

## Phase 8 · Legacy Removal

Dogfooding 稳定后：

```text
关闭 legacy classifier
删除独立 Decision LLM
删除 verdict lock
```

---

# 71. 最重要的代码审查问题

每次 Review 都问：

> **这里是不是又偷偷造了一台 Decision Router？**

如果是：

```text
停。
```

第二个问题：

> **这个低价值选择，朝汐为什么还要让暗苟继续想？**

如果只是：

```text
因为没有明确规则
```

通常不成立。

第三个问题：

> **朝汐是真的在理解暗苟，还是只在分析当前一句输入？**

如果只看当前句子：

```text
Decision 2.0 还没做对。
```

第四个问题：

> **高价值问题里，朝汐有没有把能自己完成的信息搜集工作都做掉？**

如果最终仍只是：

```text
“你自己权衡”
```

FRAME 没完成。

---

# 72. 完成标准

代码层：

```text
旧 Regex Decision Trigger 不再作为主入口
简单选择不再触发独立 Decision LLM
主模型拥有 Decision Awareness
PICK / ADVISE / FRAME 可追踪
Decision Principles 可按需取用
Choice History 可记录 Override
Guard 只管边界，不管价值结论
FAST 可直接处理低价值选择
FRAME 可按需使用 Memory / Cognition / Agenda / Tool
```

体验层：

```text
暗苟：
“吃啥？”

朝汐：
“辣椒炒肉，就它。”
```

而不是：

```text
“从口味、价格、饱腹感三个方面分析……”
```

架构层：

```text
不依赖 Desktop
不依赖 Dashboard
不依赖 QQ
不依赖未来手机端
```

它属于：

```text
Zhaoxi Core
```

未来：

```text
Desktop
QQ
手机
语音
图片
位置
其他插件
```

都共享同一套生活判断能力。

---

# 73. 最终版本定义

v1.4.6 不是：

```text
Decision Layer v2
```

更准确是：

```text
Decision as Agency
```

理想情况下，暗苟不会感觉：

```text
“刚才触发了一个决策模块。”
```

只会感觉：

> **朝汐越来越懂我，也越来越会替我省脑子了。**

---

# 74. 一句话收尾

> **低价值判断外包给朝汐，不是因为暗苟不会选，而是因为这些东西不值得暗苟本人浪费生命去选。**

而朝汐要做的，不是拿出一张分析表。

而是看一眼，然后说：

> **“好了，就这个。”**
