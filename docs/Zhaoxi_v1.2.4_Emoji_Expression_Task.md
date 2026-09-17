# Zhaoxi v1.2.4 开发任务书：本地表情包表达系统 + 纯图片消息展示优化

## 0. 版本定位

**版本：v1.2.4**

本版本作为 v1.2 系列的收尾增强版本，目标不是继续扩展朝汐的核心认知能力，而是补齐“视觉表达”这一层：

1. 为朝汐加入可主动调用的本地表情包能力；
2. 表情包由本地数据目录统一管理，并用结构化元数据描述其语义；
3. LLM 只负责表达“想传达什么情绪/语义”，不直接记忆具体图片文件；
4. 增加基本的候选检索、防重复、无匹配返回等机制；
5. 优化聊天 UI：**纯图片消息不再套默认文字气泡**；
6. 为后续 QQ 接入、桌宠、多端和 AI 作画扩展留下稳定接口。

本版本应尽量轻量，不引入新的复杂 Agent 架构，不影响 v1.3 的“外界信息适配层”开发。

---

# 1. 总体设计原则

表情包能力应属于朝汐的 **Expression / 表达层**，而不是记忆系统、Planner 或知识系统的一部分。

推荐链路：

```text
用户消息
  ↓
朝汐正常理解与回复
  ↓
判断当前语境是否适合附加表情
  ↓
LLM 调用 send_emoji(intent=...)
  ↓
EmojiService 根据 intent / emotion / tags 检索
  ↓
返回最合适的本地图片
  ↓
当前 Chat Adapter / UI 发送图片消息
```

关键约束：

- LLM 不需要知道具体文件名；
- LLM 不直接调用某个固定 `emoji_id`；
- LLM 只描述“当前想表达什么”；
- 表情库变动不应要求修改 System Prompt；
- 没有合适表情时允许不发送；
- 表情不能变成每条消息的固定尾巴；
- 表情发送逻辑与具体前端/QQ/未来移动端解耦。

---

# 2. 本地目录结构

建议在 `data/` 下新增独立目录：

```text
data/
└─ emoji/
   ├─ images/
   │  ├─ zhaoxi_001.png
   │  ├─ zhaoxi_002.webp
   │  ├─ zhaoxi_003.gif
   │  └─ ...
   │
   └─ emoji_registry.json
```

要求：

- 所有本地表情图片集中放入 `data/emoji/images/`；
- 不要将图片散落到前端资源目录、代码目录或 prompt 目录；
- 注册表只保存相对路径；
- 支持至少：
  - PNG
  - JPG/JPEG
  - WEBP
  - GIF
- 若遇到损坏文件、缺失文件，应跳过并记录日志，不应导致朝汐主进程崩溃。

---

# 3. emoji_registry.json 设计

第一版使用 JSON 即可，不需要 SQLite。

示例：

```json
[
  {
    "id": "zhaoxi_001",
    "file": "images/zhaoxi_001.png",
    "description": "被夸奖后明显有点得意，带一点臭屁和邀功感，适合在做成某件事、被认可或者想炫耀一下时发送。",
    "tags": ["得意", "开心", "邀功", "炫耀", "可爱"],
    "emotion": "proud",
    "intensity": 0.7,
    "enabled": true
  },
  {
    "id": "zhaoxi_002",
    "file": "images/zhaoxi_002.png",
    "description": "无语又有一点嫌弃地看着对方，适合吐槽、被整不会了、懒得反驳但又想表达态度时发送。",
    "tags": ["无语", "嫌弃", "吐槽"],
    "emotion": "speechless",
    "intensity": 0.5,
    "enabled": true
  }
]
```

字段约束：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `id` | 是 | 表情唯一标识 |
| `file` | 是 | 相对 `data/emoji/` 的文件路径 |
| `description` | 是 | 主要语义描述，优先用于匹配 |
| `tags` | 是 | 辅助关键词 |
| `emotion` | 否 | 粗粒度情绪分类 |
| `intensity` | 否 | 0~1，表示情绪强度 |
| `enabled` | 是 | 是否允许被检索 |

