# Zhaoxi / 朝汐

Zhaoxi 1.2.3 是一个可扩展的本地个人 Agent Core，提供对话、联想记忆、潮庭书库、规划、确定性工作流、权限确认、主动提醒、语音入口、Reflection 与可选 Tool Package 能力。

最新界面设置、模型思考开关、Beat 预算和验收边界统一见 [当前状态](docs/CURRENT_STATUS.md)。

## v1.2.3 自然语言能力预路由

在既有动态 Tool Router 前补齐轻量语义匹配：饮食、睡眠、任务、生活状态等自然问法可直接预挂 Life HUD；带时间指代的复盘查找会预挂本地搜索与文件读取；“之前怎么说”类问题直接保留记忆检索能力。未命中时继续使用 v1.2.2 Discovery，不新增 LLM 调用。详见 [v1.2.3 开发报告](docs/Zhaoxi_v1.2.3_Release_Notes.md)。

## v1.2.2 钥匙柜与广记修复

补齐 v1.1.9 的工具系统：记忆“记、改、想”三件套与两把目录/发现钥匙默认常驻；Registry 自动生成实时清单，支持能力解析与按轮扩展。小桌边 → 维护抽屉 → Debug · 钥匙柜可启停工具、强制暴露和恢复默认，设置自动保存到 `data/debug/tool_overrides.json`。详见 [v1.2.2 开发报告](docs/Zhaoxi_v1.2.2_Release_Notes.md)。

## v1.2.1 桌面壳与陪伴模式

同一个窗口在主界面和陪伴模式间切换，保留聊天、草稿与 WebView。陪伴模式直接显示最近对话，无头像抬头，输入栏仅保留文字与发送；图片和语音位于右上角菜单。菜单可切换陪伴置顶，关闭按钮隐藏到托盘，快捷键呼出陪伴模式，再按快捷键或 Esc 隐藏。

正式模式默认关闭浏览器 UI，桌面使用独立会话令牌进入，localhost API 保留。浏览器开发调试需设置 `ZHAOXI_DEV_BROWSER_UI=true`；`ZHAOXI_DESKTOP_SYSTEM_NOTIFICATIONS=true` 可显式改用 Windows Toast。两种窗口尺寸与位置保存在 `.zhaoxi/window-geometry.json`。

实现、测试、原生边框与手动验收边界见 [v1.2.1 开发报告](docs/Zhaoxi_v1.2.1_Release_Notes.md)。

## v1.2.0 秋日麦田

已完成 Phase 1–3：麦田背景、暖玻璃聊天区、专用朝汐头像、动作描写分组，以及默认收起的右侧小桌边公告栏。新留言只亮金点，可见后沿用现有接口确认已读；输入托盘与聊天区对齐，系统消息、设置和维护功能收在公告栏下方。

窗口、托盘、网页与快捷方式统一使用向日葵图标。运行中的窗口和托盘需彻底退出朝汐后重新启动；快捷方式使用独立图标路径，重新生成方式见下方启动说明。

当前实现、前后截图与验收边界见 [Phase 3 开发报告](docs/Zhaoxi_v1.2.0_Phase3_Release_Notes.md)。[Phase 1](docs/Zhaoxi_v1.2.0_Release_Notes.md) 和 [Phase 2](docs/Zhaoxi_v1.2.0_Phase2_Release_Notes.md) 报告保留各阶段设计与验证记录，不代表当前布局。

## v1.1.8 动态 ToolProvider 与 MCP 接入

- Core 新增协议无关的 `ToolProviderProtocol`；Registry 支持动态注册、原子刷新、卸载与统一关闭 Provider。
- MCP Client、stdio Server 生命周期、MCP Schema 适配和权限提示映射全部位于独立 `tools/mcp` Tool Package，Core 不导入 MCP 模块。
- 每个远程 MCP Tool 都转换成独立 Zhaoxi Tool，Agent、Planner、Workflow 继续复用现有 Registry、ToolExecutor 与 PermissionGateway。
- 当前安装的 9 个 MCP Server 可发现 78 个独立 Tool；Package 默认只发现、不启用，设置 `ZHAOXI_TOOL_MCP_ENABLED=true` 后装配。

