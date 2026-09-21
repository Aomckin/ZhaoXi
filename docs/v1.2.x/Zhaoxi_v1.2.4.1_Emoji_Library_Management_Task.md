# Zhaoxi v1.2.4.1 开发任务书：表情柜 + 表情收藏工具

## 0. 版本定位

本补丁建立在 v1.2.4 已完成的本地表情表达系统之上，不重做 `send_emoji`，只补齐“如何自然地把表情喂给朝汐并管理”的使用闭环。

v1.2.4 已经具备本地表情目录、JSON 注册表、EmojiService、`send_emoji(intent, emotion?, intensity?)`、独立图片消息、纯图片无气泡以及 Emoji Debug。本补丁在这些能力上增加：

- 聊天中直接把图片交给朝汐收藏；
- 朝汐自动生成表情语义标签；
- 统一的 EmojiManager 负责落盘与注册表维护；
- 侧边栏新增「表情柜」；
- 支持浏览、编辑、删除、启停；
- 支持批量拖入与“待整理”；
- 支持“让朝汐整理”批量生成元数据。

目标体验：

```text
暗苟：
[图片]
这个存一下，以后我说离谱话时可以用

朝汐：
理解图片 + 用户说明 + 当前语境
    ↓
生成 description / tags / emotion / intensity
    ↓
调用 save_emoji(...)
    ↓
EmojiManager 落盘
    ↓
更新 registry
    ↓
自动 Reload
    ↓
立即可被 send_emoji 使用
```

---

## 1. 核心原则

### 1.1 LLM 负责理解，程序负责保存

LLM 不直接写 JSON，不自行拼路径，不决定最终文件名。

LLM 只负责提供语义：

```json
{
  "description": "被主人整无语以后死鱼眼看着对方，适合轻微吐槽或嫌弃时使用。",
  "tags": ["无语", "嫌弃", "吐槽"],
  "emotion": "speechless",
  "intensity": 0.6
}
```

真正的文件复制、ID 生成、去重、注册表写入、删除、更新、Reload 都统一交给 EmojiManager。

---

## 2. 新增 EmojiManager

建议新增：

```text
core/expression/
├─ emoji_service.py
└─ emoji_manager.py
```

职责：

```text
EmojiService
→ 负责“发哪张”

EmojiManager
→ 负责“图库怎么增删改查”
```

建议接口：

```python
class EmojiManager:
    def add_from_message(...): ...
    def add_from_file(...): ...
    def update_metadata(...): ...
    def delete(...): ...
    def list_all(...): ...
    def get(...): ...
    def reload(...): ...
    def find_duplicate(...): ...
```

任何 Web UI、Tool、Debug 都不能绕过 EmojiManager 直接修改 `emoji_registry.json`。

---

## 3. 新增 Tool：save_emoji

建议：

```python
save_emoji(
    image_ref: str,
    description: str,
    tags: list[str],
    emotion: str | None = None,
    intensity: float | None = None
)
```

`image_ref` 指向当前会话里已经存在的图片消息/附件。

具体名字可以按现有消息模型改成：

```text
image_message_id
attachment_id
media_id
```

但不要让 LLM 传本地绝对路径。

---

## 4. Tool 使用规则

只有用户明确表达以下意图时才调用：

```text
“存一下这个”
“这个收进表情包”
“以后可以拿这个吐槽我”
“把这张记到表情库里”
```

不能因为用户单纯发图就自动收藏。

Tool Prompt 中明确：

- `description` 描述“表达含义和适用语境”，不是纯画面描述；
- `tags` 用自然中文短词；
- `emotion` 只做粗分类；
- `intensity` 范围 0~1；
- 可以结合用户说明和当前上下文；
- Tool 返回失败时不能假装保存成功；
- 已存在的图片允许返回 duplicate；
- 不确定用途时不要过度脑补。

不推荐：

```text
description = “一个女孩捂脸”
```

推荐：

```text
description = “因为自己刚做了蠢事而尴尬捂脸，带一点心虚和想蒙混过去的感觉。”
```

---

## 5. 图片保存流程

```text
Conversation Image
    ↓
解析真实图片资源
    ↓
校验格式
    ↓
计算 SHA-256
    ↓
查重
    ↓
生成 emoji_id
    ↓
复制到 data/emoji/images/
    ↓
更新 registry
    ↓
Reload EmojiService
    ↓
返回结果
```

支持：

- PNG
- JPG / JPEG
- WebP
- GIF

GIF 必须保留动图，不得无意转成静态图片。

---

## 6. 文件命名

不要使用用户上传时的超长原始文件名。

推荐：

```text
emoji_0001.png
emoji_0002.webp
emoji_0003.gif
```

或短 UUID。

优先建议序号式 ID，便于 Debug 和人工排查。

---

## 7. 基础去重