重点：

`description` 不要只写“开心”“难过”这种极短标签，而应写成具体使用场景。

---

# 4. EmojiService

新增独立服务，例如：

```text
core/expression/
└─ emoji_service.py
```

或按现有工程目录风格放置。

职责：

1. 启动时读取注册表；
2. 校验表情文件是否存在；
3. 根据 LLM 给出的 intent 检索候选；
4. 对候选进行简单排序；
5. 排除近期重复使用；
6. 返回最终图片路径；
7. 无可靠匹配时返回 `no_match`；
8. 记录必要的 Debug 日志。

建议接口：

```python
class EmojiService:
    def search(
        self,
        intent: str,
        emotion: str | None = None,
        intensity: float | None = None,
        limit: int = 5,
    ) -> list[EmojiCandidate]:
        ...

    def select(
        self,
        intent: str,
        emotion: str | None = None,
        intensity: float | None = None,
    ) -> EmojiResult:
        ...
```

返回建议：

```json
{
  "status": "matched",
  "emoji_id": "zhaoxi_002",
  "path": "data/emoji/images/zhaoxi_002.png"
}
```

无匹配：

```json
{
  "status": "no_match"
}
```

---

# 5. 第一版检索策略

v1.2.4 不要求做完整向量检索。

第一版可以使用：

```text
intent
  ↓
description + tags 关键词/文本相似度
  ↓
emotion / intensity 辅助加权
  ↓
过滤 disabled
  ↓
过滤近期重复
  ↓
Top N
  ↓
选最高分或 Top N 内轻度随机
```

要求：

- 不允许“调用了 send_emoji 就随便发一张”；
- 分数低于阈值时返回 `no_match`；
- 可以加入少量随机性，避免每种场景永远只发同一张；
- 但随机范围只能发生在“语义合理”的候选内。

后续若表情库扩大，可再将检索层换成 embedding，不影响上层工具接口。

---

# 6. 防重复与发送频率

新增简单的近期使用记录。

例如：

```python
recent_emoji_ids = deque(maxlen=5)
```

规则：

- 同一张表情不能连续发送；
- 最近 3~5 次使用过的表情降低权重；
- 表情不是每轮对话都必须发；
- 表情调用失败不能影响正常文本回复。

可选增加：

```text
emoji_min_interval_seconds
```

但 v1.2.4 不需要复杂限流系统。

---

# 7. LLM Tool：send_emoji

增加一个供朝汐调用的 Tool。

建议：

```python
send_emoji(
    intent: str,
    emotion: str | None = None,
    intensity: float | None = None
)
```

参数说明：

### intent

必须。

自然语言描述朝汐当前想通过表情传达的意思，例如：

```text
"被主人夸了以后有点得意，想邀功"
```

```text
"无语地看着对方，带一点轻微嫌弃"
```

```text
"刚刚犯蠢以后有点心虚，又想装作什么都没发生"
```

### emotion

可选。

例如：

```text
happy
proud
speechless
embarrassed
sad
angry
confused
```

不要要求固定枚举过严，避免限制表达。

### intensity

可选，范围 0~1。

---

# 8. Tool Prompt / 使用约束

给 LLM 的工具说明中明确：

- 表情包用于增强自然交流，不需要每次回复都调用；
- 有明显情绪、吐槽、玩笑、邀功、撒娇、尴尬等场景时才考虑；
- 严肃任务、长篇分析、工具执行反馈中应降低使用频率；
- 不需要知道图库中有哪些具体表情；
- 只描述当前表达意图；
- `no_match` 是正常返回；
- `no_match` 后不要立即再次调用换一个描述硬搜。

---

# 9. 消息模型兼容

确认当前消息模型可以区分：

```text
text
image
text + image
tool
```

若当前统一使用一个消息对象，至少增加足够的信息判断：

```python
message.has_text
message.has_image
message.is_image_only
```

