# Zhaoxi v1.0 · 正式版开发任务书

> 版本代号：**Zhaoxi / 有事找朝汐**  
> 开发分支：`v1.0`  
> 起点提交：`87eb9c6 feat: complete v0.9 reliability hardening`  
> 起草日期：2026-09-01  
> 前置版本：v0.9 · Reliability；v1.0 采用全新安装策略

> **前置门：**必须先完成 [LifeHUD-Tool 解耦开发任务书](Zhaoxi_v1.0_Prerequisite_LifeHUD_Tool_Decoupling_Task.md)，使 Life HUD 以一个独立 Tool Package 接入，且 Life HUD 项目本体保持只读；完成后再进入本文阶段 0。

---

## 1. 版本定位

v1.0 不是继续横向堆叠大量功能，也不以“接完所有工具”为目标。本版的任务是把 v0.1～v0.9 已经建立的 Conversation、Memory、Planner、Workflow、Permission、Proactive、Presence、Voice、Reflection 与 Reliability 收束成一个可安装、可理解、可恢复、可连续日用的正式产品。

正式版承诺：

> **用户可以每天把真实事情交给朝汐；成功时结果清楚，不能做时原因清楚，失败后知道如何恢复。**

一句话验收：

> **有事找朝汐。**

---

## 2. 当前基线与开工事实

### 2.1 已具备能力

- 统一的 CLI、Web 与 Windows Desktop 入口；Voice 进入同一 Interface Gateway。
- 长期 Memory、自动记忆与生命周期管理。
- `DIRECT / TOOL / PLAN / WORKFLOW` 认知路由。
- Planner、Session、Permission 与业务 Store 的 SQLite 持久化及恢复边界。
- Tool Registry、统一 ToolExecutor、PermissionGateway 与脱敏审计。
- Proactive、Inbox、Quiet/Night 策略与 Windows 通知入口。
- Daily/Weekly/Monthly 等 Reflection 基础能力。
- Provider 有界重试、fallback、熔断和请求预算。
- 关联日志、进程内指标、诊断 API、备份恢复与 Windows wheel 脚本。

### 2.2 开工检查结果

- `v1.0` 从 `87eb9c6` 创建，未夹带工作区改动。
- Core 与 LifeHUD-Tool 包版本已统一为 `1.0.0`。
- 2026-09-02 本机全量测试结果为 **240 passed**，Voice Night Mode 已改为可注入时钟，显式朗读与 Quiet/Night 语义已有确定性测试。
- Life HUD 已解耦为独立 `tools/lifehud_tool` 包，Core Registry 只暴露一个 `lifehud` Tool。
- `docs/CODEBASE_STATUS.md` 的 Planner/Permission、安装链路、测试数与 Git 基线旧事实已校正。
- README Roadmap 已切换到 v1.0，并加入无需启动 Agent 的 `python main.py --doctor` 首次启动诊断。

### 2.3 v1.0 前仍需验证的现实缺口

- 尚无真实凭据驱动的端到端集成测试记录；现有自动化主要使用 Fake Provider 与 Mock Transport。
- Life HUD 写能力覆盖面有限；GitHub、Calendar、Files 等通用真实业务工具未交付。
- Windows 11 实机、代码签名、自动更新和操作系统级 Tool Sandbox 尚未完成。
- 多 Session 通知深链接、Voice 体验增强、硬删除与通用事务回滚仍不完整。
- v1.0 后续能力、版本号和测试数必须继续在同一提交中同步，防止事实源再次漂移。

---

## 3. 正式版成功标准

### 3.1 用户价值

- 新用户能在 10 分钟内完成安装、配置、首次对话和一次真实任务。
- 用户无需理解内部模块即可知道朝汐“能做什么、正在做什么、为什么需要确认”。
- 至少形成三条可重复的日用闭环：对话/记忆、Life HUD 工作流、主动提醒或回顾。
- 任务失败、权限等待、Provider 不可用和数据恢复均给出可执行下一步。