设计边界、配置和验证结果见 [v1.1.8 开发报告](docs/v1.1.x/Zhaoxi_v1.1.8_Release_Notes.md)。

## v1.1.7 ACTIVE 对话闭环

ACTIVE 现在独立调度 Conversation Beat：沉默默认 180 秒后获得判断机会，后续至少间隔 300 秒；普通闲聊也可触发，open thread 只是一种理由。模型可选择 SILENT / CONTINUE / COMMENT / ASK / CALLBACK，SILENT 不消耗发送预算。

每段会话初始预算 2、上限 3，主动发送扣 1，用户有效回应后补 1。持续极高输入、BLOCKED、Quiet、夜间、待确认或正在处理请求时不调用常规 Beat 模型；LOW 不再自动阻断；普通主动消息与 Beat 共享发送历史和冷却。无人回应时不会靠主动发送无限续期，约 20 分钟后冷却到 SEMI_ACTIVE。

诊断包含 `active` 会话、Beat 时间、预算及拦截原因；`/api/proactive/active/inspect` 可查看最近模型决策。配置及验收状态见 [v1.1.7 开发报告](docs/v1.1.x/Zhaoxi_v1.1.7_Release_Notes.md)。本版为 v1.1.x 功能收尾，之后仅修复缺陷。

## v1.1.6.1 普通对话桌面上下文

普通聊天现在通过独立 `[Desktop Activity]` Runtime 区块获得当前前台进程、标题、输入频率和已有活动推测。只复用现有采样与缓存，不增加 Activity LLM 调用；超过 15 秒的观察明确标记 stale，无法采样或模块关闭时标记 unavailable。原始区块不写入 Session / Memory，diagnostics 保持脱敏。

实现、测试与人工验收见 [v1.1.6.1 补丁报告](docs/v1.1.x/Zhaoxi_v1.1.6.1_Release_Notes.md)。

## v1.1.6 桌面活动感知

- Desktop Host 每 2 秒读取当前前台进程、标题和 Presence；键鼠 hook 只累计事件数量，不读取输入内容或坐标。
- 1 / 5 分钟事件频率、窗口切换与约 20 分钟标题缓冲全部只驻留内存。
- 需要判断主动关心或对话延续时，才低频结合窗口语义、行为形状和近期对话推测活动，保留置信度和其他可能。
- 持续高输入降低 Interruptibility 并暂缓 ACTIVE Continuation；长时间高输入结束可生成 SEMI_ACTIVE 候选。全屏退出不再单独形成高权重提醒。
- 普通 diagnostics 不含完整标题；显式 `/api/desktop/activity/inspect` 可查看短期上下文，Desktop 会话继续要求本地令牌。

开关、计数单位、自动测试、手动验收及限制见 [v1.1.6 开发报告](docs/v1.1.x/Zhaoxi_v1.1.6_Release_Notes.md)。

## v1.1.5 本体主权与能力边界

- Tool Package 必须声明公共 SDK 版本与显式 Capability，不再因为包存在就无条件进入所有运行链。
- Tool Package 默认只发现、不启用；`ZHAOXI_TOOL_<ID>_ENABLED=true` 显式授权后才装配。Tool、Workflow、Router Hint、Proactive、Reflection 与 State Signal 支持分项启停。
- Core 只聚合 `StateSignal`，不读取 Life HUD 对象；Interaction State 与 Interruptibility 已分离。
- ACTIVE 表示仍在持续的对话，拥有独立的 Conversation Continuation、静默时间、冷却和每窗口预算。
- Memory 与 Life HUD 采用分域权威：精确结构化生活事实优先 Life HUD，经历与对话语境优先 Memory，两者不互相覆盖。

