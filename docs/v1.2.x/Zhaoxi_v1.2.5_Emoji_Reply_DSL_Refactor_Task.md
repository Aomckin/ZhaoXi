# Zhaoxi v1.2.5 开发任务书：表情包系统重构为 Reply DSL

## 0. 版本定位

本版本不是继续修补现有 `send_emoji` Tool，而是明确推翻“发表情 = Tool 调用”的架构，改为：

> **表情 = 朝汐回复内容的一部分。**

此前真实使用已经暴露了旧方案的问题：

```text
用户
→ CognitiveRouter
→ requires_tool_call
→ Agent
→ send_emoji
→ 图片消息
→ 文本回复
```

这种结构把一个轻量表达行为做成了外部动作，带来了：

- 表情和文本难以自然穿插；
- Tool 调用位置容易固定在回复前后；
- 模型可能嘴上说“发了”，实际没有 Tool Call；
- Router / Agent / Tool Choice / Retry 为一个表情引入了过多复杂度；
- 多表情、句中表情、文本-表情-文本很别扭。

本版本将表情重新定义为：

```text
Reply Expression
```

而不是：

```text
External Action
```

---

## 1. 新架构目标

最终链路：

```text
聊天上下文
    ↓
构建当前可用表情属性目录
    ↓
注入 Replyer 上下文
    ↓
LLM 一次生成完整回复
    ↓
Reply DSL Parser
    ↓
ReplySequence
    ├─ TextSegment
    ├─ EmojiSegment
    ├─ TextSegment
    └─ EmojiSegment
    ↓
各 Adapter 按顺序输出
```

示例：

```text
哼，我当然会啦。
[emoji:得意,邀功]
这次总看见了吧！
```

解析后：

```text
TextSegment("哼，我当然会啦。")
EmojiSegment(tags=["得意", "邀功"])
TextSegment("这次总看见了吧！")
```

再由本地 Emoji Resolver 匹配真实图片：

```text
[emoji:得意,邀功]
    ↓
emoji_registry
    ↓
emoji_0005
```

---

## 2. DSL 规范

统一使用：

```text
[emoji:属性1,属性2]
```

例如：

```text
[emoji:开心,欢快]
[emoji:得意,邀功]
[emoji:无语,嫌弃]
[emoji:委屈,撒娇,泪汪汪]
```

不要再使用：

```text
[[emoji:emoji_0005]]
```

也不要要求模型知道具体 `emoji_id`。

核心原则：

```text
模型负责“表达什么”
本地负责“用哪张图表达”
```

---

## 3. 表情上下文注入

朝汐专属表情预计最多约 30 张，本版本不引入召回系统。

每轮 Replyer 调用前，直接注入全部启用表情的主要属性。

示例：

```text
当前可用表情：

- [开心,欢快,打招呼]
- [得意,邀功,臭屁,被夸]
- [无语,嫌弃,吐槽]
- [害羞,脸红,心虚]
- [委屈,泪汪汪,撒娇]
- [生气,鼓脸,抗议]
```

程序内部仍保持：

```text
emoji_0001 -> [开心,欢快,打招呼]
emoji_0002 -> [得意,邀功,臭屁,被夸]
...
```

但不要把 ID 暴露给 LLM，除非 Debug 模式需要。

---

## 4. Registry 继续保留

现有 `emoji_registry.json` 不推翻。

继续保留：

```json
{
  "id": "emoji_0005",
  "file": "images/emoji_0005.png",
  "description": "被夸以后很得意，带一点邀功和臭屁感。",
  "tags": ["得意", "邀功", "臭屁", "被夸"],
  "emotion": "proud",
  "intensity": 0.7,
  "enabled": true
}
```

其中：

- `id`：内部稳定标识；
- `file`：真实资源；
- `description`：表情柜管理、人工理解、未来扩展；
- `tags`：DSL 匹配主要依据；
- `emotion`：可选辅助；
- `intensity`：可选辅助；
- `enabled`：是否提供给 Replyer。

