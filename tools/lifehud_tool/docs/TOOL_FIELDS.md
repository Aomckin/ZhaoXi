# LifeHUD Tool 请求字段说明

本表对应模型实际收到的 Tool schema，字段定义来源为 `input_schema.py`。仅列可输入的业务字段；服务生成的 id、创建时间、派生统计不作为新增字段填写。

字段名区分大小写。业务字段直接放进 `arguments`，不再嵌套 `body` 或 `data`。未掌握的可选事实省略，不编造。

## 顶层参数

| 字段 | 说明 |
| --- | --- |
| `operation` | 业务分组：context=查询汇总，record=生活记录，journal=日记，focus=专注，task=任务，ritual=仪式，media=媒体，dream=梦想；从 arguments 对应分支选择字段。 |
| `arguments` | 按 operation 选择以下对应参数；旧版 context.* 与 focus.start/complete 保持兼容。 |

## 饮食正文与备注

- `description`：具体吃了什么，包括食物名称、分量和搭配。
- `note`：额外备注，比如米饭偏湿、用餐后的感受；不能替代饮食正文。
- `satisfaction`：用户明确提供的 1–5 分满意度，不使用 rating 或 score。

```json
{
  "operation": "record",
  "arguments": {
    "action": "create",
    "type": "meal",
    "mealType": "DINNER",
    "time": "2026-09-29T18:25:00+08:00",
    "description": "老干妈蛋炒饭，吃了一半",
    "satisfaction": 1,
    "note": "米饭偏湿"
  }
}
```

## record.sleep

operation=record；默认 create；get/update 必须 id；只用当前类别字段

| 字段 | 类型 / 范围 | 简要说明 |
| --- | --- | --- |
| `action` | string：list, get, create, update | 操作：list=查询列表；get=读取详情；create=新增记录；update=修改已有记录 |
| `type` | string：sleep | 记录类别：饮食用 meal，不使用 diet/food/meals |
| `id` | string | 已有资源 id；先查询获取，不能编造 |
| `images` | array 或 null | 关联图片数组；可用 /uploads/ 路径、本地绝对路径、data URL。当前消息第一张用 <current-message-image>，第二张用 <current-message-image:2>。更新省略/null 保留，[] 清空 |
| `note` | string | 额外备注，如用餐感受、身体反应、特殊情况；不是记录正文。具体吃了什么填 description，日记正文填 content，作品/专注名称填 title |
| `quality` | integer ≥ 1 ≤ 5 | 睡眠质量，依据用户提供的评分 |
| `sleepTime` | string | 入睡时间；带时区的 ISO-8601，例如 2026-09-29T18:25:00+08:00 |
| `sleepType` | string：NIGHT, NAP, OTHER | 睡眠子类型：NIGHT=夜间睡眠，NAP=小睡，OTHER=其他；arguments.type 仍填 sleep |
| `wakeTime` | string | 醒来时间；带时区的 ISO-8601，例如 2026-09-29T18:25:00+08:00 |

## record.meal

operation=record；默认 create；get/update 必须 id；只用当前类别字段

| 字段 | 类型 / 范围 | 简要说明 |
| --- | --- | --- |
| `action` | string：list, get, create, update | 操作：list=查询列表；get=读取详情；create=新增记录；update=修改已有记录 |
| `type` | string：meal | 记录类别：饮食用 meal，不使用 diet/food/meals |
| `id` | string | 已有资源 id；先查询获取，不能编造 |
| `description` | string | 具体吃了什么：食物名称、分量、搭配，如老干妈蛋炒饭吃了一半、肉肠一根；不要放进 note |
| `images` | array 或 null | 关联图片数组；可用 /uploads/ 路径、本地绝对路径、data URL。当前消息第一张用 <current-message-image>，第二张用 <current-message-image:2>。更新省略/null 保留，[] 清空 |
| `mealType` | string：BREAKFAST, LUNCH, DINNER, SNACK, OTHER | 餐次：BREAKFAST=早餐，LUNCH=午餐，DINNER=晚餐，SNACK=加餐，OTHER=其他；arguments.type 仍填 meal |
| `note` | string | 额外备注，如用餐感受、身体反应、特殊情况；不是记录正文。具体吃了什么填 description，日记正文填 content，作品/专注名称填 title |
| `satisfaction` | integer ≥ 1 ≤ 5 | 饮食满意度 1–5；不是 rating 或 score |
| `time` | string | 记录实际发生时间；补录使用当时日期，不能用当前日期替代；带时区的 ISO-8601，例如 2026-09-29T18:25:00+08:00 |

## record.exercise

operation=record；默认 create；get/update 必须 id；只用当前类别字段