第一版只做 SHA-256 即可。

重复时：

```json
{
  "status": "duplicate",
  "emoji_id": "emoji_0017"
}
```

不要重复复制。

感知哈希、相似图片检测留到以后。

---

## 8. Registry 写入安全

修改 `emoji_registry.json` 时：

1. 读取当前 registry；
2. 修改内存对象；
3. 写入临时文件；
4. 校验 JSON；
5. 原子替换正式文件。

示意：

```text
emoji_registry.json.tmp
        ↓
write
        ↓
validate
        ↓
replace
```

避免异常导致 registry 被写残。

---

## 9. 自动 Reload

成功执行：

```text
add
update
delete
```

后自动刷新 EmojiService。

聊天里收藏完后，不应再要求用户去 Debug 手动 Reload。

Debug 的 Reload 保留为维护入口。

---

## 10. 侧边栏新增「表情柜」

当前“小桌边”新增：

```text
▶ 表情柜
```

建议结构：

```text
小桌边
├─ 系统消息
├─ 设置
├─ 维护抽屉
├─ 钥匙柜
├─ 表情柜
└─ Debug
```

第一版展开：

```text
表情柜                         42 张

[ 搜索…… ]

[ + 添加表情 ]  [ 刷新 ]

最近加入

┌─────┐ ┌─────┐ ┌─────┐
│ 图1 │ │ 图2 │ │ 图3 │
└─────┘ └─────┘ └─────┘

[ 查看全部 ]
```

不要直接在侧边栏加载整个图库。

---

## 11. 表情列表

点击“查看全部”：

```text
← 表情柜                42 张

[搜索……]

[全部] [启用] [停用]

┌──────┐ ┌──────┐
│ 图像 │ │ 图像 │
└──────┘ └──────┘
无语       得意
吐槽       开心
```

需要支持：

- 缩略图；
- emotion / tags；
- enabled 状态；
- 搜索；
- 点击进入详情。

搜索范围：

```text
description
tags
emotion
emoji_id
```

---

## 12. 表情详情编辑

```text
← 返回

[       图片预览       ]

ID
emoji_0021

描述
[ 被主人整无语以后死鱼眼…… ]

标签
[无语] [嫌弃] [吐槽] [+]

情绪
[ speechless ]

强度
[------●---] 0.6

[x] 启用

[保存修改]

[删除表情]
```

支持：

- 修改 description；
- 修改 tags；
- 修改 emotion；
- 修改 intensity；
- 启用/停用；
- 删除；
- 查看原图。

保存后自动 Reload。

---

## 13. 从 UI 手动添加

`+ 添加表情` 支持：

```text
选择图片 / 拖入图片
```

进入待编辑状态后提供两种方式。

### 模式 A：手工填写

用户自行填写元数据。

### 模式 B：让朝汐整理

按钮：

```text
[ 让朝汐识别 ]
```

模型使用现有视觉能力分析图片，生成：

```text
description
tags
emotion
intensity
```

结果先展示给用户确认，不直接写入正式表情库。

---

## 14. 新增「待整理」Inbox

建议增加：

```text
data/
└─ emoji/
   ├─ images/
   ├─ pending/
   └─ emoji_registry.json
```

批量拖入图片时先进入：

```text
data/emoji/pending/
```

此时：

- 不进入正式 registry；
- 不会被 `send_emoji` 检索；
- 等待人工或朝汐整理。

表情柜顶部显示：

```text
待整理 12
```

---

## 15. 批量「让朝汐整理」

Pending 页面提供：

```text
[让朝汐整理全部]
```

单张也提供：

```text
[让朝汐整理]
```

处理后展示：

```text
01
[图]

无语 / 嫌弃 / 吐槽

“完全被整不会了，但又懒得认真反驳。”

[✓ 保存] [✎ 修改] [× 丢弃]
```

第一版不要做“自动分析完直接全部入库”。

保留一次快速确认，避免语义污染表情库。

---

## 16. 建议 API

按现有 Web/Core 架构调整具体路由：

```text
GET    /api/emoji
GET    /api/emoji/{id}
POST   /api/emoji
PATCH  /api/emoji/{id}
DELETE /api/emoji/{id}

POST   /api/emoji/reload

GET    /api/emoji/pending
POST   /api/emoji/pending
DELETE /api/emoji/pending/{id}
POST   /api/emoji/pending/{id}/commit
```

UI 不直接读取本地 JSON 和文件系统。

---

## 17. 删除行为

删除时同时处理：

```text
registry record
+
本地图片
```

提供二次确认：

```text
确定从朝汐的表情柜里删除这张表情吗？
```

任何失败都不能留下半完成状态。

---

## 18. 与现有 send_emoji 兼容

本补丁不能改变原 `send_emoji` 接口。

仍然：

