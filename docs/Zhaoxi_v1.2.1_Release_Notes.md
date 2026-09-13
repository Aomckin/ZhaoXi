# v1.2.1 · Single Window Desktop Shell

开发基线：`89ecf6d`，稳定 v1.2.0 Phase 3。开始开发时工作树中只有两份未跟踪的 v1.2.1 任务书；基线已回滚到位，没有再次 reset，也没有沿用旧双窗口实现。版本号已升级到 1.2.1。

任务依据为 `Zhaoxi_v1.2.1_Desktop_Shell_and_Companion_Mode_Rebuild_Task.md`。用户在开发中明确调整两点，优先于任务书的推荐布局：**陪伴模式去掉头像及角色抬头，主体留给信息；输入栏压小并简化**。因此最终 Companion 无 Compact Character Header，身份只出现在窗口标题栏。

## 实现与边界

| 项目 | 最终实现 |
| --- | --- |
| Single Window Architecture | DesktopHost 只持有一个 DesktopWindow；唯一一次 `webview.create_window` 创建长期窗口。MAIN / COMPANION 为同一对象的模式。Core / Session / Memory 不分叉。 |
| Window identity | HWND、WebView 和页面 JS 标记在 20 次往返中保持不变。模式切换不调用 load_url，不销毁窗口，不请求重载 Session。 |
| MAIN layout | 保留 Autumn Wheat、Character Anchor、Conversation、Input Tray、Deskboard、Settings / Debug / Maintenance。只为 36px 自绘 Chrome 留出上方空间。 |
| COMPANION layout | 无头像及角色抬头；当前对话从 Chrome 下方开始。默认 390×480，最小 300×320。底栏仅小桌边提示与展开。 |
| Current Conversation Surface | 从现有聊天 DOM 投影最近用户消息及当前朝汐回复；新用户消息等待回复时保留上一条朝汐消息。长正文有字符上限与容器裁切，提供“展开主界面查看完整内容”。历史 DOM 原样留在 MAIN。无对话区域滚动或嵌套历史滚动。 |
| Input | 复用同一个 textarea、发送队列、图片草稿和语音确认逻辑。陪伴输入区仅单行文字与 28px 发送按钮；图片和语音入口移入 ⋯ 菜单。有待发送图片或语音确认时仍使用原来的预览/确认区。 |
| Resize | Win32 `SetWindowSubclass` + `WM_NCHITTEST`，返回八向 HT 常量，使用按 GetDpiForWindow 缩放的命中带；保留 WS_THICKFRAME，WM_NCCALCSIZE 保留自绘 client chrome。WebView 边缘区域也可通过 SC_SIZE 进入系统缩放，不使用 CSS resize 冒充窗口缩放。 |
| Drag / Chrome | 标题区域达到移动阈值才调用 SC_MOVE，避免双击误拖动；按钮和边缘命中区域独立。关闭按钮隐藏，最小化使用原生最小化。 |
| Main double click | 自绘标题双击执行原生 Maximize / Restore。 |
| Companion double click | 同一个窗口返回 MAIN；标准位置的按钮显示 ↗。原生 SC_MAXIMIZE 在 Companion 中被拦截。 |
| Topmost | ⋯ 菜单中开启；只在布尔状态发生变化时于 WinForms UI 线程设置 TopMost 一次。记录 old/new/native_call_count，无轮询、定时刷新或窗口事件反向调用。返回 MAIN 撤销实际置顶，保留 Companion 偏好，下次进入恢复。 |
| Geometry persistence | `.zhaoxi/window-geometry.json` 分开保存 main / companion；切换、隐藏、退出和显式置顶变更时原子替换文件。主模式保留 maximized，陪伴保留 topmost。恢复时限制到最近显示器 WorkingArea；最小化时读取 RestoreBounds。 |
| Notification | 默认临时 WinForms 通知卡，不创建第二个 WebView；最多一张，8 秒关闭、替换旧卡、关闭时释放 Timer/Form，使用不激活窗口的显示方式。桌面聚焦时抑制。 |
| Notification routing | 普通会话通知点击进入同一个 Companion；Important / Urgent 进入 MAIN。沿用持久化 inbox / activate 逻辑，原有 INFO 不弹窗策略保留。 |
| Toast fallback | Native 初始化/显示失败、桌面未准备好或显式系统模式时懒加载 Windows Toast。通知不可用仍保留持久化 inbox。 |
| Browser entry blocking | 根页面和静态 HTML 默认 403，包含 Windows 大小写及重复分隔符路径。Desktop 使用随机会话令牌，经 `/desktop-entry` 换取 HttpOnly / SameSite=strict Cookie 并重定向干净 URL；不使用 User-Agent。内部 API 与 SSE transport 保留。Desktop Uvicorn access log 关闭，避免启动令牌进入访问日志。 |
| DEV browser mode | `ZHAOXI_DEV_BROWSER_UI=true` 允许浏览器 UI；如连接带 API token 的 Desktop 服务仍需认证。独立 Web 开发模式可直接使用。 |
| Tray / Shortcut | 托盘：打开朝汐 → MAIN、切换陪伴模式 → COMPANION、隐藏、设置、安静模式、退出。原有热键保持；MAIN / 隐藏状态呼出 Companion，Companion 再按隐藏，Esc 隐藏。 |
| Desktop Activity self-window | 同一 HWND 与 `Zhaoxi.Desktop` App Identity；沿用已有进程 PID 自身窗口识别，不复制 Presence / Activity。置顶回调不触发 Presence 操作。 |
| Desktop Pet | 未实现。 |