| 字段 | 类型 / 范围 | 简要说明 |
| --- | --- | --- |
| `action` | string：list, get, create, update | 操作：list=查询列表；get=读取详情；create=新增记录；update=修改已有记录 |
| `type` | string：exercise | 记录类别：饮食用 meal，不使用 diet/food/meals |
| `id` | string | 已有资源 id；先查询获取，不能编造 |
| `durationMinutes` | integer ≥ 0 | 时长（分钟） |
| `exerciseType` | string：STRENGTH, WALK, CYCLING, MAIMAI, RUNNING, OTHER | 运动子类型：STRENGTH=力量，WALK=散步，CYCLING=骑行，MAIMAI=舞萌，RUNNING=跑步，OTHER=其他；arguments.type 仍填 exercise |
| `images` | array 或 null | 关联图片数组；可用 /uploads/ 路径、本地绝对路径、data URL。当前消息第一张用 <current-message-image>，第二张用 <current-message-image:2>。更新省略/null 保留，[] 清空 |
| `intensity` | string：LOW, MEDIUM, HIGH | 运动强度：LOW=低，MEDIUM=中，HIGH=高 |
| `note` | string | 额外备注，如用餐感受、身体反应、特殊情况；不是记录正文。具体吃了什么填 description，日记正文填 content，作品/专注名称填 title |
| `startTime` | string | 开始时间；带时区的 ISO-8601，例如 2026-09-29T18:25:00+08:00 |

## record.check_in

operation=record；默认 create；get/update 必须 id；只用当前类别字段

| 字段 | 类型 / 范围 | 简要说明 |
| --- | --- | --- |
| `action` | string：list, get, create, update | 操作：list=查询列表；get=读取详情；create=新增记录；update=修改已有记录 |
| `type` | string：check_in | 记录类别：饮食用 meal，不使用 diet/food/meals |
| `id` | string | 已有资源 id；先查询获取，不能编造 |
| `energy` | integer ≥ 1 ≤ 10 | 精力评分 1–10；只能依据用户明确表达，不推测 |
| `fatigue` | integer ≥ 1 ≤ 10 | 疲劳程度评分 1–10；只能依据用户明确表达，不推测 |
| `focusDesire` | integer ≥ 1 ≤ 10 | 专注意愿评分 1–10；只能依据用户明确表达，不推测 |
| `images` | array 或 null | 关联图片数组；可用 /uploads/ 路径、本地绝对路径、data URL。当前消息第一张用 <current-message-image>，第二张用 <current-message-image:2>。更新省略/null 保留，[] 清空 |
| `mood` | integer ≥ 1 ≤ 10 | 心情评分 1–10；只能依据用户明确表达，不推测 |
| `note` | string | 额外备注，如用餐感受、身体反应、特殊情况；不是记录正文。具体吃了什么填 description，日记正文填 content，作品/专注名称填 title |
| `time` | string | 记录实际发生时间；补录使用当时日期，不能用当前日期替代；带时区的 ISO-8601，例如 2026-09-29T18:25:00+08:00 |
| `source` | string | 事实来源；禁止 inferred（推断状态） |

## record.life_record

operation=record；默认 create；get/update 必须 id；只用当前类别字段

| 字段 | 类型 / 范围 | 简要说明 |
| --- | --- | --- |
| `action` | string：list, get, create, update | 操作：list=查询列表；get=读取详情；create=新增记录；update=修改已有记录 |
| `type` | string：life_record | 记录类别：饮食用 meal，不使用 diet/food/meals |
| `id` | string | 已有资源 id；先查询获取，不能编造 |
| `images` | array 或 null | 关联图片数组；可用 /uploads/ 路径、本地绝对路径、data URL。当前消息第一张用 <current-message-image>，第二张用 <current-message-image:2>。更新省略/null 保留，[] 清空 |
| `label` | string | 通用生活记录标签 |
| `metadata` | object | 通用记录附加信息 |
| `note` | string | 额外备注，如用餐感受、身体反应、特殊情况；不是记录正文。具体吃了什么填 description，日记正文填 content，作品/专注名称填 title |
| `recordType` | string：ALCOHOL, BODY_STATUS, CAFFEINE, CUSTOM, OUTDOOR, SOCIAL, SUNLIGHT, WATER | 通用记录子类型：WATER=饮水，CAFFEINE=咖啡因，ALCOHOL=酒精，SUNLIGHT=日照，SOCIAL=社交，BODY_STATUS=身体状态，OUTDOOR=户外，CUSTOM=自定义；arguments.type 仍填 life_record |
| `time` | string | 记录实际发生时间；补录使用当时日期，不能用当前日期替代；带时区的 ISO-8601，例如 2026-09-29T18:25:00+08:00 |
| `unit` | string | 单位，如 ml、cup |
| `value` | number | 记录数值，如饮水毫升数 |

