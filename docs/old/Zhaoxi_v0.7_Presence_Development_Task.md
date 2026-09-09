# Zhaoxi v0.7 · Presence 开发任务书

> 项目：**Zhaoxi / 朝汐**  
> 版本：**v0.7 · Presence**  
> 开发基线：**v0.6.1 · Local Interaction Shell**  
> 主平台：**Windows 10，单用户、本机运行**  
> 目标：**让朝汐从“需要主动打开的本地网页”变成可常驻、可随时呼出、会正确通知的日常桌面入口。**

本任务书承接：

- `docs/Zhaoxi_v0.1-v1.0_Development_Plan.md` 中 v0.7 Presence 路线；
- `docs/Zhaoxi_v0.6_Proactive_Agent_Development_Task.md` 的主动事件与投递边界；
- `docs/Zhaoxi_v0.6.1_Local_Interaction_Shell_Task.md` 的本地 Web Chat、Permission Card、Activity 与 SSE 能力；
- `docs/CODEBASE_STATUS.md` 中现有 Core、Planner、Workflow、Permission、Proactive 与测试基线。

核心原则：

> **Presence 负责“朝汐在哪里、怎样被看见和听见”；Zhaoxi Core 继续负责“她怎样理解、规划、执行与记忆”。**

---

## 1. 版本定位

v0.6.1 已经证明：浏览器界面可以通过统一 Adapter 复用同一套 Zhaoxi Core。v0.7 不重写聊天页面，也不复制 Agent Loop，而是在这个基础上补齐日常存在感：

```text
python / launcher 启动
  ↓
单实例后台常驻
  ↓
托盘 / 全局快捷键 / 通知
  ↓
统一 Interface Gateway
  ↓
同一个 Zhaoxi Core
  ↓
Conversation / Planner / Workflow / Permission / Proactive / Tools
```

本版完成后，用户不需要先找终端、运行命令、复制地址再打开浏览器。正常使用路径应缩短为：

```text
按下快捷键 → 输入 → 得到回复
```

主动路径应缩短为：

```text
Proactive Delivery → 系统通知 → 点击后进入对应会话或权限卡片
```

---

## 2. 成功标准

v0.7 必须同时满足：

1. 朝汐可在 Windows 本机以单实例方式常驻，重复启动不会产生多个 Core、Scheduler 或托盘图标；
2. 托盘菜单可以显示、隐藏、打开窗口、查看状态、切换 Quiet Mode 和安全退出；
3. 全局快捷键能在常用前台应用中呼出输入窗口，冲突或注册失败时有明确降级；
4. Desktop、Web 与 CLI 经统一消息边界进入同一 Core，不维护第二套 Agent、Session、Permission 或 Proactive 逻辑；
5. NOTICE / IMPORTANT / URGENT 可映射为系统通知，点击通知能回到正确上下文；
6. Permission 必须在 Core 中创建和裁决，桌面层只能展示并提交 approve / deny；
7. 退出、启动失败、离线或 Provider 异常不会留下不可控后台进程；
8. `python / launcher` 可以稳定启动 Desktop Host，不要求本版完成安装器与发布工程；
9. v0.1～v0.6.1 的核心行为和权限边界不回归；
10. 不依赖真实 API Key 即可完成主要自动化测试。

---

## 3. 范围与优先级

### P0 · 发布阻塞

- Interface Gateway 与统一消息 / 响应 / 活动事件契约；
- Windows 单实例 Desktop Host；
- 托盘、窗口显示隐藏、可控退出；
- 全局快捷键呼出；
- 复用现有 Web UI 的桌面窗口；
- Proactive Delivery 到系统通知；
- 通知点击、Permission 与 Session 路由；
- 生命周期、配置、安全、日志与自动测试；
- 全量回归与文档交付。

### P1 · v0.7 体验完善

- 小型快速输入浮窗；
- 多显示器窗口位置恢复；
- 托盘状态摘要；
- 基础无障碍快捷键与焦点优化。

### P2 · 有余量再做