### 3.2 工程质量

- 全量自动化测试、compileall、wheel 构建和 `git diff --check` 全绿。
- 测试不依赖真实时间、随机网络、执行顺序或用户本机残留状态。
- v0.9 的安全、权限、恢复、预算与脱敏边界不得回退。
- v1.0 不承诺迁移早期人工测试数据；新建数据必须可备份、校验和恢复。
- 正式版文档、代码版本、诊断版本、构建产物和发布说明完全一致。

### 3.3 发布质量

- 在可用的干净 Windows 环境完成安装、首次启动、卸载和保留数据验证；未实测系统版本必须写入已知限制。
- Release Candidate 经过至少一次长时或加速 soak，无无界资源增长和未解释错误。
- 已知限制按 P0/P1/P2 分类，P0 为零；任何延期项都有用户可见说明。

---

## 4. 范围与优先级

### P0 · 正式发布阻塞

1. 修复 Voice 夜间测试的时间依赖，冻结显式朗读与 Quiet/Night 的产品语义。
2. 校正 `CODEBASE_STATUS.md`、README、版本号与真实测试基线，建立单一事实源。
3. 完成全新安装、当前数据备份恢复与卸载保留数据演练。
4. 为安装、首次启动、配置错误、Provider 故障、权限确认和恢复建立完整用户路径。
5. 完成当前 Windows 10 主机隔离 Release Candidate 冒烟；Windows 11 未实测状态写入发布说明。
6. 全量回归、构建、静态编译、隐私 canary、安全回归和 soak 全绿。
7. 产出发布说明、运维手册更新、已知限制与回滚方案。

### P1 · v1.0 完整体验

1. 统一首次启动检查与设置提示，减少手改 `.env` 的误配置成本。
2. 提供能力清单和示例任务，让用户知道对话、记忆、工作流、主动能力与回顾的边界。
3. 选择 2～3 条真实高价值闭环做端到端验收，不用新增大量通用 Tool 稀释正式版质量。
4. 统一 CLI/Web/Desktop 的错误文案、Permission Card、等待状态和恢复提示。
5. 补齐诊断导出前的内容预览和隐私说明。
6. 完成可访问性、键盘操作、空状态、加载态和失败态检查。

### P2 · 明确延期，不阻塞 v1.0

- 代码签名与自动更新。
- 操作系统级 Tool Sandbox。
- 本地 STT、Push-to-talk、音量指示与多候选转写。
- 通用 Files、Calendar、GitHub 全量写工具。
- 多用户、账号体系、云同步与跨设备权限。
- Workflow 图形编辑器、DAG、通用循环和跨系统事务回滚。
- RAG、向量数据库和记忆物理硬删除。

---

## 5. 明确不做

- 不为了 1.0 数字重写现有 Core。
- 不引入新的前端构建链或大型框架。
- 不把所有第三方系统接入作为正式版门槛。
- 不绕过 PermissionGateway 追求“自动化演示效果”。
- 不以真实用户数据库、密钥或私人正文作为测试 fixture。
- 不在缺少事实源时伪造已完成、已恢复或已写入的结果。
- 不把 P2 项偷偷转成发布阻塞，除非出现明确安全或数据风险。

---

## 6. 正式版核心工作包

### 6.1 基线与事实源治理

- 将 `docs/CODEBASE_STATUS.md` 作为当前能力、限制、测试数和 Git 基线的首要交接入口。
- 删除或改写其中已过时的 v0.7/167 项/内存 Store 描述。
- README 只保留用户需要的当前能力、安装、使用和安全边界；历史路线链接到版本任务书。
- 版本号统一修改 `pyproject.toml`、`src/zhaoxi/__init__.py`、诊断输出、构建脚本和文档。
- 增加发布检查，防止源码版本、包版本与文档版本再次漂移。

### 6.2 确定性与回归基线

