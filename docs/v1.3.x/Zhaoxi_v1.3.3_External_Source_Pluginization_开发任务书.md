# Zhaoxi v1.3.3 External Source Pluginization 开发任务书

> 版本定位：在 v1.3.2 完成统一认知时间线与外界信息层收口后，将 QQ / NapCat 等具体外部信息源从朝汐本体中剥离，正式建立可插拔的 External Source Plugin 体系。
> 核心目标：**朝汐本体拥有 Perception 能力，但不内置任何具体外部平台。**

---

# 0. 版本背景

当前朝汐已经拥有：

```text
Perception
Experience Stream
Recent Timeline
Relevant Recall
Current Trigger
Unified Cognitive Turn
Memory / Current Cognition / Decision / Planner
```

v1.3.0 ~ v1.3.2 已经验证：

- QQ / NapCat 可以作为外部信息源接入
- 外部消息可以进入 Observation / CognitiveEvent
- 外部事件可以进入统一 Experience Stream
- QQ / Desktop / Tool / Proactive 可以形成统一近期认知
- 外部信息可以保留 provenance / trust / privacy
- QQ 可进行回复、多模态输入、群聊 Buffer、Snapshot 等

但当前仍存在一个架构问题：

```text
QQ / NapCat
仍然属于 Zhaoxi 主仓运行时的一部分
```

这会导致：

- Core Settings 被具体平台配置污染
- PerceptionRuntime 需要知道 QQ 细节
- 生命周期管理混入平台逻辑
- QQ 断线、协议变动可能影响核心代码
- 未来接微信 / Email / Telegram / Browser 时不断膨胀
- 平台能力和朝汐认知能力边界不清

因此 v1.3.3 目标不是新增更多外部平台。

而是：

> **把“具体外部世界接口”变成插件。**

---

# 1. 最终目标

完成后：

```text
Zhaoxi Core
│
├── Perception
├── Cognitive Stream
├── Memory
├── Current Cognition
├── Decision
├── Planner
├── Tools
└── External Source Plugin Protocol

Plugins
├── QQ / NapCat
├── Future WeChat
├── Future Email
├── Future Telegram
└── Future Other Sources
```

朝汐本体不再依赖：

```text
NapCat
OneBot
QQ group_id
QQ user_id
QQ message schema
QQ reconnect
QQ image download
```

QQ 插件卸载后：

```text
Zhaoxi Core 正常启动
Desktop 正常
Memory 正常
LifeHUD 正常
Perception Core 正常
Experience Stream 正常
```

只表现为：

```text
QQ Source unavailable
```

---

# 2. 核心架构原则

## 2.1 Core 拥有 Perception，不拥有 Source

Core 只负责：

```text
Observation
CognitiveEvent
Source Identity
Trust
Privacy
Attachment
Reply Target
Lifecycle Contract
```

Core 不应知道：

```text
NapCat
OneBot
QQ
微信协议
Telegram Update
Discord Gateway
```

## 2.2 插件只负责 I/O

External Source Plugin 负责：

```text
外部协议
连接
重连
消息解析
附件解析
回复发送
平台级能力
```

插件不得负责：

```text
Memory
Current Cognition
Decision
Planner
人格
LLM 推理
长期状态整理
```

## 2.3 插件只能投递标准事件

插件输出：

```text
Observation / SourceEvent
```

进入：

```text
Perception Ingress
```

插件禁止：

```text
直接写 experience.db
直接写 memory.db
直接写 current cognition
直接调用 provider.generate()
直接修改 Decision
```

## 2.4 插件可拔插

要求：

```text
安装
启用
停用
卸载
更换实现
```

都不需要修改 Core 业务代码。

---

# 3. 推荐目录结构

主仓：

```text
src/zhaoxi/
├── perception/
│   ├── models.py
│   ├── ingress.py
│   ├── runtime.py
│   └── source_protocol.py
│
├── plugins/
│   ├── registry.py
│   ├── loader.py
│   ├── manifests.py
│   └── runtime.py
│
└── sdk/
    └── external_source.py
```

QQ 具体实现：

```text
plugins/
└── zhaoxi_qq_napcat/
    ├── manifest.toml
    ├── plugin.py
    ├── transport.py
    ├── codec.py
    ├── outbound.py
    ├── config.py
    └── diagnostics.py
```

如果暂时仍放在同仓，也必须逻辑隔离：