- 有限的外观设置。

P2 未完成不阻塞 v0.7；不得为了 P2 延误 P0 的生命周期、安全和通知闭环。

---

## 4. 明确不做

本版不做：

- Voice 全部能力，包括 Push-to-talk、Recorder、STT、TTS、音频生命周期和设备异常处理；这些统一进入 v0.7.1；
- Live2D、3D 模型或大型动画系统；
- QQ / 夏苟、Discord、Telegram 等第三方聊天入口；
- 手机客户端；
- 公网部署、远程控制、多用户与账号体系；
- 客户端自己规划、选 Tool、访问 Memory DB 或 Life HUD；
- 为 Desktop 复制一份独立 Conversation；
- 安装、升级、卸载、自动更新和干净 Windows 环境发布验收；这些统一进入 v0.9；
- 开机自启及其残留清理；这些统一进入 v0.9；
- 完整插件市场和主题商店；
- Planner 持久化、Permission 跨进程持久化等非 Presence 核心重构；
- 自动申请管理员权限或绕过操作系统安全提示。

第三方聊天入口必须在本地桌面闭环稳定之后另立任务书。Voice 由 v0.7.1 独立承接；Reliability 与 Release Engineering 由 v0.9 承接。

---

## 5. 架构边界

### 5.1 目标结构

```text
CLI ───────────────┐
Web ───────────────┼─→ Interface Gateway ─→ Zhaoxi Core
Desktop Window ────┘          ├─→ Activity Stream
                              ├─→ Permission View Model
Proactive Runtime ─→ Delivery ┴─→ Notification Router
                                      ├─ Web SSE
                                      ├─ Desktop Toast
                                      └─ Tray Badge / Inbox
```

必须保证：

- Interface Adapter 不导入具体 Tool；
- Desktop Host 不直接读写 Memory、Workflow 或 Proactive SQLite；
- 系统通知不把外部文本当作可执行指令；
- 每个入口提供 `channel`、`session_id`、`request_id`、`origin` 与能力声明；
- Core 返回统一结果，入口只按自身能力渲染；
- Desktop 与 Web 可以共享进程内应用实例，但共享方式必须由 bootstrap 明确组装。

### 5.2 建议目录

```text
src/zhaoxi/
  interfaces/
    models.py          # UnifiedMessage / UnifiedResponse / activity contract
    gateway.py         # chat、permission、session、event 统一入口
  desktop/
    app.py             # Desktop Host 生命周期
    instance.py        # 单实例锁与二次启动激活
    window.py          # 窗口创建、显示、隐藏、恢复
    tray.py            # 托盘菜单与状态
    hotkey.py          # 全局快捷键注册
    notifications.py   # 系统通知 Adapter
```

现有 `src/zhaoxi/web/` 保留为 Web Renderer / Transport，逐步改为调用 Interface Gateway。不要在迁移中一次性重写页面。

---

## 6. 技术决策与 Spike

在阶段 1 结束前完成一个短 Spike，并写入 ADR。至少验证：

- 桌面容器能否直接承载现有本地 Web UI；
- 托盘库在 Windows 10 上的退出、重启和图标回收；
- `RegisterHotKey` 或选定实现的注册、冲突和注销；
- 系统 Toast 的点击回调和开发运行行为；
- `python / launcher` 运行时的静态资源定位。

技术选择顺序：

1. 优先复用 Python 运行时和现有 FastAPI / 原生前端；
2. 优先标准库或小型、维护活跃、边界单一的依赖；
3. 平台相关实现藏在 Adapter 后；
4. 若桌面容器无法稳定支持托盘、快捷键和通知，再评估 Tauri 等更重方案；
5. 不因 UI 框架选择重写 Zhaoxi Core。

ADR 必须记录：候选、选择、理由、已知限制和后续替换成本。Spike 代码不可直接进入生产路径，除非补齐测试和错误处理。

---

## 7. Interface Gateway

### 7.1 UnifiedMessage

最小字段：

