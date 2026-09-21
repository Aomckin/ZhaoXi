# Zhaoxi v1.0 前置 · LifeHUD-Tool 解耦开发任务书

> 性质：v1.0 正式版前置架构整理  
> 开发分支：`v1.0`  
> 起点提交：`87eb9c6 feat: complete v0.9 reliability hardening`  
> 起草日期：2026-09-01  
> 核心约束：**Life HUD 对 Zhaoxi 只能表现为一个 Tool；Life HUD 项目只读，不在本任务中修改。**

---

## 1. 任务背景

最初架构要求是 Core 与 Tools 解耦，具体业务系统不应成为 Zhaoxi Core 的硬编码依赖；Tool 与 Core 也不共用版本号。

当前实现虽然把 Life HUD 代码放在 `src/zhaoxi/tools/integrations/lifehud/`，但仍存在结构性耦合：

- `src/zhaoxi/cli.py` 直接 import、构造和注册 `LifeHudClient`。
- `Settings` 直接包含一组 `lifehud_*` 配置。
- `CognitiveRouter` 直接识别 “LifeHUD / Life HUD / 铁幕 / 开幕 / 落幕”。
- Core Agent 中存在 Life HUD 专用成功与失败文案。
- `workflows/lifehud/` 位于 Core 仓库级 Workflow 目录，并引用多个 Life HUD Tool 名。
- Life HUD 当前被拆成 10 个 Context READ Tool、1 个 Focus READ Tool和 2 个 Focus WRITE Tool。
- 测试集中在 Core 的 Workflow 测试目录，边界测试与 Tool 自身测试未分开。

这意味着当前实际关系更接近：

```text
Zhaoxi Core
├── 知道 Life HUD 配置
├── 知道 Life HUD Client
├── 知道 Life HUD 意图词
├── 知道 Life HUD Workflow ID
├── 知道 Life HUD 错误文案
└── 注册 13 个 lifehud_* Tool
```

目标关系应改为：

```text
Zhaoxi Core
├── 发现 Tool Package
├── 注册一个 Tool
├── 按调用参数计算权限与副作用
├── 加载 Tool Package 提供的 Workflow/Intent 元数据
└── 只理解通用 ToolResult / ReliabilityError

tools/lifehud-tool
├── Life HUD API Client
├── schema 与时间语义
├── 一个 lifehud Tool
├── Life HUD Workflow
├── Life HUD 意图提示元数据
└── Tool 自身测试
```

---

## 2. 不可违反的边界

### 2.1 Life HUD 项目只读

本任务不得修改 Life HUD 项目的源码、数据库、schema、API、配置或测试。允许的操作仅包括：

- 阅读已有 API 文档和响应样例；
- 使用 MockTransport/Fake Server 固化当前契约；
- 在人工冒烟时调用其公开 HTTP API；
- 把发现的契约问题记录为兼容说明，而不是回写 Life HUD 项目。

如果当前 API 无法支持某项能力：

> **LifeHUD-Tool 明确返回“不支持”，不得通过直读数据库、复制业务逻辑或修改 Life HUD 来绕过。**

### 2.2 Life HUD 是唯一事实源

- Zhaoxi 不复制睡眠、饮食、Focus、任务、Dream、Journal 等生活事实数据库。
- 实时事实优先通过 LifeHUD-Tool 查询。
- Memory 可以保存稳定偏好和关系，不把可重新查询的 Life HUD 事实当成长期真相。
- 不读取 Life HUD 内部数据库、JSON 文件或私有目录。

### 2.3 Life HUD 只能是一个 Tool

Core Registry 中只允许存在一个 Life HUD Tool：

```text
name = "lifehud"
```

禁止继续注册：

```text
lifehud_today
lifehud_recent
lifehud_status
lifehud_focus
lifehud_tasks
lifehud_dreams
lifehud_life
lifehud_journal
lifehud_media
lifehud_growth
lifehud_focus_current
lifehud_focus_start
lifehud_focus_complete
```

