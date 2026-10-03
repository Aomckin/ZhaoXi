# Zhaoxi v1.4.5 开发记录

日期：2026-10-03。依据 [开发任务书](Zhaoxi_v1.4.5_Dashboard_Control_Plane_开发任务书.md)。本记录对应最终 v1.4.5 本地版本提交，包含工程面板点击修复、本地文件工具链修复及 Dashboard 浏览器迁移。正式桌面实例未重启加载，未推送或外部发布；其他版本任务书和独立 LifeHUD 改动保留在工作区。

## 实现

| 任务主线 | 实现位置与行为 |
| --- | --- |
| Dashboard Split | `web/dashboard.py` 与独立 `dashboard*.js/html/css`；`index.html` 移出工程控件，原 Shell 脚本提取为 `shell.js`；`engineering.html/js` 复用原检查器并按页面延迟加载。 |
| Action Receipt | `internal_activity/receipt.py` 模型与确定性中文模板；Runtime 发出同 action_id 的 started / finished SSE，记录成功、无变化、跳过、拒绝、失败与取消。修改列表与原始数据折叠。 |
| Activity History | `activity_history` SQLite 表，最多 200 条、默认每页 20 条；常规未到期候选不刷屏，Heartbeat 诊断仍记录其跳过原因。 |
| Presence Control | `internal_activity/control.py` 与 `proactive/interaction.py`；驻留时钟、五态倍率、开关、睡眠窗口、进入时间和切换预测；Heartbeat 等待收到配置更新后重新排期。 |
| Activity Matrix | 复用现有 Registry / Scheduler / TickBudget；五态 AUTO / MANUAL_ONLY / DISABLED、启用、priority、interval、daily budget；前台与社交安全 Gate 保持有效。 |
| Cognition Editor | `current_cognition/editor.py`：领域操作、元数据、抑制记录、合并、淡出、事务修订与目标级 undo；API 有版本冲突检查。 |
| Manual Guard | `service.py` 与 Gardening：PINNED 不自动降温退出，LOCKED 不覆盖正文；resolved / dismissed 活跃条目退出，7 天旧证据抑制；渲染保留受保护的陈旧条目。 |
| Persistence / Backup | Runtime 设置 JSON 原子替换，配置验证失败不改变生效值；新配置文件纳入 `bootstrap/storage.py` 数据源注册表。 |
| Desktop Navigation | 小桌边与托盘通过系统浏览器打开 Dashboard；管理页不加载原生窗口控件，唤起桌面按钮调用 Host 回调。 |

## 验收结果

| 验收范围 | 最终结果 |
| --- | --- |
| Python 全量 | Python 全量 1169 项通过、1 项跳过（233.79 秒）。命令：`python -m pytest -q -o addopts='' --basetemp=.zhaoxi/v145-commit-final`。 |
| Node 前端 | `node --test tests/web/*.test.cjs`，78 项通过；提交前复跑通过。 |
| Web / Desktop 专项 | 浏览器迁移后的 Python 152 项通过，覆盖独立会话、请求来源和原生回调。 |
| Dashboard 整体浏览器 | `dashboard_smoke_server.py` + `dashboard_smoke.cjs`；独立存储、假模型、无插件，八项检查通过，无脚本错误。 |
| 浏览器入口与工程点击 | `dashboard_web_smoke.cjs` + `dashboard_engineering_smoke.cjs`；开发模式关闭、无桌面 cookie，根地址跳转、设置保存、四页 28 个折叠项展开 / 收起与键盘焦点通过。 |
| 桌面导航 | Python opener 回调及浏览器中的 native bridge mock 通过；真实 pywebview 窗口尚未重启验收。 |
| 打包 | wheel 构建完成；280 个源码与静态资源文件一致，旧 Dashboard 原生桥接脚本不再打包。 |

验收汇总见 [JSON 记录](evidence/dashboard_v145_acceptance.json)，浏览器迁移原始结果见 [Web 验收](evidence/dashboard_web_v145_acceptance.json)。截图和 wheel 保存在本地 `.zhaoxi/`，不纳入版本提交。Starlette TestClient 原有弃用警告仍存在。

## 专项覆盖