```text
message_id
request_id
session_id
channel            # cli / web / desktop
origin             # user / proactive / system
content
created_at
reply_to
capabilities       # markdown / permission_card / audio / notification
metadata           # 有界、白名单、不可执行
```

要求：

- ID 不由前端任意复用；
- `origin=user` 才能作为用户消息进入正常认知链路；
- Proactive 与 System 消息不能伪装成用户消息；
- metadata 有大小、层级和字段白名单；

### 7.2 UnifiedResponse

至少表达：

```text
request_id / session_id / trace_id
status
content
activity
permission
attachments
error_view
```

普通渲染层不得收到 traceback、密钥、完整 Tool 参数、Memory 正文或原始外部 payload。

### 7.3 并发与顺序

- 同一 Session 默认串行处理用户请求；
- 重复 request_id 幂等返回或明确拒绝；
- 正在处理时再次发送必须排队或显式取消，不允许静默并发污染 Conversation；
- Activity 与最终结果带 request_id，避免桌面窗口把旧状态显示到新请求；
- Desktop 退出时不强杀正在进行的 WRITE；应等待有界时间或保留明确的未知结果审计。

---

## 8. Desktop Host

### 8.1 单实例

使用用户级锁和本地激活通道：

```text
首次启动 → 获得锁 → 启动 Core / Web / Proactive / Tray
再次启动 → 不创建新 Core → 通知已有实例显示窗口 → 自己退出
```

要求：

- 锁异常退出后可恢复；
- 激活通道仅监听本机并使用随机令牌或等价保护；
- 不因残留锁永久阻止启动；
- 二次启动不得再次运行 Scheduler 或重复投递通知。

### 8.2 生命周期

状态机：

```text
STARTING → RUNNING → STOPPING → STOPPED
             ↓
          DEGRADED
```

启动顺序建议：

```text
加载配置
→ 获得单实例锁
→ 组装 Core 与 Store
→ 启动本地 Web / Interface Gateway
→ 启动 Proactive Runtime
→ 注册通知、托盘与快捷键
→ 创建或恢复窗口
```

退出顺序反向执行。每一步都要支持部分启动失败后的清理。

### 8.3 窗口行为

- 默认关闭按钮隐藏到托盘，不结束 Core；
- 托盘“退出朝汐”才执行完整 graceful shutdown；
- 首次运行明确提示“关闭窗口后仍在后台运行”；
- 窗口位置必须限制在当前可见屏幕范围；
- 本地服务未就绪时显示可恢复错误页，不显示空白窗口；
- 开发者可通过配置选择“关闭即退出”。

---

## 9. 托盘与全局快捷键

托盘菜单至少包含：

```text
打开朝汐
快速输入
当前状态
Quiet Mode：开 / 关
打开日志目录
设置
退出朝汐
```

P0 中“快速输入”和“设置”可以先路由到主窗口相应区域，不要求独立复杂页面。

快捷键要求：

- 默认值配置化，例如 Ctrl+Alt+小键盘 0（`ctrl+alt+numpad0`）；
- 注册失败时显示可理解提示并保留托盘入口；
- 支持重新注册和退出时注销；
- 不记录用户在其他程序中的按键；
- 不实现通用键盘钩子日志；
- 长按或连按不得创建多个窗口；
- 输入框获得焦点，Esc 隐藏，未发送草稿按明确策略保留。

---

## 10. 系统通知

### 10.1 Notification Router

系统通知是 `NotificationSink`，不是新的 Interrupt Policy。它只消费 Core 已经裁决为可投递的 Delivery：

```text
Interrupt Policy
→ Delivery
→ Notification Router
   ├─ Web SSE
   ├─ Windows Toast
   └─ Inbox / Tray
```

建议映射：

| Priority | 默认桌面行为 |
|---|---|
| INFO | 仅 Inbox / 托盘状态，不弹 Toast |
| NOTICE | 普通 Toast，可被 Quiet / Night 延期 |
| IMPORTANT | 强调 Toast，但不抢占输入焦点 |
| URGENT | 高优先通知；仍尊重用户显式全局关闭 |

