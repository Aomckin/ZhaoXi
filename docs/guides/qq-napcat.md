# QQ / NapCat 本机连接

朝汐使用 QQ **2899706784**，Owner QQ 为 **2305396720**。本机另一个 QQ **3768425246** 占用 3001，不能把朝汐接到该端口。

## NapCatQQ Desktop

1. 在朝汐 2899706784 的卡片点设置，进入网络配置，新建连接。
2. 选择 **WebSocket 服务器**，启用；Host 填 `127.0.0.1`，Port 填 `3002`，消息格式选 `array`，强制推送事件保持开启。
3. 保存。若设置访问 Token，将相同值填到本机 `config/plugins/qq_napcat.toml` 的 `access_token`。本机环回联调可留空。WebUI 登录 Token 与 OneBot WebSocket Token 是两个不同配置。

将 `config/plugins/qq_napcat.example.toml` 复制为 `config/plugins/qq_napcat.toml`，并配置：

```toml
enabled = true
ws_url = "ws://127.0.0.1:3002"
access_token = ""
bot_user_id = "2899706784"
owner_user_id = "2305396720"
```

首次安装插件后重启朝汐；之后可在维护抽屉 **External Sources** 运行时启停或重启，并查看 `connected`、`identity_verified` 和 `logged_in_qq`。若账号不匹配，插件拒绝处理与发信。旧 `ZHAOXI_QQ_*` 环境变量在插件配置迁移期仍可读取，但启用开关以插件 TOML 为准。

## Desktop 中的外部消息节奏

在朝汐 Desktop 的「设置」中调整「外部输入防抖」与「外部逐段发送间隔」。防抖范围为 0–15 秒，0 表示关闭；同一会话、同一发言者在安静窗口内连续发送的 QQ Direct 会合并处理，图和文字可作为一次输入。发送间隔范围为 0–5 秒，0 表示立即发送后续段。设置保存后对后续消息生效，无需重启 Core。普通群消息仍按 Ambient 处理。

## 联调记录

2026-09-27：3002 的 `get_login_info` 返回 2899706784；朝汐桌面进程保持 WebSocket 长连接。朝汐发往 2305396720 的私信返回 `retcode=0`，用户确认收到并回复；该入站私聊按 Direct 处理，用户确认收到自动回复。群聊普通消息保持在 Ambient Buffer；用户 `@朝汐` 后，群聊 Direct 被处理且用户确认看到回复。群聊形成 20 条消息的 SocialSnapshot，Observation ID 和 raw_ref 各保留 20 个。