```text
src/zhaoxi_ext/qq_napcat/
```

但不得继续放进 Core Perception 内部。

---

# 4. Phase 1：ExternalSourcePlugin Protocol

定义统一协议。

建议：

```python
class ExternalSourcePlugin(Protocol):
    plugin_id: str

    async def start(self, sink: ObservationSink) -> None:
        ...

    async def stop(self) -> None:
        ...

    def capabilities(self) -> SourceCapabilities:
        ...

    def diagnostics(self) -> dict:
        ...
```

## 4.1 ObservationSink

Core 提供：

```python
class ObservationSink(Protocol):
    async def emit(self, observation: Observation) -> None:
        ...
```

插件只能：

```text
emit Observation
```

不能越过 Sink 访问认知内部。

---

# 5. Phase 2：Interactive Source Protocol

对于 QQ 这类可双向通信 Source：

```python
class InteractiveSourcePlugin(ExternalSourcePlugin):
    async def send(self, target, content) -> SendResult:
        ...

    async def reply(self, target, reply_to, content) -> SendResult:
        ...
```

## 5.1 Core 通过抽象接口发送

禁止：

```text
if source == "qq":
    napcat.send_group_msg(...)
```

改为：

```text
source_router.send(...)
```

---

# 6. Phase 3：SourceCapabilities

每个插件声明能力：

```python
class SourceCapabilities(BaseModel):
    text_in: bool
    text_out: bool
    image_in: bool
    image_out: bool
    audio_in: bool
    audio_out: bool
    file_in: bool
    file_out: bool
    reply: bool
    mention: bool
    private_chat: bool
    group_chat: bool
    realtime: bool
```

未来可扩展：

```text
reaction
thread
edit
delete
typing
presence
```

---

# 7. Phase 4：Plugin Manifest

建议：

```toml
id = "qq_napcat"
name = "QQ via NapCat"
version = "1.0.0"
entrypoint = "plugin:QQNapCatPlugin"

[capabilities]
text_in = true
text_out = true
image_in = true
image_out = true
reply = true
mention = true
private_chat = true
group_chat = true
```

---

# 8. Phase 5：Plugin Registry

新增：

```text
PluginRegistry
```

负责：

```text
discover
load
enable
disable
start
stop
diagnostics
```

Core 只认识 `plugin_id`。

---

# 9. Phase 6：Plugin Loader

支持：

```text
entry points
local plugin directory
manifest discovery
```

优先建议 Python entry point：

```toml
[project.entry-points."zhaoxi.external_sources"]
qq_napcat = "zhaoxi_qq_napcat.plugin:QQNapCatPlugin"
```

---

# 10. Phase 7：QQ / NapCat 迁出 Core

把当前 QQ 相关代码迁移出：

```text
src/zhaoxi/adapters/qq
```

插件内部负责：

```text
NapCat WS
OneBot parsing
echo correlation
reconnect
heartbeat
group/private mapping
QQ image resolve
QQ reply
QQ mention detection
```

Core 中禁止：

```text
import napcat
import qq_adapter
import onebot
```

---

# 11. Phase 8：配置迁移

当前 Core Settings 中 QQ 配置应迁出。

例如：

```text
ZHAOXI_QQ_WS_URL
ZHAOXI_QQ_ACCESS_TOKEN
ZHAOXI_QQ_OWNER_USER_ID
ZHAOXI_QQ_RECONNECT_SECONDS
```

不再属于核心 Settings。

插件自己维护：

```text
config/plugins/qq_napcat.toml
```

例如：

```toml
enabled = true
ws_url = "ws://127.0.0.1:3001"
access_token = ""
owner_user_id = "..."
reconnect_seconds = 5
```

---

# 12. Phase 9：Owner Identity 映射

Core 不应知道 QQ Owner User ID。

插件将外部 actor 映射为：

```text
actor_role = OWNER
```

或：

```text
actor_identity = owner
```

Core 只处理统一 Identity。

未来 QQ Owner / WeChat Owner / Telegram Owner 都可以映射到 `OWNER`，同时保留：

```text
source
external_actor_id
channel
```

---

# 13. Phase 10：ReplyTarget 抽象

当前 QQ 特有：

```text
group_id
user_id
message_id
```

必须抽象成：