完整实现与验收见 [v1.1.5 开发报告](docs/v1.1.x/Zhaoxi_v1.1.5_Release_Notes.md)。

## v1.1.4.1 联想记忆闭环修正

- 新 Episode 数量与时间间隔可触发低频自动 Consolidation；纯代码无候选时不调用模型。
- Cluster 使用 tag、entity、lexical、embedding centroid 与时间接近度综合匹配，并支持可追溯合并。
- AutoMemory 可输出实体名称型 EDGE Candidate；Service 负责 Concept/alias 解析、建边与缺字段降级。

完整实现与验收见 [v1.1.4.1 开发报告](docs/v1.1.x/Zhaoxi_v1.1.4.1_Release_Notes.md)。

## v1.1.4 联想记忆

- 单轮 AutoMemory 可批量提取 0~N 条原子生活记忆，覆盖 EPISODIC / SEMANTIC / STATE / INTENT / RELATIONSHIP。
- 长期权重拆分为稳定 `importance`、可衰减 `activation` 与查询时动态 `contextual_relevance`。
- SQLite schema v3 提供 Cluster、成员、Graph Edge、Embedding 与 Semantic Evidence 表，并无损迁移 v1/v2 数据。
- 召回组合 keyword、O(n) local embedding、时间有效性、2-hop graph expansion 和 cluster diversity rerank。
- Consolidation 保留原 Episode，并通过 EVIDENCE_FOR / DERIVED_FROM 边记录可追溯证据。

设计、实现与验收结果见 [v1.1.4 开发报告](docs/v1.1.x/Zhaoxi_v1.1.4_Release_Notes.md)。

## v1.1.3 潮庭书库

`data/archive/` 是人工维护的本地 Markdown 资料库。启动时按文件哈希增量更新 `.zhaoxi/archive.db`，不会把整座书库常驻注入模型上下文。Agent 只在需要正式设定、用户长期资料或项目文档时调用 `archive_list_documents`、`archive_search`、`archive_read` 三个只读 Tool。

书库支持 `zhaoxi`、`user`、`projects`、`reference` 四个 scope，以及 `canonical`、`reference`、`personal`、`draft` 四个 authority。当前用户明确指令优先级最高；canonical 高于普通 Archive 与 Memory；没有记录的细节不得编造。图片采用同名 Sidecar Markdown 和 `attachments` 元数据，不做 OCR 或图片向量化。

```bash
python main.py --archive-status
python main.py --reindex-archive
```

配置、实现边界与验收结果见 [v1.1.3 开发报告](docs/v1.1.x/Zhaoxi_v1.1.3_Release_Notes.md)。

Life HUD 通过独立的 `tools/lifehud_tool` 包接入，Core Registry 只注册一个 `lifehud` Tool；各能力由封闭 `operation` 区分，并按调用动态解析 READ/WRITE 权限。Life HUD API 的时间戳按原始 UTC 契约读取且不改写；发送给模型的 Tool observation 默认转换为 `Asia/Shanghai`，可通过 `ZHAOXI_TOOL_LIFEHUD_DISPLAY_TIMEZONE` 配置。

## v1.1.1 潮汐心跳

常驻 Web / Desktop 现在每 30 秒进行纯代码观察，LifeHUD Focus / 任务快照每 2 分钟读取一次；候选事件聚合、去重并经过 Quiet Mode、夜间、最近交互和冷却筛选后，才允许模型判断是否开口。普通主动消息默认冷却 45 分钟，自然关心最多每天一次。

右侧主动消息支持时间、未读 / 已读和点击续聊；Windows 通知点击进入同一上下文。配置见 `.env.example`，实现与验收详见 [v1.1.1 开发报告](docs/v1.1.x/Zhaoxi_v1.1.1_Release_Notes.md)。

## v1.1 入口体验