这些能力应成为 `lifehud` 的受限 `operation`，而不是独立 Tool。

---

## 3. 目标目录

建议在仓库根目录新增独立 Tool 工作区：

```text
tools/
└── lifehud-tool/
    ├── pyproject.toml
    ├── README.md
    ├── src/
    │   └── zhaoxi_lifehud_tool/
    │       ├── __init__.py
    │       ├── package.py
    │       ├── tool.py
    │       ├── operations.py
    │       ├── client.py
    │       ├── models.py
    │       ├── errors.py
    │       └── time_display.py
    ├── workflows/
    │   ├── iron_curtain_open_v1.yaml
    │   └── iron_curtain_close_v1.yaml
    └── tests/
        ├── test_contract.py
        ├── test_read_operations.py
        ├── test_write_operations.py
        ├── test_permissions.py
        └── test_workflows.py
```

Core 只保留通用设施：

```text
src/zhaoxi/tools/
├── base.py
├── registry.py
├── discovery.py
├── package.py
└── builtin/
```

最终删除 Core 内的：

```text
src/zhaoxi/tools/integrations/lifehud/
workflows/lifehud/
```

目录迁移必须使用版本控制可追踪的移动，并在兼容测试全绿后删除旧入口。

---

## 4. 单 Tool 调用契约

### 4.1 输入模型

建议统一为：

```json
{
  "operation": "focus.current",
  "arguments": {}
}
```

第一阶段操作集合：

| operation | 含义 | 权限 | 自动重试 |
|---|---|---:|---:|
| `context.today` | 今日整体上下文 | READ | 是，有界 |
| `context.recent` | 近期摘要 | READ | 是，有界 |
| `context.status` | 当前状态 | READ | 是，有界 |
| `focus.current` | 当前 Focus | READ | 是，有界 |
| `context.tasks` | 任务 | READ | 是，有界 |
| `context.dreams` | Dream/Goal | READ | 是，有界 |
| `context.life` | 睡眠、饮食等生活事实 | READ | 是，有界 |
| `context.journal` | 日记与时间线 | READ | 是，有界 |
| `context.media` | 作品与 Session | READ | 是，有界 |
| `context.growth` | 成长状态 | READ | 是，有界 |
| `focus.start` | 开启铁幕 Focus | WRITE | 否 |
| `focus.complete` | 结束铁幕 Focus | WRITE | 否 |

`operation` 必须是封闭枚举；不得允许任意 URL、HTTP method、path 或 JSON body 透传。

### 4.2 输出模型

所有操作返回统一 ToolResult：

```json
{
  "success": true,
  "content": "已从 Life HUD 读取事实。",
  "data": {},
  "metadata": {
    "fact_source": "lifehud",
    "operation": "focus.current",
    "schema_version": "1",
    "retryable": false,
    "safe_to_replay": true
  }
}
```

`data` 保存结构化结果；`content` 是稳定、简短的边界说明。具体自然语言回答由 Agent 生成，不在 Core 写 Life HUD 专用回复模板。

### 4.3 动态权限

当前 `Tool.permission` 和 `Tool.side_effects` 是类级静态属性，无法安全表达一个 Tool 中 READ 与 WRITE 并存。Core 必须先支持逐调用解析：

```python
tool.permission_for(arguments)
tool.side_effects_for(arguments)
tool.resource_scope(arguments)
tool.safe_to_replay(arguments)
```

要求：

- 默认实现继续返回现有静态声明，保证内置 Tool 兼容。
- `lifehud` 根据已验证的 `operation` 返回权限。
- 未知 operation 在进入 PermissionGateway 前直接拒绝。
- 权限确认冻结完整 operation、参数摘要、资源范围和 invocation ID。
- WRITE 不因网络错误自动重放；未知结果进入 `needs_reconciliation`。
- 模型不能通过伪造 metadata 或嵌套字段降低权限。