---

## 5. Replyer Prompt 规则

加入轻量规则：

```text
你可以在回复中使用当前提供的表情。

格式：
[emoji:属性1,属性2]

规则：
1. 只使用当前可用表情中实际存在的属性。
2. 每次选择 1~3 个最贴切属性。
3. 没有合适表情时不要输出 emoji DSL。
4. 表情可以放在回复开头、中间或结尾。
5. 表情不是每条消息必须使用。
6. 严肃任务、长篇技术说明中少用。
7. 不要输出具体 emoji_id。
8. 不要解释 DSL。
```

---

## 6. 新增 Reply DSL Parser

新增统一解析层，例如：

```text
core/reply/
├─ parser.py
├─ segments.py
└─ renderer.py
```

或按现有工程结构调整。

第一版至少支持：

```text
TextSegment
EmojiSegment
```

语法：

```regex
\[emoji:([^\]]+)\]
```

输入：

```text
[emoji:得意,邀功]
```

解析为：

```python
EmojiSegment(
    requested_tags=["得意", "邀功"]
)
```

---

## 7. ReplySequence

建立统一内部结构：

```python
ReplySequence([
    TextSegment(...),
    EmojiSegment(...),
    TextSegment(...),
])
```

目标：

```text
LLM 原始字符串
→ DSL Parser
→ ReplySequence
→ Adapter
```

不要再让 Web、QQ、未来 Mobile 各自解析 LLM 原始文本。

---

## 8. Emoji Resolver

改造现有 EmojiService，从：

```text
intent -> emoji
```

转为：

```text
requested_tags -> emoji
```

示例：

```text
请求：
["得意", "邀功"]

emoji_0005:
["得意", "邀功", "臭屁", "被夸"]

emoji_0007:
["开心", "得意"]

优先 emoji_0005
```

第一版评分保持简单：

```text
命中标签数
+
命中比例
+
emotion/intensity 可选辅助
+
recent history 降权
```

不要引入 embedding。

---

## 9. 无匹配行为

如果：

```text
[emoji:开心,庆祝]
```

找不到合适候选：

```text
EmojiSegment 直接丢弃
```

并记录：

```text
emoji_resolve_no_match
```

不能让整个回复失败。

---

## 10. 多表情支持

天然支持：

```text
等等，你先别说。
[emoji:震惊,懵]
你刚才是不是认真的？
[emoji:无语,嫌弃]
```

解析为：

```text
Text
Emoji
Text
Emoji
```

不再需要多次 Tool Call。

---

## 11. Web 渲染

Web Adapter 根据 ReplySequence 顺序渲染。

规则：

```text
TextSegment
→ 普通文字气泡

EmojiSegment
→ 独立无气泡图片
```

示例：

```text
[文字气泡]

[表情图片]

[文字气泡]
```

必须保留原始顺序。

---

## 12. QQ / NapCat 预留

虽然 v1.3 才正式做外界信息适配，但 ReplySequence 必须天然可映射：

```text
TextSegment -> OneBot text
EmojiSegment -> OneBot image
```

不要把 DSL 解析写死在 Web 页面里。

---

## 13. 移除 `send_emoji` 公开 Tool

本版本完成后：

```text
send_emoji
```

不再作为普通 Agent Tool 暴露。

需要：

- 从 Tool Manifest 移除；
- 从 Router 能力目录移除；
- 删除 `requires_tool_call` 针对表情发送的逻辑；
- 删除表情专用 Tool Choice；
- 删除表情发送失败强制重试；
- 删除“口头说发了但无 Tool Call”的表情专用校验；
- 删除针对“再来一张 / 多发几个”等表情发送的特殊路由补丁。

---

## 14. `save_emoji` 继续保留为 Tool

注意：

```text
send_emoji
```

退出 Tool 系统。

但：

```text
save_emoji
```

继续保留。

因为：

```text
保存表情
→ 修改本地资源
→ 修改 registry
→ 有真实副作用
```

