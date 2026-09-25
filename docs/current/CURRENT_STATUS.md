# 当前状态与使用说明

2026-09-25：代码已接入 v1.2.8 Internal Activity。后台按候选信号、间隔、优先级与每轮预算调度 Current Cognition 整理、长期 Memory 维护、Agenda 时间状态维护和主动检查；状态与最近结果写入 `.zhaoxi/internal-activity.db`，维护抽屉可查看和手动触发。小桌边将近期状态标为「Current Cognition」，自动刷新；头像按活跃、半活跃、闲置/离开状态切换。Debug 可临时强制活跃、半活跃或离开，再次点击恢复自动判断。运行时包版本仍为 `1.2.7`，v1.2.9 Decision Layer 尚未实施。验证及剩余人工验收见 [v1.2.8 交付记录](../v1.2.x/Zhaoxi_v1.2.8_Internal_Activity_交付记录.md)。

以下是按时间保留的历史状态；涉及 STM 的描述仅对应当时版本。

2026-09-24 v1.2.7.1：请求预算增加受控的两次 Planner 扩容、Hard Limit 与收尾保留额度；逐轮记录实际 Provider payload 的 Context 构成估算，并在维护抽屉新增 Budget / Context Debug。旧成功 Tool Result 仅在模型上下文副本中压缩，最终回复不再携带 Tool Schema。合成数据实机验收已验证一次扩容、多 Tool 收尾及 STM/Agenda/长期 Memory 连续性；中文 Planner 测试仍出现重复工具调用和过短回复。详见 [v1.2.7.1 交付记录](../v1.2.x/Zhaoxi_v1.2.7.1_Budget_Context_Tuning_Report.md)。

2026-09-24 v1.2.6 完成后端与前端调整：Working Notes 便签领域模型和 `notes_*` 工具已退出运行时，改为结构化、跨重启的滚动 Short-Term Memory；后台 Maintainer 在主回复后按需提交 Patch，STM 每轮常驻 Context。旧 `working-notes.db` 只作历史备份。小桌边现在用日期时间线展示 Agenda、用单张纸页展示 STM；桌面入口避开窗口栏。Debug 可查看 STM 状态、Snapshot、最后处理消息和最近 Patch。详见 [v1.2.6 交付与验收](../v1.2.x/Zhaoxi_v1.2.6_Release_Notes.md)。

2026-09-23 v1.2.7：Chat、重新生成及权限续执行接入请求级 Agent Event，Web 复用现有 SSE 展示行动轨迹与安全 Debug 信息。Tool 调用通过 `tool_call_id` 和 `invocation_id` 对账；参数校验失败后的同名修复会将旧尝试标记为 superseded，成功写入各自保留独立记录。Recovery 读取最终动作状态，区分已完成、仍失败、结果未知；Token 预算耗尽和 Provider HTTP 错误各有明确错误码及文案。Life HUD Sensor 和 Heartbeat 的异常日志补齐阶段、用时及错误类型。详见 [v1.2.7 发布说明](../v1.2.x/Zhaoxi_v1.2.7_Release_Notes.md)。

2026-09-22 v1.2.6 初版曾提供 Agenda 与 Working Notes 的只读纸条栏位和独立开关；这是已被 2026-09-24 调整取代的历史状态。原始任务书保留供需求溯源，不应据此判断当前运行时。

同日 Tool Transcript 补丁：能力目录检查与钥匙组加载改走本轮内部 Context，不再伪装成正式业务 Tool 回执，避免文本工具协议在连续发现后触发 provider HTTP 400；Agenda 等实际业务工具的标准回执保持不变。

2026-09-22 v1.2.5：表情发送退出 Tool 系统，改为 Reply DSL。Replyer 使用 `[emoji:属性1,属性2]` 生成完整回复，Core 统一解析、按属性匹配本地资源，并将文本/表情段按原顺序持久化和输出；`save_emoji`、表情柜和旧 emoji 历史继续兼容。详见 [v1.2.5 发布说明](../v1.2.x/Zhaoxi_v1.2.5_Release_Notes.md)。

