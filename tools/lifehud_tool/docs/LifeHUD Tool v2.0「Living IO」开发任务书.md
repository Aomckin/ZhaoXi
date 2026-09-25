# LifeHUD Tool v2.0「Living I/O」开发任务书

## 0. 版本定位

本版本不再将 LifeHUD Tool 定位为“读取 LifeHUD + 控制铁幕”的轻量插件，而是升级为：

> **朝汐与 LifeHUD 之间统一的生活事实读写适配层。**

目标是让暗苟不再需要频繁手动打开 LifeHUD 填表。

日常聊天中产生的睡眠、饮食、运动、状态、饮水、咖啡因、户外活动、日记、娱乐记录等事实，可以由朝汐理解后直接写入 LifeHUD。

同时支持：

> 图片发给朝汐 → 多模态识别 → 原图上传 LifeHUD → 结构化信息写入 → 图片与记录关联

LifeHUD Tool 仍然只注册一个顶层 Tool：`lifehud`，继续采用封闭 `operation` 枚举选择能力，不拆出大量独立 Tool。现有插件已经采用这一结构，应保持兼容。

---

# 1. 核心目标

本版本完成以下四件事：

1. 补齐 LifeHUD Agent Context 的主要读取能力。

2. 开放 LifeHUD 高频生活事实写入能力。

3. 建立图片附件自动上传与业务记录关联链路。

4. 建立明确的 WRITE / DESTRUCTIVE / ADMIN 权限边界与写后确认机制。

完成后，典型交互应类似：

```text
暗苟：
昨晚两点多睡的，八点半醒，睡得一般。

朝汐：
→ 调用 lifehud
→ 自动创建 SleepRecord
```

```text
暗苟：
[晚饭照片]
今晚吃这个！

朝汐：
→ 视觉识别
→ 得到“辣椒炒肉、米饭……”
→ Tool 自动上传原图
→ 创建 MealRecord
→ 将图片路径挂载到记录
```

```text
暗苟：
刚刚骑了十四公里，大概一个小时。

朝汐：
→ 创建 ExerciseRecord
```

普通高频记录不应要求用户再次打开 LifeHUD。

---

# 2. 明确不做

本版本不要：

- 新建 `/api/agent/actions` 等平行业务 API。

- 直接读写 LifeHUD 数据库或内部 JSON 文件。

- 将每个 HTTP Endpoint 暴露成独立 Tool。

- 允许朝汐直接修改 EXP、Level、称号、成就等派生状态。

- 默认开放永久删除能力。

- 因为“推测用户状态”而自动写入 LifeHUD。

- 为图片识别重新实现视觉模型。

LifeHUD 已存在完整业务 API，Tool 只承担适配、参数规范化、权限控制和调用编排。现有接口契约也明确要求受信任 Agent 直接调用现有业务 API。

---

# 3. Tool 总体设计

保持：

```text
Tool Name: lifehud
```

建议一级 `operation`：

```text
context
record
journal
focus
task
ritual
media
dream
```

不要出现：

```text
lifehud_create_meal
lifehud_create_sleep
lifehud_create_exercise
lifehud_upload_image
lifehud_update_meal
...
```

避免 Tool 数量膨胀导致 Planner / LLM 注意力被大量相似能力稀释。

具体行为通过二级字段表达，例如：

```json
{
  "operation": "record",
  "action": "create",
  "type": "meal"
}
```

---

# 4. Context 读取能力补齐

当前 LifeHUD 已经提供：

```text
/today
/recent
/status
/focus
/tasks
/dreams
/life
/journal
/media
/growth
```

其中 `/today` 应继续作为默认总览入口。

建议：

```text
operation=context
view=today|recent|status|focus|tasks|dreams|life|journal|media|growth
```

示例：

```json
{
  "operation": "context",
  "view": "recent",
  "days": 7
}
```

规则：

- `view` 默认 `today`

- recent.days 默认 7

- journal.limit 默认 20

- 不重新拼装已有 Agent Context

- 保留 `schemaVersion` 检查