- Owner 输入刷新窗口，前台结束刷新驻留，ACTIVE → SEMI_ACTIVE → IDLE；强制状态不被输入清除；恢复自动、保存时长与禁用 Heartbeat。
- Heartbeat 等待被配置修改唤醒，重排下次预计时间；无值、NaN / Infinity、负数与非法倍率不写入设置。
- 五态 × 三态权限 × 自动 / 手动；总开关和日预算不能被手动调用绕过；动态注册活动仍可运行。
- RUNNING / FINISHED action_id 一致；持久历史；前台抢占 CANCELLED；失败阶段；社交未确认不调用模型或发送消息。
- Overview / Thread / Watch / Change 人工编辑、元数据、历史、merge / undo；保留不相关后台变化并拒绝有冲突的撤销。
- PINNED / LOCKED 的陈旧保护、锁定概览与正文不覆盖、RESOLVED / DISMISSED 不以同 key 或等价旧证据重生。
- Dashboard 和工程 HTML 使用独立本机浏览器会话，桌面对话 HTML 保留 Desktop 会话边界；API 参数有界；字段显示使用 textContent，字面 HTML 不执行。

## 设计边界

- Activity 与资源每日预算对旧的无独立上限行为保留高上限默认值；现有 Reminiscence / Social 等独立预算继续优先限制。资源计数是保守预留，可能包含无模型调用的本地筛选与失败尝试。
- 强制 Presence 可压过自动判断，但不会绕过正在执行的前台任务对后台 Activity 的拒绝。
- 抑制采用 key、规范化文本相似度和旧证据集合，属于有界防重生规则；没有引入新的语义模型。
- Undo 仅撤销最近人工修订；目标被后台改动后返回冲突，避免整个快照回滚覆盖新状态。
- 工程工具仍复用原 Shell 代码，未开展全量 Web Backend、Memory 或 Scheduler 重写。
- 可选生活风格 Preset 未实现；正式 pywebview 交互、真实模型 / QQ 与长期 dogfooding 尚未进行。当前源码版本为 1.4.5，正式进程版本需要重启后确认。

## 工程子面板点击修复

独立工程页复用 `scene.css`，继承收起抽屉的 `#desk { pointer-events: none }`，导致内容可见但无法交互。工程页布局明确覆盖为 `pointer-events: auto`。

原验收只检查 iframe 加载；现已加入真实鼠标点击四页 28 个可见折叠项（含嵌套项）、展开 / 收起、刷新请求及输入框焦点检查。设置页在无 Context Builder 的隔离 fixture 中返回 409，页面明确显示原因。

## 本地文件工具链修复

日志显示目录与搜索工具已成功，正文读取前却因发现轮占用额度进入强制收尾；随后 Provider 返回格式错误。纯控制轮成功扩展新可用 schema 时，LoopSafety 最多给予一次独立发现轮额度，实际模型调用仍全部计数。重复发现、失败发现、混合业务调用和业务开始后的发现不增加额度；FAST、Token、`max_steps`、模型总预算与权限限制继续生效。

没有新增用户文本关键词路由。Provider 严格解析协议，只补充错误类型及位置诊断。实际 Filesystem MCP 列出并完整读取本地任务书，15914 字符与直接读取一致；该探针没有调用真实模型。证据、专项回归与未知错误边界见 [排查记录](Zhaoxi_v1.4.5_Local_File_Tool_Investigation.md)及 [排查证据](evidence/local_file_tool_investigation.json)。

## Dashboard 浏览器入口

根地址进入 `/dashboard`，首次打开建立独立 HttpOnly / SameSite=Strict 会话。管理页及该会话的 API 校验回环来源、Host、Origin 和 Fetch Metadata；工程 iframe 复用会话。桌面 cookie 继续负责生活页面。

小桌边的 `open_dashboard` 原生命令和托盘设置通过系统浏览器打开管理页，聊天 WebView 保留原页面；普通开发浏览器链接打开新标签。移除 Dashboard 原生窗口控件，顶部按钮调用受保护 API 唤起桌面主窗口；无 Host 回调时返回 409 并显示原因。

加载本次 Python 变更需退出并重新启动整个桌面进程；单独重建 Agent 的“重启 Core”不足以重新加载模块。正式进程尚未重启，当前验收均为隔离实例。