2026-09-21 v1.2.4.2：完成表情发送全链路稳定性审计。CognitiveRouter 使用运行时 Tool Manifest 和 `requires_tool_call / required_tool` 契约；Agent 对明确副作用请求使用强制 Tool Choice；独立图片消息统一经过持久化、Gateway 消息模型与前端 `renderMessage()`。Debug 可区分 Core/前端版本并查看最近 Emoji Trace。详见 [v1.2.4.2 审计报告](../v1.2.x/Zhaoxi_v1.2.4.2_Emoji_Send_Stability_Audit_Report.md)。

2026-09-17 v1.2.4.1：新增 EmojiManager 和 `save_emoji`，用户明确提出收藏时可把当前会话图片连同模型生成的表达语义入库；文件、去重、Registry 原子写入与 Reload 全部由 Manager 统一处理。小桌边新增表情柜，支持搜索、详情编辑、启停、删除、批量导入 Pending、视觉识别和逐张确认。详见 [v1.2.4.1 报告](../v1.2.x/Zhaoxi_v1.2.4.1_Release_Notes.md)。

2026-09-17 v1.2.4：新增本地表情表达层。`data/emoji/emoji_registry.json` 维护语义注册表，`send_emoji` 只接收表达 intent，由 EmojiService 完成校验、检索、阈值拒绝和防连续重复；命中后作为独立 assistant image message 持久化。Web 已在组件层区分纯图片与气泡消息，纯图片/GIF/多图不再使用默认文字气泡，文字加图片保持原样。Debug 支持运行时启停、Reload Registry 和 intent 测试。详见 [v1.2.4 报告](../v1.2.x/Zhaoxi_v1.2.4_Release_Notes.md)。

2026-09-14 v1.2.3：新增轻量 Semantic Capability Routing。自然语言中的饮食、睡眠、任务、FocusSession、生活状态、历史表达和本地复盘查找可在模型调用前预挂对应 Tool Group；普通生活陈述不触发查询。Diagnostics 新增 `semantic_route_matched`、`semantic_route_groups`、`semantic_route_reason`。未命中仍沿用 v1.2.2 Discovery。详见 [v1.2.3 报告](../v1.2.x/Zhaoxi_v1.2.3_Release_Notes.md)。

同日时间语义修复：普通对话正文不再注入逐条 timestamp header；仅在明确需要时注入独立 Temporal Context，并把聊天时间限制为离散 observation。Memory 区分 event/recorded/known/source，禁止从导入时间推断事件或朝汐 presence；Session v2 会迁移并持续清理已泄漏的 assistant 内部时间头。

人格表达同步修复：few-shot 以措辞、态度、关系感、调侃和判断为主要角色载体，舞台描写改为低频情绪强调；技术与 Agent 工作示例完全不使用动作。旧 assistant 历史中的连续模板动作只在模型上下文副本中轻量收敛，不修改用户可见记录。

回复重新生成：模型失败等可重试错误旁提供 `🔄`；正常朝汐回复默认不显示，需在维护抽屉的 Debug 区临时开启。它会沿独立重试 API 重新执行对应用户请求并替换回复，不走“戳一戳”主动消息链路。旧回复、主动消息及待确认操作不会被误重放，重试失败保留原会话。

维护抽屉已将“钥匙柜”和“Debug”拆开。钥匙名称与用途改为精简中文，内部 ID 仅作为辅助信息；可写钥匙可独立设置“写入前确认”，默认开启，关闭也不会越过全局拒绝或更高风险权限。Filesystem 的读取目录与修改目录分别配置，修改目录必须属于读取目录，写工具执行前还有 Core 侧路径校验。保存后重启 Core 生效。`job_application_tool` 已从当前工具包集合移除，独立的 ResumeBridge 与 form-pilot 保留。

