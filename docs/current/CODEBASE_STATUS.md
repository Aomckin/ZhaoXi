# 朝汐代码现状

更新：2026-10-06。源码版本仍为 v1.4.7，包含结构维护、运行修复与调试设置，没有版本升级。

当前架构以 [架构说明](ARCHITECTURE.md) 为入口；测试范围、隔离约束与统一命令见 [测试指南](../guides/testing.md)。结构维护见 [原维护记录](../maintenance/2026-10-04-architecture-and-tests.md)，最新修复与逐项证据见 [运行维护总览](../maintenance/2026-10-06-runtime-repair-summary.md)。

- `bootstrap/` 负责装配；`ZhaoxiAgent.runtime` 用有类型的字段持有共享服务，旧 `agent.<service>` 访问转发到同一值。
- Web 请求模型、生命周期、设置、感知、表情、记忆 API 已分模块；聊天、会话、诊断及鉴权仍在 `web/app.py`。
- Experience 与模型设置使用显式 Settings 路径，装配和备份共用配置。
- pytest 默认状态重定向到临时目录；Core、Tool Python、前端 Node 和 Career Node 测试通过 `scripts/test.py` 统一运行。

- FAST 升级复用完整 STANDARD 额度；未执行/部分完成状态、明确重试上下文和工具后回复恢复按真实执行结果处理。
- 启动先完成 SQLite 正常初始化与事务恢复再检查健康；HTTP/SSE 连接和 Core 就绪状态分开显示。
- 原生工具结果批次在 Provider 出站时保持连续；群图观察保留来源，失败提醒只追加一次。
- 当前模型图片受最长边 1600 / 每张 512 KiB 约束；正式附件与 LifeHUD 原图不变。历史图片继续发送 512 像素缩略图，没有此次新增的数量上限。
- Token / Planner 预算控件仅位于 Web Dashboard，Desktop 侧边栏保留其他常用调试功能；预算覆盖持久化、下一次请求生效，Planner 最多批准一次追加。

本轮未重启正式实例、运行真实模型业务或发布。安装、启动方式见根 README；真实使用验收边界继续以对应版本记录为准。

此前混合了多个版本状态、架构描述及不同年代测试数字的交接文档已完整保存在 [2026-10-04 历史快照](../old/CODEBASE_STATUS_2026-10-04.md)。该快照保留历史事实，不作为当前测试基线。
