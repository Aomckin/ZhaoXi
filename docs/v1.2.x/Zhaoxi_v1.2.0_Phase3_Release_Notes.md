# v1.2.0 Phase 3 · 小桌边公告栏与角色整合

在 `v1.2` 分支承接 Phase 2，保持版本号 1.2.0。主空间收束为角色抬头、聊天与输入；小桌边改为全尺寸默认收起的右侧公告栏。未新增 Agent 功能、状态机或摘要模型。

## 实现清单

| 项目 | 实现 |
| --- | --- |
| Character Anchor | 头像与姓名、四态标签、副标题合为同一抬头，与聊天区左边缘对齐，间隔 12px；取消独立漂浮身份卡。 |
| Avatar Asset | 使用用户提供的 `data/ACTIVE头像.png`，完整缩放为 `avatar-default.webp`：512×512，58,356 字节；不再用设定图取景。宽屏圆形 140px，窄屏 76–96px，保留原图耳朵和向日葵发卡。 |
| Avatar Fallback | 图片缺失或配置无效时显示“汐”字；不回退到设定图。 |
| Character Config | 头像地址仅配置于 index.html 的 `characterConfig` JSON；由 deskboard.js 加载，与主题 CSS 解耦。替换头像只需修改此处地址及对应静态素材。 |
| Conversation Layout | 宽屏 68vw、最大 1120px，位于中左主区域；取消雪山禁区和 34vh 顶部保留空间。玻璃底板透明度约 .80，文字气泡维持独立底色。 |
| Input Tray Alignment | 与聊天区左右边缘和宽度一致，同样圆角、材质；桌面间距 18px、窄屏 16px。 |
| Deskboard Closed State | 所有尺寸默认关闭，只有右侧小把手，不占布局列宽；关闭时 aria-hidden 和 inert 阻止隐藏内容被键盘进入。 |
| Deskboard Open State | 400px 公告栏从右侧覆盖进入，不改变聊天区宽度或位置；窄窗口限制为视口宽度减 16px。抬头固定，内容独立滚动。 |
| Deskboard Animation | 280ms ease-out 的 translateX / opacity，关闭时同步退场；支持 reduced-motion。收起按钮、把手、Escape 均可关闭并恢复把手焦点。 |
| Proactive Note | 显示最近两条真实主动消息，新增便签不自动展开；正文仍照常进入现有聊天队列，去重逻辑保留。 |
| Unread Indicator | 把手使用小金点，aria-label 明确说明有未读留言；便签自身有“未读”可访问标记，无红色数字角标。 |
| Read State | 公告栏入场完成、页面可见且便签进入滚动视口后，调用既有 `/api/proactive/{id}/activate`。确认 acknowledged 后才去掉金点，不重新读取/重建聊天 DOM。不可见便签不标记，保存失败保留金点并提示，下次查看重试；同 ID 请求去重。 |
| Quick Prompt | 留言下方为低权重话题纸片；点击仍只填入草稿，不发送模型请求。 |
| Maintenance Drawer | 最下方按系统消息、设置、维护抽屉组织。维护抽屉默认关闭，保留清空会话、连接、地址、Debug、诊断/原始 JSON、戳一戳和重启。 |
| Responsive | 1920×1080、2560×1440、3840×2160、1600×900、1366×768，以及 720×520、390×844、320×568 已检查。公告栏展开前后聊天边界完全一致，输入区未越出视口。 |
| Performance | 头像由约 1.93 MB 降为约 58 KB；背景静态，最多聊天底板和公告栏两处 blur；无高频 Canvas、WebGL 或新运行依赖。 |

## 向日葵图标补充

- 窗口与网页使用 `zhaoxi.ico`，托盘使用 `zhaoxi.png`，均已替换为透明背景向日葵。
- ICO 包含 16、20、24、32、40、48、64、128、256px 多尺寸；PNG 为 512×512，向量源为 `sunflower.svg`。
- 快捷方式生成脚本改用独立的 `sunflower.ico`，避免继续引用 Windows 缓存中的旧图标路径。本机 `启动朝汐.lnk` 已更新，其目标与启动参数保持不变；该机器专用快捷方式不纳入 Git。
- 运行中的窗口/托盘不会热替换图标，需要彻底退出后重启；资源与引用已核验，图标和托盘专项测试 3 项通过。

## 回归与产物

- Node 前端回归：29 passed。
- Python 全量：502 passed、1 skipped；存在既有 Starlette/httpx 弃用警告。
- Edge 无头浏览器：上述 8 个尺寸通过，检查默认关闭、展开/关闭/焦点、真实动画与 reduced-motion、聊天位置不变、输入对齐、头像存在/缺失、DPR 2 像素足够、长聊天和动作识别。
- 已读回归覆盖：关闭时不请求、新主动消息不弹板、打开可见后确认、重载持久化、保存失败保留金点、不可见第二张便签滚入后才确认、重复事件不重复投递、草稿和聊天 DOM 不被清空。
- 静态资源接口测试覆盖 deskboard.js 与 avatar-default.webp；data 目录仍未公开。
- `build/v1.2-phase3/zhaoxi-1.2.0-py3-none-any.whl` 已构建并确认包含场景 CSS、公告栏脚本与新头像。

浏览器验收脚本为 `tests/web/visual_refresh.cjs`，使用独立示例会话和模拟 API，不访问运行中的 Core。运行时需要本机 Edge 和包含 Playwright 的 Node 环境；可用 NODE_PATH 指向 bundled packages。

## 前后截图

| 场景 | 截图 |
| --- | --- |
| Before · Phase 2 / 1920×1080 | [Phase 2](../screenshots/v1.2-phase2/scene-1920x1080.png) |
| After · Phase 3 / 1920×1080 | [Phase 3](../screenshots/v1.2-phase3/scene-1920x1080.png) |
| 默认关闭 | [桌面](../screenshots/v1.2-phase3/desktop.png) |
| 公告栏展开 | [小桌边](../screenshots/v1.2-phase3/deskboard-open.png) |
| 维护区 | [展开 Debug](../screenshots/v1.2-phase3/maintenance.png) |
| 窄屏 | [390×844](../screenshots/v1.2-phase3/scene-390x844.png) / [公告栏展开](../screenshots/v1.2-phase3/mobile-board.png) |
| 头像缺失 | [汐字回退](../screenshots/v1.2-phase3/avatar-fallback.png) |
| 4K | [3840×2160](../screenshots/v1.2-phase3/scene-3840x2160.png) |

## 修改文件与限制

主要修改：`src/zhaoxi/web/static/index.html`、`scene.css`，新增 `deskboard.js` / `avatar-default.webp`，更新 pyproject.toml 的 JS 打包规则、浏览器验收、消息测试替身、静态素材接口测试与文档索引。Phase 1/2 截图保留用于对比，原始头像和任务书保持原样。

已读复用原有 activate 语义，因此同时沿用原来的会话上下文接入和互动时间更新；没有新建独立“仅预览已读”的后端状态。公告栏只展示最近两条便签，旧消息继续保留在后端和原有聊天记录中。

当前只有一张默认头像，四态使用光晕/透明度而非四张独立绘图。没有实施自绘标题栏、Live2D、桌宠或主题自动切换。

本次验证为本机 Edge 无头渲染和自动化回归，未重启当前桌面实例，未进行真实模型发送、真机语音或数小时 GPU/帧率验收。