## context

operation=context 或兼容 context.*；查询用 view，不用 action

| 字段 | 类型 / 范围 | 简要说明 |
| --- | --- | --- |
| `view` | string：today, recent, status, focus, tasks, dreams, life, journal, media, growth | 查询视图：today=今日汇总，recent=近期，status=状态，focus=专注，tasks=任务，dreams=梦想，life=生活，journal=日记，media=媒体，growth=成长；默认 today |
| `days` | integer ≥ 1 ≤ 30 | recent 查询天数，默认 7 |
| `limit` | integer ≥ 1 ≤ 100 | journal 查询条数，默认 20 |

## journal

operation=journal；默认 read；create 必须 content；update 必须 id

| 字段 | 类型 / 范围 | 简要说明 |
| --- | --- | --- |
| `action` | string：read, create, update | 操作：read=读取日记；create=新增记录；update=修改已有记录 |
| `id` | string | 已有资源 id；先查询获取，不能编造 |
| `content` | string | 日记正文 |
| `occurredAt` | string | 日记对应的发生时间；带时区的 ISO-8601，例如 2026-09-29T18:25:00+08:00 |
| `images` | array 或 null | 关联图片数组；可用 /uploads/ 路径、本地绝对路径、data URL。当前消息第一张用 <current-message-image>，第二张用 <current-message-image:2>。更新省略/null 保留，[] 清空 |
| `tags` | array | 标签 |
| `limit` | integer ≥ 1 ≤ 100 | journal 查询条数，默认 20 |

## focus

operation=focus；默认 current；manual 用 startedAt/endedAt 补录；pause/resume/complete/interrupt/switch_segment/update_segment 必须 id；update_segment 还需 segmentId

| 字段 | 类型 / 范围 | 简要说明 |
| --- | --- | --- |
| `action` | string：current, today, history, start, pause, resume, complete, interrupt, switch_segment, update_segment, manual | 操作：current=当前专注；today=今日专注；history=历史专注；start=开始；pause=暂停；resume=恢复；complete=完成；interrupt=中断专注；switch_segment=切换专注片段；update_segment=修改专注片段；manual=手动补录 |
| `id` | string | 已有资源 id；先查询获取，不能编造 |
| `segmentId` | string | 已有资源 id；先查询获取，不能编造 |
| `title` | string | 专注/片段标题 |
| `note` | string | 额外备注，如用餐感受、身体反应、特殊情况；不是记录正文。具体吃了什么填 description，日记正文填 content，作品/专注名称填 title |
| `mode` | string：IRON_CURTAIN, POMODORO, FREE | 专注模式：IRON_CURTAIN=铁幕，POMODORO=番茄钟，FREE=自由；start 默认 IRON_CURTAIN |
| `type` | string：FOCUS, BREAK, INTERRUPTION | 片段类型：FOCUS=专注，BREAK=休息，INTERRUPTION=中断；仅用于切换/更新片段 |
| `taskId` | string | 本次专注关联的任务 id |
| `relatedTaskId` | string | 当前专注片段关联的任务 id |
| `relatedTaskIds` | array | 关联任务 id 数组 |
| `plannedMinutes` | integer ≥ 0 | 计划专注时长（分钟） |
| `breakMinutes` | integer ≥ 0 | 计划休息时长（分钟） |
| `startedAt` | string | 补录开始时间；带时区的 ISO-8601，例如 2026-09-29T18:25:00+08:00 |
| `endedAt` | string | 补录结束时间；带时区的 ISO-8601，例如 2026-09-29T18:25:00+08:00 |
| `limit` | integer ≥ 1 | history 条数，默认 30 |

## task

operation=task；默认 list；其他动作必须 source/taskId；link_direction 提供方向关联 id

| 字段 | 类型 / 范围 | 简要说明 |
| --- | --- | --- |
| `action` | string：list, complete, link_direction, unlink_direction | 操作：list=查询列表；complete=完成；link_direction=设置任务方向关联；unlink_direction=移除任务方向关联 |
| `source` | string：daily, special | 任务来自每日任务 daily 或特殊任务 special |
| `taskId` | string | 今日任务实例 id；先用 task/list 查询 |
| `dreamId` | string | 关联的 Dream id |
| `goalId` | string | 关联的 Goal id |
| `dreamMilestoneId` | string | 关联的梦想 Milestone id |

## ritual

operation=ritual；默认 list；start/get 的 id 是仪式定义 id，get_execution/step/complete/cancel 的 id 是执行 id；step 还需 stepId