- Windows 当前用户登录自启动、隐藏启动与双击启动入口。
- Ctrl+Alt+小键盘 0 切换窗口显示/隐藏，保留单实例与托盘退出。
- 回复按空行拆成气泡，第一段立即显示，后续每段随机等待 5～10 秒；历史立即恢复。
- 连续文字/图片输入以 15 秒防抖合并，回复期间输入排队。
- 支持选择/粘贴 PNG、JPEG、WebP，每次最多 20 张，每张 100 MB，图片随会话保存。

详情见 [v1.1 发布说明](docs/v1.1.x/Zhaoxi_v1.1_Release_Notes.md)；登录自启动命令与验收见 [常驻说明](docs/presence-autostart.md)。

## Architecture

```text
CLI / Web / Desktop
          ↓
   Interface Gateway
          ↓
     Zhaoxi Core
 Cognitive Router → Conversation / Tools / Planner
                          ↓
              Auto Memory + Lifecycle
                          ↓
              Permission Gateway + Audit
          ↓
   Model Provider  ←→  Workflow Runtime
                         ↓
                    Tool Registry
                         ↓
                 independently registered Tools
```

Core 使用内部消息和响应类型，不依赖厂商对象；新增工具只需实现 `Tool` 并注册，无需修改 Agent 循环。

## v0.9 Reliability

- 修复 v0.8 Reflection SQLite 类作用域类型注解遮蔽，恢复全量测试基线；
- `ReliabilityError` 明确错误机器码、分类、是否可重试及是否可安全重放；
- Interface Gateway 为每次用户请求建立 `trace_id / request_id / session_id` 关联上下文；
- 成功、失败、缓存命中和耗时进入不含用户正文的进程内指标；
- `GET /api/diagnostics` 返回版本、组件开关和脱敏指标快照；
- Planner、Session 与 Permission 使用 SQLite 持久化；Planner 权限等待可在重启后重建，无法安全重建的临时 Agent 写操作失败关闭；
- Provider 与 Life HUD 只读调用复用有界重试策略，Provider 支持 fallback、熔断、调用与 Token 硬预算；
- 写操作没有稳定重放声明时不会自动重试，不确定结果进入 `needs_reconciliation`；
- 多数据库在线备份提供 manifest、SHA-256、SQLite integrity、恢复前 safeguard 和目录逃逸防护；
- Tool 参数限制大小、深度、集合与 URL 目标；日志和权限审计按大小轮转；
- 后台任务受统一 supervisor 管理，关闭时有界取消；
- Windows wheel、构建/安装/卸载脚本和运维恢复手册已提供，卸载默认保留用户数据。

## v1.0 prerequisite · LifeHUD-Tool decoupling

- Life HUD Client、schema、错误、时区展示与铁幕 Workflow 已移出 Core，归属独立 `tools/lifehud_tool` 包；
- Zhaoxi 通过通用 Tool Package discovery 和 entry point 加载外部 Tool；
- Registry 与模型只看到一个 `lifehud` Tool，旧的 13 个 `lifehud_*` Tool 不再注册；
- `context.*` 与 `focus.current` 为 READ，`focus.start/complete` 为 WRITE 并继续经过 PermissionGateway；
- Core Settings、启动装配、Router 与 Workflow 不再直接 import Life HUD 业务实现；
- Life HUD 项目保持只读，集成只调用公开 HTTP API，不读取其数据库或内部文件；
- Voice 显式朗读不再被当前真实小时导致的 Night Mode 测试干扰；Web Voice policy 支持注入时钟，Quiet 仍优先禁止朗读。

## v1.0 development

- 缺少模型配置时 Web/Desktop 进入可诊断的 Setup Mode，不因单个 Tool Package 加载失败而整体退出；
- `python main.py --doctor` 输出无密钥、无用户正文的启动检查，Web 提供同样受本地令牌保护的诊断与能力目录；
- CLI 提供 `/reflection`、`/reflections`，Web 提供生成与历史接口；Reflection 现已组合 Memory 与独立 Tool Package 的只读证据源；
- LifeHUD-Tool 通过公开 Agent Context API 提供 Reflection 证据，Core 不读取 Life HUD 项目文件或数据库；
- Reflection API 默认只返回结论、引用 ID 和证据数量，不暴露原始证据摘录或模型元数据。