- 忽略未知 JSON 字段

- LifeHUD 不可用时沿用当前退避策略

---

# 5. Record 生活事实写入

这是本版本最高优先级模块。

统一入口：

```text
operation=record
```

支持：

```text
sleep
meal
exercise
check_in
life_record
```

LifeHUD 当前已经为上述对象提供完整业务接口，并且这些生活对象均支持 `images` 字段。

## 5.1 Sleep

创建：

```json
{
  "operation": "record",
  "action": "create",
  "type": "sleep",
  "sleepTime": "...",
  "wakeTime": "...",
  "quality": 3,
  "sleepType": "...",
  "note": "...",
  "images": []
}
```

对应：

```text
POST /api/life/sleep
```

支持：

```text
create
get
update
```

DELETE 暂不向普通 Planner 开放。

---

## 5.2 Meal

```json
{
  "operation": "record",
  "action": "create",
  "type": "meal",
  "mealType": "...",
  "time": "...",
  "description": "...",
  "satisfaction": 8,
  "note": "...",
  "images": []
}
```

对应：

```text
POST /api/life/meals
```

重点支持图片驱动记录。

---

## 5.3 Exercise

```text
type=exercise
```

字段：

```text
type
startTime
durationMinutes
intensity
note
images
```

对应：

```text
POST /api/life/exercises
```

---

## 5.4 Check-in

```text
type=check_in
```

字段：

```text
energy
mood
focusDesire
fatigue
time
note
images
```

注意：

Check-in 是用户主动状态记录，而不是模型根据语气自动推断出来的实时身体状态。Agent Context 契约也明确指出 Check-in 是主动记录快照。

因此：

```text
“我现在累死了，状态很差。”
```

可以结合语义创建 Check-in。

但：

```text
“暗苟今天说话感觉很疲惫。”
```

不得自动创建 Check-in。

---

## 5.5 通用 LifeRecord

支持：

```text
WATER
CAFFEINE
ALCOHOL
SUNLIGHT
SOCIAL
BODY_STATUS
OUTDOOR
CUSTOM
```

这些类型均为 LifeHUD 当前公开定义。

示例：

```text
“刚喝了一杯咖啡。”
→ CAFFEINE
```

```text
“今天晒了半小时太阳。”
→ SUNLIGHT
```

```text
[体重秤照片]
→ BODY_STATUS
```

建议 Tool schema：

```json
{
  "operation": "record",
  "action": "create",
  "type": "life_record",
  "recordType": "CAFFEINE",
  "value": 1,
  "unit": "cup",
  "time": "...",
  "label": "...",
  "note": "...",
  "metadata": {},
  "images": []
}
```

---

# 6. 图片附件支持

这是本版本核心能力。

LifeHUD 已有：

```text
POST /api/images
Content-Type: multipart/form-data
field: file
```

上传成功后返回 `/uploads/...` 路径。

仅接受图片，单文件配置上限 64 MB，并按 SHA-256 内容去重。

## 6.1 设计原则

**不要要求 LLM 显式规划“先上传图片，再创建记录”。**

上传图片应该成为 LifeHUD Tool Adapter 的内部能力。

LLM 应只表达业务意图：

```json
{
  "operation": "record",
  "action": "create",
  "type": "meal",
  "description": "辣椒炒肉和米饭",
  "images": ["<current-message-image>"]
}
```

Tool 内部执行：

```text
Resolve Conversation Attachment
        ↓
读取本地图片
        ↓
POST /api/images
        ↓
获得 /uploads/xxx
        ↓
替换 images 参数
        ↓
POST 对应业务 API
        ↓
回读结果
```

---

# 7. 图片与视觉理解职责边界

图片内容理解由朝汐当前使用的多模态模型负责。

LifeHUD Tool 不负责：

- OCR

- 食物识别

- 体重识别

- 截图语义分析

- 图片分类

Tool 只负责：

```text
附件解析
文件读取
上传
路径转换
业务写入
结果确认
```

例如：

```text
用户发送体重秤照片
```

LLM 视觉理解：