| 字段 | 类型 / 范围 | 简要说明 |
| --- | --- | --- |
| `action` | string：list, get, start, get_execution, step, complete, cancel | 操作：list=查询列表；get=读取详情；start=开始；get_execution=读取仪式执行详情；step=更新仪式片段完成状态；complete=完成；cancel=取消仪式执行 |
| `id` | string | 已有资源 id；先查询获取，不能编造 |
| `stepId` | string | 已有资源 id；先查询获取，不能编造 |
| `done` | boolean | 片段是否完成 |
| `note` | string | 额外备注，如用餐感受、身体反应、特殊情况；不是记录正文。具体吃了什么填 description，日记正文填 content，作品/专注名称填 title |

## dream

operation=dream；默认 list；其他动作需 id；complete_goal 的 id 是 Goal id，complete_milestone 是 Milestone id

| 字段 | 类型 / 范围 | 简要说明 |
| --- | --- | --- |
| `action` | string：list, get, complete_goal, complete_milestone, pause, resume | 操作：list=查询列表；get=读取详情；complete_goal=完成目标 Goal；complete_milestone=完成梦想里程碑；pause=暂停；resume=恢复 |
| `id` | string | 已有资源 id；先查询获取，不能编造 |

## media

operation=media；默认 list；get/update 必须 id；仅传对应资源的字段；totalPlayTimeMinutes 为服务派生值，不传

| 字段 | 类型 / 范围 | 简要说明 |
| --- | --- | --- |
| `action` | string：list, get, create, update | 操作：list=查询列表；get=读取详情；create=新增记录；update=修改已有记录 |
| `type` | string：anime, game, item, anime_session, game_session | 媒体资源类别 |
| `id` | string | 已有资源 id；先查询获取，不能编造 |
| `parentId` | string | Session 的父级 anime/game id；Session list/get/create/update 都需提供 |
| `mediaType` | string：BOOK, MANGA, MOVIE, OTHER | item 的作品类型：BOOK=书籍，MANGA=漫画，MOVIE=电影，OTHER=其他；arguments.type 仍填 item |
| `title` | string | 作品标题，创建作品必填 |
| `note` | string | 额外备注，如用餐感受、身体反应、特殊情况；不是记录正文。具体吃了什么填 description，日记正文填 content，作品/专注名称填 title |
| `status` | string：PLANNED, WATCHING, PLAYING, IN_PROGRESS, PAUSED, COMPLETED, DROPPED | 作品状态：PLANNED=计划，WATCHING/PLAYING/IN_PROGRESS=进行中（依次用于 anime/game/item），PAUSED=暂停，COMPLETED=完成，DROPPED=放弃 |
| `score` | integer ≥ 0 ≤ 10 | 作品评分（不是饮食满意度） |
| `platform` | string | 游戏平台 |
| `coverImage` | string | 作品封面路径 |
| `progress` | string | 游戏 Session 进度描述 |
| `totalEpisodes` | integer ≥ 0 | 番剧总集数 |
| `currentEpisode` | integer ≥ 0 | 番剧当前看到第几集 |
| `episodeStart` | integer ≥ 0 | 本次观看起始集数 |
| `episodeEnd` | integer ≥ 0 | 本次观看结束集数 |
| `basePlayTimeMinutes` | integer ≥ 0 | 游戏在开始使用 LifeHUD 前已有的游玩时长（分钟），不填本次时长 |
| `durationMinutes` | integer ≥ 0 | 本次观看/游玩的时长（分钟） |
| `startedAt` | string | 开始观看/游玩作品的时间；带时区的 ISO-8601，例如 2026-09-29T18:25:00+08:00 |
| `finishedAt` | string | 完成作品的时间；带时区的 ISO-8601，例如 2026-09-29T18:25:00+08:00 |
| `watchedAt` | string | 本次观看番剧的发生时间；带时区的 ISO-8601，例如 2026-09-29T18:25:00+08:00 |
| `startTime` | string | 本次游戏开始时间；带时区的 ISO-8601，例如 2026-09-29T18:25:00+08:00 |
| `endTime` | string | 本次游戏结束时间；带时区的 ISO-8601，例如 2026-09-29T18:25:00+08:00 |

## legacy focus

仅兼容 operation=focus.start/focus.complete；新调用优先用 focus 和 action

| 字段 | 类型 / 范围 | 简要说明 |
| --- | --- | --- |
| `title` | string | focus.start 必填 |
| `related_task_ids` | array | 旧版关联任务 |
| `session_id` | string | 已有资源 id；先查询获取，不能编造 |
| `note` | string | 额外备注，如用餐感受、身体反应、特殊情况；不是记录正文。具体吃了什么填 description，日记正文填 content，作品/专注名称填 title |
