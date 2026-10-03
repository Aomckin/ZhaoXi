# v1.4.4 FAST 表情回复接入

日期：2026-10-03。版本仍为 1.4.4。

## 行为与范围

FAST 的系统提示复用 EmojiService 当前启用的属性目录和 `[emoji:属性1,属性2]` 规则。模型可在正常闲聊中自行选择合适表情，也可回应“发个得意表情”“请发一个表情给我”等单句请求。不匹配的属性和关闭的表情服务沿用现有纯文字退化行为；目录为空时不注入表情提示。正常 FAST 回复保持一次模型调用，不添加工具 schema、记忆检索或额外选图模型调用。

表情属于本轮表达。保存、收藏、转发到其他会话以及复合行动请求不使用这项 FAST 特例；图片输入和待确认权限继续优先进入标准通道。升级或被拒绝的 FAST 草稿在安全校验之前不提交、不匹配表情、不消耗最近使用记录。

最终 FAST 回复复用共享 Reply DSL 解析与本地属性匹配。Web / Desktop 沿用有序图文输出，CLI 接口也保留结构化输出；具体终端的图片展示能力仍由终端决定。

QQ Owner 私聊传递本轮已经解析的图文序列；Source Router 使用选定的 emoji_id 读取文件，不再次按属性选择，避免重选造成实际发送和历史记录不一致。文字与图片按回复顺序发送，纯表情回复也视为有效输出。文件缺失、不可读、超过原有 10 MiB 上限或服务关闭时省略该图片；剩余文字仍可发送。空输出不调用发送插件，记录 outbound_reply_empty。发送成功后只将可发送的段写回 QQ Session，保留 emoji_id、requested_tags 和 reply_group_id。发送失败沿用插件错误处理，不写入成功回复记录。此变更没有扩大 QQ 群聊或第三方消息的 FAST 准入。

本地与 QQ 的认知时间线都记录可读的“曾使用表情”属性和本轮结构化段信息，避免纯表情轮次丢失。FAST 读取 Session 中的旧表情时只提供属性说明，不把内部 ID、文件路径或旧表情图片作为新的视觉输入。QQ 会话不会写入本地桌面 Conversation。

## 代码入口

- `core/fast_chat.py`：属性提示、最终已解析序列及可读历史。
- `cognitive/fast_gate.py`：仅本轮表情表达的准入与工具升级意图排除。
- `core/agent.py`、`core/reply/segments.py`：共享提交结果和携带序列的频道回复。
- `cognitive/coordinator.py`、`interfaces/gateway.py`：本地 FAST 序列传递及纯表情认知记录。
- `perception/runtime.py`、`plugins/source_router.py`：QQ 纯表情发送、一次选图与成功后的分段持久化。
- `tests/core/test_fast_emoji.py`：23 项回归验证。

## 验证

新增测试覆盖三个本地接口的图文与纯表情回复、一次模型调用、启用属性提示、关闭/空库/无匹配退化、保存与其他会话行动边界、草稿升级不消费选图、QQ 图文顺序及一次选图、Session 与 Experience 持久化、历史可读性、缺失文件和空发送防护。

Python 全量 **1094 通过、1 跳过**（系统不能创建符号链接），保留既有 Starlette/httpx 弃用提示。全量回归启动后的最后一项本地纯表情认知记录衔接，另以最终代码复测相关 Core、Cognitive、Cognitive Stream、Interface、Plugin、Perception 模块，**383 通过**。Node **66 通过**；修改文件编译与差异检查通过。验证汇总见 [FAST 表情验收证据](evidence/fast_emoji_acceptance.json)。

测试使用临时数据库、合成模型和模拟 QQ transport；未调用真实模型、发送真实 QQ 消息或重启正在运行的实例。加载新代码需要重启 Core；真实模型选用表情及 QQ 图片展示仍需实机观察。已有 LifeHUD 工作区修改保留，本补丁没有修改它们。