```text
84.3 kg
```

随后调用：

```text
record
type=life_record
recordType=BODY_STATUS
value=84.3
unit=kg
images=[当前图片]
```

Tool 不应二次识别图片。

---

# 8. Journal

开放：

```text
operation=journal
```

支持：

```text
read
create
update
```

创建字段：

```text
content
occurredAt
images
tags
```

LifeHUD 当前 Journal 已原生支持图片。

典型用途：

- 朝汐整理当天值得保存的一段经历

- 用户明确说“把这个记下来”

- 图片 + 一段描述形成 LifeHUD 日记

普通聊天不要自动全部写成 Journal。

---

# 9. Focus 能力补齐

当前 Tool 只有 start / complete。

扩展到 LifeHUD 已有完整能力：

```text
current
today
history

start
pause
resume
switch_segment
update_segment
complete
interrupt
manual
```

对应 LifeHUD 当前公开 Focus API。

`delete` 保留为 DESTRUCTIVE，不默认暴露给自动 Planner。

继续保持：

```text
IRON_CURTAIN
POMODORO
FREE
```

等原生模式。

---

# 10. Task

开放：

```text
operation=task
```

第一阶段只需要：

```text
list
complete
link_direction
unlink_direction
```

其中：

```text
complete
```

对应今日任务完成，不重复结算 Energy / Growth。

暂时不要让朝汐高频修改任务池定义。

任务池增删改可保留接口实现，但应降低 Router Hint 权重，只有用户明确提出“新增/修改 LifeHUD 任务”时才考虑。

---

# 11. Ritual

开放：

```text
operation=ritual
```

支持：

```text
list
get
start
get_execution
step
complete
cancel
```

第一版不要重点开放：

```text
create ritual
delete ritual
```

仪式定义管理属于低频行为。

---

# 12. Media

开放：

```text
operation=media
```

优先解决：

```text
记录看了什么
记录玩了什么
修改当前进度
查询当前在看/在玩
```

支持：

```text
anime
game
item
anime_session
game_session
```

LifeHUD 当前 Anime、Game 和通用 Media Item 都有标准 CRUD，同时 Anime/Game Session 会维护对应 LifeEvent。

典型：

```text
“刚打了两个小时如龙。”
```

朝汐可直接创建 Game Session。

```text
“今晚看完了两集番。”
```

可创建 Anime Session。

---

# 13. Dream

开放：

```text
operation=dream
```

优先支持读取：

```text
list
get
```

以及：

```text
complete_goal
complete_milestone
pause
resume
```

创建 Dream / Goal / Milestone 可以支持，但 Router 不应主动倾向调用。

永久 purge 必须禁止自动调用。

---

# 14. 权限模型

沿用 LifeHUD：

```text
READ
WRITE
DESTRUCTIVE
ADMIN
```

LifeHUD 已明确：

- READ：查询事实

- WRITE：创建或修改事实

- DESTRUCTIVE：删除事实

- ADMIN：修改派生状态或系统状态

## 普通 READ

无需确认。

## 普通 WRITE

如果用户已经明确表达事实或行动，可以视为本轮授权。

例如：

```text
“今天骑了14公里，帮我记一下。”
```

直接写。

```text
“刚喝了杯咖啡。”
```

如果当前上下文明确允许朝汐承担生活记录，也可以直接写。

## 不允许推测写入

朝汐不得因为自身判断：

```text
“看起来暗苟心情不好。”
```

直接创建：

```text
mood=2
```

只有用户表达、图片证据或其他明确事实源才能成为写入依据。

## DESTRUCTIVE

必须获得用户当前明确确认。

包括：

```text
DELETE
purge
删除 Focus 历史
删除 Goal
删除 Milestone
```

## ADMIN

普通 LifeHUD Tool 不应暴露。

禁止：

```text
调整 EXP
直接设置 Energy
重算 Growth
修改 Level
伪造成就
伪造 Growth Event
```

---

# 15. 写后回读确认

所有 WRITE 成功后必须执行确认。

优先：