- 为 VoicePolicy 注入 clock 或直接传入已计算的 night/quiet 状态，测试固定边界时刻。
- 明确：用户点击“朗读”是否可以覆盖 Night；Quiet 是否始终阻止语音。产品决定必须由测试固化。
- 扫描 wall clock、随机数、端口、用户目录和 `.zhaoxi` 残留对测试的影响。
- 消除测试顺序依赖，确保单测、文件级测试与全量测试结果一致。

### 6.3 首次启动与日用闭环

- 启动时检查 Python/可选依赖、Provider 配置、数据目录和数据库健康。
- 对缺失模型配置、Voice 不可用、端口冲突与 Desktop 可选依赖缺失给出可操作提示。
- 建立三个集中用户旅程：
  1. 首次对话并记住一条稳定偏好；
  2. 执行一次 Life HUD 铁幕开幕/落幕并确认事实源；
  3. 创建一次提醒或生成一次带证据的 Reflection。
- 每条旅程覆盖成功、拒绝权限、外部失败和重启恢复。

### 6.4 数据与恢复

- 建立 v1.0 数据 fixture，覆盖所有 SQLite Store、审计、日志和配置。
- 验证备份 manifest、schema 和恢复 safeguard；失败时安全退出。
- 早期 v0.9 人工测试数据允许重置，不实现原位迁移兼容层。
- 卸载默认保留数据；用户数据删除仍需独立明确操作。
- 发布包不得包含 `.env`、数据库、日志、备份、音频或测试密钥。

### 6.5 安全、隐私与可信反馈

- 复测 Prompt Injection、路径逃逸、SSRF、参数走私、超大 payload 和审计失败。
- 用户正文、Memory、Authorization、Cookie、Desktop token 不进入 metrics、日志或诊断包。
- 所有写操作必须展示目标、范围和副作用；未知结果进入 `needs_reconciliation`。
- 任何能力不可用时不得生成“已经替用户完成”的误导性回复。

### 6.6 发布工程

- 使用同一 Git commit 可重复构建 wheel。
- 在可用 Windows 主机验证隔离安装、首次启动和可选能力；未实测版本写入已知限制。
- 生成 SHA-256、版本信息、构建记录和冒烟结果。
- 明确签名与自动更新状态；未交付时不得在文档中暗示已具备。

---

## 7. 开发流程

### 阶段 0：冻结 v1.0 起点

任务：

- 记录起点 commit、分支、环境和全量测试结果。
- 修复 Voice 时间依赖；补 Night 起止边界、Quiet、显式朗读与自动朗读测试。
- 清理状态文档中的冲突事实。
- 运行全量 pytest、compileall 与 `git diff --check`。

退出条件：测试全绿且可重复；文档只描述当前真实能力。

### 阶段 1：正式版契约与发布清单

任务：

- 冻结 P0/P1/P2、用户旅程、兼容范围和延期项。
- 建立版本一致性、数据清单、全新安装矩阵和发布 Checklist。
- 对 v1.0 不新增的大功能写清边界。

退出条件：所有 P0 都有责任模块、验证方法和完成证据。

### 阶段 2：首次启动纵向切片

任务：

- 从安装 → 配置 → 启动 → 首次对话贯穿 CLI/Web/Desktop。
- 统一配置错误、可选依赖和 Provider 不可用提示。
- 为新用户提供最小能力说明与安全说明。

退出条件：干净环境 10 分钟内可完成首次成功任务。

### 阶段 3：三条日用闭环

任务：

- 完成记忆、Life HUD、Proactive/Reflection 三条端到端路径。
- 覆盖权限拒绝、外部超时、重启与对账。
- 只修闭环缺口，不扩张成大型新 Tool 项目。

退出条件：每条路径都有自动化集成测试和人工黑盒记录。

### 阶段 4：全新安装与恢复演练

任务：

- 从空数据目录安装 v1.0 并创建测试数据。
- 执行备份、恢复、失败回滚、卸载保留数据。
- 验证 schema、当前配置与未知副作用状态。

退出条件：全新安装可用；当前数据恢复不扩大权限、不重复动作，失败可回到 safeguard。