```python
send_emoji(
    intent,
    emotion=None,
    intensity=None
)
```

新增或修改的表情自动进入原 EmojiService 的检索范围。

架构保持：

```text
save_emoji
    ↓
EmojiManager
    ↓
Registry / Images
    ↓
EmojiService
    ↓
send_emoji
```

不能另起一套图库。

---

## 19. Debug 调整

现有 Emoji Debug 保留，可增加：

```text
Loaded Emojis: 42
Pending Emojis: 7
Last Added: emoji_0042
Registry Status: OK
```

Debug 只用于维护和诊断。

正式管理入口为「表情柜」。

---

## 20. UI 风格要求

表情柜继续服从当前“小桌边”的视觉语言：

- 轻量；
- 卡片化；
- 圆角；
- 留白；
- 图片优先；
- 管理感弱；
- 收藏柜/抽屉感强。

目标是：

> 朝汐自己的表情收藏柜

而不是：

> Emoji Database Admin Console

---

## 21. 本补丁明确不做

不做：

- AI 作画；
- 自动生成新表情；
- QQ 自动偷表情；
- 收到图片就自动收藏；
- 感知哈希高级去重；
- embedding 重构；
- 云端图库；
- 长期使用频率分析；
- 自动清理冷门表情；
- 多用户表情库；
- v1.3 外界信息适配。

---

## 22. 测试要求

### EmojiManager

覆盖：

- add；
- update；
- delete；
- list；
- duplicate；
- registry 原子写入；
- 自动 reload；
- GIF 保留。

### save_emoji Tool

完整链路：

```text
用户图片消息
→ image_ref
→ save_emoji
→ images/
→ registry
→ EmojiService
```

错误引用：

```text
status=not_found
```

重复图片：

```text
status=duplicate
```

### 表情柜

测试：

- 展开；
- 列表；
- 搜索；
- 查看详情；
- 修改；
- enabled 切换；
- 删除；
- 上传；
- pending；
- commit。

### 回归

确认：

- 原 `send_emoji` 正常；
- 防重复正常；
- 纯图片无气泡正常；
- GIF 正常；
- 历史图片消息正常；
- 普通聊天不受影响；
- Tool 清单与运行时启停不受影响。

---

## 23. 人工黑盒验收

### Case 1：聊天收藏

```text
[发一张图片]
“这个存一下”
```

检查：

```text
朝汐理解语义
→ 调 save_emoji
→ 图片入库
→ registry 有记录
→ 表情柜出现
```

### Case 2：实际发送

继续聊天制造相似语境。

检查：

```text
send_emoji
→ 能召回刚刚收藏的图片
→ 图片正常发出
→ UI 无外围气泡
```

### Case 3：编辑

在表情柜修改 description，再制造语境，确认新描述参与检索。

### Case 4：删除

删除表情后确认：

```text
registry 删除
图片删除
send_emoji 不再召回
```

### Case 5：批量

一次拖入 5~10 张图片，检查 Pending 与批量整理流程。

---

## 24. 验收清单

- [ ] EmojiManager 建立；
- [ ] Registry 增删改查统一走 EmojiManager；
- [ ] `save_emoji` Tool 可用；
- [ ] Tool 可引用当前聊天图片；
- [ ] LLM 负责生成语义元数据；
- [ ] 程序负责文件与 registry；
- [ ] SHA-256 基础去重；
- [ ] 自动 Reload；
- [ ] 侧边栏新增「表情柜」；
- [ ] 支持图片网格浏览；
- [ ] 支持搜索；
- [ ] 支持详情编辑；
- [ ] 支持 enabled 开关；
- [ ] 支持删除；
- [ ] 支持手动添加；
- [ ] 支持“让朝汐识别”；
- [ ] 支持 pending 待整理目录；
- [ ] 支持批量导入后快速确认；
- [ ] 不影响原 `send_emoji`；
- [ ] 不影响图片无气泡；
- [ ] 自动测试通过；
- [ ] 完成人工黑盒测试。

---

## 25. 最终体验目标

完成后，添加表情不再是：

```text
打开文件夹
→ 复制图片
→ 找 registry
→ 手写 JSON
→ Debug Reload
```

而是：

```text
[把图丢给朝汐]

“这个你收着，以后拿来吐槽我。”

朝汐：
“记住啦！”
```

背后自动完成：

```text
理解
→ 标注
→ 收藏
→ 入库
→ Reload
→ 可发送
```

大量整理时：

```text
打开右侧「表情柜」
→ 批量拖入
→ 让朝汐整理
→ 快速确认
→ 完成
```

聊天入口负责“随手喂”，表情柜负责“集中整理”。

开发完成后，再开始一次性给朝汐塞第一批真实表情包，并以真实聊天作为 v1.2.4 系列最后的黑盒验收。
