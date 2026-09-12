# Zhaoxi v1.1.2 开发与验收报告

日期：2026-09-07。分支 `v1.1.2`；基线 `0b65cfd`（已提交的 v1.1.1）。本次包含前一轮架构清理及潮间态开发，运行时与 Core 包版本均为 `1.1.2`，LifeHUD-Tool 保持独立版本 `1.0.0`。

## 实现与文件

| 范围 | 主要文件 | 实现 |
| --- | --- | --- |
| 消息时间轴 | `core/message.py`、`conversation.py`、`context.py`、`session/sqlite.py` | 复用已有 timezone-aware `timestamp`，避免引入第二套时间字段；保留用户/助手原始时间，主动消息新增 `delivery_id` 和有界 `background`，随 Session JSON 持久化。 |
| 模型上下文 | `core/context.py`、`cli.py` | 用消息副本注入绝对时间、时区、角色和主动消息标识；系统提示包含当前时间与互动状态。原始消息正文不被时间前缀修改，图像和工具调用结构保持。 |
| 主动消息续聊 | `interfaces/gateway.py`、`web/app.py` | 在读取会话及下一轮聊天前，将已送达消息按原发送时间插入时间轴，按 delivery ID 去重；点击只更新已读并保留背景；清空后持久化时间边界，避免旧消息自动重现。 |
| 历史兼容 | `session/sqlite.py` | 读取 v1.1.1 的 `[朝汐主动消息 · 时间]` 记录时分离时间、正文与背景，下次保存写入结构化字段。无需变更 SQLite 表结构。 |
| 状态机 | `proactive/interaction.py`、`policy.py` | ACTIVE / SEMI_ACTIVE / IDLE / AWAY，使用可注入时间；状态缓存、last_seen、变化队列有界。 |
| 桌面采样 | `desktop/presence.py`、`desktop/app.py` | 默认每个 Heartbeat 采样一次，在线程中执行轻量 Win32 查询；模型决策返回后再采样一次，防止等待期间进入全屏却仍弹消息。 |
| 主动门槛 | `proactive/heartbeat.py`、`scoring.py`、`runtime.py`、`worker.py`、`buffer.py` | 接入状态阈值、全屏延迟、离开仅 Inbox；延迟消息的重新投递也经过策略。变化事件去重、30分钟 TTL，非候选变化只留事件记录，不显示调试文字。 |
| 动态建议 | `core/suggestions.py`、`core/agent.py`、`proactive/decision.py`、`web/app.py` | 普通回复可附加建议 JSON，服务端提取并移除；主动决策可返回同一结构。无合法模型建议时根据时间、最近对话、互动状态、Focus 和近期主动消息本地生成四条建议。 |
| UI | `web/static/index.html`、`web/adapter.py`、`interfaces/models.py` | 图片按钮改相册 SVG、保留 tooltip 和上传能力；普通/主动消息统一使用配置时区显示时间；建议从 `/api/suggestions` 获取，聊天/主动消息后及每分钟刷新缓存视图。 |
| 应用图标 | `web/static/zhaoxi.ico`、`zhaoxi.png`、`desktop/window.py`、`tray.py`、`scripts/create_desktop_launcher.ps1`、`pyproject.toml` | 蓝底“汐”字 PNG/多尺寸 ICO，接入 pywebview、AppUserModelID、托盘、favicon 和快捷方式；只打包图片，不分发字体文件。 |
| 配置与交接 | `config/settings.py`、`.env.example`、`README.md`、`docs/README.md`、`CODEBASE_STATUS.md` | 新配置说明与当前版本事实同步。 |

## 状态转换

- 用户发送消息或打开主动消息：ACTIVE，刷新最后互动时间。实际聊天执行期间 `interacting` 阻止主动打断。
- 默认20分钟没有新互动：SEMI_ACTIVE；随后45分钟没有新信号：IDLE。
- 键鼠闲置达到30分钟或检测到锁屏/不可访问桌面：AWAY。
- AWAY 后检测到输入恢复：SEMI_ACTIVE，产生一次 `user.returned`；不会恢复旧 ACTIVE 计时。
- 退出全屏、活动重新开始、Focus 结束、手动打开窗口：在非 ACTIVE/AWAY 状态下进入 SEMI_ACTIVE。窗口回调通过线程安全信号交给采样处理，不直接跨线程改状态。
- `user.away/returned`、`activity.started/stopped`、`fullscreen.entered/exited`、`foreground.changed`、`focus.started/ended`、`conversation.started/cooled` 仅在变化时产生。

## Windows API 与隐私

采样使用 `GetLastInputInfo` / `GetTickCount` 计算闲置秒数；使用 `OpenInputDesktop` / `GetUserObjectInformationW` / `CloseDesktop` 判断输入桌面可访问性；通过 `GetForegroundWindow`、`GetWindowThreadProcessId`、`OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`、`QueryFullProcessImageNameW` 查询进程并只保留文件名；通过 `GetWindowRect`、`MonitorFromWindow`、`GetMonitorInfoW` 比较前台窗口与所在显示器完整边界。

不读取按键、文本、鼠标坐标/点击内容、剪贴板、窗口标题、网页正文、文档或截图；不安装键盘 Hook。进程完整路径不会存储或进入模型上下文。桌面状态元数据会进入已配置模型的上下文。采样失败时标记 unhealthy，普通消息保守延迟；异常不会终止 Heartbeat。

