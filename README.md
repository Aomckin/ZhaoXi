# Zhaoxi / 朝汐

朝汐是一个以本地运行、长期陪伴和可控工具执行为核心的个人 Agent。当前开发版本为 **1.4.4**（[版本说明](docs/v1.4.x/Zhaoxi_v1.4.4_Release_Notes.md)）。Core 提供请求级运行观测、长任务中间回复、Perception、认知时间线和 External Source Plugin 协议；QQ / NapCat 作为可选插件接入。

## 主要特点

- 多轮对话与图文输入，支持本地桌面窗口、陪伴小窗、Web、CLI 和 QQ。
- Perception System 将 QQ 群消息分流为 Direct 或 Ambient；普通群消息批量形成可追溯摘要，可按群号、时间和关键词搜索已保存原消息并展开证据。
- Memory 3.0：自然联想 / 明确回忆 / 广泛搜索分层，语义簇优先与 FTS / 语义 / 实体全局候选联合召回，非线性热度与可追溯证据。
- 独立于长期记忆的近期日程与 Current Cognition 结构化小本子，主线可更新、降温和退出，每轮提供轻量时间和近期状态。
- 潮庭书库、本地资料检索、Planner 和确定性 Workflow。
- 按需触发的 Decision Layer，结合当前事实与少量规则给出 L0/L1/L2 方向；朝汐主回复链负责表达。
- 统一 Tool Registry、动态能力发现、权限确认和脱敏审计。
- FAST_CHAT 轻量对话通道：Fast Gate 2.0 综合近期对话、Current Cognition、能力与资源信号；高置信聊天单次前台模型调用，模糊输入交给 Router 并可判回 FAST，明确动作进入工具链；发现真实 Tool / Recall / Decision 需求时丢弃草稿，每轮单向升级 STANDARD 最多一次；Owner QQ 私聊复用 FAST 并保留外部边界。
- STANDARD 工具任务在调用成功后可继续执行后续操作，支持先查询、再修改；预算或耗时接近上限时进入无工具收尾。
- 请求级运行指标、LLM/Tool 归属与耗时、Memory Retrieval Inspector、Planner Trace 桥接和独立的长任务中间回复。
- 请求级行动轨迹、Tool 最终状态归并与 Token 预算错误归因。
- Presence 2.0：前台抢占、Registry 内部活动、FAST 弱趋势消化、认知/记忆/簇增量整理和不增热的历史重温；可选授权 QQ 群闲逛默认关闭。
- 主动心跳、桌面活动感知、语音输入与朗读。
- 本地表情库、Reply DSL 属性匹配、收藏管理和有序图文回复。
- SQLite 本地持久化、运行诊断、备份恢复和请求级 Trace。

## 环境要求

