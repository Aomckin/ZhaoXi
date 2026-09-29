# Zhaoxi / 朝汐

朝汐是一个以本地运行、长期陪伴和可控工具执行为核心的个人 Agent。当前开发版本为 **1.4.0**。Core 提供请求级运行观测、长任务中间回复、Perception、认知时间线和 External Source Plugin 协议；QQ / NapCat 作为可选插件接入。

## 主要特点

- 多轮对话与图文输入，支持本地桌面窗口、陪伴小窗、Web、CLI 和 QQ。
- Perception System 将 QQ 群消息分流为 Direct 或 Ambient；普通群消息批量形成可追溯摘要。
- 分层长期记忆、联想召回、生命周期管理与可追溯整合。
- 独立于长期记忆的近期日程与 Current Cognition，每轮提供轻量时间和近期状态。
- 潮庭书库、本地资料检索、Planner 和确定性 Workflow。
- 按需触发的 Decision Layer，结合当前事实与少量规则给出 L0/L1/L2 方向；朝汐主回复链负责表达。
- 统一 Tool Registry、动态能力发现、权限确认和脱敏审计。
- 请求级运行指标、LLM/Tool 归属与耗时、Memory Retrieval Inspector、Planner Trace 桥接和独立的长任务中间回复。
- 请求级行动轨迹、Tool 最终状态归并与 Token 预算错误归因。
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

## 图片、语音与表情

- 图片：点击输入区图片按钮或直接粘贴；发送前可预览和移除。
- 语音：安装 voice 可选依赖并在 `.env` 中启用对应 Provider。
- 表情：本地注册表位于 `data/emoji/emoji_registry.json`，可在维护抽屉的表情柜中管理。

## 测试

```powershell
python -m pytest
```

## 文档

- [文档索引](docs/README.md)
- [当前运行状态](docs/current/CURRENT_STATUS.md)
- [代码库状态](docs/current/CODEBASE_STATUS.md)
- [运维与恢复](docs/v1.0.x/Zhaoxi_v1.0_Operations_Runbook.md)
- [未来开发计划](<docs/roadmap/Zhaoxi 未来开发计划.md>)

各版本任务书、发布说明和历史验收记录全部位于 `docs/`，根 README 只维护当前产品特点和使用方式。

## External Source Plugins

Core 默认不启用任何第三方聊天平台。插件通过 `ObservationSink` 发送标准 Observation，Core 负责认知、权限和回复路由。仓库附带可选的 QQ / NapCat 插件；将 `config/plugins/qq_napcat.example.toml` 复制为被 Git 忽略的 `config/plugins/qq_napcat.toml`，配置账号与连接并设置 `enabled = true` 后启用，也可在维护抽屉的 External Sources 中运行时启停或重启。移除插件包后，Core 的本地对话、Memory 和 Experience Stream 继续可用。协议和配置见 [External Source Plugin Spec](docs/plugin/External_Source_Plugin_Spec.md) 与 [QQ 插件](docs/plugin/QQ_NapCat_Plugin.md)。
