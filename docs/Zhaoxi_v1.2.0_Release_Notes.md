# v1.2.0 · 秋日麦田

本页记录 Phase 1 基线。后续场景构图与最新截图见 [Phase 2 报告](Zhaoxi_v1.2.0_Phase2_Release_Notes.md)。

基于 v1.1.9，在 `v1.2` 分支完成 Visual Refresh Phase 1。沿用原生 HTML/CSS/JS 与现有 Core 协议。

## 交付内容

| 项目 | 实现 |
| --- | --- |
| Theme Token | `themes.css` 的 `data-theme="autumn-wheat"` 定义颜色、背景、透明度、Bubble Tint、Accent、圆角和阴影；新主题可覆盖变量，无需修改组件规则。 |
| Autumn Wheat Background | 使用用户提供的 `data/golden field.png`；原图保留，发布素材缩为 2560×1440 WebP，475,032 字节，较原 PNG 体积减少约 96.4%。cover / center，静态暖色 overlay。 |
| Glass Panel | 主聊天区奶白暖玻璃、28px 圆角、18px blur；侧栏不叠加 blur。无 backdrop-filter 时使用实色回退。 |
| Header / State Badge | 汐字暖金图标、22px 角色名、潮庭女仆长副标题；四种状态均有文字和颜色。连接地址使用实际 location.host，仅在维护区展示。 |
| Assistant / User Bubble | 朝汐奶白暖色，用户秋空蓝渐变；用户正文采用深色以改善浅蓝底对比度。 |
| Message Group | 每次 assistant reply 共用一个容器，组内紧凑，仅最后一段显示时间；历史恢复和实时分段都使用同一结构。 |
| Action Segment parser | 识别独占一行的全角或 ASCII 括号动作，支持连续单换行和空行；普通正文内括号不识别；保留 fenced code，不改变 Core 原文。 |
| Action styling | 0.9em、淡色斜体、额外留白、透明背景，动作与对白交替显示。 |
| Input Area | 奶白信纸托盘、低边框、44px 图片/发送按钮、低饱和蓝发送按钮和明确焦点提示。 |
| Sidebar / Proactive Note | 小桌边、快捷开场、真实主动消息便签；最多展示最近 3 条，未读使用金点，时间降权。主动消息仍沿用普通聊天投递链。 |
| Maintenance Drawer | 默认折叠，容纳连接状态、实际地址、系统消息、设置和 Debug；系统消息激活、原始 JSON、戳一戳和重启功能保留。 |
| Animation | 消息 200ms 淡入上移、状态点 3s 呼吸、折叠内容轻淡入；支持 reduced-motion。 |
| Responsive | 820px 以下显示小桌边开关，390px 验收无横向溢出，输入区保持可用；聊天和侧栏独立滚动。 |
| Performance | 静态背景、仅主面板 blur、便签数量有界；无新增前端框架或运行依赖。 |

## 修改文件

- `src/zhaoxi/web/static/index.html`：角色化结构、维护区、分组与动作解析、真实主动便签、侧栏开关。
- `src/zhaoxi/web/static/themes.css`、`autumn-wheat.webp`：主题和发布素材。
- `src/zhaoxi/web/app.py`：仅挂载随包静态目录，不公开 data 目录。
- `pyproject.toml`、`src/zhaoxi/__init__.py`：1.2.0 版本与 CSS/WebP 打包规则。
- `tests/web/reply_segments.test.cjs`、`interaction_badge.test.cjs`、`delivery_channel.test.cjs`、`test_web.py`：新行为及静态素材回归。
- `tests/web/visual_refresh.cjs`：独立浏览器验收与截图，不访问真实 Core。
- `tests/integration/test_reliability_composition.py`：将依赖包发现顺序的断言改为验证 LifeHUD 包存在。
- README、文档索引、当前状态及本报告；用户原始任务书修改保持原样。

## 验证

- Node 全量前端测试：29 passed，涵盖分段、代码块、动作、分组、输入合并、图片、撤回、主动队列、状态和系统消息。
- Python 全量：502 passed，1 skipped；包含 31 项 Web 测试。存在既有 Starlette/httpx 弃用警告。
- Edge 无头浏览器：1440×960 / 390×844，三处动作、同轮分组、真实数据结构便签、维护抽屉、Debug、侧栏开关、输入边界、长聊天滚动及无脚本错误检查通过。
- Wheel：使用本机 bundled setuptools 构建，核验 HTML/CSS/WebP 均包含在包中。项目 .venv 缺少 setuptools，故未使用其 pip 构建入口。

截图采用隔离的示例会话，不含真实聊天记录：

- [桌面](screenshots/v1.2/desktop.png)
- [维护抽屉](screenshots/v1.2/maintenance.png)
- [窄窗口](screenshots/v1.2/mobile.png)

复跑浏览器验收：在含 Playwright 的 Node 环境执行 `node tests/web/visual_refresh.cjs`，本机使用已安装的 Edge；必要时通过 NODE_PATH 指向 bundled Node packages。

## 配置和限制

背景由 `--background-image` 配置，玻璃透明度由 `--panel-opacity` 配置；当前无主题选择器，Sunflower Sea 等主题只预留扩展结构。

动作识别是展示层启发式：独占行的括号补充说明也会视为动作，不进行语义分类。Markdown 能力仍沿用原来的轻量实现。

侧栏便签是主动消息预览，不额外修改 Core 已读状态；完整消息保留在聊天记录中。系统通知继续位于维护抽屉。

本次未连接真实模型发送验收消息、未重启正在运行的桌面实例，也未进行数小时 GPU/帧率或真机语音验收；图片和语音沿用原有调用逻辑，自动回归不替代硬件验收。修改在源码分支中，现有桌面实例重新打开/重启后方可加载完整新版本。