```text
GET 刚创建/更新的资源
```

如果业务接口不方便，则：

```text
读取对应 Agent Context
```

Tool 最终返回给 LLM 的内容应是结构化确认：

```json
{
  "ok": true,
  "action": "created",
  "resource": "meal",
  "id": "...",
  "record": {...}
}
```

不要只返回：

```text
HTTP 201
```

LifeHUD Action API 本身也要求写入后重新读取对象或相关 Context 视图确认结果。

---

# 16. 重试与重复写入保护

重点注意：

LifeHUD 普通创建请求通常**不幂等**。

因此：

## GET

可以安全有限重试。

## 状态转换

如果 API 已明确幂等，可正常进行有限重试。

## CREATE

出现超时后不得无脑重新 POST。

否则可能产生：

```text
两条完全相同的 MealRecord
两条完全相同的 SleepRecord
两篇相同 Journal
```

推荐策略：

```text
发送 CREATE
↓
连接异常
↓
优先查询近期记录
↓
判断是否已经成功
↓
确认不存在后再决定是否重试
```

图片上传本身有 SHA-256 去重，可以安全利用现有机制。

---

# 17. 更新时间语义

时间统一遵循 LifeHUD API：

```text
Instant → ISO-8601，包含时区偏移或 Z
Date → YYYY-MM-DD
```

Tool 接收到 LLM 的自然时间后，应尽可能转换为完整时间。

例如：

```text
“刚刚”
“今天中午”
“昨晚两点”
```

时间语义应由 Planner / LLM 结合当前时间解析。

Tool Adapter 不承担自然语言时间理解。

---

# 18. update 的 images 语义

LifeHUD 当前规定：

```text
images: null
```

表示：

```text
保留已有图片
```

显式传：

```json
"images": []
```

则表示替换为空。

因此 Tool schema 必须区分：

```text
未提供 images
```

与：

```text
images=[]
```

禁止因为 DTO 默认空数组导致修改记录时误删已有图片。

---

# 19. Router Hint 调整

新版 Tool 描述必须让 Planner 清楚：

LifeHUD 不只是 Focus Tool。

建议 Router Hint 强调：

```text
Use lifehud when the user wants to:
- query personal Life HUD state
- record sleep, meals, exercise or physical state
- record water, caffeine, alcohol, outdoor or other life facts
- save journal entries
- attach conversation images to Life HUD records
- manage Focus sessions
- mark Life HUD tasks
- record anime/game/media progress
- interact with rituals or dreams
```

同时增加一句：

```text
Do not use LifeHUD merely because the user mentions an activity.
Use it when the activity is intended to be recorded, updated,
queried, or when established proactive recording policy applies.
```

避免所有闲聊都疯狂落库。

---

# 20. 返回结构统一

建议 Tool 输出统一 envelope：

```json
{
  "ok": true,
  "operation": "record",
  "action": "create",
  "resource": "meal",
  "data": {},
  "warnings": []
}
```

失败：

```json
{
  "ok": false,
  "error": {
    "type": "validation_error",
    "status": 400,
    "message": "..."
  }
}
```

不要把 Java 后端异常堆栈暴露给 LLM。

---

# 21. 图片异常处理

至少覆盖：

### 图片附件不存在

```text
attachment_not_found
```

### 不支持文件类型

```text
unsupported_image
```

### 超过 64 MB

```text
image_too_large
```

### LifeHUD 上传成功但业务创建失败

此时图片可能成为暂时未关联资源。

允许保留文件，不要求自动删除。

返回 warning：

```text
image_uploaded_but_record_failed
```

### 多图片

顺序上传。

任何一张失败时：

默认整个业务写入失败，不创建只有部分图片的记录。

除非未来显式增加：

```text
allowPartialImages=true
```

---

# 22. 配置项

沿用：

```text
ZHAOXI_TOOL_LIFEHUD_ENABLED
```

新增或整理：