实现依据：[Microsoft GetLastInputInfo](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getlastinputinfo)、[OpenInputDesktop](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-openinputdesktop)。LastInput 是当前用户会话的信息，不是所有登录会话的全局输入记录。

## Gate 与 Natural Check-in

ACTIVE / SEMI_ACTIVE / IDLE 默认阈值为 0.45 / 0.55 / 0.70；配置校验要求按此顺序非递减。AWAY 普通消息只进入 Inbox；全屏或桌面采样不健康时延迟普通消息。Quiet、夜间、最近聊天15分钟、普通消息45分钟冷却继续有效；Reminder 和 URGENT 沿用已有优先级规则，只有 URGENT 绕过 Quiet/夜间。

ACTIVE、AWAY 不产生自然巡检；SEMI_ACTIVE 在至少45分钟无聊天后可产生轻量巡检；IDLE 继续默认至少3小时。仍要求近期键鼠活动、无 Focus、健康生活来源、有上下文，每个本地日期最多一个 natural_checkin。返回、退出全屏和 Focus 结束可另产生低成本变化候选。

## Suggestions 与 Debug

建议按 chat / action / life / explore 四类验证，要求非空、有界、不同质文本；JSON 标记不会进入正式回复。缓存包含 generated_at、suggestions、source_context，默认最长180分钟，上下文变化可本地刷新。`ZHAOXI_QUICK_SUGGESTIONS_REFRESH_MINUTES` 控制缓存时长；不增加后台刷新模型请求，额外 LLM 调用数固定为0。

聊天区只呈现正文、主动标识和本地时间。原始时间、delivery/event ID、触发原因及相关背景在独立 `/api/proactive/{id}/inspect` 中提供，点击消息后写入 Debug；该接口遵循 Desktop API token 边界。普通 `/api/session` 和 Inbox 列表不暴露背景字段。

## 清理项

移除了 Web 固定响应类型的 getattr 默认成功兜底、CLI 为不完整 Settings 替身保留的分支、旧 metadata API 兼容、重复 capability 定义/赋值，以及重复导入测试。Permission 使用统一 save_grant；Planner 使用公开 list_sync 恢复权限等待。发布测试改为实际校验 wheel/版本/敏感文件/哈希，以及使用替身执行安装卸载脚本。build_release 的冒烟版本不再写死1.0.0，而使用验证器返回值。

## 自动化与实测

- Python：351项通过；Node：17项通过；1项既有 Starlette/httpx 弃用警告。
- compileall 与 git diff --check 通过。
- 包含跨日时间恢复、模型时间上下文、旧主动消息迁移、完整状态衰减/返回/锁屏、全屏几何和状态变化、决策后再次采样、动态门槛、自然巡检、建议缓存与单次模型调用、API鉴权和清空后不重现等行为测试。
- Windows 采样已在本机只读执行，返回类型与健康状态正常；未打印实际前台进程等用户状态。
- 浏览器隔离数据验收完成：跨日/本地时间、图片图标、四条动态建议、主动消息已读切换、正文与 Debug 分离；不调用真实模型或 LifeHUD。
- Core / LifeHUD-Tool 验证 wheel 位于 `dist/v1.1.2-validation`；资源及敏感文件检查、SHA256 输出、隔离目录安装导入通过，未安装覆盖用户运行实例。
- 构建使用本机已有 setuptools 工具链。项目 venv 缺少 setuptools 且网络安装受限，使用已安装的全局 Python 构建，无需新增运行依赖。

## 手动验收

1. 完全退出已有朝汐并启动新版 Desktop；检查标题栏、任务栏、托盘和快捷方式图标。
2. 发送两轮消息，查看 `/api/diagnostics` 中 presence 为 ACTIVE；停止聊天，按20/45分钟观察衰减。可在测试配置中缩短超时，不修改真实数据。
3. 锁屏/长时间离开后返回，观察一次 user.returned 与 SEMI_ACTIVE；普通消息不应在 AWAY 弹出。
4. 进入和退出全屏程序，观察 fullscreen 与变化事件，普通主动消息应延迟；跨显示器测试边界。
5. 次日继续对话，查看旧消息时间和模型是否理解跨天；点击旧主动消息，确认正文无背景字段，Debug 能查看背景。
6. 聊天、结束专注后查看建议变化；diagnostics 的 quick_suggestions_llm_calls 应为0。
7. 验证 Reminder / Quiet / 夜间、Windows Toast 点击和真实 LifeHUD Focus 的端到端行为。

## 已知限制

- 实机锁屏、系统睡眠/唤醒、全屏应用、Toast、任务栏图标及真实模型/LifeHUD长时运行仍需上述人工验收；自动测试和浏览器样例不等于这些场景已实测。
- 采用周期采样，短于采样间隔的变化可能不被捕获；睡眠期间进程无法采样，恢复后依赖输入桌面/闲置读数更新，不单独订阅系统电源事件。
- 状态与建议缓存为进程内数据，重启重新采样；消息时间和关联背景持久保存。旧记录如果本来没有时间字段，无法推断真实发生时间。
- Fullscreen 是前台窗口几何判断，不做屏幕内容识别；某些特殊覆盖层/游戏窗口需要实机确认。
- 模型若不返回合法建议，使用本地上下文兜底；不为提高建议多样性额外消耗模型调用。
- 验证 wheel 是开发验收产物，尚未签名、发布或做用户安装覆盖。本报告与实现由 v1.1.2 提交一并归档。
