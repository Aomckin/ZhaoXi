# 朝汐代码现状

更新：2026-10-05。源码版本仍为 v1.4.7，本轮是结构与测试维护，没有版本升级。

当前架构以 [架构说明](ARCHITECTURE.md) 为入口；测试范围、隔离约束与统一命令见 [测试指南](../guides/testing.md)。本轮修改与验证见 [维护记录](../maintenance/2026-10-04-architecture-and-tests.md)。

- `bootstrap/` 负责装配；`ZhaoxiAgent.runtime` 用有类型的字段持有共享服务，旧 `agent.<service>` 访问转发到同一值。
- Web 请求模型、生命周期、设置、感知、表情、记忆 API 已分模块；聊天、会话、诊断及鉴权仍在 `web/app.py`。
- Experience 与模型设置使用显式 Settings 路径，装配和备份共用配置。
- pytest 默认状态重定向到临时目录；Core、Tool Python、前端 Node 和 Career Node 测试通过 `scripts/test.py` 统一运行。

本轮未重启正式实例、运行真实模型业务或提交发布。安装、启动方式见根 README；真实使用验收边界继续以对应版本记录为准。

此前混合了多个版本状态、架构描述及不同年代测试数字的交接文档已完整保存在 [2026-10-04 历史快照](../old/CODEBASE_STATUS_2026-10-04.md)。该快照保留历史事实，不作为当前测试基线。
