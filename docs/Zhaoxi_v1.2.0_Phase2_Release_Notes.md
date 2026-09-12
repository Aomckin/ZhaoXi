# v1.2.0 Phase 2 · Scene Composition

本页记录 Phase 2 基线。专用头像、公告栏和当前构图见 [Phase 3 报告](Zhaoxi_v1.2.0_Phase3_Release_Notes.md)。

在 `v1.2` 分支承接 Phase 1，保留 1.2.0 版本号。实现范围是空间构图与展示层，未修改 Agent、Memory、Proactive、State Machine 或 Desktop 业务逻辑。

## 场景交付

| 项目 | 结果 |
| --- | --- |
| Scene Layout | 独立 Background / Ambient 层；角色区与聊天区拆开。宽屏上方保留 34vh 场景空间，聊天区最大 760px，桌边 270px，中间留出风景。天空、山峰和麦田能直接露出。 |
| Character Anchor | 复用 `data/archive/zhaoxi/朝汐设定图.png`，压缩为 1000×1000、247,874 字节的 `zhaoxi-character.webp`，通过 CSS 取景展示头像；不改原始设定图。结构可换独立头像或半身资源。 |
| Header Composition | 独立角色区：头像、朝汐姓名、潮庭女仆长副标题与状态；ACTIVE / SEMI_ACTIVE 显示轻光晕，IDLE / AWAY 降低头像透明度，保留四态文字。 |
| Sidebar / Desk Area | 移除等高侧栏容器。小桌边标题、话题纸片、便签、维护区各有独立形态，桌边自身滚动。 |
| Quick Prompt Card | 去掉快捷开场 Accordion 和满宽按钮列表，改成自动换行的纸片话题卡；点击仍仅填入草稿。 |
| Proactive Note | 暖色便签、不到一度的轻微倾斜、纸胶带边缘；未读金点、淡时间、原消息内容与三条数量上限保持。 |
| Maintenance Drawer | 默认关闭；完整保留连接、地址、设置、系统消息和 Debug。清空会话移入抽屉，降低角色区操作密度。 |
| Conversation Area | 聊天区与角色、输入区分层，消息底板保证可读性；同轮细线与较小间距加强 Message Group，轮间留白增大，动作仍为纯文字。 |
| Input Tray | 与聊天内容区相隔 16px 的浮动奶白托盘，保留图片、语音复核、发送与焦点反馈。 |
| Theme Compatibility | 新 `scene.css` 管布局，原 `themes.css` 管主题。`--scene-clearance`、`--scene-position`、`--conversation-width`、`--desk-width`、`--character-image`、`--character-framing`、`--character-size` 可覆盖。无需雪山专用 DOM，未来主题可复用。 |
| Responsive | 1150px 以下桌边为可折叠 overlay；600px 以下缩小角色卡，650px 以下降低顶部留白。抽屉高度显式受视口约束；Escape、关闭按钮和开关均可收起，关闭后焦点回到开关。 |
| Performance | 背景静态；仅消息底板一层 12px blur；角色仅轻透明度/阴影过渡，遵守 reduced-motion；无新增 Canvas/WebGL、框架或运行依赖。 |

## Custom Titlebar 调研结论

本阶段保留原生标题栏。现有 `src/zhaoxi/desktop/window.py` 使用 pywebview 原生窗口，依赖 closing / minimized / restored / maximized 事件维护隐藏到托盘和窗口状态。当前没有自绘窗口按钮或拖动桥接；安全上线需要另外验证 Windows 拖动、最大化还原、DPI、关闭到托盘与快捷键行为。任务书将此项列为 optional，因此未把未实机验证的 frameless 模式带入本版本。

## 验证与截图

- Node 前端回归：29 项通过。
- Python 全量回归：502 项通过，1 项跳过；保留一项既有 Starlette/httpx 弃用警告。
- 浏览器：本机 Edge 无头模式，1920×1080、1600×1000、1440×960、1000×720、720×520、390×844、320×568。
- 验证动作识别、同轮分组、主动便签、四态角色映射、话题草稿、维护区入口、长聊天滚动、横向边界、输入可用性、抽屉边界、关闭和 Escape 焦点恢复；无脚本错误。
- 修复验收发现的窄屏抽屉被内容撑高并遮挡开关问题。
- 构建 `build/v1.2-phase2/zhaoxi-1.2.0-py3-none-any.whl`，检查 scene.css、themes.css、背景和角色 WebP 都随包分发。

截图均使用隔离示例数据，浏览器验收不调用真实 Core：

| 对比 | 截图 |
| --- | --- |
| Before · Phase 1 | [桌面](screenshots/v1.2/desktop.png) |
| After · Phase 2 同尺寸 | [桌面](screenshots/v1.2-phase2/desktop.png) |
| 16:9 | [1920×1080](screenshots/v1.2-phase2/scene-1920x1080.png) |
| 16:10 | [1600×1000](screenshots/v1.2-phase2/scene-1600x1000.png) |
| 维护区 | [展开](screenshots/v1.2-phase2/maintenance.png) |
| 窄窗口 | [390×844](screenshots/v1.2-phase2/mobile.png) / [桌边展开](screenshots/v1.2-phase2/mobile-desk.png) |
| 低高度 | [720×520](screenshots/v1.2-phase2/scene-720x520.png) |

## 文件与验收边界

主要文件：`src/zhaoxi/web/static/index.html`、新增 `scene.css` / `zhaoxi-character.webp`、`tests/web/visual_refresh.cjs`、状态/消息分流测试、静态素材接口测试及文档索引。Phase 1 截图保留用于对比。

当前头像是既有设定图的 CSS 取景，不是新增专用立绘；可后续替换更适合头像尺寸的独立资源。未实现自绘标题栏、Live2D、环境文案开关或前景粒子，这些均为任务书可选项。

浏览器通过不能等同于桌面宿主长时间流畅性验收：本次没有重启正在运行的实例，没有进行真机语音、数小时 GPU/帧率测试或真实模型聊天。原生标题栏和托盘行为保持现状。