## Quick start

需要 Python 3.12 或更新版本。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m pip install -e .\tools\lifehud_tool --no-deps
# Windows Desktop Presence
python -m pip install -e ".[dev,desktop,voice]"
copy .env.example .env
```

在 `.env` 中填写兼容 OpenAI Chat Completions API 的模型配置：

```dotenv
ZHAOXI_MODEL_BASE_URL=https://api.openai.com/v1
ZHAOXI_MODEL_API_KEY=your-key
ZHAOXI_MODEL_NAME=your-model
```

人格与表达方式使用两个独立、版本化的 YAML 输入：

- `src/zhaoxi/personality/zhaoxi_v1.yaml`：身份、关系、性格与长期设定，决定“朝汐是谁”。
- `src/zhaoxi/personality/expression_v1.yaml`：语气、节奏、情绪表达与格式偏好，决定“朝汐怎么说”。

修改任一文件后需要重启朝汐。运行时按人格 → 表达方式 → Core 规则的顺序组合；普通对话、Tool/Workflow 最终回复与主动消息使用同一组合 Prompt。

运行与测试：

```bash
python main.py --doctor
python main.py
python main.py --web
python main.py --desktop
python -m pytest
```

Web 模式默认打开在 `http://127.0.0.1:4913`。可通过 `ZHAOXI_WEB_HOST` 和 `ZHAOXI_WEB_PORT` 调整；如无明确需要，不要把 Host 改为公网地址。

## v0.7.1 Voice

- 输入区麦克风按钮明确开始和停止录音，录音后必须先复核、编辑或重录，再进入同一个 Core；
- OpenAI-compatible STT 通过独立配置接入，默认关闭且失败时始终保留文字交互；
- Windows 10 使用系统 SAPI5 朗读，可随时停止，自然播放结束后自动回到空闲状态；
- Quiet、Night 与 Permission 等待由确定性策略禁止自动朗读，自动发送和自动朗读默认关闭；
- WAV 临时文件有大小与时长上限，在确认、取消、失败和退出时清理；
- 后续 v0.9 已完成安装器、卸载器、可选开机自启和发布构建硬化。

## v0.7 Presence

- `python main.py --desktop` 启动以 Windows 10 为主平台的 Desktop Host；
- 用户级单实例协调：重复启动只激活已有窗口，不创建第二套 Core 或 Scheduler；
- pywebview 复用现有 Web Shell，关闭窗口后隐藏到托盘；
- 托盘提供打开、快速输入、运行状态、Quiet Mode 与安全退出；
- Ctrl+Alt+小键盘 0（`ctrl+alt+numpad0`） 默认全局切换：显示时隐藏到托盘，隐藏或最小化时恢复窗口；冲突时降级为托盘入口；
- Windows Toast 消费 Core 已裁决的 Delivery，INFO 只进入 Inbox，点击通知激活窗口；
- Desktop API 使用每次启动随机令牌，继续只监听 `127.0.0.1`；
- Web、Desktop 通过统一 Interface Gateway 串行进入同一 Conversation，并按 request ID 幂等；
- Voice 已在 v0.7.1 实现；后续 v0.9 已完成安装、卸载与发布工程。

## v0.6.1 Local Interaction Shell

- 原生 HTML / CSS / JS 本地聊天界面，无前端构建链；
- 多轮消息、Enter 发送、Shift+Enter 换行、请求中防重复发送；
- Permission Card 展示操作、权限和资源范围，批准或拒绝后恢复原 Core 流程；
- 折叠 Debug 面板只展示 route、goal、workflow、request 等安全元数据；
- SSE Activity / Proactive 事件通道，主动消息与普通回复分开展示；
- 当前 Session 查看与清空；
- Provider / Tool / Workflow 异常在 API 边界转换为可继续使用的错误，不向聊天区透传 traceback 或内部对象。