边界：

```text
save_emoji
→ Tool

[emoji:得意,邀功]
→ Reply DSL
```

---

## 15. 表情柜继续保留

现有表情柜继续使用。

建议卡片优先展示：

```text
图片
tags
enabled
```

详情页继续保留：

```text
description
tags
emotion
intensity
```

---

## 16. Prompt Context 构建

新增类似：

```python
build_emoji_context()
```

输出：

```text
可用表情：
[开心,欢快,打招呼]
[得意,邀功,臭屁,被夸]
[无语,嫌弃,吐槽]
...
```

只输出：

```text
enabled=true
```

的表情。

---

## 17. 重复属性处理

允许多个表情拥有类似属性：

```text
emoji_0002 = [得意,邀功]
emoji_0017 = [得意,邀功]
emoji_0021 = [得意,开心]
```

Resolver：

```text
先筛语义匹配
→ recent history 降权
→ 高分候选中轻度随机
```

---

## 18. 防重复继续复用

保留现有 recent emoji history。

例如最近 5 张。

同分时优先没用过的。

---

## 19. DSL 安全处理

必须兼容：

### 正常

```text
[emoji:开心,欢快]
```

### 多余空格

```text
[emoji: 开心, 欢快 ]
```

### 中文逗号

```text
[emoji:开心，欢快]
```

### 空 DSL

```text
[emoji:]
```

忽略。

### 未闭合

```text
[emoji:开心,欢快
```

按普通文本或安全清理处理，不能崩溃。

### 不存在标签

```text
[emoji:宇宙爆炸式快乐]
```

no_match，忽略 EmojiSegment。

---

## 20. DSL 不得泄露给用户

正常渲染后：

```text
[emoji:得意,邀功]
```

不能作为原始文字显示。

只有 Debug 模式可查看 Raw Reply。

---

## 21. 会话持久化策略

建议持久化 **解析后的结构化消息**，而不是只保存原始 DSL 文本。

推荐：

```json
{
  "segments": [
    {"type": "text", "content": "哼，我当然会啦。"},
    {
      "type": "emoji",
      "emoji_id": "emoji_0005",
      "requested_tags": ["得意", "邀功"]
    },
    {"type": "text", "content": "这次总看见了吧！"}
  ]
}
```

这样历史恢复时不需要重新跑 Resolver，也不会因为标签或图库后来变化而换图。

---

## 22. Raw Reply 可选保存

Debug / 审计可保留：

```text
raw_reply
```

例如：

```text
哼，我当然会啦。
[emoji:得意,邀功]
这次总看见了吧！
```

用户侧只渲染 `segments`。

---

## 23. 旧历史兼容

已有：

```text
source=emoji
emoji_id=...
```

的独立图片消息继续兼容显示。

不要为了新 DSL 强迁移所有旧会话。

新旧格式可以并存。

---

## 24. Debug 调整

Debug Emoji 区改为显示：

```text
Loaded Emojis
Current Emoji Context
Last Raw Reply
Parsed Segments
Requested Tags
Resolved Emoji ID
Recent Emoji History
```

示例：

```text
Raw:
“哼。”
[emoji:得意,邀功]
“看见了吧。”

Parsed:
TEXT
EMOJI requested=[得意,邀功]
TEXT

Resolved:
emoji_0005
```

---

## 25. 删除旧“表情 Tool 体检”逻辑

原先为了 Tool 架构加入的表情专属：

```text
requires_tool_call
required_tool
tool_called
gateway_emitted
```

相关 Debug 可删除或降级。

通用 Tool Debug 保留。

---

## 26. 测试要求

### Parser

覆盖：

```text
纯文本
单表情
文本+表情
表情+文本
文本+表情+文本
多表情
空 DSL
错误 DSL
中文逗号
空格
未知标签
```

### Resolver

覆盖：

```text
单标签
多标签
并列候选
disabled
recent 降权
no_match
```

### ReplySequence

验证：

```text
Text
Emoji
Text
Emoji
```