## 验证

- Python 全量：**510 passed、1 skipped**，39.47 秒。跳过原有 symlink 创建测试；存在既有 Starlette/httpx 弃用警告。最后补充的 Windows 路径入口专项另行通过 2 项。
- Node 消息/队列/图像/互动状态回归：**29 passed**。
- 新增 `tests/desktop/test_shell.py`：20 次模式往返与窗口身份、geometry 保存恢复、置顶幂等及 1000 次重复请求/事件、双击、通知抑制与路由、损坏 geometry、五档 DPI/负坐标命中计算。
- 新增 `tests/web/test_desktop_entry.py`：正式访问拒绝、静态入口别名、有效 Desktop token/cookie、错误 token、DEV opt-in。
- 原有 Phase 3 Edge 视觉验收：8 种尺寸、公告栏覆盖/已读持久化/失败重试、头像回退和 DPR 2、长聊天全部通过；输出隔离到 `build/v1.2.1/main-regression`，未覆盖历史截图。
- `tests/web/desktop_shell.cjs`：隔离 Edge 模拟 API，20 次页面模式往返、输入/消息 DOM 身份、草稿、无 Session 重读、最近 turn、四档 Companion 尺寸（300×320、390×480、420×540、600×700）、移除头像、精简输入区及双击展开。
- `tests/desktop/native_shell_smoke.py`：实际 Windows / WebView2、本地静态页，无 Core/真实会话。20 次往返、同 HWND 与同 JS 页面标记；168 次真实 WM_NCHITTEST；MAIN 原生最大化/还原；Companion 系统最大化拦截；Native Notification 创建/释放。
- 60 秒原生置顶静置：调用计数保持 1，关闭后总计 2；本次父 Python 进程空闲 CPU 增量为 0.0 秒。此计量**不包括 WebView2 子进程**，不等同于 20–30 分钟真实使用验收。

原生脚本默认静置 60 秒，可用 `ZHAOXI_TEST_SOAK_SECONDS=1200` 延长；运行时会短暂显示隔离测试窗口。测试结果写入 `build/v1.2.1/native-smoke.json`，本次 60 秒证据保存在 `build/v1.2.1/native-soak-60s.json`。初期 `about:blank` 测试未产生 loaded 事件，已更换为真实本地静态页面；最终验证使用后者。

## 产物与截图

- 安装包：`build/v1.2.1/zhaoxi-1.2.1-py3-none-any.whl`。
- 新模块：`desktop/native.py`、`web/static/desktop.js`、`web/static/desktop.css`。
- 配置见 `.env.example`：DEV browser、geometry 路径、系统通知开关。
- [MAIN](screenshots/v1.2.1/main.png)
- [Companion 390×480](screenshots/v1.2.1/companion-390x480.png)
- [Companion 300×320](screenshots/v1.2.1/companion-300x320.png)

运行中的正式实例没有被强行退出或重启，也没有进行真实模型发送、修改个人聊天、改写自启动注册或覆盖用户快捷方式。源代码使用者在托盘彻底退出朝汐再启动后加载新桌面壳。

## 尚需手动验收

代码与自动化完成不替代以下实机验收：

- 在 VS Code 旁连续 20–30 分钟聊天、拖动、缩放、置顶；观察整个进程树 CPU / 内存与输入响应。
- 真实鼠标四边四角 cursor 与拖拽手感；自动化已验证 native hit-test 返回值，未用真实鼠标跑完操作矩阵。
- 100%、125%、150%、175%、200% 实际显示缩放，以及混合 DPI 多屏、拔屏、通知位置。自动化仅验证五档命中数学和当前屏幕的 HWND 行为。
- 托盘/全局快捷键与正式自启动环境、真实语音设备、系统 Toast 的 Windows 通知中心点击。

当前桌面原生适配器面向 Windows WinForms / WebView2。没有把这些未实测项目标记为通过。

## 临时提示修正

Voice 未启用、图片/输入校验错误和窗口操作失败等临时提示统一在 3 秒后清除；重复提示重新计时，旧计时器不会清除已经替换它的录音或思考状态。新增 3 项提示计时回归，Node 共 32 项通过。