---

## 5. Tool Package 契约

### 5.1 Core 所需的最小接口

新增通用 `ToolPackage` 协议，建议提供：

```python
class ToolPackage(Protocol):
    package_id: str
    package_version: str

    def create_tools(self, config: Mapping[str, object]) -> list[Tool]: ...
    def workflow_paths(self) -> list[Path]: ...
    def routing_hints(self) -> list[RoutingHint]: ...
    def diagnostics(self) -> dict[str, object]: ...
```

对 LifeHUD-Tool：

- `package_id = "lifehud-tool"`
- `create_tools()` 必须只返回一个 `LifeHudTool`。
- Workflow 与 routing hint 随包提供，不写进 Core。
- Core 不 import `LifeHudClient`、Life HUD model 或 Life HUD error。

### 5.2 发现机制

优先使用 Python entry point，开发环境允许显式本地路径安装：

```toml
[project.entry-points."zhaoxi.tools"]
lifehud = "zhaoxi_lifehud_tool.package:create_package"
```

Core 启动流程：

```text
读取通用 Tool 配置
→ 发现已安装 Tool Package
→ 校验 package_id/version
→ 创建 Tool
→ 注册 Registry
→ 加载该包 Workflow 与 routing hint
→ 输出脱敏诊断
```

单个外部 Tool 加载失败不得破坏基础对话启动；但必须在诊断中明确标记 unavailable。

### 5.3 配置边界

Core Settings 不再声明 Life HUD 专用字段。建议使用通用命名空间：

```dotenv
ZHAOXI_TOOL_LIFEHUD_ENABLED=true
ZHAOXI_TOOL_LIFEHUD_BASE_URL=http://127.0.0.1:8025
ZHAOXI_TOOL_LIFEHUD_CONTEXT_PATH=/api/agent/context
ZHAOXI_TOOL_LIFEHUD_SCHEMA_VERSION=1
ZHAOXI_TOOL_LIFEHUD_TIMEOUT_SECONDS=10
ZHAOXI_TOOL_LIFEHUD_MAX_RETRIES=2
ZHAOXI_TOOL_LIFEHUD_DISPLAY_TIMEZONE=Asia/Shanghai
```

通用 Loader 只负责收集 `ZHAOXI_TOOL_<ID>_*`；具体字段、默认值和校验属于 LifeHUD-Tool。

旧 `ZHAOXI_LIFEHUD_*` 在一个兼容周期内可由 LifeHUD-Tool 读取并输出弃用警告，Core 不再解释它们。

---

## 6. 路由与 Workflow 解耦

### 6.1 Router

删除 Core 中这些业务硬编码：

- `lifehud` / `life hud` 关键词判断；
- “开幕/开始铁幕”到固定 Workflow ID 的映射；
- “落幕/结束铁幕”到固定 Workflow ID 的映射；
- Life HUD 专用 prompt 文本。

改由 Tool Package 提供声明式 `RoutingHint`：

```text
intent_id
examples
target: TOOL | WORKFLOW
tool_name / workflow_id
input_mapping
priority
```

确定性 fallback 只遍历已启用 Tool Package 的 hint，不知道 Life HUD 的具体名字。

### 6.2 Workflow

铁幕 Workflow 迁入 LifeHUD-Tool，并统一调用：

```yaml
tool: lifehud
with:
  operation: focus.current
  arguments: {}
```

写步骤：

```yaml
tool: lifehud
with:
  operation: focus.start
  arguments:
    title: ${input.title}
```

Workflow 仍执行“写前读 → 写 → 写后读”，不得因合并为单 Tool 而丢失事实核验。

### 6.3 Agent 文案

删除 Core 中 Life HUD 专用结果文案。ToolResult metadata 和 Workflow result 应提供足够状态，让通用 Agent 生成：

- 已完成；
- 未完成；
- 状态未知，需要对账；
- 事实源当前不可用。