CLI 支持 `/tools`、`/permissions`、`/approve`、`/deny`、`/revoke`、`/audit`、`/clear` 和 `/exit`。缺少关键模型配置时会显示可操作的提示，不会输出 traceback 或密钥。

## v0.5 capabilities

- Workflow 输入按定义归一化，无害未知字段被忽略并进入 Run 事件
- Permission Resume 后继续原 Workflow，再由模型生成自然语言最终回复
- 普通模式禁止输出 raw WorkflowResult、Pydantic DTO、JSON 或 traceback
- Life HUD 查询与工具检查路由补强，避免“声称检查但未调用”
- Workflow 参数错误和意外 CLI 错误转换为带追踪号的可继续回复

- Life HUD v0.8 Agent Context `/today /recent /status /focus /tasks /dreams /life /journal /media /growth`
- schemaVersion 1 校验、强类型 ISO 8601 时间、null/空集合和未知字段前向兼容
- Agent Context GET 对网络/5xx 有限退避，400 返回业务 detail，写操作不自动重放
- 铁幕 Workflow 使用 `/api/agent/context/focus` 判断状态，并在 start/complete 后重新读取事实源确认

- YAML 版本化 Workflow Definition、Loader 与 Registry
- 受限 `tool / condition / ask / set / end` DSL，不执行任意代码
- 参数校验、条件分支、输出绑定、有限重试和有界运行事件
- Workflow 暂停、输入恢复、权限恢复、取消与 SQLite 运行历史
- `DIRECT / TOOL / PLAN / WORKFLOW` 认知路由
- `/workflow` CLI 检查、启动、恢复、批准、拒绝、暂停和取消
- Life HUD Focus HTTP Tool：current、start、complete
- “朝汐，开幕 / 落幕”流程，避免重复开幕或误结束非铁幕 Focus
- 所有 Workflow Tool Step 复用 v0.4 `ToolExecutor / PermissionGateway`

## v0.4 capabilities

- `READ / WRITE / DELETE / EXTERNAL_ACTION / DANGEROUS` 权限等级
- Tool 权限、资源范围与副作用声明
- Agent 与 Planner 共用 `ToolExecutor` 和 `PermissionGateway`
- READ 默认自动允许；记忆新增与更新默认允许，用户禁止记忆或显式 WRITE deny 时拒绝；其他 WRITE / DELETE 默认确认，DANGEROUS 默认拒绝
- 用户明确的同范围记住/忘记命令可作为窄范围本轮授权
- 确认绑定原始 Tool、参数摘要、资源范围和 invocation ID
- 单个待确认操作支持自然语言“允许/确认/执行”和“拒绝/不要/取消”，回复在进入模型前处理
- 批准或拒绝都会为原 `tool_call_id` 写入 Tool Message，再恢复 Agent Loop
- 同一模型响应中连续、同 Tool/同权限的调用合并为一次批量确认，并展示冻结的资源范围；不同 Tool 不合并
- 批次可部分批准，例如“只删12，保留34”或“允许1、2，拒绝3、4”；每项仍保留原参数和 `tool_call_id`
- 参数变化不能复用旧授权，授权单次消费并支持撤销
- Planner 可进入 `waiting_for_permission` 并在同一 Goal 上批准、拒绝或取消
- 权限判断、确认、执行和拒绝写入追加式脱敏审计
- ToolResult 标记为不可信外部数据并限制进入上下文的长度
- 后台 Auto Memory 不允许模型自行执行归档、遗忘或整合

