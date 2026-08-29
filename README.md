# Zhaoxi / 朝汐

Zhaoxi 是一个可扩展的个人 Agent Core。v0.3.2 · Memory Lifecycle 在自然认知路由之上加入记忆的活跃、冷却、归档、重新激活、压缩与遗忘，让长期 Memory 不再是只增不减的数据库。

## Architecture

```text
CLI / future interfaces
          ↓
     Zhaoxi Core
 Cognitive Router → Conversation / Tools / Planner
                          ↓
              Auto Memory + Lifecycle
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

CLI 支持 `/tools`、`/clear` 和 `/exit`。缺少关键模型配置时会显示可操作的提示，不会输出 traceback 或密钥。

## v0.3.2 capabilities

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

备份时退出正在运行的 Zhaoxi，再复制 `.zhaoxi/memory.db`。删除该文件会清空全部长期记忆，操作前请先备份。

## Roadmap

当前版本要求见 [v0.3.2 Memory Lifecycle 任务书](docs/Zhaoxi_v0.3.2_Memory_Lifecycle_Task.md)，认知整合见 [v0.3.1 任务书](docs/Zhaoxi_v0.3.1_Cognitive_Integration_Task.md)。后续按 [总开发计划](docs/Zhaoxi_v0.1-v1.0_Development_Plan.md) 推进 v0.4 Permission。本版不接入 Life HUD、GitHub 等外部 Tool，也不包含后台定时任务、向量数据库或 RAG。