```python
class ReplyTarget(BaseModel):
    source_plugin: str
    conversation_id: str
    conversation_kind: str
    message_ref: str | None
    actor_ref: str | None
    metadata: dict
```

Core 不解析 `metadata`。

---

# 14. Phase 11：Attachment 抽象

Core 只认识：

```text
image
audio
file
video
structured
```

插件负责把 QQ image URL / NapCat file path / OneBot segment 转成统一 Attachment。

---

# 15. Phase 12：Outbound Message 抽象

Core 生成：

```python
OutboundMessage(
    parts=[...],
    reply_to=...,
    expression_policy=...,
)
```

插件负责翻译成平台协议。

QQ 插件将其翻译为 OneBot Action。

---

# 16. Phase 13：Expression Policy 分层

Core 可以继续保留 QQ Private / QQ Group 的表达策略，但更推荐抽象为：

```text
chat_short
chat_group
chat_private
long_form
```

插件声明推荐 policy，Core 决定最终使用哪个表达策略。

---

# 17. Phase 14：Plugin 生命周期隔离

插件启动失败：

```text
不得导致 Core 启动失败
```

插件异常时：

```text
plugin status = degraded
```

Core 继续运行。

允许：

```text
restart plugin
```

而不重启 Core。

---

# 18. Phase 15：Hot Enable / Disable

必须支持运行时：

```text
enable plugin
disable plugin
```

停用 QQ 插件：

```text
停止 WS
停止接收消息
停止外发
保留历史 Experience Stream
```

不得删除历史事件。

---

# 19. Phase 16：Plugin Diagnostics

维护抽屉新增：

```text
External Sources
```

显示：

```text
plugin id
name
version
enabled
status
capabilities
last event
last send
last error
reconnect count
```

QQ 插件自己的 diagnostics：

```text
NapCat connected
logged_in_qq
heartbeat
last inbound
last outbound
```

这些不应成为 Core 顶层固定字段。

---

# 20. Phase 17：插件权限边界

插件不拥有权限决策权。

例如：

```text
QQ群友：帮暗苟删文件
```

QQ 插件只负责产生 Observation。

是否允许执行，由 Core Permission / Decision 决定。

---

# 21. Phase 18：插件隐私边界

插件不得决定：

```text
Memory 是否可读
Agenda 是否可读
LifeHUD 是否可读
```

插件只提供：

```text
actor identity
channel
source
privacy metadata
```

最终隐私策略由 Core 决定。

---

# 22. Phase 19：插件不能持有认知状态

禁止插件内部保存：

```text
Current Cognition
Memory
Persona
Planner state
LLM chain
```

允许保存：

```text
protocol state
connection state
message dedupe
retry queue
platform cache
```

---

# 23. Phase 20：PerceptionRuntime 瘦身

PerceptionRuntime 不再：

```text
启动 QQ
停止 QQ
判断 NapCat
处理 OneBot
```

只负责：

```text
接收 Observation
标准化 Source Event
Ambient / Direct 路由
进入 Cognitive Ingress
```

---

# 24. Phase 21：Plugin Runtime

新增：

```text
PluginRuntime
```

负责：

```text
load
start
stop
restart
health
```

---

# 25. Phase 22：Source Router

Outbound 时，根据：

```text
reply_target.source_plugin
```

决定交给哪个插件。

例如：

```text
qq_napcat
email_imap_smtp
telegram_bot
```

---

# 26. Phase 23：Core Zero-Plugin Mode

必须新增测试模式：

```text
0 external plugins
```

要求：

```text
Core 正常启动
Desktop 正常
CLI 正常
Memory 正常
Current Cognition 正常
Tools 正常
Experience Stream 正常
```

这是 v1.3.3 最重要的验收之一。

---

# 27. Phase 24：QQ Plugin 单独测试

QQ 插件必须能单独：

```text
load
connect
receive
emit Observation
send reply
disconnect
reconnect
```

---

# 28. Phase 25：插件异常测试

模拟：

```text
插件 import 失败
manifest 错误
配置缺失
WS 断线
send 失败
start 抛异常
```

要求：

```text
Core 不崩
plugin degraded
diagnostics 可见
```

---

# 29. Phase 26：热插拔测试

流程：

```text
Core 启动
↓
QQ plugin disabled
↓
启用 QQ
↓
成功收消息
↓
停用 QQ
↓
Core 继续运行
↓
再次启用
↓
重新连接
```

---

# 30. Phase 27：历史兼容