通用错误契约保留机器码，LifeHUD-Tool 负责将 HTTP 语义映射为该契约。

---

## 7. 一次性切换策略

### 7.1 Tool 名切换

内部 Workflow 与测试一次性迁移到 `lifehud` + `operation`。

不注册旧 Tool alias，因为这会违反“Registry 中只有一个 Life HUD Tool”。早期版本仅产生人工测试数据，v1.0 允许重置旧 Workflow/Planner/Permission 状态；旧写 Step 不在新版本中自动重放。

### 7.2 旧人工测试状态

若检测到以下旧人工测试状态，应失败关闭或提示重置，不做原位迁移：

- 等待权限的 `lifehud_focus_start/complete` invocation；
- 未完成的铁幕 Workflow Run；
- `needs_reconciliation` 写操作；
- Planner Observation 中旧 Tool 名。

安全规则：

- 已冻结的旧写请求不得自动改写后直接执行。
- 等待权限的旧请求应失效关闭，提示用户重新发起。
- 未知写结果保持对账状态，不自动重放。
- 旧历史不属于 v1.0 兼容承诺，可通过移动旧 `.zhaoxi` 目录保留副本。

### 7.3 配置切换

- v1.0 只以新 Tool namespace 为配置契约。
- 旧配置不作为 v1.0 发布兼容承诺；用户按 `.env.example` 重新配置。
- 发布说明明确全新安装与旧测试目录重置策略。

---

## 8. 前置开发路线

### 阶段 0：冻结现状与契约

任务：

- 固化当前 13 个 Tool 的行为、HTTP 请求、schema、错误码、时间显示和权限测试。
- 建立 Life HUD API Mock fixtures；不依赖真实 Life HUD 项目运行。
- 盘点持久 Workflow/Permission/Planner 中可能保存的旧 Tool 名。
- 记录当前 Core 耦合清单。

退出条件：现有行为可由测试完整描述；整个阶段不修改 Life HUD 项目。

### 阶段 1：Core 动态权限能力

任务：

- 为 Tool 增加逐调用 permission、side effect、resource scope 和 replay 声明。
- 改造 ToolExecutor、PermissionGateway、批量确认与审计使用解析后的冻结策略。
- 保证所有旧 Tool 通过默认实现继续工作。
- 增加参数篡改、权限降级、恢复篡改和未知 operation 测试。

退出条件：一个 Tool 可安全承载 READ/WRITE 操作，现有权限测试无回退。

### 阶段 2：通用 Tool Package 与发现器

任务：

- 定义 `ToolPackage`、entry point、配置命名空间、Workflow path 与 routing hint 契约。
- 改造启动装配，使 Core 不直接 import 外部业务 Tool。
- Tool Package 加载失败时基础 Core 可启动并可诊断。
- 给未来 calendar-tool/files-tool 写最小 fake package 契约测试，证明机制非 Life HUD 特供。

退出条件：Core 可在不知道具体业务包的情况下发现并注册 Tool。

### 阶段 3：建立独立 LifeHUD-Tool

任务：

- 创建 `tools/lifehud-tool/` 独立包和版本号。
- 迁移 Client、Models、Errors、TimeDisplay 与 Mock fixtures。
- 实现唯一 `lifehud` Tool 和封闭 operation dispatcher。
- 将配置解析与诊断移入包内。

退出条件：`create_tools()` 只返回一个 Tool；全部读写契约测试通过。

### 阶段 4：Workflow 与 Router 解耦

任务：

- 将铁幕 Workflow 迁入 LifeHUD-Tool。
- 将所有步骤改为调用 `lifehud` + operation。
- 用 package routing hints 替代 Core 的 Life HUD/铁幕硬编码。
- 删除 Core Agent 中 Life HUD 专用文案。

退出条件：未安装 LifeHUD-Tool 时，Core 源码、Router 和启动入口均不引用 Life HUD。

