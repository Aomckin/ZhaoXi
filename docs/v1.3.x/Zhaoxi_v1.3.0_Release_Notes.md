# Zhaoxi v1.3.0 Perception System 发布说明

> 状态：2026-09-27 正式发布 v1.3.0。NapCat WebSocket、QQ 私聊与群聊 Direct、Ambient Batch/Snapshot 已完成实机验证。真实断线重连与长时运行仍待观察。

## 本次实现

- 新增独立 `perception/`：带来源、说话者、会话、时间、raw_ref、信任级别的 Observation；SQLite Store 对 `source + raw_ref` 去重。普通 Ambient 默认 168 小时 TTL，重启后 Buffer 可恢复。
- QQ 群聊默认进入按来源和会话隔离的 Buffer；达到 300 秒或 20 条形成 Batch。Digest 通过结构化工具参数接受模型摘要；响应无效时退回本地摘要。Snapshot 保存 observation IDs 和 raw refs。
- @机器人、回复机器人消息、以“朝汐”开头的群消息和私聊进入 Direct。Direct 只调用独立的外部上下文模型请求，不写本地 Conversation，不调用 AutoMemory、Current Cognition、Decision 更新或工具。外部上下文最多 3 个近期 Snapshot、4000 字符，并带来源和不可信数据提示。
- 新增 NapCat 正向 WebSocket 客户端：Bearer Token、`get_login_info`、`get_msg`、echo 对账、自动重连和关闭；回复原群或私聊，回复引用不支持时退回纯文本。text、at、reply、image 元数据可解析。Meta/notice 不进入 Observation。
- `ZHAOXI_QQ_OWNER_USER_ID` 可标识 Owner，但即使是 Owner QQ 消息也保留 QQ 来源，AutoMemory 和写工具仍关闭。第三方没有读取私有 Memory、Agenda、LifeHUD、文件或执行写操作的模型工具入口；PermissionGateway 还会直接拒绝 `InvocationOrigin.EXTERNAL`，包括只读与预批准调用。
- Web/Desktop 生命周期接入 Perception 和 QQ 后台任务；QQ 默认关闭，故障隔离于 Core。`perception.db` 纳入备份，Diagnostics 和维护抽屉可查看状态、最近记录、强制 flush、清理过期及请求重连。

## 配置

```dotenv
ZHAOXI_PERCEPTION_ENABLED=true
ZHAOXI_PERCEPTION_DB_PATH=.zhaoxi/perception.db
ZHAOXI_PERCEPTION_BATCH_WINDOW_SECONDS=300
ZHAOXI_PERCEPTION_BATCH_MAX_MESSAGES=20
ZHAOXI_PERCEPTION_CONTEXT_MAX_CHARS=4000
ZHAOXI_PERCEPTION_SNAPSHOT_LIMIT=3
ZHAOXI_PERCEPTION_OBSERVATION_TTL_HOURS=168
ZHAOXI_QQ_ENABLED=false
ZHAOXI_QQ_WS_URL=ws://127.0.0.1:3002
ZHAOXI_QQ_ACCESS_TOKEN=
ZHAOXI_QQ_OWNER_USER_ID=2305396720
ZHAOXI_QQ_BOT_USER_ID=2899706784
ZHAOXI_QQ_RECONNECT_SECONDS=5
```

## 验证与限制

- `python -m pytest tests/perception -q`：感知测试通过；覆盖时间戳校验、群聊路由、Owner 标识、去重与重启、Batch/Direct 边界、WebSocket 鉴权、echo、事件接收、断线重连和关闭。
- `python -m pytest -q`：全仓测试通过，保留现有 Starlette `httpx` 弃用警告。
- 2026-09-27 已在本机 3002 端口通过 `get_login_info` 与朝汐项目虚拟环境中的长连接确认 QQ 为 2899706784。3001 属于另一个 QQ，不用于朝汐。配置增加机器人账号校验，错号时不处理事件或发送消息。
- 2026-09-27 私聊发送返回 `retcode=0`，2305396720 确认收到并回复；朝汐私聊 Direct 自动回复已送达。群聊普通消息只进入 Buffer，`@朝汐` 的 Direct 回复已送达。20 条群聊形成 Snapshot，保留了 20 个 Observation ID 和 20 个 raw_ref。
- 真实 NapCat 断线重连与长时运行仍待观察；自动测试已覆盖重连。
- 外部 Direct 第一版采取保守策略：所有外部身份均无工具与私有资料访问能力，Owner 也不能通过 QQ 修改 Agenda。回复只取当前人格提示和外部会话上下文；此范围比任务书建议的受限只读能力更窄。
- 纯图片仅记录元数据，不做视觉理解；不处理 QQ 语音和完整 OneBot API。
