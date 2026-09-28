# Zhaoxi v1.3.3 开发记录

2026-09-28：按《External Source Pluginization 开发任务书》完成插件化代码切片。

## 已实现

- Core SDK 定义 `ExternalSourcePlugin`、`InteractiveSourcePlugin`、`ObservationSink`、`SourceCapabilities`、`ReplyTarget`、`Attachment`、`OutboundMessage` 和 `SendResult`。Observation 与 Experience Stream 事件保留 `source_plugin`，旧 `source=qq` 事件无需迁移。
- `PluginManifest`、本地目录与 entry point 发现、动态加载、`PluginRegistry` / `PluginRuntime`、Source Router 与 Web 运行时启停/重启 API 已接入。启动或发送异常隔离为 degraded，诊断在维护抽屉的 External Sources 展示。
- QQ / NapCat 的 WebSocket、OneBot 解析、账号映射、图片解析、逐段发送和重连移至 `src/zhaoxi_ext/qq_napcat`。Core Settings 和 PerceptionRuntime 不再依赖 QQ 配置、协议与生命周期。QQ 插件只投递 Observation；Core 处理认知和发送路由。
- 插件配置示例在 `config/plugins/qq_napcat.example.toml`。本机旧 `.env` QQ 配置已复制到被 Git 忽略的 `config/plugins/qq_napcat.toml`；迁移期仍可读取旧变量，插件 TOML 优先。
- Core 可在零外部插件情况下处理 Observation；停用插件不删除历史 Experience Stream。

## 验证

- 完整 Python pytest 套件通过（1 项既有跳过）；`compileall -q src tests` 与 `git diff --check` 通过。
- 新增零插件、双 Fake 插件、热启停、来源路由、启动与发送失败、清单错误、本地目录加载及 QQ 标准身份测试。原有 QQ 传输、图片、分段回复和认知时间线回归通过。
- 本地 wheel 构建成功，并核对安装包包含 QQ 插件代码与 `manifest.toml`。
- 本机 NapCat 端口可达；使用新插件做只读连接冒烟，`connected=true`、`identity_verified=true`、`last_error=None`，随后正常断开。

## 待验收

- 本轮未主动发送 QQ 消息。真实私聊/群聊回复、图片输入、断线重连、运行时停用后再次启用及长时运行仍需实机交互冒烟；自动测试与只读连接不能替代这些验收。
- v1.3.2 任务书 A–E 的完整跨频道黑盒验收仍未因本次插件化自动完成。