2026-09-13 v1.2.2：修复 v1.1.9 遗留的广记描述与动态能力发现问题。三把 Memory Core 与目录/发现两把钥匙默认常驻；统一 Manifest、能力解析及按轮加载，最多两次扩展；Debug 可实时启停、Force Expose 和恢复默认，override 持久化。记忆新增与更新默认允许，不再显示 WRITE 确认；明确禁止记忆时仍不写入。详见 [v1.2.2 报告](../v1.2.x/Zhaoxi_v1.2.2_Release_Notes.md)。

2026-09-13 v1.2.1：单窗口 MAIN / COMPANION、原生八向缩放、独立 geometry、一次性置顶与临时通知。陪伴模式按用户要求移除头像抬头，输入栏仅保留文字和发送。浏览器 UI 默认关闭，开发可设置 `ZHAOXI_DEV_BROWSER_UI=true`。完整实现与验收边界见 [v1.2.1 报告](../v1.2.x/Zhaoxi_v1.2.1_Release_Notes.md)。

以下保留 v1.2.0 阶段记录。

2026-09-12 Phase 3：已使用 `data/ACTIVE头像.png` 的专用头像；小桌边在所有窗口尺寸下默认收起，通过右侧把手打开。系统消息、设置、维护抽屉位于公告栏下方；新的主动留言点亮金点，不自动展开，可见后沿用现有 activate 接口确认已读。最新布局及验收见 [Phase 3 报告](../v1.2.x/Zhaoxi_v1.2.0_Phase3_Release_Notes.md)。

窗口、托盘、网页和快捷方式已统一为向日葵图标。运行中的图标需彻底退出托盘后重启加载；项目快捷方式由 `scripts/create_desktop_launcher.ps1` 生成，使用 `sunflower.ico`。

阶段记录：[Phase 1](../v1.2.x/Zhaoxi_v1.2.0_Release_Notes.md) / [Phase 2](../v1.2.x/Zhaoxi_v1.2.0_Phase2_Release_Notes.md)。当前行为以 Phase 3 和本页为准。

## v1.1.x 业务与设置基线

本节保留截至 2026-09-10 的业务基线；上方视觉状态更新于 2026-09-12。旧版本报告中的测试数字、预算和未完成事项属于当时记录；当前行为以本页及代码为准。原始开发任务书保留，不改写为验收报告。

## 动态 ToolProvider 与 MCP

Core SDK 1.1 新增协议无关的 `ToolProviderProtocol`。Provider 产生的每个 Tool 独立进入现有 Registry；Agent、Planner、Workflow 不感知来源。Registry 支持运行时原子刷新，并在 CLI/Web 退出时统一关闭 Provider。

MCP 实现只存在于 `tools/mcp/`：stdio JSON-RPC Client、Server 进程生命周期、MCP inputSchema 校验与 Zhaoxi Tool Schema 适配、MCP annotations 权限映射均不进入 Core。当前本机安装 9 个 Server，合计发现 78 个 Tool。

默认不启用。启用全部或部分 Server：

```dotenv
ZHAOXI_TOOL_MCP_ENABLED=true
ZHAOXI_TOOL_MCP_SERVERS=filesystem,time,playwright
ZHAOXI_TOOL_MCP_TIMEOUT_SECONDS=20
```

Filesystem 默认仅开放朝汐启动工作目录；Memory 数据与 Playwright 输出写入 `tools/mcp/data/`。Everything 文件搜索 MCP 已安装但仍要求系统提供 `es.exe`。

## 界面设置