### 10.2 点击与动作

- 点击正文：打开对应 Session / Delivery；
- `查看`：进入通知详情并显示 explain；
- `稍后提醒`：调用 Core 的 defer 能力，不由 OS 层自行计时；
- Permission 操作默认只打开 Permission Card；
- P0 不在 Toast 上直接批准 WRITE / DELETE / EXTERNAL_ACTION / DANGEROUS；
- 已过期或已处理的通知点击后显示真实状态，不重复执行动作。

通知正文不得包含密钥、完整路径、完整 Tool 参数、Memory 原文或未经清洗的外部 payload。

---

## 11. 后续版本边界

### v0.7.1 · Voice

Voice 整块延后，不在 v0.7 中预埋半套实现。v0.7.1 独立负责：

- Push-to-talk 与录音状态；
- Recorder 和音频生命周期；
- 可替换 STT / TTS Provider；
- transcript 复核与发送；
- 可中断 TTS；
- 麦克风、设备切换、临时文件、超时与失败恢复；
- Quiet / Night 与语音播报策略；
- 语音隐私、安全边界和完整状态机。

v0.7 只需保证 Interface Gateway 能在未来增加新 channel，不为 Voice 添加发布阻塞项。

### v0.9 · Reliability / Release Engineering

以下内容统一由 v0.9 承接：

- 安装、升级、卸载与自动更新；
- 干净 Windows 用户环境验收；
- 开机自启及残留项清理；
- 正式构建物、签名、发布、回滚和长期运行硬化。

v0.7 的运行边界是：

```text
python / launcher → 单实例 Desktop Host → 托盘 / 快捷键 / 通知
```

---

## 12. 配置

建议新增：

```dotenv
ZHAOXI_DESKTOP_ENABLED=true
ZHAOXI_DESKTOP_START_HIDDEN=false
ZHAOXI_DESKTOP_CLOSE_TO_TRAY=true
ZHAOXI_DESKTOP_SINGLE_INSTANCE=true
ZHAOXI_DESKTOP_HOTKEY=ctrl+alt+numpad0
ZHAOXI_DESKTOP_NOTIFICATIONS=true
ZHAOXI_DESKTOP_WINDOW_WIDTH=1080
ZHAOXI_DESKTOP_WINDOW_HEIGHT=760
```

要求：

- 所有枚举、尺寸、时长和快捷键必须校验；
- 配置错误应定位到具体变量，桌面层可降级时不要让整个 Core 无法启动；
- 新增配置同步 `.env.example`、配置测试、README 和 `CODEBASE_STATUS.md`；

---

## 13. 安全与隐私

1. Desktop 内嵌页面只允许访问本地可信 Origin；
2. 继续默认监听 `127.0.0.1`，不得为了桌面接入改为 `0.0.0.0`；
3. 本地 API 采用每次启动生成的会话令牌或等价防护，防止其他网页跨站调用；
4. CSP 禁止任意远程脚本，静态资源由本地可信路径提供；
5. 外部链接交给系统浏览器，并在打开前校验协议；
6. 通知和托盘入口均不能绕过 `PermissionGateway`；
7. 高风险确认必须在可见 UI 中完成；
8. 日志和 Crash Report 不得保存密钥和完整敏感上下文；
9. Desktop Host 不提供任意命令执行、任意文件 URL 或调试远程端口。

---

## 14. 可观测性与错误体验

日志事件至少包含：

```text
desktop_start / desktop_stop
single_instance_activate
window_show / window_hide
tray_action
hotkey_register / hotkey_conflict
notification_deliver / notification_open
interface_request / interface_result
```

只记录必要元数据、状态、耗时、request_id 和 trace_id；不记录完整用户消息或 Tool 原始参数。

错误分层：

- 用户可恢复：在窗口中给出动作，例如“重新注册快捷键”；
- 功能降级：托盘失败时仍可用 Web / CLI，快捷键失败时仍可从托盘打开；
- 启动阻塞：Core 配置或 Store 损坏时展示诊断并安全退出；
- 开发详情：写入日志与 Debug Drawer，不进入普通聊天气泡。

