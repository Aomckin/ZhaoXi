# Zhaoxi / 朝汐

Zhaoxi 是一个可扩展的个人 Agent Core。v0.3 · Planner 在 Conversation、Tool Calling 和长期 Memory 之上，增加了显式、可检查、可恢复的多步任务执行；它不是 Life HUD 后端、通用工作流引擎或多 Agent 框架。

## Architecture

```text
CLI / future interfaces
          ↓
     Zhaoxi Core
 Conversation + Context + Memory + Planner
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

## v0.3 capabilities

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

长期记忆默认保存到 `.zhaoxi/memory.db`，可通过 `ZHAOXI_MEMORY_DB_PATH` 修改。数据库目录已被 Git 忽略。普通聊天不会自动写入长期记忆，只有明确的记忆请求才应调用写入工具。

CLI 可直接检查记忆：

```text
/memory search 咖啡
/memory get <memory_id>
```

显式启动和控制多步任务：

```text
/plan 帮我分步骤准备明天下午的面试
/plan
/resume <goal_id> OpenAI 的后端工程师岗位
/trace <goal_id>
/cancel <goal_id>
```

普通聊天与简单 Tool Call 仍使用轻量 Agent Loop，不会被强制套入 Planner。规划任务当前保存在进程内，退出程序后不会恢复；持久化与崩溃恢复留给 Reliability 版本。

备份时退出正在运行的 Zhaoxi，再复制 `.zhaoxi/memory.db`。删除该文件会清空全部长期记忆，操作前请先备份。

## Roadmap

当前版本的设计与验收细则见 [v0.3 开发计划](docs/Zhaoxi_v0.3_Development_Plan.md)。后续按 [总开发计划](docs/Zhaoxi_v0.1-v1.0_Development_Plan.md) 推进 v0.4 Permission。v0.3 不包含通用 Workflow、DAG、多 Agent、完整权限系统，也不接入写入型外部业务系统。