推荐：

```python
is_image_only =
    has_image
    and not visible_text.strip()
```

不要仅通过“消息 type == image”判断，因为未来可能存在：

```text
文字 + 图片
多图片
GIF
AI 生成图片 + 说明文字
```

---

# 10. 前端优化：纯图片消息取消气泡

当前 UI 默认所有消息都套统一聊天气泡。

v1.2.4 修改规则：

## 10.1 纯文本消息

保持现状。

```text
[ 气泡背景 ]
  文本内容
```

## 10.2 文本 + 图片消息

保持气泡。

```text
[ 气泡背景 ]
  文本
  图片
```

理由：图片属于这条文本消息的一部分。

## 10.3 纯图片消息

**不使用默认消息气泡。**

目标效果：

```text
时间 / 元信息

┌───────────────┐
│     图片      │
└───────────────┘
```

而不是：

```text
████████████████████
█ ┌──────────────┐ █
█ │     图片     │ █
█ └──────────────┘ █
████████████████████
```

具体要求：

- 去掉外围气泡背景色；
- 去掉气泡 padding；
- 去掉气泡圆角容器；
- 图片本身仍可保留自己的圆角；
- 保持当前消息左右对齐规则；
- 保持时间显示；
- 保持图片最大宽高限制；
- 保持点击预览能力；
- GIF 仍应正常播放；
- 多张图片的纯图片消息也应使用“无气泡图片组”展示。

推荐前端判断：

```js
const isImageOnly =
  message.images?.length > 0 &&
  !message.text?.trim();
```

渲染：

```jsx
{isImageOnly ? (
  <ImageOnlyMessage ... />
) : (
  <MessageBubble ... />
)}
```

不要通过大量 CSS override 强行把已有 bubble 变透明。

应在组件层真正区分：

```text
Bubble Message
Image-only Message
```

避免未来继续叠补丁。

---

# 11. 朝汐发送表情后的消息形态

表情包由 `send_emoji` 发送时，应作为一条真正的图片消息进入消息流。

推荐：

```text
assistant
type=image
source=emoji
emoji_id=zhaoxi_002
path=...
```

不要把它伪装成：

```markdown
![emoji](...)
```

也不要混入文本消息正文。

这样未来 QQ Adapter 可以直接映射：

```text
image message
    ↓
OneBot / NapCat image segment
```

而 Web UI 则直接映射：

```text
image-only message
    ↓
无气泡图片组件
```

---

# 12. Debug 支持

延续 v1.2.x 当前的 Debug 思路，为表情模块提供可观察性。

Debug 页面至少能够看到：

```text
Emoji Module: Enabled / Disabled
Loaded Emojis: 37
Last Intent: "无语又嫌弃地看着主人"
Candidates:
  zhaoxi_013  0.82
  zhaoxi_021  0.76
  zhaoxi_004  0.61

Selected:
  zhaoxi_013

Recent:
  zhaoxi_002
  zhaoxi_019
  zhaoxi_013
```

最好允许：

- 运行时启用/关闭 Emoji Tool；
- Reload Registry；
- 测试输入 intent；
- 查看匹配候选；
- 手动预览某个表情。

无需修改 `.env` 再重启。

---

# 13. 配置项

建议加入统一配置：

```yaml
expression:
  emoji:
    enabled: true
    registry: data/emoji/emoji_registry.json
    recent_history_size: 5
    candidate_limit: 5
    min_match_score: 0.4
```

具体格式按现有配置体系调整。

不要新增一堆零散环境变量。

---

# 14. 异常处理

必须保证：

### 注册表不存在

```text
Emoji module disabled with warning
```

主程序继续运行。

### 图片文件不存在

跳过该条记录并输出 Warning。

### JSON 格式错误

表情模块禁用，主程序继续运行。

### Tool 调用时没有匹配项

返回：

```text
no_match
```

不抛异常给 LLM。

### 图片发送失败

记录错误，但不能导致当前正常文本回复丢失。