- 短期 Conversation 与上下文裁剪
- 独立版本化的人格与表达方式 YAML：人格决定“朝汐是谁”，表达方式决定“朝汐怎么说”
- OpenAI-compatible Model Provider
- 支持单个/并行多个 Tool Call 的 Agent Runtime
- 工具结果回填、再次推理、超时与最大步数保护
- `echo`、安全 `calculator`、`current_time`
- 内存 Session Store、结构化日志和无真实 API 的测试
- SQLite 长期 Memory，进程重启后仍可读取
- Episodic / Semantic / State / Intent / Relationship 分层、来源、时间、置信度与标签
- `remember_memory`、`search_memories`、`update_memory`、`forget_memory`
- 跨 Session 相关记忆检索与有边界的 Context 注入
- 精确去重、冲突确认、显式替换与软遗忘
- 显式 Goal、线性 Plan、版本化 Re-plan 与受保护的状态迁移
- 多步骤 Tool Action / Observation 执行
- 可重试错误、同一步 Tool fallback 与确定性次数限制
- 信息不足时暂停，用户补充后恢复同一 Goal
- 规划任务取消、单步/总超时和最大执行步数保护
- 有界、结构化 Execution Trace
- Cognitive Router 自动区分 `DIRECT`、`TOOL` 和 `PLAN`
- 简单问题不启动 Planner，复杂依赖型目标自动规划
- `DIRECT` 路径不暴露 Tool Schema
- 回复后执行一次独立 Auto Memory 批量原子提取
- 自动记忆一轮可生成 0~N 条候选，并兼容旧 `IGNORE` / `CREATE` / `UPDATE` / `MERGE` / `CONFLICT`
- 用户“记住 / 不要记 / 忘掉”意图拥有最高优先级
- 只读规划任务会从确定性执行层阻止状态变更工具
- `importance` / `activation` 持久权重与动态 `contextual_relevance`
- `ACTIVE → COLD → DORMANT → ARCHIVED` 自然生命周期；明确遗忘才进入 `FORGOTTEN`
- 检索命中提升 activation，并向 1/2-hop 邻居轻量传播
- Pinned 关键记忆不参与自动归档，用户仍可显式遗忘
- `archive_memory`、`reactivate_memory`、`pin_memory`、`consolidate_memories`
- 多条 Episode 可归纳为带证据链的 Semantic Memory，原 Episode 保留
- 可重复查询的 Tool 事实默认不复制进长期 Memory
- SQLite schema v1/v2 自动迁移至 v3，不丢失旧记录

长期记忆默认保存到 `.zhaoxi/memory.db`，可通过 `ZHAOXI_MEMORY_DB_PATH` 修改，数据库目录已被 Git 忽略。普通对话默认向主 Agent 暴露 `remember_memory`、`update_memory` 与 `search_memories`（Debug 显式停用除外），是否写入仍由模型判断；独立 Auto Memory Extractor 继续宽松提取值得留下的生活痕迹，再由 Cluster、Graph 与 Hybrid Retrieval 控制召回。用户明确要求记住、禁止记忆或遗忘时，其意图拥有最高优先级。

CLI 可直接检查记忆：

```text
/memory search 咖啡
/memory history 咖啡
/memory get <memory_id>
/memory maintain
```

正常输入会自动选择执行路径。显式规划命令继续保留，作为开发和调试入口：

```text
/plan 帮我分步骤准备明天下午的面试
/plan
/resume <goal_id> OpenAI 的后端工程师岗位
/trace <goal_id>
/cancel <goal_id>
```

普通聊天与简单 Tool Call 不会被强制套入 Planner。Auto Memory 使用单次、无 Tool Choice 的 JSON 决策请求，并对身份、命名缘由和稳定偏好提供保守的本地兜底；用户明确禁止时不会保存。Memory maintenance 当前按检索或 `/memory maintain` 执行，不包含后台定时任务。日志只显示 `auto_memory action=...`，不输出记忆正文。Planner、Session 与 Permission 状态使用 SQLite 持久化；可安全恢复的等待状态会在重启后重建，无法证明可安全重放的临时写操作会失败关闭。

