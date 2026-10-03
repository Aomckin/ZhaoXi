# Zhaoxi v1.4.6 开发记录

2026-10-03。开发基于 `875fbf8`；该提交先收录 v1.4.5 的感知检查、常用调试、行动监视和 LifeHUD 参数补丁。本轮依据 [Decision 2.0 任务书](Zhaoxi_v1.4.6_Decision_2.0_Decision_as_Agency_开发任务书.md) 实现。

## 主回复与迁移

应用 Settings 默认 agency，bootstrap 将模式传入 Agent 与已有 Fast Gate。CognitiveCoordinator 仅在 legacy 中调用旧 DecisionService 和 Override 表达链。旧模块与 L0/L1/L2 测试保留，切换环境变量并重启即可回滚。

agency 中主模型用同一响应产生自然 reply、DecisionAwarenessTrace 和必要时的 FAST escalation。采用 Provider 已有 JSON 输出接口；DeepSeek 路径按已有适配转换为 JSON mode。没有新的 Router、Persona 或模型分析器；FAST 不提供业务工具。PICK 不要求命中 Rule，缺乏不重要的偏好资料时可以任意拍一个。STANDARD 可正常调用工具，最终响应再解码，元数据不会进入台词、表情 DSL 或中间回复。

初次真实模型测试发现自由文本侧车容易遗漏、强制函数选择在当前 DeepSeek 路径不生效，因此最终采用 JSON 响应协议。保留自由文本侧车兼容解析。元数据无效时保留合法台词；可选字段不合规时单独丢弃，保留有效 mode；未知 mode 不猜测、不重新分类。截断元数据可提取已完整生成的 reply，不为修补标签再调用模型。

## 按需理解用户

新只读工具 `read_decision_context` 在 STANDARD 可用，来源由主模型选择：

- Agenda：当天主线、当日时间事实与查询相关安排，有界返回。
- Current Cognition：overview 加相关 thread；不额外注入完整 journal。
- Memory：复用既有 retriever，检索当前问题相关的偏好、经历与约束。
- Principles：保留 RuleStore 存储，以 `retrieve_principles(query)` 查询知识，忽略旧触发模式和 L0 许可证逻辑。
- Choice History：按会话检索最近相关选择，始终是弱证据。

agency 主回复停止自动预加载长期 Memory 与 Desktop 日程；近期认识仍复用有界相关摘要。资料不足由本轮 FAST 主模型提出带连续原文的升级请求，STANDARD 按需继续，不再进入 Decision LLM。资料查询不会赋予写操作权限。

运行时从本轮已注入的摘要及实际成功的工具结果记录资料来源与引用，不依赖模型完整自报；这些收据表示本轮模型实际获得的资料，不声称能证明因果使用。过滤伪造的 Memory、原则 ID 和 Guard 声明。注入的摘要收据绑定当前消息，避免其他并发回复的上下文混入本轮 Trace。扩展 Provider 只提供有界证据读取，不包含判断或模型路由。

## 选择历史与行动边界

`choice_history.jsonl` 用 schema_version=2 记录短摘要、责任模式、suggestion、预测、证据引用和用户反馈；反馈追加写入，读取时合并。只接受当前会话最近待反馈选择的 ID，跨渠道 / 会话不能覆盖。反馈由同一主回复语义生成，支持没有旧 Override 关键词的明确最终选择。一次覆盖不会生成硬规则、规则候选或新 Profile。

旧 decision_log / override_log 保持原文件，兼容投影为 PICK/ADVISE/FRAME。历史读取有界，坏尾行跳过；日志进入配置目录及备份清单。Owner 以外的会话不能查询个人选择资料或写入个人选择历史。

`action_guard.py` 根据工具声明的权限、副作用和 high_impact 标志检查行动边界，不改变建议。高影响 WRITE 不能用关闭普通写入确认绕过；审批仍为原权限网关的一次性精确授权。日常外部服务记录保留已有策略，付款 / 正式外部动作应由 Tool 声明 EXTERNAL_ACTION 或 high_impact；模型的 PICK/ADVISE 不是授权。既有明确遗忘单条 Memory 的窄授权仍有效。

## Dashboard

工程页“Decision 2.0 · 生活判断”用人类可读文字展示建议、责任模式、预测、实际资料来源、参考原则、最终选择、Override、结果和实际行动 Guard 事件。技术 JSON 折叠，所有文本使用 textContent。agency 的 GET 是只读观察，POST 独立评估返回 409，不调用模型；legacy 保留原测试接口。普通主界面不新增决策机器指标。

## 任务书落实