顺序不能错位。

### Web

测试：

```text
文本气泡
纯表情
文本-表情-文本
多个表情
历史恢复
```

### Context

确认：

```text
只注入 enabled 表情
不暴露文件路径
不要求模型记 emoji_id
```

---

## 27. 人工黑盒测试

### Case 1

用户：

```text
摸摸狗头
```

允许：

```text
……就摸一下哦。
[emoji:害羞,脸红]
```

### Case 2

```text
你刚刚是不是又犯蠢了？
```

允许：

```text
才没有！
[emoji:心虚,害羞]
……最多只算一点点。
```

### Case 3

```text
给我表演一下情绪变化
```

允许：

```text
一开始当然很开心啦。
[emoji:开心,欢快]

然后发现你又在逗我……
[emoji:无语,嫌弃]
```

### Case 4

严肃技术问题中，没有合适场景就不输出 DSL。

### Case 5

带表情回复后：

```text
关闭
重启
重新加载会话
```

顺序、图片、文本必须保持。

---

## 28. 清理旧架构

本版本必须认真删除无用代码，不让两套发送体系长期并存。

检查并清理：

```text
send_emoji Tool 注册
表情发送 Tool schema
表情专用 Router 强制执行
表情专用 required_tool
表情专用 tool_choice
表情专用 retry
“多发几个”等硬编码
旧 Emoji Tool Trace
重复 Gateway 逻辑
```

如果某段逻辑仍被其他 Tool 共用，只删除 emoji 专属部分。

---

## 29. 本版本不做

不做：

- AI 生图；
- AI 自动制作新表情；
- embedding；
- 大规模表情召回；
- QQ 接入；
- 语音；
- v1.3 外界信息适配；
- 新角色系统；
- 复杂 DSL。

第一版 Reply DSL 只需要：

```text
[emoji:...]
```

---

## 30. 最终架构

```text
                    ┌────────────────┐
                    │ emoji_registry │
                    └───────┬────────┘
                            ↓
                   build_emoji_context
                            ↓
用户消息 ─────────→ Replyer / LLM
                            ↓
                       Raw Reply
                            ↓
                       DSL Parser
                            ↓
                      ReplySequence
                    /      |       \
                 Text    Emoji     Text
                          ↓
                   Emoji Resolver
                          ↓
                     emoji_0005
                          ↓
               Conversation Persistence
                          ↓
                       Adapter
                     /         \
                   Web       Future QQ
```

---

## 31. 验收标准

- [ ] `send_emoji` 不再作为公开 Tool；
- [ ] `save_emoji` 仍正常工作；
- [ ] Replyer 能看到全部启用表情属性；
- [ ] LLM 不需要知道 emoji_id；
- [ ] 支持 `[emoji:属性1,属性2]`；
- [ ] Reply DSL Parser 稳定；
- [ ] Emoji Resolver 可根据属性匹配真实表情；
- [ ] 支持文本-表情-文本；
- [ ] 支持多表情；
- [ ] 表情位置由 Replyer 决定；
- [ ] 防重复继续有效；
- [ ] 无匹配不影响正文；
- [ ] DSL 不泄露到用户界面；
- [ ] 历史恢复不会重新解析错图；
- [ ] 旧 emoji 历史消息继续兼容；
- [ ] 删除表情专用 Tool 补丁；
- [ ] 自动测试通过；
- [ ] 完成真实聊天探索性测试。

---

## 32. 最终目标

旧方案：

```text
“我要发表情”
→ 路由判断
→ Tool
→ 强制调用
→ 图片
→ 再回复
```

新方案：

```text
“这是我的完整回复”
        ↓

“你居然还敢笑我。”
[emoji:生气,鼓脸]
“……不许笑了。”

        ↓
本地解析
        ↓
真正的多段回复
```

最终要做到：

> **表情包不是朝汐执行的一项任务，而是朝汐说话时自然使用的一种语言。**

完成本版本后，再继续扩充朝汐专属表情包。
