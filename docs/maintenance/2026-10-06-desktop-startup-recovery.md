# 快速入口 Core 启动失败排查与修复

日期：2026-10-06。依据用户截图检查实际进程、监听端口、日志和数据库。源码修复与隔离验收已完成；正式实例未重启，原数据库与事务日志保持原样。

## 进程与现象

快速入口 `启动朝汐.lnk` 正确指向本项目 `.venv/Scripts/pythonw.exe`，参数为本项目 `main.py --desktop`，工作目录也是项目根目录。

检查时 PID 6488 是虚拟环境启动器，PID 29688 是其 Python 3.14 实际解释器；二者不是两个独立 Core。PID 29688 监听 `127.0.0.1:4913`。日志在 09:57:02 记录该进程的 Uvicorn 服务完成启动。

通过本地 Dashboard 正常建立管理会话后，只读 API 返回：`core.healthy=false`、`activity_available=false`，但启动诊断却为 `ready`、模型配置完整、存储诊断为空。这是 `StartupUnavailableAgent` 降级服务的特征：HTTP 服务运行，完整 Core 未完成初始化。旧代码未记录捕获的启动异常，桌面将 SSE 建立连接直接显示为“本地 Core 已连接”，造成截图中的矛盾。

## 原因与数据验证

生产数据库逐个使用 SQLite `mode=ro` 执行 `PRAGMA quick_check`。14 个数据库返回 `ok`，仅 `internal_activity` 报 `OperationalError: attempt to write a readonly database`；该文件存在 8720 字节的 rollback journal。

把数据库及 journal 一起复制到本机诊断目录，在副本上使用 SQLite 正常读写打开，使其执行标准事务恢复。随后 `PRAGMA integrity_check` 返回 `ok`，三张活动表仍存在，副本 journal 已由 SQLite 移除。原数据库和 journal 的 SHA-256 在操作前后相同。没有手动删除正式 journal，没有恢复旧备份，没有修改正式数据。

根因是 `bootstrap/runtime.py` 先执行只读健康检查，再初始化 `InternalActivityRuntime`。残留 hot journal 需要 SQLite 正常打开数据库后完成回滚；只读连接无法恢复，于是健康检查误判失败并抛出 `ConfigError`。日志为什么残留尚未确定，不能仅凭它推断实际数据库损坏或是哪次退出造成的。

## 源码修复

- 内部活动存储初始化后再运行原有只读健康检查，让 SQLite 在正常初始化期间处理 hot journal。健康检查本身仍为只读，不跳过完整性检查。
- 内部活动初始化发生 SQLite 错误时转换为可诊断的 `ConfigError`，仍阻止完整 Core 启动；真正损坏的数据库不会被当成健康数据继续运行。
- Desktop 和 Web 记录捕获的 Core 初始化失败；降级 Agent 在启动诊断中加入失败原因，将配置完整但初始化失败的状态改为 `blocked`。
- Desktop 的连接状态根据启动诊断显示；SSE 连接成功先显示检查中。Dashboard 概览显示实际启动原因。配置完整的降级聊天也返回真实错误，不再只提示首次配置。
- `/api/health` 保留 HTTP 服务存活字段，并增加 `core_ready` 区分完整 Core 是否就绪。前端构建标识为 `v1.4.7-startup-recovery-20261006`。

## 验收

[结构化证据](evidence/2026-10-06-desktop-startup-recovery.json)。

- Python 专项共 57 项通过，覆盖运行时装配、Desktop、Web、Dashboard、启动诊断和备份存储。最后新增损坏数据回归后，运行时装配 4 项重新通过，其余 53 项沿用此前已通过结果。
- 新增测试用独立子进程中断 SQLite 写事务，确认只读检查真实报 readonly；完整 Core 装配可以恢复、通过健康检查，并保持中断前已提交的数据。未使用正式数据库或真实模型调用。
- 真正损坏的内部活动文件仍抛出 `ConfigError`，文件字节保持不变。
- 前端 Node 98 项通过，包含配置完整但初始化失败的提示、首次配置提示、健康状态和既有界面回归；`shell.js` 语法与 `git diff --check` 通过。
- 正式原库及 journal 的哈希未变；排查当时 PID 29688 运行旧代码；这是当时进程快照，不代表提交时已重新核验的进程状态。没有把隔离测试结果当成正式实例已恢复。

## 生效方式

从系统托盘完全退出朝汐，确认当前实例退出后重新使用快速入口启动，再刷新 Dashboard。仅关闭桌面窗口会继续常驻；侧边栏“重启 Core”只在当前解释器里重新组装服务，不能重新加载这些 Python 源码修改。

重新启动时由 SQLite 处理正常事务恢复，无须删除 journal 或回退旧备份。正式重启后的 Core 就绪、内部活动与模型/插件联网行为尚未验收。

原始与已恢复副本只保存在 Git 忽略的 `.zhaoxi/diagnostics/startup-check-20261006/`，不收入文档或版本控制。