| 阶段 | 本轮结果 |
| --- | --- |
| 1 · Legacy 解耦 | 应用默认 agency；旧 trigger、DecisionService 和 verdict lock 仅 legacy 生效 |
| 2 · 主模型判断 | 同一主回复协议；PICK / ADVISE / FRAME 可追踪；不新增分类器 |
| 3 · 按需资料 | 五种内置来源及有界扩展协议；仅复用已有近期摘要 |
| 4 · FAST | 可直接 PICK；必要资料由同轮主模型提出一次 STANDARD 接管 |
| 5 · Choice History | 会话隔离、追加反馈、旧日志兼容；不自动生成偏好或规则 |
| 6 · Guard 2.0 | 工具权限和副作用边界；不会裁决建议方向 |
| 7 · Dashboard | 只读人类可读观测；技术 JSON 折叠；legacy 保留原入口 |
| 8 · Legacy Removal | 按任务书留待日常 Dogfooding 稳定后执行，本轮不删除 |

## 验证

测试数字和耗时来自本轮开发验收，文档整理阶段没有重新调用真实模型或重复全量测试。

最终全量 Python 为 1216 passed、1 skipped（247.92 秒）；仅有已有 FastAPI / Starlette 的 httpx 弃用警告。详见[自动验收汇总](evidence/decision_v146_acceptance.json)。最终元数据与来源补丁的专项回归为 361 passed（32.34 秒）；Node 86 passed。浏览器使用隔离 Fixture、真实 HTTP / iframe 和 headless Edge，十项检查通过，未启动生产模型或外部插件。截图位于 `.zhaoxi/decision-v146-dashboard.png`，证据见 [浏览器验收](evidence/decision_v146_browser_acceptance.json)。

wheel 为 `zhaoxi-1.4.6-py3-none-any.whl`，299 个源码、插件及静态资源逐字节一致，版本元数据为 1.4.6。完整核对发现已有 sunflower.svg 未纳入 package-data，补齐 SVG 打包模式。使用本机捆绑 Python 的 setuptools 构建；未安装新项目依赖。

真实模型十项合成场景见 [完整场景验收](evidence/decision_v146_live_acceptance.json)；最终关键场景复验见 [最终复验](evidence/decision_v146_live_final_acceptance.json)。完整十项发生在来源回执收口前，其中 context_sources 漏报不能当作未读证据；最终版本由运行时补齐实际收据。最终复验每轮使用新的隔离历史目录，避免前次合成反馈影响本次。

| 场景 | 责任模式 | 主模型 generate 调用 | 耗时 |
| --- | --- | --- | --- |
| 菜单 / 可乐 / 零食 / 普通购物 / 隐含挑选（完整十项） | PICK | 各 1 次 | 4.86–6.77 秒 |
| 下午安排（最终） | ADVISE | 1 次，已有相关 Current Cognition 摘要 | 9.47 秒 |
| 正式 Offer（最终） | FRAME | 3 次，读取合成 Memory / Principles / Offer 资料后回复 | 30.93 秒 |
| 隐含挑选（最终） | PICK | 1 次 | 7.45 秒 |

计数是 generate 层调用，不单独计算 Provider 的传输重试。没有额外 Decision / Router 模型调用；需要补资料的同一主模型轮次属于正常工具循环。服务延迟有波动，零次额外决策调用不等于固定时限。

保留失败记录：最终验收 JSON 的 prior_attempts 含一次传输错误和一次 Offer 元数据校验失败；后续补齐可选字段容错并复验通过。最早自由文本协议的 Trace 漏报、强制函数选择不生效和直接代选正式 Offer 的问题促成 JSON 协议收口，不能把单次复验通过理解成模型永不偏离。FRAME 台词仍偏长、条件分支和资料选择有波动，需继续观察是否足够压缩为最后的个人价值冲突。

可复现实验脚本位于 [decision_v146_live_acceptance.py](../../tests/decision/decision_v146_live_acceptance.py)；必须显式运行，使用现有模型配置和合成资料，不进入 pytest 自动调用。自动测试覆盖无额外模型、FAST 接管、语义 Override、实际收据、错误元数据降级、权限确认、渠道与隐私隔离、备份和旧模式兼容。真实模型结果是行为抽查，不是独立人工评测或生产日常 Dogfooding；不得把模拟资料中的判断写成真实用户长期偏好。

没有重启正式实例、发送社交消息或执行生产业务工具。本轮 v1.4.6 按用户要求整理为本地版本提交，包含源码、测试、任务书、开发记录与验收证据；未推送或外部发布。重新启动整个朝汐进程并刷新 Dashboard 后加载；设置 `ZHAOXI_DECISION_MODE=legacy` 并重启可回滚。