- Python 3.12+
- Windows 桌面模式需要 WebView、托盘和热键相关可选依赖
- 一个兼容 OpenAI Chat Completions API 的模型服务

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,desktop,voice]"
python -m pip install -e .\tools\lifehud_tool --no-deps
Copy-Item .env.example .env
```

在 `.env` 中至少设置：

```dotenv
ZHAOXI_MODEL_BASE_URL=https://api.openai.com/v1
ZHAOXI_MODEL_API_KEY=your-key
ZHAOXI_MODEL_NAME=your-model
```

## 使用方式

先检查配置：

```powershell
python main.py --doctor
```

启动不同入口：

```powershell
python main.py             # CLI
python main.py --web       # 本地 Web，默认 http://127.0.0.1:4913
python main.py --desktop   # Windows 桌面窗口与托盘
```

Windows 也可以生成双击启动快捷方式：

```powershell
powershell -NoProfile -File .\scripts\create_desktop_launcher.ps1
```

窗口关闭后默认隐藏到托盘；彻底退出请使用托盘菜单。修改 Python Core 后需要重启进程，修改前端静态资源后需要刷新或重开桌面窗口。

## v1.4.3 记忆迁移

先体检并预览，默认不写原库：

```powershell
python main.py --memory-maintenance audit
python main.py --memory-maintenance all --output-dir .zhaoxi/memory-v143-preview
```

本机 2026-10-01 已完成原库迁移及启用，证据见 [任务书核对](docs/v1.4.x/Zhaoxi_v1.4.3_任务书核对.md)。下列命令用于后续维护。

退出桌面 / Web / CLI 进程后，执行带备份的离线迁移。Ctrl+C 或 `--cancel-file <路径>` 可在发布前取消：

```powershell
python main.py --memory-maintenance all --apply --offline --output-dir .zhaoxi/memory-v143-migration
python main.py --rollback-memory .zhaoxi/memory-v143-migration/memory.db.bak --offline
python main.py --media-migrate experience --apply --offline
python main.py --media-migrate perception --apply --offline
python main.py --media-migrate session --apply --offline
python main.py --vacuum-session --apply --offline
```

已有兼容向量快照时，可在记忆迁移命令增加 `--embedding-snapshot <after.db>`；只复用空间、内容 hash 和向量格式一致的条目，不覆盖原库记录。

百炼文本记忆推荐配置（独立于对话模型密钥）：

```dotenv
ZHAOXI_MEMORY_EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
ZHAOXI_MEMORY_EMBEDDING_MODEL=text-embedding-v4
ZHAOXI_MEMORY_EMBEDDING_VERSION=1
ZHAOXI_MEMORY_EMBEDDING_DIM=1024
ZHAOXI_MEMORY_EMBEDDING_API_KEY=your-bailian-key
```

也可使用百炼业务空间专属域名，接口地域必须与密钥一致。连接检查只发送合成文本；真实库副本验收会向配置的服务发送记忆正文：

```powershell
python scripts/check_memory_embedding_v143.py
python scripts/benchmark_memory_v143.py --semantic --output .zhaoxi/memory-v143-semantic-benchmark
```

已有冻结旧报告、快照、缓存查询向量和复核标签时，可运行 `python scripts/accept_memory_v143.py` 进行无外部请求的对照；门槛失败退出码为 1。结果同时保留原固定 ID 与开发代理复核口径，后者不是独立人工 gold。输入路径可通过脚本参数指定。

换模型或维度前须离线重建旧向量；该副本验收不会迁移业务库。对照报告固定记录旧提交号，提交新版本后请用 `--baseline-ref <旧提交号>` 保持基线。

真语义 Embedding 通过 `.env.example` 中的独立端点、模型、版本、维度配置接入。未配置时使用词法 hash 回退；换模型后须离线 reindex，禁止跨空间比较。维护抽屉的记忆检索检查器可选择模式并检查簇、候选来源、排除原因和数据库状态。真实库抽样验证及尚待完成的持续使用验收见开发记录。

## 图片、语音与表情

- 图片：点击输入区图片按钮或直接粘贴；发送前可预览和移除。
- 语音：安装 voice 可选依赖并在 `.env` 中启用对应 Provider。
- 表情：本地注册表位于 `data/emoji/emoji_registry.json`，可在维护抽屉的表情柜中管理。

## 测试

```powershell
python -m pytest
```

## 文档

- [v1.4.4 Presence 2.0 开发记录](docs/v1.4.x/Zhaoxi_v1.4.4_开发记录.md)
- [v1.4.3 开发记录与迁移说明](docs/v1.4.x/Zhaoxi_v1.4.3_开发记录.md)
- [v1.4.2 开发记录与验收](docs/v1.4.x/Zhaoxi_v1.4.2_开发记录.md)
- [文档索引](docs/README.md)
- [当前运行状态](docs/current/CURRENT_STATUS.md)
- [代码库状态](docs/current/CODEBASE_STATUS.md)
- [运维与恢复](docs/v1.0.x/Zhaoxi_v1.0_Operations_Runbook.md)
- [未来开发计划](<docs/roadmap/Zhaoxi 未来开发计划.md>)

各版本任务书、发布说明和历史验收记录全部位于 `docs/`，根 README 只维护当前产品特点和使用方式。

## External Source Plugins

Core 默认不启用任何第三方聊天平台。插件通过 `ObservationSink` 发送标准 Observation，Core 负责认知、权限和回复路由。仓库附带可选的 QQ / NapCat 插件；将 `config/plugins/qq_napcat.example.toml` 复制为被 Git 忽略的 `config/plugins/qq_napcat.toml`，配置账号与连接并设置 `enabled = true` 后启用，也可在维护抽屉的 External Sources 中运行时启停或重启。移除插件包后，Core 的本地对话、Memory 和 Experience Stream 继续可用。协议和配置见 [External Source Plugin Spec](docs/plugin/External_Source_Plugin_Spec.md) 与 [QQ 插件](docs/plugin/QQ_NapCat_Plugin.md)。
