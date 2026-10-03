# v1.4.5 常用调试入口补回

2026-10-03，基于 `06e4878` 的源码补丁。

## 原因

Dashboard 工程页迁移后，`engineering.js` 的页面筛选没有包含 `debugPanel`，原有戳一戳、长时等待、强制 FAST 和普通回复重新生成开关被隐藏；Desktop 的小桌边也移除了这些控件。原重新生成开关只影响当前页面，在工程 iframe 修改不会改变 Desktop 对话。

## 当前入口与行为

- Dashboard 的“设置”与“运行观测”页保留原“调试”面板。
- Desktop 小桌边顶部新增默认展开的“常用调试”，提供三个开关、戳一戳、五态强制与重启 Core；沿用现有动作接口和前台忙碌限制。
- 长时等待继续将请求上限设置为 120 秒；强制 FAST 沿用 Desktop / Web 与 Owner 私聊的原生效范围。
- 普通回复重新生成开关保存为 `show_normal_regenerate`（默认关闭），控制当前对话最新可重新生成的普通回复按钮；失败重试和后端重新生成约束沿用现有实现。
- 两侧共用 `interface-settings.json`；`PATCH /api/settings/interface` 只更新被修改字段，避免短面板或旧页面覆盖输入合并、发送间隔及其他开关。保留原 PUT 接口。
- 保存后通过已有 SSE 发布 `interface_settings`，两侧立即同步；启动、重新聚焦及定期刷新也读取持久设置。设置读取前开关禁用，保存失败回读服务端值。

## 验证与生效

Web / Desktop Python 155 项、Node 78 项通过。新 API 回归覆盖局部更新、超时与强制 FAST 生效、持久恢复、广播、鉴权及非法参数不修改配置。

隔离 Edge 中同时打开 Desktop 页面与 Dashboard，十项验收通过：两侧入口、设置双向同步、普通重新生成按钮显示 / 隐藏、刷新恢复、其他间隔不被覆盖、两侧戳一戳请求与忙碌阻止等；无脚本错误。戳一戳响应和桌面桥接使用 mock，没有真实模型调用或社交发送。四个工程页共 30 个可见折叠项（新增两个调试入口）实际点击通过。

证据见 [验收汇总](evidence/quick_debug_controls_patch.json)。截图保存在本地 `.zhaoxi/quick-debug-desktop.png` 和 `.zhaoxi/quick-debug-dashboard.png`。正式桌面进程未重启，需退出并重新启动整个朝汐进程，再刷新 Dashboard；本次未自动提交或重建安装包。