---

## 15. 开发流程

### 阶段 0：冻结基线与补齐 v0.6 契约

工作：

- 保存并确认当前 v0.6/v0.6.1 未提交基线；
- 跑全量测试、编译检查与 Web 黑盒冒烟；
- 对齐 `CODEBASE_STATUS.md` 与实际能力；
- 明确 Proactive 中 Quiet、限频、延期重投哪些是 v0.7 前置阻塞；
- 冻结 UnifiedMessage、UnifiedResponse、Activity 与 Notification Sink 契约。

退出条件：当前行为有可重复验证结果，Presence 不依赖未定义的 v0.6 状态。

### 阶段 1：技术 Spike 与 ADR

工作：验证桌面容器、托盘、快捷键、Toast 和本地资源定位。

退出条件：形成一份 ADR；能够在开发环境完成“托盘 → 呼出窗口 → Toast 点击回到窗口”的最小实验。

### 阶段 2：Interface Gateway

工作：

- 新增统一 DTO、Gateway、request_id 和 channel/origin；
- 让现有 Web Adapter 改走 Gateway；
- 固化 Session 串行、错误视图、Permission View Model 和 Activity 关联；
- 保持 CLI 行为兼容。

退出条件：CLI 与 Web 对同一 Fake Core 的语义一致，Web 回归测试通过。

### 阶段 3：Desktop Host 纵向切片

工作：

- 单实例；
- 生命周期组装；
- 承载现有 Web UI；
- 显示、隐藏、退出；
- 托盘与快捷键；
- 本地令牌和安全 Origin。

退出条件：重复启动只激活已有窗口；连续显示隐藏 20 次无多余实例；退出后端口、锁、图标和快捷键均释放。

### 阶段 4：通知闭环

工作：

- Desktop Notification Sink；
- Priority 映射；
- 点击路由；
- explain、ack、defer 与过期状态；
- Quiet / Night / 全局关闭联动。

退出条件：Fake Clock 触发 Delivery 后只出现一次通知，点击进入正确 Session，处理后不重复动作。

### 阶段 5：运行恢复与硬化

工作：

- 固定 `python / launcher` 启动方式；
- 资源路径与配置目录；
- 崩溃后锁恢复；
- 全量测试、编译、lint/diff 检查；
- 生命周期与并发压力；
- 权限、Origin 和通知隐私审计；
- 更新版本号、README、`.env.example`、`CODEBASE_STATUS.md`；
- 检查仓库和运行说明中无 `.env`、数据库、日志或真实用户数据。

退出条件：P0 全部通过，P1 未完成项有明确记录且不破坏文字路径；安装与发布工程明确留给 v0.9。

---

## 16. 测试矩阵

### Interface

- channel / origin / session / request ID 校验；
- 同 Session 串行与重复请求幂等；
- Activity 不串线；
- Proactive 不能伪装 user；
- 错误视图不泄漏内部对象；
- CLI / Web / Desktop 语义一致。

### Desktop 生命周期

- 首次启动、重复启动、异常锁恢复；
- 部分初始化失败后的逆序清理；
- 显示、隐藏、Esc、关闭到托盘；
- graceful shutdown 和有界超时；
- 端口、锁、快捷键、托盘图标释放；
- 多显示器拔插后的窗口恢复。

### 托盘与快捷键

- 菜单动作路由；
- Quiet 状态同步；
- 快捷键注册、冲突、重注册、注销；
- 快速连按只显示一个窗口；
- 不采集其他按键。

### 通知

- 四级 Priority 映射；
- Quiet / Night / global off；
- 去重、过期、ack、defer；
- 点击进入正确 Session / Delivery；
- 已处理通知不重复执行；
- Permission 只打开卡片，不在 Toast 直接批准；
- 正文脱敏与长度限制。

### 安全与回归

