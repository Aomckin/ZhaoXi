# Zhaoxi / 朝汐

朝汐是一个以本地运行、长期陪伴和可控工具执行为核心的个人 Agent。运行时包版本为 **1.2.7**；代码已接入 v1.2.8 和 v1.2.9 开发增量，尚未正式发布。

## 主要特点

- 多轮对话与图文输入，支持本地桌面窗口、陪伴小窗、Web 和 CLI。
- 分层长期记忆、联想召回、生命周期管理与可追溯整合。
- 独立于长期记忆的近期日程与 Current Cognition，每轮提供轻量时间和近期状态。
- 潮庭书库、本地资料检索、Planner 和确定性 Workflow。
- 按需触发的 Decision Layer，结合当前事实与少量规则给出 L0/L1/L2 方向；朝汐主回复链负责表达。
- 统一 Tool Registry、动态能力发现、权限确认和脱敏审计。
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
