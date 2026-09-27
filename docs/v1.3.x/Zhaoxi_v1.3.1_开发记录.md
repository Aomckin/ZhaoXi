# Zhaoxi v1.3.1 开发与验收记录

> 状态：代码和自动测试通过；QQ 私聊、图文、群聊定向回复及 Desktop 跨窗口认知已完成实机冒烟。正式发布仍待长时连接和真实断线重连观察。

## 实现范围

- QQ 私聊和群聊分别使用 `qq/private/<user_id>`、`qq/group/<group_id>` Session。外部消息在存储中保留 `Role.EXTERNAL`、频道元数据和消息引用，不写入本地 `local` Conversation；Session SQLite 自动迁移到 v3。
- `InteractionLedger` 在 `perception.db` 保存短期 Self Event 和 Runtime Self State。Desktop 与 CLI 能读取 QQ 互动；跨进程状态超过 90 秒未刷新时标为 stale。QQ 和 Desktop 使用同一个朝汐自我，不将频道当成两个角色。
- Direct 由 `ExternalCognitionPlanner` 决定是否回复，并可提出近期认知、长期记忆和后台意图候选。只有已校验 Owner 私聊中的直接文字可进入认知与记忆 Guard；第三方及 Snapshot 不能写入 Owner 事实。后台意图仅保留候选，不执行工具或日程写入。
- Ambient 群消息先形成 Batch 和 SocialSnapshot，再由 Internal Activity 在后台整理；普通消息不逐条调用 Planner 或回复。
- Observation 的 `parts` 保留文字、图片等顺序，旧 `content + attachments` 仍可读取。图片经受控下载、MIME 与大小校验、临时目录和 TTL 后，同时进入 Planner 与 Reply Generator。视觉 Planner 返回格式错误时，Owner 私聊可走无认知候选的保守回复兜底。
- QQ 私聊与群聊使用不同表达策略。回复按空行与 Reply DSL 表情拆成 OneBot 文本或图片消息，按顺序发送；超过段数上限时只合并相邻文本，不截断正文。
- Desktop「设置」提供外部输入防抖（0–15 秒，默认 5 秒）和外部逐段发送间隔（0–5 秒，默认 0.5 秒）。同一会话、同一发言者在防抖窗口内的 Direct 合为一次 Observation，并保留所有 QQ 消息引用；Ambient 不受影响。设置保存到现有界面设置文件，后续 QQ 输入和回复无需重启即可使用。
- 维护抽屉增加 QQ Sessions、Self Events、待处理 Snapshot、Ledger 清理、图片重解析和频道表达策略入口；Diagnostics 展示候选数、图片状态和发送段数。

## 安全与兼容

- 外部 Planner 和回复生成均不提供 Tool Schema。第三方不注入 Owner 私人 Memory 或 Current Cognition；Owner 的相关记忆只用于已校验身份的外部私聊。
- 图片解析拒绝任意本地路径、无效 MIME、超限数据及非允许的私网目标。NapCat 本机图片只允许配置的 QQ WebSocket 主机和端口。
- 旧 Observation 与 SocialSnapshot 保持可读；v1.3.0 没有持久化的 QQ Session 历史，不伪造旧对话。

## 自动验证

- `python -m pytest -q`：全仓通过，仅见已有的 Starlette/httpx 弃用警告。
- 测试覆盖 Session 连续性与隔离、共享活动、Planner 不回复、候选 Guard、纯图片视觉输入、Ambient 后台整理、分段图文发送、外部防抖的同人合并与跨人隔离、Desktop 设置持久化及发送间隔。
- `git diff --check` 通过。

## 2026-09-27 实机验证

- NapCat 3002 校验为朝汐 QQ 2899706784；Owner QQ 2305396720 的私聊文字、纯图片和普通表情包均能回复，图片内容可识别，回复按独立气泡送达。
- 实机发现视觉 Planner 偶发非 JSON、QQ 把图文拆成两条消息、模型误判 Owner 昵称。已加格式容错、Owner 身份提示及相邻图文关联。修复后，图文追问能准确描述图片。
- Desktop 曾把近期 QQ 查询误判为工具任务，反复查询目录并超时；现基于核实的 Self Activity 一步直答。随后纠正了「另一个我」的表达，用户复测确认跨窗口回答自然统一。
- 群聊 Owner `@朝汐` 走 Direct 并返回短句；普通群消息保持 Ambient。实机数据库记录了 27 个 SocialSnapshot，其中 7 个已完成一次后台认知整理。
- Desktop 保存 15 秒外部防抖和 1.5 秒发送间隔后，Owner 分开发图片与提问，落库为一次含图文 `parts`、两条来源引用的 Direct；只回复一次且理解正确，用户已确认。发送间隔由自动测试验证。

## 剩余观察

- 长时连接与真实断线重连尚未完成持续实机观察。
- QQ 图片依赖当前兼容模型支持视觉输入；若 Reply Generator 无法处理图片，该条 Direct 会失败并记录诊断状态。