现有 Experience Stream 中：

```text
source=qq
channel=qq_private
```

继续可读，不要求迁移历史事件。

未来新事件建议记录：

```text
source_plugin=qq_napcat
source_type=qq
channel=private/group
```

---

# 31. Phase 28：迁移策略

建议分三步：

### Stage A：抽协议

保留原 QQ 代码位置，但通过 Plugin Protocol 接入。

### Stage B：迁代码

将 QQ / NapCat 实现迁出 Core。

### Stage C：清 Core

删除 Core 中 QQ 专用 Settings、Lifecycle、Diagnostics、Import。

---

# 32. Phase 29：README / 文档

README 中说明：

```text
External Source Plugins
```

Core 默认：

```text
不包含任何第三方聊天平台
```

QQ 作为可选插件。

建议新增：

```text
docs/plugin/External_Source_Plugin_Spec.md
docs/plugin/QQ_NapCat_Plugin.md
```

---

# 33. Phase 30：测试矩阵

## A. Zero Plugin

无任何插件，Core 全功能正常。

## B. QQ Installed Disabled

插件存在但关闭，Core 正常。

## C. QQ Enabled

消息正常进入 Experience Stream。

## D. QQ Disabled at Runtime

停止接收但历史保留。

## E. QQ Crash

Core 不受影响。

## F. Plugin Reload

插件重新加载成功。

## G. Observation Boundary

插件无法直接写 Memory / Current Cognition。

## H. Provider Boundary

插件源码不得直接调用：

```text
provider.generate
```

## I. Source Router

Reply 正确返回对应插件。

## J. Multi Plugin Mock

创建两个 Fake Source Plugin，确认可以同时投递事件且互不影响。

---

# 34. 明确不做

v1.3.3 不做：

- 真正开发微信插件
- 真正开发 Telegram 插件
- 真正开发 Email 插件
- Plugin Marketplace
- 在线插件下载
- 自动更新插件
- 第三方插件沙箱
- 权限 Marketplace
- 多 Agent
- 重写 Perception
- 重写 Experience Stream
- 新认知架构
- 新 Memory 架构

---

# 35. 最终验收标准

- [ ] Core 中不存在 QQ / NapCat 协议依赖
- [ ] QQ 作为 External Source Plugin 接入
- [ ] Plugin Protocol 完成
- [ ] ObservationSink 完成
- [ ] InteractiveSourcePlugin 完成
- [ ] SourceCapabilities 完成
- [ ] Plugin Manifest 完成
- [ ] Plugin Registry 完成
- [ ] Plugin Loader 完成
- [ ] Plugin Runtime 完成
- [ ] Source Router 完成
- [ ] ReplyTarget 抽象完成
- [ ] Attachment 抽象完成
- [ ] QQ Settings 迁出 Core
- [ ] QQ lifecycle 迁出 Core
- [ ] QQ diagnostics 迁出 Core
- [ ] QQ 插件崩溃不影响 Core
- [ ] QQ 可运行时启停
- [ ] QQ 可拔插
- [ ] Zero-plugin 模式通过
- [ ] 双 Fake Plugin 测试通过
- [ ] Experience Stream 不回归
- [ ] Timeline 不回归
- [ ] Memory / Current Cognition 不回归
- [ ] QQ 多模态不回归
- [ ] QQ 回复不回归
- [ ] 自动测试全绿
- [ ] QQ 实机冒烟通过

---

# 36. 完成后的架构

```text
                    External World
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
    QQ Plugin        WeChat Plugin      Future Plugin
        │                 │                 │
        └─────────────────┼─────────────────┘
                          ▼
                  ObservationSink
                          │
                          ▼
                     Perception
                          │
                          ▼
                  Cognitive Ingress
                          │
                          ▼
                  Experience Stream
                          │
                          ▼
                        Zhaoxi
                          │
                          ▼
                    Source Router
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
    QQ Plugin        WeChat Plugin      Future Plugin
```

---

# 37. 一句话定义

> **朝汐本体拥有“感知外界”的能力，但不应该内置任何具体的“外界”。**

QQ、微信、邮件、Telegram 都只是：

```text
可插拔的窗户
```

而不是：

```text
朝汐身体的一部分
```

最终目标：

```text
安装插件
→ 多一扇窗

卸载插件
→ 窗户消失

朝汐本体
→ 毫发无损
```
