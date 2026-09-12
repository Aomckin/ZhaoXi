# Zhaoxi v1.1.8 Development Task
# 动态 ToolProvider 与 MCP 隔离接入

> 版本：v1.1.8
> 基线：v1.1.7 ACTIVE Conversation Closure
> 性质：Core 扩展边界 / 外部工具协议接入
> 核心目标：让外部协议提供的每一项 Tool 动态进入现有 ToolRegistry，同时保持 Agent、Planner 与 Core 对具体协议无感。

## 1. 强制架构边界

Core 仅允许增加协议无关的 `ToolProvider` 扩展能力：

```text
ToolProvider
  -> provide_tools() -> list[Tool]
  -> close()

ToolRegistry
  -> register_provider()
  -> refresh_provider()
  -> unregister_provider()
  -> close_providers()
```

Core 禁止：

- import MCP SDK、MCP Client 或 MCP transport；
- 解析 MCP schema、content 或 annotations；
- 管理 stdio MCP Server 进程；
- 在 Agent 或 Planner 中增加 MCP 分支。

## 2. MCP Package 边界

以下能力必须全部位于 `tools/mcp/`：

- MCP stdio JSON-RPC Client；
- initialize、notifications/initialized、tools/list 与 tools/call；
- MCP Server 启动、超时、异常和关闭；
- MCP inputSchema 到 Zhaoxi Tool schema/输入校验的适配；
- MCP annotations 到现有权限与副作用声明的映射；
- MCP content、structuredContent、isError 到 ToolResult 的归一化；
- 已安装 Server 的本地路径、参数、环境和工作目录。

不得实现单一的“万能 MCP Bridge Tool”。每个远端 MCP Tool 必须成为一个独立的 Zhaoxi `Tool`，拥有独立名称、描述、schema、权限和资源范围。

## 3. Registry 行为

- Provider 注册必须先完整发现并校验 Tool，再原子写入 Registry。
- Provider 内部重名、与既有 Tool 冲突或权限声明非法时，不得留下部分注册状态。
- Refresh 失败必须保留旧 Tool 集。
- Agent 每轮继续调用 `registry.schemas()`，动态刷新后自然获得新 schema。
- Planner、Workflow 与 Agent 继续共用同一 Registry 和 ToolExecutor。

## 4. 命名与权限

MCP Tool 公共名称使用稳定 server 前缀：

```text
mcp_<server_id>_<remote_tool_name>
```

名称只保留 function calling 允许的字符；超过长度限制时使用稳定哈希后缀。

权限映射：

- `readOnlyHint=true` -> READ / NONE；
- `destructiveHint=true` -> DELETE / DATA_DELETION；
- 其他操作 -> WRITE，并根据 `openWorldHint` 区分本地或外部写入副作用。

所有调用仍必须经过 `ToolExecutor / PermissionGateway`，不得由 MCP Client 自行绕过权限。

## 5. 本次 Server 范围

- Everything Windows Search；
- MCP 官方 reference Everything；
- Filesystem；
- Memory；
- Sequential Thinking；
- Fetch；
- Git；
- Time；
- Microsoft Playwright MCP。

Filesystem 默认只开放朝汐进程工作目录。Memory 和 Playwright 产生的本地数据放入 `tools/mcp/data/`。

## 6. 配置与默认关闭

延续 Tool Package 的显式授权原则：安装不等于启用。

```dotenv
ZHAOXI_TOOL_MCP_ENABLED=true
ZHAOXI_TOOL_MCP_SERVERS=all
ZHAOXI_TOOL_MCP_TIMEOUT_SECONDS=15
```

`SERVERS` 可使用逗号选择子集。某一个 Server 启动失败时，应记录该 Provider 错误并继续装配其他 Server。

## 7. 验收标准

1. Core 源码没有 MCP-specific import。
2. 每个 MCP Tool 作为独立 Tool 出现在 Registry。
3. Agent 和 Planner 无需知道 Tool 来源。
4. MCP schema、必填项和基础约束在远端调用前校验。
5. READ 自动执行，写入与删除继续遵守既有权限策略。
6. Web/CLI 关闭时不遗留 stdio Server 子进程。
7. 9 个本地 Server 均能完成 initialize 与 tools/list。
8. 全量既有回归通过。

## 8. 非目标

- 不接入 MCP prompts、resources 或 sampling；
- 不把 MCP 协议类型加入 Core；
- 不为 Agent 增加独立 MCP Loop；
- 不绕过现有 Tool output 长度、信任标记、审计或权限边界；
- 不自动安装 Everything 桌面程序或修改系统级配置。
