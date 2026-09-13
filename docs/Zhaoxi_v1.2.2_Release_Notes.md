# Zhaoxi v1.2.2 开发报告（整合修订版）

当前以 [Tool System Completion 整合任务书](Zhaoxi_v1.2.2_Tool_System_Completion_Task.md) 为验收依据；[原版任务书](Zhaoxi_v1.2.2_Tool_Discovery_Memory_Semantics_Task.md) 和 [v1.1.9 任务书](v1.1.x/Zhaoxi_v1.1.9_Tool_Context_Router_Task_v2.md) 保留为历史需求。开发分支与运行时版本均为 `v1.2.2`。Tool 在对话中继续称为“钥匙”。

## 本次补齐

| 新增要求 | 实现 |
| --- | --- |
| Memory Core / 广想 | `remember_memory`、`update_memory`、`search_memories` 默认常驻，允许自然关联改善对话时主动检索，避免为展示记忆而频繁搜索 |
| 完整 Manifest | 从实时 Registry 生成 name、group、source、summary、registered、enabled、available、persistent、exposed、read_only、destructive、aliases、intents 与 force_expose |
| Inventory | 常驻 `inspect_tool_catalog`，支持 summary、list_groups、list_tools、inspect_group、inspect_tool |
| Capability Resolver | `resolve_capability(need, manifest)` 使用元数据与少量领域规则；模型通过 `inspect_tool_catalog(action=resolve, need=...)` 使用，无额外 LLM 请求 |
| 行动前能力核实 | Runtime 规则要求先查目录、解析并加载；Core 对行动请求中的无依据能力拒绝进行一次目录核实，匹配后加载并重试 |
| 新工具可扩展 | 注册后自动进入 Manifest；新 group 不需要加入 Discovery 的固定 enum，可用工具自身 aliases / intents 参与解析 |
| Debug 控制 | 小桌边 → 维护抽屉 → Debug · 钥匙柜；分组折叠、单工具和整组启停、Force Expose、单工具/整组/全部恢复默认 |
| 即时生效 | Catalog、Resolver、Router、Discovery、暴露列表共用 Manifest；ToolExecutor 在执行前再次检查可用性，已停用工具在权限确认恢复后也不能执行 |
| 持久化 | 原子保存 `data/debug/tool_overrides.json`，先保存成功再切换内存状态；重启恢复；reset 清除 override 后按启动默认值计算 |
| Diagnostics | 注册/启用/依赖可用/携带数量、匹配组、初始和最终工具、扩展记录、Force Expose、schema 字符数及 API 返回的 prompt_tokens |

## 记忆写入默认权限

`remember_memory` 与 `update_memory` 默认自动允许，不再弹出 WRITE 确认。仍保留 WRITE 声明和审计；用户明确禁止记忆、只读要求、显式 WRITE deny 以及 Debug 停用继续拦截。其他写入和记忆删除、归档等管理操作保留原权限策略；内容冲突核实仍按记忆服务规则处理。

## 常驻与动态能力

默认常驻五把钥匙：三把 Memory Core，加 `request_tool_group` 与 `inspect_tool_catalog`。Memory 工具只有实际注册后才存在，Debug 显式停用仍优先。记忆管理（固定、遗忘、归档、恢复、整理）继续按需暴露。

Discovery 每个用户轮最多两次成功扩展，重复组及已携带组不重复消耗次数，拒绝 `all`。本轮和权限恢复后保留，下一用户轮重新计算。旧 `memory_search` 请求兼容映射到 `memory_core`；原 `search` 组使用 `local_search`。

查询目录或取得钥匙不代表完成业务查询；用户本来就在询问钥匙柜清单时，成功的 Inventory 查询可完成该请求。`all` 模式保留，但只暴露已启用且可用的工具。

## Debug 使用

打开小桌边，展开“维护抽屉”和“Debug · 钥匙柜”。普通 Tool Package 的工具定义在启动时登记，即使 `.env` 默认停用，也会显示为 registered=true、enabled=false，可直接勾选启用和 Force Expose 进行黑盒测试。注册工具定义不会执行该工具业务；启用单个工具不会同时开启包的 Workflow、Proactive 或 Reflection。

运行时/持久化 override 优先于工具的 `.env` 启动默认值，后者优先于代码默认值。路径可通过 `ZHAOXI_TOOL_OVERRIDES_PATH` 更改。面板操作即时返回后端状态，展开时每五秒刷新，不使用浏览器独立清单。保留 API 原有 Desktop 会话鉴权。

`available` 表示工具声明的依赖状态，独立于 `enabled`。工具可提供布尔值、属性或无网络的状态函数；默认注册成功视为可用，不代表远端服务已做联网健康探测。MCP 工具读取现有子进程存活状态，不为刷新面板发送额外请求。未启动或注册失败的 MCP Server 不会凭空产生 Tool 清单；Provider 的首次配置与启动仍遵循原启动配置。

关闭工具会拦截后续调用，包括暂停后恢复的调用；不会撤销已经开始执行的业务操作。Force Expose 不绕过启用状态、依赖状态或现有权限规则。

## 新工具元数据

Tool 可声明 `group`、`source`、`summary`、`aliases`、`intents`、`default_enabled`、`available`；可选 `persistent`。内置工具沿用兼容元数据，Provider 来源从 Registry 注册记录取得。没有专用 group 的外部工具按来源归组，普通未知工具进入 other，仍可经 Inventory 找到并按组加载。

没有手工维护的第二份工具清单。`metadata.py` 仅为已有工具提供默认分组，Manifest 的成员和运行状态始终来自 Registry。

## 验证

2026-09-13，在保留已有 v1.2.1 桌面改动的工作区验证：

- 全量 Python：`.venv/Scripts/python.exe -m pytest`，530 passed、1 skipped；一项既有 Starlette/httpx 弃用提示。
- Node：`node --test tests/web/*.test.cjs`，32 passed。
- 独立包回归：`tools/mcp/tests` 与 `tools/job_application_tool/tests`，12 passed。
- Edge 浏览器连接隔离测试 Core：单个启用、Force Expose、刷新页面、整组停用、单个/整组/全部恢复默认全部通过，无页面脚本错误。
- 新增覆盖：广想常驻、完整 Inventory 数量、新工具与新组自动发现、Resolver → Discovery → 实际执行、无依据拒绝纠正、停用传播、依赖不可用、运行时 Force Expose 取消、重启持久化、保存失败不应用、权限暂停后停用、API 鉴权和无效输入。
- 既有 Memory recall、人格、Presence、Function Calling、权限与桌面回归通过。

截图：[Debug 钥匙柜](screenshots/v1.2.2/tool-control.png)。浏览器验收脚本为 `tests/web/tool_control_smoke.cjs`，配合独立 `tool_control_smoke_server.py`；仅使用测试工具和临时状态，没有操作日常 Core 或真实业务。

真实模型 API 未调用。结构与执行闭环经过模拟模型及真实本地 API 验证；真实对话措辞下的模型选择和实际 token 用量仍需启动新版朝汐后验收。