- 本地 API 令牌、Origin、CSP 和外部链接协议；
- Desktop / Notification 不绕过 Permission；
- 无真实凭据的全量测试；
- v0.1～v0.6.1 全部自动化测试通过；
- Web 仍可独立运行，CLI 仍可独立运行。

测试分层：

```text
纯单元测试：状态机、DTO、策略、路由、配置
Adapter 合约测试：Fake OS / Fake Notification
进程集成测试：单实例、启动退出、端口和锁释放
Windows 黑盒测试：托盘、快捷键、Toast、窗口焦点
```

自动化测试不能依赖真实 sleep；时间、OS Adapter 和通知均需可注入 Fake。

---

## 17. 集中黑盒冒烟验收

人工验收不再按每个开发阶段重复执行。以朝汐本体开发完成、自动化测试通过后进行一次集中黑盒冒烟为基准，只保留四条主链路。

### Case A：日常呼出

启动朝汐后关闭窗口；按全局快捷键，窗口在可见屏幕内出现且输入框聚焦。发送“你是谁？”，回复正常，Debug 信息不进入聊天区。

### Case B：重复启动

朝汐已运行时再次启动。已有窗口被激活，系统中仍只有一个 Core、一个 Proactive Runtime、一个托盘图标和一个监听端口。

### Case C：权限与主动通知

提出一个 WRITE 请求，验证 Permission Card 的允许与拒绝。再用 Fake Clock 触发 NOTICE，验证普通时段只通知一次、点击进入正确上下文；Quiet 下延期并在恢复后最多投递一次。Toast 不直接批准权限。

### Case D：故障与退出

断开 Provider，确认页面给出可恢复提示，托盘仍可用。在普通请求、等待 Permission、主动任务运行三种状态中抽取代表性状态执行退出；程序有界停止，重启后无重复通知、残留锁或僵尸进程。

---

## 18. 交付物

- `src/zhaoxi/interfaces/` 统一接口层；
- `src/zhaoxi/desktop/` Windows-first Desktop Host；
- 对应 `tests/interfaces/`、`tests/desktop/`；
- 技术选型 ADR；
- Windows `python / launcher` 开发运行与故障排查说明；
- 更新后的 README、`.env.example`、版本号和 `CODEBASE_STATUS.md`；
- 本体开发完成后的一份集中黑盒冒烟结果；
- 仓库中不包含真实凭据、数据库、日志或用户数据。

---

## 19. Definition of Done

v0.7 完成必须满足：

1. P0 全部完成并有自动化证据；
2. Desktop、Web、CLI 共享 Interface Gateway 和同一 Core 语义；
3. `python / launcher` 能启动单实例 Desktop Host；
4. 单实例、托盘、快捷键、通知和退出在当前 Windows 10 开发环境通过集中黑盒冒烟；
5. 通知不绕过 Permission、Quiet、Night 和 Proactive Policy；
6. 默认不监听公网；
7. 所有本版平台资源在正常退出和异常恢复后可清理；
8. 全量自动化测试通过，测试数和验证命令写入 `CODEBASE_STATUS.md`；
9. 版本号、README、`.env.example`、任务书和交接文档一致；
10. Voice 明确留给 v0.7.1，安装、卸载、开机自启和干净环境发布硬化明确留给 v0.9。

---

## 20. 推荐提交切片

```text
1. docs: freeze v0.7 presence contracts and ADR
2. feat: add unified interface gateway
3. feat: add single-instance desktop host
4. feat: add tray and global hotkey presence
5. feat: route proactive deliveries to desktop notifications
6. test: harden lifecycle security and regression coverage
7. docs: finalize v0.7 delivery and codebase status
```

每个切片都必须保持文字交互可用；涉及平台资源的切片必须同时提交清理路径和测试。

---

## 21. 一句话验收

> **当用户通过 `python / launcher` 启动朝汐后，无需寻找终端或浏览器，只要按下快捷键就能叫出她；当朝汐主动提醒时，通知只出现一次、可以解释、不会越权，并且所有入口始终复用同一个安全可控的 Zhaoxi Core，v0.7 才算完成。**
