# QQ / NapCat 可选插件

实现位于 `src/zhaoxi_ext/qq_napcat`。将 `config/plugins/qq_napcat.example.toml` 复制为被 Git 忽略的本机配置 `config/plugins/qq_napcat.toml`；设置 `enabled = true`、`ws_url`、`owner_user_id` 和按需设置 `access_token`、`bot_user_id`、`external_bot_user_ids`。敏感值请只放在本机未跟踪的配置或环境变量中；迁移期插件也可从旧 `.env` 与环境变量读取 `ZHAOXI_QQ_*`，但启用开关以插件 TOML 为准。

插件负责 NapCat WebSocket、OneBot 消息解析、Owner 身份映射、图片解析、重连和回复发送。Core 只接收 Observation。维护抽屉的 External Sources 可启用、停用、重启并查看连接诊断。旧 Experience Stream 的 `source=qq` 继续可读，新事件额外记录 `source_plugin=qq_napcat`。

实机验证需先运行 NapCat：启用后检查连接状态、收一条私聊及一条群聊消息、图片输入、分段回复、断线重连与运行时停用。自动测试用模拟连接覆盖协议和路由；本次代码验证不能代替实机冒烟。
