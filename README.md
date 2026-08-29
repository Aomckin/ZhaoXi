# Zhaoxi / 朝汐

Zhaoxi 是一个可扩展的个人 Agent Core。v0.4 · Permission 为 Agent、Planner 与 Tool 之间增加统一权限执行门、显式确认和脱敏审计，让模型可以提出动作，但不能自行授予权限。

## Architecture

```text
CLI / future interfaces
          ↓
     Zhaoxi Core
 Cognitive Router → Conversation / Tools / Planner
                          ↓
              Auto Memory + Lifecycle
                          ↓
              Permission Gateway + Audit
          ↓
   Model Provider  ←→  Tool Registry
                         ↓
                 independently registered Tools
```

Core 使用内部消息和响应类型，不依赖厂商对象；新增工具只需实现 `Tool` 并注册，无需修改 Agent 循环。

## Quick start

需要 Python 3.12 或更新版本。

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
copy .env.example .env
```

在 `.env` 中填写兼容 OpenAI Chat Completions API 的模型配置：

```dotenv
ZHAOXI_MODEL_BASE_URL=https://api.openai.com/v1
ZHAOXI_MODEL_API_KEY=your-key
ZHAOXI_MODEL_NAME=your-model
```

运行与测试：

```bash
python main.py
python -m pytest
```

CLI 支持 `/tools`、`/permissions`、`/approve`、`/deny`、`/revoke`、`/audit`、`/clear` 和 `/exit`。缺少关键模型配置时会显示可操作的提示，不会输出 traceback 或密钥。

## v0.4 capabilities

- `READ / WRITE / DELETE / EXTERNAL_ACTION / DANGEROUS` 权限等级
- Tool 权限、资源范围与副作用声明
- Agent 与 Planner 共用 `ToolExecutor` 和 `PermissionGateway`
- READ 默认自动允许，WRITE / DELETE 默认确认，DANGEROUS 默认拒绝
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
- YAML 版本化人格
- OpenAI-compatible Model Provider
- 支持单个/并行多个 Tool Call 的 Agent Runtime
- 工具结果回填、再次推理、超时与最大步数保护
- `echo`、安全 `calculator`、`current_time`
- 内存 Session Store、结构化日志和无真实 API 的测试
- SQLite 长期 Memory，进程重启后仍可读取
- Episodic / Semantic 分层、来源、时间、置信度与标签
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
- 回复后执行独立的 Auto Memory Decision
- 自动记忆支持 `IGNORE`、`CREATE`、`UPDATE`、`MERGE`、`CONFLICT`
- 用户“记住 / 不要记 / 忘掉”意图拥有最高优先级
- 只读规划任务会从确定性执行层阻止状态变更工具
- `importance` / `relevance` 二维记忆模型与可配置衰减策略
- `ACTIVE → COLD → ARCHIVED → FORGOTTEN` 生命周期
- 检索命中提升 relevance，COLD 记忆可按相关主题重新激活
- Pinned 关键记忆不参与自动归档，用户仍可显式遗忘
- `archive_memory`、`reactivate_memory`、`pin_memory`、`consolidate_memories`
- 多条细节记忆可压缩为高重要度 Semantic Memory
- 可重复查询的 Tool 事实默认不复制进长期 Memory
- SQLite schema v1 自动迁移至 v2，不丢失旧记录

长期记忆默认保存到 `.zhaoxi/memory.db`，可通过 `ZHAOXI_MEMORY_DB_PATH` 修改，数据库目录已被 Git 忽略。主 Agent 不会在普通对话中自行调用记忆写入工具；最终回复生成后，独立的 Auto Memory Decision 会判断是否保存稳定偏好、身份关系、长期目标和项目状态等高价值信息。用户明确要求记住、禁止记忆或遗忘时，其意图拥有最高优先级。

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

普通聊天与简单 Tool Call 不会被强制套入 Planner。Auto Memory 使用单次、无 Tool Choice 的 JSON 决策请求，并对身份、命名缘由和稳定偏好提供保守的本地兜底；用户明确禁止时不会保存。Memory maintenance 当前按检索或 `/memory maintain` 执行，不包含后台定时任务。日志只显示 `auto_memory action=...`，不输出记忆正文。规划任务当前保存在进程内，退出程序后不会恢复；持久化与崩溃恢复留给 Reliability 版本。

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

备份时退出正在运行的 Zhaoxi，再复制 `.zhaoxi/memory.db`。删除该文件会清空全部长期记忆，操作前请先备份。

## Roadmap

当前版本要求见 [v0.4 Permission 开发计划](docs/Zhaoxi_v0.4_Permission_Development_Plan.md)，记忆生命周期见 [v0.3.2 任务书](docs/Zhaoxi_v0.3.2_Memory_Lifecycle_Task.md)。后续按 [总开发计划](docs/Zhaoxi_v0.1-v1.0_Development_Plan.md) 推进 v0.5 Workflow。本版不接入 Life HUD、GitHub 等外部 Tool，也不包含后台定时任务、向量数据库或 RAG。