### 阶段 5：状态与配置切换

任务：

- 对旧 Workflow definition、等待权限、Planner trace 和对账状态失败关闭。
- 明确旧 `ZHAOXI_LIFEHUD_*` 不属于 v1.0 配置契约，按新 Tool namespace 重新配置。
- 验证旧状态不自动执行写请求、不扩大权限。

退出条件：旧人工测试状态不会自动重放；Registry 仍只出现一个 Life HUD Tool。

### 阶段 6：删除旧实现与全量验证

任务：

- 删除 Core 内 `tools/integrations/lifehud` 与仓库级 `workflows/lifehud`。
- 清理旧 imports、settings、router 分支、文案、测试与文档。
- 运行 Core 全量回归、Tool 包测试、compileall、build 和 `git diff --check`。
- 使用只读方式对真实 Life HUD 环境做查询冒烟；写操作仅在用户明确授权的测试环境执行。

退出条件：源码搜索证明 Core 无 Life HUD 业务依赖；所有验收通过。

### 阶段 7：接回 v1.0 正式版路线

任务：

- 更新 v1.0 正式版任务书的基线、测试数、已知限制和 Tool 架构。
- 分别冻结 Zhaoxi Core 与 lifehud-tool 的版本。
- 将 LifeHUD-Tool 安装、升级、禁用和诊断纳入正式版发布流程。

退出条件：后续 v1.0 工作只依赖通用 Tool Package 契约。

---

## 9. 测试矩阵

### Core Contract

- 静态权限旧 Tool 完全兼容。
- 动态权限在参数校验后、执行前冻结。
- WRITE 不自动重放，READ 才允许有界重试。
- Registry 对 Life HUD 只有 `lifehud` 一个 Schema。
- 外部 Tool Package 缺失或损坏不阻止基础对话启动。

### LifeHUD-Tool

- 12 个 operation 全部有输入、输出和错误测试。
- schemaVersion 不匹配、无效 JSON、400/404/409/5xx、timeout 与离线。
- UTC 原始事实不修改，仅 observation 按展示时区转换。
- null、空集合和未知可选字段前向兼容。
- 任意 path/method/body 透传被拒绝。

### Permission / Recovery

- `focus.current` 自动 READ。
- `focus.start/complete` 进入 WRITE 确认。
- 修改已冻结 operation 或 arguments 不能复用授权。
- 旧 pending 写请求升级后不自动执行。
- unknown outcome 保持 reconciliation，不重放。

### Workflow / Routing

- 开幕、重复开幕、落幕、错误落幕和写后核验。
- routing hints 已安装时生效，禁用包时不生效。
- Router/Core 文件不含 Life HUD 业务关键词或 Workflow ID。
- Workflow Package 未加载时返回能力不可用，不崩溃。

### Boundary

- 测试期间不访问 Life HUD 数据库或项目内部文件。
- 自动化不要求真实 Life HUD 服务。
- 真实服务仅通过公开 HTTP API 冒烟。
- 日志、trace、metrics 与 audit 不含用户生活正文或密钥。

---

## 10. 集中黑盒验收

### Case A：单 Tool 可见性

执行 `/tools` 或读取模型 Tool Schema，只出现一个 `lifehud`，其 operation 为封闭枚举，不出现旧的 13 个名称。

### Case B：读写动态权限

查询今日状态不弹确认；开启铁幕必须确认。把已确认参数从 `focus.start` 换成其他写操作后授权失效。

### Case C：铁幕闭环

“开幕”由 package routing hint 进入 package Workflow，依次执行 `focus.current → focus.start → focus.current`；Core 不知道铁幕业务细节。

### Case D：卸载或禁用 Tool

禁用 LifeHUD-Tool 后，基础对话、Memory、Planner 和其他 Tool 正常启动；相关请求明确提示能力未安装或未启用。

### Case E：旧人工测试状态