- 输入合并：0–30 秒，默认 15 秒，0 关闭。只合并模型请求，每次发送的气泡、时间和图片归属独立保存。旧记录缺少发送边界，无法可靠拆回。
- 分段回复间隔：滑条 0–15 秒，实际间隔为该值到两倍该值；默认 5–10 秒，0 立即显示。
- v1.1.9 起，两项时间设置同时持久化到 `.zhaoxi/interface-settings.json`，重启 Core 或浏览器存储丢失后仍可恢复；旧 `localStorage` 值保留为兼容回退。
- 模型思考：三选一开关，控制请求体是否附带 `thinking` 字段。`不带 thinking` 完全不发该字段；`thinking.type=disabled` 与 `thinking.type=enabled` 按所选项发送。不再限定接口域名，任何 OpenAI 兼容接口都可选择，能否被接受交由用户自行判断；主模型后续调用生效，已发出的请求不改变。普通聊天、Beat 和共享主模型的后台任务均使用该设置。备用模型保持自身默认行为。
- 选定具体模式时，工具调用所需的 reasoning_content 随内部消息保存并回传；`不带 thinking` 时不回传。选择保存于 .zhaoxi/model-settings.json（`thinking_enabled` 取 true / false / null），重启保留。思考文本不显示在聊天界面。
- 主动回复进入普通聊天气泡，沿用分段速度；任务完成、到期提醒、模板 inbox 通报及 system.* 通知仅显示在右侧系统消息区；已有历史记录按事件来源重新分类，不凭正文关键词猜测。右侧保留可折叠的“行动记录”、系统消息、设置和 Debug；“可以这样找我”建议卡片及生成链路已移除。聊天输入框上方仅显示当前用户级阶段。
- Debug 的“戳一戳”立即请求一次 Beat，可跳过静默、冷却、输入忙碌及夜间条件；模型仍可选择沉默。请求处理中、明确阻断和主动功能关闭仍生效。
- Debug 的“重启 Core”已对 EventSource 长连接设置有界优雅关闭，不再因事件流持续连接而固定触发停止超时。

## ACTIVE Beat 与桌面判断

常规 Beat 静默阈值 180 秒、决策冷却 300 秒。每会话初始主动预算 2，上限 3；发送扣除，用户有效回应补充，模型沉默不扣除。LOW 不自动硬阻断，BLOCKED 阻断。

鼠标高频不单独触发 busy。键盘默认阈值 120 次/分钟，20 个有效输入分钟后结合个人 P80；统计 P50/P80/P95，最多 1440 个输入分钟，仅在内存保留。1m/5m < 0.6 或停止键盘超过 15 秒解释为刚停下来。朝汐自身窗口排除输入 busy。

Beat 硬性 desktop_busy 还要求新鲜样本及 1m、5m 同时达到 max(240, 自适应阈值, P95)。普通高输入交由模型结合上下文判断。

每次 Beat 最多一次模型调用；总预算 **32000 Token**，生成上限 **16000 Token**，请求等待上限仍为 30 秒。JSON 模式加严格字段校验，兼容完整 JSON 代码块。失败维持有界冷却，不以残缺正文投递。

## 日志与已确认问题

BEAT 日志含调度、Gate、输入证据、模型 action/confidence、失败阶段和投递结果。provider_error_code 区分预算、传输等错误，不再仅凭 SILENT 推测。

- 14:40 后四次旧日志仅能确认模型阶段失败，无法还原具体异常。
- 19:47:13 实机记录 COMMENT、delivered=true。
- 20:13:02 实机明确 provider_token_budget_exhausted，原 4000 总预算错误压制响应。
- 20:22:40、20:23:49 返回 finish_reason=length 且无可见正文；原 1200 生成限制已提高。
- LifeHUD 取消超时绕过退避已修复；其 502 不等同于 Beat 未调度或模型选择沉默。

详细历史证据见 [ACTIVE 排查记录](../v1.1.x/ACTIVE_Beat_Diagnostics_Fix.md)。隔离真实模型成功不替代全部 UI 长时场景验收。最新自动测试结果见此次开发回复；历史报告中的数量不代表当前测试总数。

## 技术依据

[DeepSeek 思考模式官方文档](https://api-docs.deepseek.com/guides/thinking_mode/)：思考开关参数及工具调用的 reasoning_content 回传要求。