### 阶段 5：安全与体验收口

任务：

- 跑安全/隐私矩阵和诊断 canary。
- 统一 Web/Desktop/CLI 文案、加载、空状态、错误与恢复入口。
- 检查键盘操作、窗口/托盘降级和 Voice 停止行为。

退出条件：无 P0 安全问题；失败路径对普通用户可理解。

### 阶段 6：发布候选与 Soak

任务：

- 构建 RC wheel，在 Windows 10 主机临时空目录隔离安装并测试；不推断 Windows 11 实机结果。
- 执行长时或加速 soak，观察内存、线程、队列、句柄、临时文件和错误趋势。
- 冻结依赖与构建命令，生成校验和。

退出条件：RC 无未解释资源增长；全部 P0 清零。

### 阶段 7：正式发布

任务：

- 确认版本为 `1.0.0`，同步 README、状态文档、运维手册与 Release Notes。
- 完成最终回归、构建、全新安装与恢复演练。
- 打标签前检查仓库干净、产物版本一致和已知限制完整。

退出条件：Definition of Done 全部勾选，生成可追溯发布证据。

---

## 8. 测试矩阵

### Baseline

- 全量 pytest、单文件测试和关键失败项独立运行结果一致。
- compileall、wheel build、安装导入与 `git diff --check` 通过。
- 时钟、随机、网络、端口和用户数据均可控或隔离。

### User Journey

- 首次安装、缺配置、错误配置、配置完成和首次对话。
- 显式记忆、自动记忆、检索、软忘记与重启后读取。
- Life HUD 开幕/重复开幕/落幕/外部失败/事实源确认。
- Proactive 投递、Quiet/Night、Inbox 与 Reflection 引用。

### Permission / Recovery

- 批量确认、部分批准、拒绝、TTL、撤销和重启恢复。
- Planner 等待用户/权限、未知写结果和对账。
- 备份校验失败、恢复中断、损坏库、只读目录和磁盘失败。

### Voice / Presence

- 显式朗读、自动朗读、Night/Quiet 边界、停止、录音取消和临时文件清理。
- Desktop 单实例、端口冲突、快捷键冲突、托盘降级和 token 边界。
- 无 Voice/Desktop 可选依赖时仍可使用 CLI/Web。

### Security / Privacy

- Prompt Injection 不改变权限或人格指令。
- 路径逃逸、SSRF、私网地址、参数走私和超长响应被拒绝。
- 日志、metrics、trace、audit、SSE、Toast 与诊断无隐私 canary。

### Packaging / Compatibility

- v1.0 独立新装、重复安装和旧测试数据目录存在时的明确提示。
- Windows 10 实测、Python 3.12+；Windows 11 列为未实测环境。
- 重复安装、可选自启、卸载与保留数据幂等。

---

## 9. 集中黑盒验收

### Case A：新用户第一次使用

在 Windows 10 临时空目录安装两个 wheel，验证版本与 Tool Package 导入；空配置启动 Web Setup Mode 并通过 `--doctor` 获得配置提示。Desktop 启动边界由自动化测试覆盖，不宣称执行了会修改当前用户环境的真实安装。

### Case B：有事找朝汐

通过公开 HTTP Mock 契约执行铁幕开幕、查询当前状态并落幕。朝汐调用唯一 `lifehud` Tool、写入前请求权限、回读事实源，并给出自然语言结果；不把 Mock 结果表述为真实 Life HUD 服务实测。

### Case C：失败但不失控

Provider 503、Life HUD 写入连接中断、审计失败分别发生时，系统有限重试、正确降级或失败关闭，不重复未知写操作。

### Case D：夜间语音

在 Night 起止边界测试显式朗读、自动朗读和 Quiet。行为与文档一致，不依赖测试运行时的真实小时。

### Case E：断电恢复

在 Planner 等待用户、等待权限和写结果未知阶段强制退出。重启后可恢复的继续，不可安全恢复的要求确认或对账。

