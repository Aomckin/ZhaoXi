# Windows 登录常驻（Presence P0）

在项目根目录，用项目虚拟环境执行：

```powershell
.\.venv\Scripts\python.exe main.py --install-autostart
.\.venv\Scripts\python.exe main.py --autostart-status
.\.venv\Scripts\python.exe main.py --remove-autostart
```

安装只注册任务，不立即启动。任务名为 `Zhaoxi-Desktop-<当前用户 SID>`，重复安装更新同一个任务；每个用户保留一个朝汐登录任务。搬移项目或重建虚拟环境后，请重新安装任务。查询和移除不要求原 pythonw 路径仍存在，移除不会终止当前 Desktop 或删除用户数据。

通过 Windows Task Scheduler COM API 注册当前用户的 InteractiveToken / LeastPrivilege 任务，不保存密码、不要求管理员、不使用 Windows Service。当前用户登录后延迟 8 秒，直接运行当前虚拟环境 pythonw.exe，参数为项目 main.py 的绝对路径及 `--desktop --background`，工作目录为自动定位的源码项目根目录。路径通过 JSON 传递，参数用 Windows 参数引用规则编码，支持空格和中文。

任务不设运行时限，允许电池供电，忽略任务的并行启动，不配置失败重启或周期触发。用户从托盘退出后本次登录不会自动复活；下次登录仍会启动，除非移除任务。

后台模式仍启动 Core、Web 服务、托盘和已有后台能力，窗口创建时即隐藏。手动 `--desktop` 默认显示。InstanceCoordinator 取得所有权后才构建 Core，重复启动仅发送窗口激活请求；初始化期间的激活请求保留到 GUI 就绪。点击 × 继续沿用隐藏行为，托盘退出沿用完整停止流程。Desktop 日志写入已有 Settings 配置的日志文件，兼容 pythonw 无标准输出的情况。

## 手动验收

1. 安装后查询，应显示 installed/enabled 为 true；在任务计划程序检查当前用户登录触发、8 秒延迟、普通权限、pythonw 和工作目录。
2. 注销并重新登录 Windows，等待约 8 秒及应用初始化：应无终端和主窗口，托盘存在。
3. 从托盘打开朝汐，在页面确认 Core 可交互；已有 Proactive 开启时确认既有提醒可运行。
4. 运行 `.\.venv\Scripts\python.exe main.py --desktop`：已有窗口被唤起，进程/Core/Web/托盘不重复。
5. 点击 ×：窗口隐藏，后台仍工作；再次从托盘打开。
6. 托盘选择“退出朝汐”：进程结束，等待至少一分钟确认不复活。
7. 移除后查询 installed 为 false，再次注销登录确认不启动。若希望恢复登录常驻，再执行安装。

安装、查询、移除可自动验证；注销登录、黑窗闪现、托盘视觉及实际业务交互需要在用户会话中完成验收。