权限命令：

```text
/permissions
/approve <confirmation_id>
/deny <confirmation_id>
/revoke <grant_id>
/audit [limit]
```

只有一个待确认操作或一个已合并批次时，也可以直接回复“允许”或“拒绝”。存在多个独立待确认操作时必须使用带 ID 的开发者命令，避免授权错位。

批量确认会按 `1.资源范围、2.资源范围……` 编号。1–9 项的小批次允许用“12”简写第 1、2 项；10 项以上请使用明确序号和分隔符，例如“允许 1、2，保留 12”。

默认策略可通过 `.env` 分级收紧。审计以脱敏 JSONL 写入 `.zhaoxi/audit/permission.jsonl`，不会记录 Tool 原始参数、Memory 正文或模型完整上下文。

首次运行前可执行 `python main.py --doctor`，它不会启动 Agent，也不要求模型调用；会检查 Python、模型配置、数据目录、Tool Package 和 Desktop/Voice 可选依赖。诊断不输出密钥或用户正文。

数据备份使用内置验证式备份入口 `/backup`，不要在服务写入期间直接复制 SQLite 文件。删除 `.zhaoxi` 内数据库会清空对应数据，操作前必须先生成并验证备份。

安装、卸载、备份和恢复细节见 [v1.0 运维与恢复手册](docs/Zhaoxi_v1.0_Operations_Runbook.md)。

## Roadmap

当前与历史文档的权威范围见 [文档索引](docs/README.md)。v1.0 范围见 [正式版任务书](docs/Zhaoxi_v1.0_Release_Development_Task.md)；Life HUD 边界见 [LifeHUD-Tool 解耦任务书](docs/Zhaoxi_v1.0_Prerequisite_LifeHUD_Tool_Decoupling_Task.md)。v1.0 按全新安装交付，不承诺迁移早期人工测试数据；卸载仍默认保留当前用户数据。

### 双击启动（Windows）

双击项目根目录的 **启动朝汐.lnk** 即可打开朝汐，无需打开 PowerShell。
该快捷方式直接运行项目 `.venv\Scripts\pythonw.exe main.py --desktop`，不弹终端窗口；已有实例时只唤起现有窗口。
可将快捷方式复制到桌面。关闭朝汐窗口仍会隐藏到托盘，彻底退出请使用托盘“退出朝汐”。

首次创建快捷方式，或移动项目 / 重建虚拟环境后，在项目根目录执行一次：

```powershell
powershell -NoProfile -File .\scripts\create_desktop_launcher.ps1
```

快捷方式使用当前机器路径，因此不纳入 Git；生成脚本会自动定位项目目录。

### 图片输入

在输入框左侧点击“图片”选择文件，或在输入框中直接粘贴截图。支持 PNG、JPEG、WebP，发送前可预览并点击 × 移除；可只发图片，也可配文字一起发送。

保护性上限为每次（含防抖合并后的请求）20 张、每张 100 MB。图片参与现有 15 秒输入合并，回复期间的新输入仍排队处理。图片随本地会话保存，重新打开后可查看，清空会话会一并移除该会话中的图片。

图片通过现有模型接口的多模态消息发送，需要配置支持图片输入的模型；具体服务商可能有自己的请求限制。图片回合直接使用已有 Agent 工具循环读取图文，普通文字回合继续使用原有认知路由。


## v1.1.2 潮间态

新增消息时间上下文、桌面轻量状态采样与 ACTIVE / SEMI_ACTIVE / IDLE / AWAY 互动状态。主动门槛随状态变化，动态快捷建议复用现有回复（额外模型调用为0）。统一消息时间、图片按钮及“汐”字应用图标。开发验证结果、配置和人工验收步骤见 [v1.1.2报告](docs/v1.1.x/Zhaoxi_v1.1.2_Release_Notes.md)。
