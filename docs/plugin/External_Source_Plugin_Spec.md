# External Source Plugin 协议（v1.3.3）

Core 提供 `zhaoxi.sdk.external_source` 中的 `ExternalSourcePlugin`、`InteractiveSourcePlugin`、`ObservationSink`、`SourceCapabilities`、`ReplyTarget`、`OutboundMessage` 和 `SendResult`。插件只负责连接、解析、附件标准化与发送；认知、Memory、Decision、Planner 和权限判断属于 Core。

插件 `start(sink)` 是持续运行的协程，收到平台事件后调用 `await sink.emit(observation)`。Observation 要填写 `source`（平台类型）、`source_plugin`（插件 ID）、actor role、conversation ID/kind、附件与来源引用。Sink 进入 Perception 后，Core 如需回复会通过 `ReplyTarget.source_plugin` 选择插件的 `send`。插件不得调用模型、直接写 Experience Stream 或访问内部认知状态。

同仓可选包在 `src/zhaoxi_ext/<id>/manifest.toml` 声明 `id`、`name`、`version`、`entrypoint` 与 `[capabilities]`，本地 `plugins/external_sources/<id>/manifest.toml` 也可被发现，或通过 `zhaoxi.external_sources` Python entry point 注册。启动时发现包，仅启用配置为 `enabled = true` 的插件。运行时 API：`GET /api/external-sources`、`POST /api/external-sources/{id}/enable|disable|restart`。停用不删除历史事件。

插件导入、启动、发送或运行失败会标为 degraded，并在诊断中显示错误类型；断线时 QQ 插件的连接错误也会出现在诊断中。没有插件时，Perception 和其他 Core 功能仍正常运行。插件与 Core 在同一进程；v1.3.3 不提供第三方插件沙箱。
