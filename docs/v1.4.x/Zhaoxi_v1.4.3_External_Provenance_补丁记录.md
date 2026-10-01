# v1.4.3 External Provenance Integrity 补丁记录

2026-10-01。补丁继续使用版本 `1.4.3`，修复外部信息进入统一认知后来源被 Role.USER 隐去的问题。身份、来源、会话分开处理。当前是源码补丁与自动验收结果；本轮未重启桌面加载本补丁，真实 NapCat 黑盒验收未完成。

## 图中八条复核

| 项目 | 实现与验收 |
| --- | --- |
| Phase 2 顺序与双轨 | 新 render 进入模型；旧关键词渲染仅作为 `legacy_shadow` 进 Debug。合成 Case A–J 保存旧/新完整文字快照，并断言正文、Role、跨上下文状态和图片 scope。生产分支已退出关键词驱动；诊断副本保留。 |
| unknown 分支 | `context_relation` 三态。空字符串归一为未知；没有已知差异但存在单边缺失时为 unknown，不触发 cross_context。跨渠道已有明确差异时仍为 cross。 |
| 来源真相层 | 按 event_id 优先回查 ExperienceStream，查不到才使用 provenance_snapshot。修正真相层后，来源和身份覆盖过期投影；事件消失后仍可降级渲染。旧 flat 字段仅兼容已有读者。 |
| 确定性认知来源规则 | Owner + cross 保留来源，same 可省略；未知不猜测。Current Cognition 的 overview、threads、changes、watch 保存证据，模型摘要渲染器执行规则。后台维护入队也保留 provenance。 |
| source_plugin 边界 | 已知插件不同即跨上下文；未知插件按 unknown 处理。同源组头、群聊压缩和后台合批计入插件；旧图缓存也按插件隔离。 |
| 图片 Prompt scope | Provider 可见正文含结构化 ImageProvenance；current_trigger 与 recent / attention 分开。追问复用旧图时，文字保持 current_trigger，图片保持 recent，并回查原事件来源与时间。 |
| 标签体积 | 连续同渠道、会话、类型、插件、timeline_scope 共享一个来源头；身份切换保留短发言者标识。图片 scope 逐图保留。完整 golden prompt 验证标签不重复刷；来源内标记从回复清理，避免回显。 |
| Case E 前置 | 群 A → 群 B 的基础用例放在 Provenance Contract 的 Phase 1 门槛；同 channel 的不同 session / conversation 和私聊 → 群聊单独测试。 |

## 实现范围

统一 helper 位于 `src/zhaoxi/cognitive_stream/provenance.py`。ContextBuilder、FAST、外部 Planner / Standard Reply 和 Attention 使用统一来源。Owner 外部消息仍是 USER，第三方与群聊摘要仍是 EXTERNAL。Session 与 ExperienceStream 保留原文，来源标签只在 Context 副本渲染。

Current Cognition 的来源保存在 EvidenceRef，包括 overview。AutoMemory 的原子提取、旧决策兼容路径和去重/更新保留 evidence_provenance。跨插件后台输入分别合批。Debug 来源检查器提供角色、完整来源、context_relation、timeline_scope、图片原事件以及新旧文本；空结果和失败提示使用安全文字展示。

补丁不增加依赖，不迁移或重建业务数据库，不重建百炼向量。测试使用隔离数据库；根目录不新增 pytest 临时目录，产物仍在 `.zhaoxi/`。

## 验证

- 相关模块的最后一次针对性检查：74 passed，包括 Current Cognition 的确定性来源投影和 Case A–J 完整文字对比。
- 完整 Python 回归：939 passed、1 skipped；178.22 秒，保留既有 FastAPI / Starlette 依赖弃用警告。
- Web Node：59 passed。来源 Inspector 的空结果、错误、未知状态、插件、图片 scope、新旧投影及 HTML 文本转义均覆盖。
- 内联 JavaScript：`node --check` 通过。
- 真实 Perception → Planner → Agent → QQ 回复事件 → Desktop Context 的隔离测试：私聊和群聊通过；使用合成输入与 fake provider，不通过真实 QQ 发送。
- 图片相邻追问、过期快照、Actor 修正、维护队列来源和插件隔离已自动验证。

Case A–J 的合成新旧文本位于 [golden 快照](../../tests/fixtures/provenance_cases_v143.json)，测试入口为 [来源契约测试](../../tests/cognitive_stream/test_provenance.py)与[外部程序链路测试](../../tests/perception/test_external_provenance.py)。本地完整日志：`.zhaoxi/provenance-full-final.log`、`.zhaoxi/provenance-final-focused.log`、`.zhaoxi/provenance-node-tests.log`。

## 待实机验收

真实 NapCat 私聊、测试群及 Desktop 连续切换仍未验证；已向用户请求测试环境，未把隔离程序测试冒充实机验收。桌面加载新代码后，从私聊与群各发合成文本，切回 Desktop 查看来源 Inspector；测试当前图片和群历史图片。确认模型回复归属正确、未知不会刷跨上下文标签、同源标签不重复。QQ 实机发送需用户操作或明确授权。

Memory 3.0 原有独立人工相关性标注、原生视觉验收与 Dogfooding 的边界仍见原版发布说明，本补丁不宣称完成这些项目。

## 后续群聊追溯补缺

同日增加[群聊证据回查补丁](Zhaoxi_v1.4.3_群聊证据回查_补丁记录.md)：逐句摘要引用、原消息 READ 工具、历史图片模型输入、引用保护、连发边界和 Debug 分页。此后群聊受限回复可调用同群证据回查工具，其他本地工具边界保留。上方测试数字是本来源补丁历史结果，最新结果见后续记录。