### Case F：全新安装与恢复

在临时空目录安装 v1.0 wheel；使用临时数据目录创建各 SQLite Store，并验证 Memory 数据在备份、继续修改、恢复旧快照后回到预期状态，恢复前 safeguard 可再次校验。

### Case G：隐私攻击

外部 ToolResult 含 prompt injection、密钥 canary 和超长文本；不得越权，且 canary 不进入日志、指标、通知和诊断。

### Case H：日常长时运行

执行 500 次加速 Interface 请求，验证响应缓存与 Conversation 上限；Voice 临时文件、后台任务关闭和 SSE 行为由独立回归覆盖。该结果是加速 soak，不宣称完成真实多小时实机运行。

---

## 10. 交付物

- v1.0 源码与 `1.0.0` 可复现 wheel。
- 校正后的 README、`CODEBASE_STATUS.md` 和 v1.0 Release Notes。
- 更新后的安装、卸载、备份、恢复与故障排查手册。
- v1.0 全新安装与恢复 fixture、自动化测试。
- 三条日用闭环的自动化测试和黑盒验收记录。
- Windows 10 RC 隔离冒烟记录、Windows 11 未实测说明、soak 报告和构建校验和。
- 已知限制与 P2 后续清单。

---

## 11. Definition of Done

- [x] Voice 时间依赖测试已修复，Night/Quiet/显式朗读语义已冻结。
- [x] 全量测试稳定全绿，无已知执行顺序或本机状态依赖。
- [x] `pyproject.toml`、`__version__`、API、诊断、wheel 与文档均为 `1.0.0`。
- [x] `CODEBASE_STATUS.md` 和 README 不再包含相互冲突的旧基线。
- [x] 三条日用闭环通过自动化契约与纵向集成验收；真实外部服务不作为测试依赖。
- [x] v1.0 隔离全新安装、备份恢复和卸载保留数据脚本边界通过；不迁移旧测试数据。
- [x] Permission、未知副作用、审计失败与 Prompt Injection 边界无回退。
- [x] 日志、metrics、trace、audit、通知和诊断通过自动化隐私 canary。
- [x] Windows 10 主机隔离安装与导入通过；Windows 11 未实测并已写入限制。
- [x] Release Candidate 加速 soak 无已知无界资源增长。
- [x] P0 为零；P2 在发布说明中可见。
- [x] 最终 `pytest`、`compileall`、wheel build 与 `git diff --check` 全绿。

---

## 12. 推荐提交切片

```text
test(voice): make night and explicit speech policy deterministic
docs(status): reconcile v0.9 baseline and current limitations
feat(onboarding): add actionable first-run diagnostics
test(journeys): cover memory lifehud and proactive reflection loops
feat(upgrade): harden v0.9 to v1.0 migration and rollback
fix(ux): unify permission failure and recovery feedback
test(security): complete v1.0 privacy and boundary regression
build(windows): validate reproducible v1.0 release candidate
test(soak): certify bounded long-running behavior
docs(v1.0): finalize user operations and release notes
chore(release): set version 1.0.0
```

每个提交必须同时包含对应测试或验证记录；涉及 schema、权限、外部写入与恢复的提交不得只改实现而不补失败路径。

---

## 13. 开发纪律

1. 每个阶段先写验收，再写实现；以用户旅程验证跨模块结果。
2. 新需求先判断是否是 v1.0 日用闭环所必需；否则进入 P2。
3. 每个切片保持可运行、可回退，不把所有改动堆到发布提交。
4. 任何“已完成”都要有测试、日志、构建或人工验收证据。
5. 版本、能力、限制、测试数发生变化时，同提交更新 `CODEBASE_STATUS.md`。
6. 不使用真实用户数据、密钥或私人内容作为发布证据。

---

## 14. 一句话验收

> **把一件真实的小事交给朝汐：她能听懂、记住或规划、找到正确工具、在需要时先问、执行后核实；即使中途失败或重启，也不会丢数据、越权或假装已经完成。**
