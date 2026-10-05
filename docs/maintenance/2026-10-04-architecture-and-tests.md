# 架构与测试维护记录

审阅与实施始于 2026-10-04，验证完成于 2026-10-05；源码版本：v1.4.7。用户在只读审阅后授权按建议实施，并要求在 docs 留下记录。本轮维护不升级版本，不重启正式实例，不提交或发布。

## 审阅结论

已有 bootstrap、接口网关、领域服务、Tool SDK 与插件边界，整体分层可以继续使用。主要问题是共享服务通过动态属性装配、Web 入口文件过大、测试运行入口分散，以及部分测试依赖源代码位置和字符串。

测试规模本身不足以证明臃肿；权限、预算、恢复、迁移和证据边界确有独立价值。优先处理的风险是测试触碰真实状态：Experience 路径原先硬编码，备份测试的局部隔离不完整；Career HTTP 测试原先修改真实岗位文件后再恢复。

## 已实施

1. 新增 `Settings.experience_db_path`、`model_settings_path`，同步 `.env.example`。Experience 装配和备份共享路径；主模型思考开关使用配置路径。默认业务路径兼容原来行为。
2. 根共享 pytest fixture 重定向运行时状态，屏蔽本机凭据，并保护生产 SQLite / Path 文件写入入口。pytest 临时文件移出 `.zhaoxi`。新增装配、备份与路径保护回归。
3. 增加有类型的 `AgentRuntime`，bootstrap 写入集中共享服务；既有 Agent 属性通过 descriptor 转发，读写保持同一值。
4. 拆出 Web schemas、生命周期及设置/感知/表情/记忆四组路由，保留鉴权、启动关闭和诊断 supervisor 的行为。`app.py` 从 1670 行降到 970 行，`create_app()` 从 1395 行降到 856 行。
5. 回复逻辑拆成独立前端脚本。Node 直接加载模块验证分段、节奏、回复组、图片尾段与重新生成；Python 的实现字符串断言改为资源交付与加载顺序检查。
6. 共享 Web `FakeAgent` 移到 fixture 文件，消除测试模块之间的导入依赖；删除一个与通用 release 检查重复的历史硬编码版本测试。
7. 把启动诊断的 Tool 发现导入延迟到函数内部，修复 Tool 独立导入 SDK 时的循环依赖；LifeHUD 健康检查测试使用 Mock Response，避免访问本机正式服务。增加 `scripts/test.py`，统一 Core、独立 Tool Python、前端 Node 和 Career Node 套件。Career 代码位于 Git 子模块 `tools/career`，其测试夹具与两份 Node 测试修改保留在该子模块工作区。
8. 当前代码状态文档改为精简入口，原长篇交接记录完整归档到 `docs/old/CODEBASE_STATUS_2026-10-04.md`；新增架构与测试指南。

## 验证

完整离线入口 `.\.venv\Scripts\python.exe scripts/test.py` 返回 0，各套件通过。

| 验证 | 结果 |
| --- | --- |
| Core Python | 1312 通过、1 跳过；237.74 秒 |
| Tool Python | LifeHUD 33、Career 4、MCP 8、MarkItDown 2，共 47 通过 |
| 前端 Node | 94 通过、0 失败 |
| Career Node | 冒烟 266 条断言通过；HTTP API 端到端场景通过 |
| Edge 回复分组冒烟 | 5 项检查通过，无脚本错误；重生成、刷新恢复、图文顺序和纯图片末尾分组 |
| 最后专项 | Runtime / 启动 6；Web / 可靠性装配 41；健康检查 Mock / Core 独立性 14，均通过 |
| Python 语法 | src、tests、scripts 与根 fixture 共 430 文件通过 |
| wheel | 随附 Python 3.12 离线构建；315 个源码、插件和静态资源与工作区逐字节一致 |
| diff 检查 | 主仓库与 Career 子模块 `git diff --check` 均通过 |

Core 全量完成后又整理了测试导入与健康检查 Mock，以上“最后专项”和语法检查覆盖了这两处收尾修改。Starlette TestClient 的 httpx 弃用提示仍存在，本轮未改依赖。

验证汇总、wheel hash 与浏览器检查列表保存在 [结构化证据](evidence/2026-10-04-architecture-and-tests.json)。浏览器使用假模型及系统临时状态目录，测试服务已退出。

失败尝试也予以保留：第一轮全量发现 Optional 服务断言、静态资源入口和独立 Tool 导入问题；修复后统一入口通过。最后测试导入整理曾引入缩进错误，已修复并通过 41 项受影响测试。项目虚拟环境缺少 setuptools，首次 wheel 构建失败，随后使用已有随附构建环境完成，没有安装新依赖。


## 保留的边界

- Agent 的核心长循环与 Planner / Workflow 构造依赖保持原结构；Runtime 暂未迁移全部服务消费者。
- `app.py` 仍承载聊天、会话、诊断和语音等路由，后续可继续按职责拆分。
- 其他前端测试仍有大文件片段截取或源码断言；本轮优先完成回复链这一组，未做全仓测试重写。
- Career 历史 smoke 中的静态结构检查仍存在；已先解决隔离与外部请求确定性。工具包的版本检查属于独立发布契约，本轮保留。
- pytest 保护不等于完整文件系统沙箱。后续新增存储入口、子进程或浏览器测试必须显式隔离。
- 原生 Desktop、真实模型/QQ 及长期使用验收未执行；既有正式进程未重启。