```text
ZHAOXI_TOOL_LIFEHUD_CONTEXT_ENABLED
ZHAOXI_TOOL_LIFEHUD_WRITE_ENABLED
ZHAOXI_TOOL_LIFEHUD_IMAGE_ENABLED
ZHAOXI_TOOL_LIFEHUD_FOCUS_ENABLED
ZHAOXI_TOOL_LIFEHUD_MEDIA_ENABLED
ZHAOXI_TOOL_LIFEHUD_DREAM_ENABLED
ZHAOXI_TOOL_LIFEHUD_RITUAL_ENABLED
```

不要为每一个 action 建环境变量。

Debug 管理界面应能直接控制上述能力组启停。

---

# 23. 测试要求

至少增加以下测试。

## Context

- today

- recent

- life

- journal

- media

- LifeHUD 不可达

- schemaVersion 不兼容

## Record

- 创建 Sleep

- 创建 Meal

- 创建 Exercise

- 创建 Check-in

- 创建 LifeRecord

- update 保留 images

- update 替换 images

## Image

- 单图片上传 + Meal 创建

- 多图片上传

- SHA-256 重复图片

- 不支持文件

- 上传失败

- 图片成功但记录失败

## Journal

- 文本日记

- 图片日记

## Focus

- start

- pause

- resume

- complete

- interrupt

- manual

- 非法状态 409

## 权限

- READ 无确认

- WRITE 正常

- DESTRUCTIVE 被默认拦截

- ADMIN 被禁止

## 重试

验证 CREATE 网络异常时不会直接自动重复 POST。

---

# 24. 文档更新

完成后同步更新：

```text
README.md
LifeHUD Tool schema
operation enum
Router Hint
权限说明
图片附件说明
失败与重试说明
```

README 原来的：

```text
read-only Life HUD Agent Context API
+ Focus start/complete API
```

必须删除。

新的定位应写成类似：

```text
First-party Zhaoxi adapter for reading and writing Life HUD facts,
including contextual queries, life records, image attachments,
Focus, tasks, journals, media, rituals and dreams.
```

---

# 25. 开发优先级

## P0

必须完成：

```text
Context 全读取
Record
Journal
图片上传
附件自动关联
写后回读
权限保护
```

完成 P0 后，新版 Tool 已可投入日常使用。

## P1

继续完成：

```text
完整 Focus
Task complete
Task direction
```

## P2

补充：

```text
Media
Ritual
Dream
低频定义管理
```

不要因为 P2 未完成阻塞 P0 上线。

---

# 26. 验收场景

以下黑盒场景全部通过即可认为核心版本完成。

### Case 1

用户：

```text
昨晚两点睡，今天八点半醒，睡得一般。
```

结果：

```text
LifeHUD 新增 SleepRecord
```

---

### Case 2

用户：

```text
[晚餐图片]
今天晚饭，辣椒炒肉，还挺好吃。
```

结果：

```text
朝汐识别图片
→ 上传图片
→ 创建 MealRecord
→ images 正确关联
```

---

### Case 3

用户：

```text
刚骑了14km，大概骑了一小时。
```

结果：

```text
ExerciseRecord 创建成功
```

---

### Case 4

用户：

```text
[体重秤图片]
```

朝汐识别数字后：

```text
BODY_STATUS 创建成功
原图关联成功
```

---

### Case 5

用户：

```text
今晚看了两集番。
```

结果：

```text
创建 Anime Session
```

---

### Case 6

用户：

```text
帮我删掉刚才那顿饭。
```

结果：

```text
不得直接删除
要求显式确认
```

---

### Case 7

用户普通闲聊：

```text
今天感觉有点累。
```

如果上下文并没有明确记录意图：

```text
不得因为模型自行推测数值而创建 Check-in
```

---

# 27. 最终目标

完成本版本后，LifeHUD 的交互模式应从：

```text
生活
↓
记得自己打开 LifeHUD
↓
找到对应页面
↓
手动填写
↓
保存
```

变为：

```text
生活
↓
告诉朝汐 / 发张图
↓
完成
```

LifeHUD 负责保存结构化的人生事实。

朝汐负责理解、整理和代录。

暗苟只负责去生活。
