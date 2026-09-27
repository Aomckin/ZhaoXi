# QQ / NapCat 本机连接

朝汐使用 QQ **2899706784**，Owner QQ 为 **2305396720**。本机另一个 QQ **3768425246** 占用 3001，不能把朝汐接到该端口。

## NapCatQQ Desktop

1. 在朝汐 2899706784 的卡片点设置，进入网络配置，新建连接。
2. 选择 **WebSocket 服务器**，启用；Host 填 `127.0.0.1`，Port 填 `3002`，消息格式选 `array`，强制推送事件保持开启。
3. 保存。若设置访问 Token，将相同值填到朝汐 `.env` 的 `ZHAOXI_QQ_ACCESS_TOKEN`。本机环回联调可留空。WebUI 登录 Token 与 OneBot WebSocket Token 是两个不同配置。

朝汐 `.env`：

```dotenv
ZHAOXI_PERCEPTION_ENABLED=true
ZHAOXI_QQ_ENABLED=true
ZHAOXI_QQ_WS_URL=ws://127.0.0.1:3002
ZHAOXI_QQ_ACCESS_TOKEN=
ZHAOXI_QQ_BOT_USER_ID=2899706784
ZHAOXI_QQ_OWNER_USER_ID=2305396720
```

修改 `.env` 后，需从系统托盘完全退出朝汐，再重新打开。维护抽屉的 **Perception Debug** 可查看 `connected`、`identity_verified` 和 `logged_in_qq`。若账号不是 2899706784，连接会被拒绝处理与发信。

## 联调记录

2026-09-27：3002 的 `get_login_info` 返回 2899706784；朝汐桌面进程保持 WebSocket 长连接。朝汐发往 2305396720 的私信返回 `retcode=0`，用户确认收到并回复；该入站私聊按 Direct 处理，用户确认收到自动回复。群聊普通消息保持在 Ambient Buffer；用户 `@朝汐` 后，群聊 Direct 被处理且用户确认看到回复。群聊形成 20 条消息的 SocialSnapshot，Observation ID 和 raw_ref 各保留 20 个。