---

# 15. 测试要求

至少覆盖以下测试。

## Registry

- 正常加载；
- disabled 表情不会进入候选；
- 缺失文件能被跳过；
- 错误 JSON 不导致主程序崩溃。

## Search

输入：

```text
被主人夸了以后非常得意
```

应优先召回 proud / 得意类表情。

输入：

```text
无语地看着对方
```

应优先召回 speechless 类表情。

完全无关语义时：

```text
讨论 MySQL RR 隔离级别的技术细节
```

允许返回 `no_match`。

## Anti-repeat

同一个 intent 连续调用多次时，不应永远返回同一张图片。

## Tool

验证：

```text
send_emoji -> EmojiService -> image message
```

完整链路工作正常。

## UI

逐项测试：

1. 纯文字消息：仍有气泡；
2. 文字 + 单图：仍有气泡；
3. 纯单图：无气泡；
4. 纯 GIF：无气泡；
5. 纯多图：无气泡；
6. 用户发送纯图片：无气泡；
7. 朝汐发送普通图片：无气泡；
8. 朝汐通过 `send_emoji` 发表情：无气泡；
9. 图片点击预览正常；
10. 不影响历史消息加载。

---

# 16. 本版本明确不做

v1.2.4 不要顺手扩展以下功能：

- 不做 AI 自动绘图；
- 不做图片视觉理解；
- 不自动给表情图片生成 description；
- 不自动从 QQ 收藏表情包；
- 不做大规模向量数据库；
- 不做表情包自动学习；
- 不做复杂情绪模型；
- 不做表情使用长期统计分析；
- 不将表情系统塞进记忆模块；
- 不提前实现 v1.3 外界信息适配层。

这些全部留给后续版本。

---

# 17. 为未来预留的接口

虽然本版本不实现，但架构上应允许未来：

```text
ExpressionService
├─ LocalEmojiProvider
├─ GeneratedImageProvider
├─ StickerProvider
└─ FutureProvider
```

未来可变成：

```text
LLM 表达意图
      ↓
ExpressionService
      ↓
优先查本地表情
      ↓
匹配成功 ─────→ 发送
      ↓
匹配失败
      ↓
未来：AI Image Tool
      ↓
生成图片
      ↓
发送
```

v1.2.4 只实现：

```text
ExpressionService
└─ LocalEmojiProvider
```

---

# 18. 验收标准

完成以下全部条件后可挂牌 v1.2.4：

- [ ] `data/emoji/` 独立表情目录建立；
- [ ] `emoji_registry.json` 可维护本地表情语义；
- [ ] EmojiService 可正常加载与检索；
- [ ] LLM 可通过 `send_emoji(intent=...)` 调用；
- [ ] 无匹配时安全返回 `no_match`；
- [ ] 有基础防重复机制；
- [ ] 表情模块可运行时启停；
- [ ] Debug 页面能够测试表情检索；
- [ ] 表情图片能作为独立 image message 进入消息流；
- [ ] 纯图片消息不再出现默认聊天气泡；
- [ ] 文本 + 图片消息仍保持原来的气泡；
- [ ] 用户和 assistant 的纯图片消息行为一致；
- [ ] GIF / 多图正常；
- [ ] 不影响普通文本对话；
- [ ] 不影响现有 Tool、记忆、Planner、Presence 等模块；
- [ ] 自动测试通过；
- [ ] 完成一次人工黑盒冒烟测试。

---

# 19. 最终目标

v1.2.4 完成以后，朝汐应该拥有一种新的表达能力：

> 她不只是“说一句带犬娘味的话”，而是能在恰当的时候，从自己的本地表情库里翻出一张真正符合当下语境的图发出来。

同时消息 UI 应明确区分：

```text
语言表达 → Bubble
视觉表达 → Image
```

纯图片不再被强行塞进一个为文字设计的聊天气泡里。

完成本版本后，不继续扩张 v1.2 功能范围，正式转入 **v1.3 外界信息适配层**。
