# v1.1.8 动态 ToolProvider 与 MCP 接入开发报告

> 基线提交：`73d2938`
> 开发分支：`v1.1.8`
> 日期：2026-09-10

## 结果

本版完成协议无关的动态 ToolProvider 扩展，并将 MCP 实现完全隔离在 `tools/mcp/`。没有实现单一 MCP Bridge Tool；远端 `tools/list` 返回的每一项能力都会转换成一个独立 Zhaoxi Tool，统一进入现有 ToolRegistry。

Agent、Planner 和 Workflow 不区分内置 Tool、静态 Tool Package 或动态 Provider Tool，继续共用现有 schema、ToolExecutor、PermissionGateway、审计、输出截断与 Tool observation 回灌链路。

## Core 变更

- SDK 从 1.0 升级至 1.1，新增 `ToolProviderProtocol`：`provider_id`、`provide_tools()`、`close()`。
- ToolRegistry 新增 Provider 注册、原子刷新、卸载和关闭能力，并追踪每个 Provider 的 Tool 所有权。
- Provider 首次注册和刷新均先完整校验名称冲突与权限/副作用声明，不暴露半完成状态。
- Tool Package 装配支持可选 `create_tool_providers(config)`，原有 `create_tools(config)` 保持兼容。
- Startup diagnostics 使用同一 Provider 发现路径，并在诊断结束后关闭 Provider。
- CLI 与 Web 生命周期退出时调用通用 Registry 关闭接口；测试替身没有 Registry 时安全跳过。

Core 中没有引入 MCP SDK、MCP transport、MCP schema 或 MCP Client import。

## MCP Package

`tools/mcp/` 提供：

- 标准库实现的持久 stdio JSON-RPC Client；
- initialize、tools/list、tools/call 和 notifications/initialized；
- 每 Server 独立进程、串行请求、超时、stderr 排空及 terminate/kill 收尾；
- MCP JSON Schema 到 Pydantic 输入边界和 function schema 的适配；
- Tool 名称清洗、server 命名空间与超长名称稳定哈希；
- annotations 到 READ/WRITE/DELETE 和 SideEffect 的保守映射；
- content、structuredContent 与 isError 到 ToolResult 的归一化；
- 本机已安装 Server inventory 与可选子集配置。

MCP Tool 的 `resource_scope` 只包含 server 与远端 Tool 名称，不把原始参数复制进确认文本。ToolExecutor 仍负责参数摘要哈希、确认绑定、不可信输出标记和长度限制。

## 已安装与实测

完成握手并动态注册：

| Provider | Tool 数 |
|---|---:|
| Everything Search | 2 |
| Reference Everything | 13 |
| Filesystem | 14 |
| Memory | 9 |
| Sequential Thinking | 1 |
| Fetch | 1 |
| Git | 12 |
| Time | 2 |
| Playwright | 24 |
| 合计 | 78 |

78 个 Tool 无命名冲突。根据各 Server annotations 映射为 41 READ、13 WRITE、24 DELETE。Time 的真实 `get_current_time` 调用成功返回 `Asia/Shanghai` 时间。

三个上游仓库的源码和依赖安装在 `tools/mcp/`，并由本目录 `.gitignore` 排除生成依赖、虚拟环境、运行数据与嵌套 Git checkout；仓库只提交朝汐自己的 Provider/Adapter/配置与测试代码。

## 配置

Package 遵循“发现不等于授权”，默认关闭：

```dotenv
ZHAOXI_TOOL_MCP_ENABLED=true
ZHAOXI_TOOL_MCP_SERVERS=all
ZHAOXI_TOOL_MCP_TIMEOUT_SECONDS=15
```

也可只启用部分：

```dotenv
ZHAOXI_TOOL_MCP_SERVERS=filesystem,time,playwright
```

Provider Package 已通过 `zhaoxi.tools` entry point 以 editable 方式安装到当前项目虚拟环境。本地源码 discovery 仍可作为开发模式入口，二者按 package_id 去重。

## 验证

- Core 全量回归：**475 passed、1 skipped、1 warning**。
- MCP 专项：**3 passed**。
- Core、Package 与 MCP 联合专项：**23 passed**。
- 9 Provider 同时装配：**78 tools、0 errors**。
- 9 Provider 关闭：**0 shutdown errors**，无残留 MCP 子进程。
- `compileall` 与 `git diff --check` 通过。
- warning 为既有 Starlette/httpx 弃用提示。

专项测试覆盖 MCP schema 前置校验、独立 Tool 注册、READ 调用、WRITE 权限暂停、Agent 构建装配、Provider 原子刷新与关闭。

## 已知限制

- Everything Search MCP 已安装且协议握手正常，但本机没有检测到其业务依赖 `es.exe`；实际文件搜索调用会失败并返回 ToolResult 错误。未自动安装系统级 Everything 软件。
- 当前范围只接入 MCP Tools；prompts、resources、sampling 和远端 HTTP transport 不在本版范围。
- 当前 78 个 Tool 同时启用会增加模型 tool schema 上下文；可通过 `ZHAOXI_TOOL_MCP_SERVERS` 选择实际需要的 Provider。
- Playwright 上游依赖审计仍报告 1 high、3 moderate、1 low；本版没有擅自执行会改变锁定版本的自动修复。