准备包含旧 Tool 名、等待权限和未知写结果的 fixture。v1.0 不读取或迁移旧状态，不重复写、不扩大权限，需要重发的请求给出说明。

### Case F：Life HUD 离线

关闭真实服务或让 Mock 返回 503。READ 有界重试后失败；WRITE 不自动重放；朝汐不伪造事实或成功。

### Case G：只读项目边界

整个改造的版本差异只出现在 Zhaoxi 仓库和新 `tools/lifehud-tool` 中，Life HUD 项目保持零修改。

---

## 11. 交付物

- 通用动态权限 Tool 契约及切换测试。
- 通用 ToolPackage、发现器、配置命名空间和诊断。
- 独立 `tools/lifehud-tool/` Python 包。
- 唯一 `lifehud` Tool 与封闭 operation 集。
- 随包交付的铁幕 Workflow 与 routing hints。
- 旧人工测试状态重置与失败关闭策略。
- LifeHUD-Tool README、版本路线、安装和故障排查说明。
- Core 与 Tool 包各自的测试报告。
- 更新后的 v1.0 正式版任务书、README 和 CODEBASE_STATUS。

---

## 12. Definition of Done

- [x] Life HUD 项目保持只读，零源码、数据和配置修改。
- [x] Core Registry 中 Life HUD 只注册为一个 `lifehud` Tool。
- [x] READ/WRITE 权限按已验证 operation 动态解析并冻结。
- [x] Core 启动入口不 import 或构造 LifeHudClient。
- [x] Core Settings 不声明 Life HUD 专用字段。
- [x] Core Router 不硬编码 Life HUD、铁幕或专用 Workflow ID。
- [x] Core Agent 不包含 Life HUD 专用结果文案。
- [x] Life HUD Client、schema、Workflow、routing hints 和测试位于独立 Tool 包。
- [x] 未安装 LifeHUD-Tool 时 Core 仍可启动和使用。
- [x] 旧人工测试状态不迁移、不自动重放，也不扩大权限。
- [x] 所有操作只能调用已声明的公开 HTTP API，不直读 Life HUD 内部数据。
- [x] Core 全量测试、LifeHUD-Tool 测试、compileall、build 与 diff check 全绿。
- [x] v1.0 正式版任务书已更新为新的解耦基线。

---

## 13. 推荐提交切片

```text
test(lifehud): freeze current integration contracts
refactor(tools): support invocation-scoped permission policy
feat(tools): add generic package discovery and routing hints
build(lifehud-tool): scaffold independent tool package
refactor(lifehud): expose one operation-based tool
refactor(workflow): move iron curtain flows into lifehud-tool
refactor(router): remove lifehud-specific core routing
docs(lifehud): define legacy test-state reset policy
refactor(config): move lifehud settings into tool namespace
test(lifehud): certify package boundary and read-only source access
docs(tools): document independent lifehud-tool lifecycle
```

每个切片都必须保持 Core 可启动。动态权限、旧状态失败关闭和写操作的提交必须同时包含“不自动重放”测试。

---

## 14. 与 v1.0 正式版路线的关系

本任务原为 v1.0 阶段 0 之前的前置门，现已完成：

```text
冻结现有 Life HUD 契约
→ Core 支持通用 Tool Package 与动态权限
→ LifeHUD-Tool 独立成包
→ 移动 Workflow / Router / 配置并重置旧人工测试状态
→ 删除 Core 业务耦合
→ 回到 v1.0 正式版阶段 0
```

执行期间没有扩展新的 Life HUD 写业务；完成后新增能力仍必须只通过独立 Tool Package 与公开 HTTP 契约进入。

---

## 15. 一句话验收

> **拔掉 LifeHUD-Tool，朝汐仍是一套完整可运行的 Agent Core；装上 LifeHUD-Tool，Registry 只多出一个 `lifehud`，所有生活事实与铁幕操作都通过它的受限 operation、安全权限和公开 HTTP API 完成。**
