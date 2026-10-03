"""Model-facing business fields, also returned as guidance after invalid input."""

from copy import deepcopy

from tools.lifehud_tool.living_io import LIFE_TYPES, RECORD_FIELDS, RECORD_PATHS


MEAL_EXAMPLE = {
    "operation": "record",
    "arguments": {"action": "create", "type": "meal", "mealType": "DINNER",
                  "time": "2026-09-29T18:25:00+08:00", "description": "老干妈蛋炒饭，吃了一半",
                  "satisfaction": 1, "note": "米饭偏湿"},
}


def field(kind: str, description: str, **constraints) -> dict:
    return {"type": kind, "description": description, **constraints}


def choice(description: str, *values: str) -> dict:
    return field("string", description, enum=list(values))


def instant(description: str) -> dict:
    return field("string", description + "；带时区的 ISO-8601，例如 2026-09-29T18:25:00+08:00")


def variant(title: str, description: str, actions: tuple[str, ...], properties: dict,
            required: tuple[str, ...] = ()) -> dict:
    meanings = {"list": "查询列表", "get": "读取详情", "read": "读取日记", "create": "新增记录", "update": "修改已有记录",
                "current": "当前专注", "today": "今日专注", "history": "历史专注", "start": "开始", "manual": "手动补录",
                "pause": "暂停", "resume": "恢复", "complete": "完成", "interrupt": "中断专注", "cancel": "取消仪式执行",
                "switch_segment": "切换专注片段", "update_segment": "修改专注片段", "step": "更新仪式片段完成状态",
                "get_execution": "读取仪式执行详情", "link_direction": "设置任务方向关联", "unlink_direction": "移除任务方向关联",
                "complete_goal": "完成目标 Goal", "complete_milestone": "完成梦想里程碑"}
    return {"type": "object", "title": title, "description": description,
            "properties": {"action": choice("操作：" + "；".join(action + "=" + meanings[action] for action in actions), *actions), **properties},
            "required": list(required), "additionalProperties": False}


def arguments_schema() -> dict:
    note = field("string", "额外备注，如用餐感受、身体反应、特殊情况；不是记录正文。具体吃了什么填 description，日记正文填 content，作品/专注名称填 title")
    ident = field("string", "已有资源 id；先查询获取，不能编造")
    images = {"description": "关联图片数组；可用 /uploads/ 路径、本地绝对路径、data URL。当前消息第一张用 <current-message-image>，第二张用 <current-message-image:2>。更新省略/null 保留，[] 清空",
              "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]}
    fields = {
        "note": note, "images": images,
        "sleepTime": instant("入睡时间"), "wakeTime": instant("醒来时间"),
        "quality": field("integer", "睡眠质量，依据用户提供的评分", minimum=1, maximum=5),
        "sleepType": choice("睡眠子类型：NIGHT=夜间睡眠，NAP=小睡，OTHER=其他；arguments.type 仍填 sleep", "NIGHT", "NAP", "OTHER"),
        "mealType": choice("餐次：BREAKFAST=早餐，LUNCH=午餐，DINNER=晚餐，SNACK=加餐，OTHER=其他；arguments.type 仍填 meal", "BREAKFAST", "LUNCH", "DINNER", "SNACK", "OTHER"),
        "time": instant("记录实际发生时间；补录使用当时日期，不能用当前日期替代"),
        "description": field("string", "具体吃了什么：食物名称、分量、搭配，如老干妈蛋炒饭吃了一半、肉肠一根；不要放进 note"),
        "satisfaction": field("integer", "饮食满意度 1–5；不是 rating 或 score", minimum=1, maximum=5),
        "exerciseType": choice("运动子类型：STRENGTH=力量，WALK=散步，CYCLING=骑行，MAIMAI=舞萌，RUNNING=跑步，OTHER=其他；arguments.type 仍填 exercise", "STRENGTH", "WALK", "CYCLING", "MAIMAI", "RUNNING", "OTHER"),
        "startTime": instant("开始时间"), "durationMinutes": field("integer", "时长（分钟）", minimum=0),
        "intensity": choice("运动强度：LOW=低，MEDIUM=中，HIGH=高", "LOW", "MEDIUM", "HIGH"),
        **{name: field("integer", description + "评分 1–10；只能依据用户明确表达，不推测", minimum=1, maximum=10)
           for name, description in {"energy": "精力", "mood": "心情", "focusDesire": "专注意愿", "fatigue": "疲劳程度"}.items()},
        "recordType": choice("通用记录子类型：WATER=饮水，CAFFEINE=咖啡因，ALCOHOL=酒精，SUNLIGHT=日照，SOCIAL=社交，BODY_STATUS=身体状态，OUTDOOR=户外，CUSTOM=自定义；arguments.type 仍填 life_record", *sorted(LIFE_TYPES)),
        "value": field("number", "记录数值，如饮水毫升数"), "unit": field("string", "单位，如 ml、cup"),
        "label": field("string", "通用生活记录标签"), "metadata": field("object", "通用记录附加信息", additionalProperties=True),
    }
    branches = []
    aliases = {"sleep": "sleepType", "exercise": "exerciseType", "life_record": "recordType"}
    for kind in RECORD_PATHS:
        names = (RECORD_FIELDS[kind] - {"type"}) | ({aliases[kind]} if kind in aliases else set())
        props = {"type": choice("记录类别：饮食用 meal，不使用 diet/food/meals", kind), "id": ident,
                 **{name: fields[name] for name in sorted(names)}}
        if kind == "check_in":
            props["source"] = field("string", "事实来源；禁止 inferred（推断状态）")
        branches.append(variant("record." + kind, "operation=record；默认 create；get/update 必须 id；只用当前类别字段",
                                ("list", "get", "create", "update"), props, ("type",)))
    context = {"view": choice("查询视图：today=今日汇总，recent=近期，status=状态，focus=专注，tasks=任务，dreams=梦想，life=生活，journal=日记，media=媒体，growth=成长；默认 today", "today", "recent", "status", "focus", "tasks", "dreams", "life", "journal", "media", "growth"),
               "days": field("integer", "recent 查询天数，默认 7", minimum=1, maximum=30),
               "limit": field("integer", "journal 查询条数，默认 20", minimum=1, maximum=100)}
    branches.append({"type": "object", "title": "context", "description": "operation=context 或兼容 context.*；查询用 view，不用 action",
                     "properties": context, "additionalProperties": False})
    branches.append(variant("journal", "operation=journal；默认 read；create 必须 content；update 必须 id",
                            ("read", "create", "update"), {"id": ident, "content": field("string", "日记正文"),
                            "occurredAt": instant("日记对应的发生时间"), "images": images,
                            "tags": field("array", "标签", items={"type": "string"}), "limit": context["limit"]}))
    branches.append(variant("focus", "operation=focus；默认 current；manual 用 startedAt/endedAt 补录；pause/resume/complete/interrupt/switch_segment/update_segment 必须 id；update_segment 还需 segmentId",
                            ("current", "today", "history", "start", "pause", "resume", "complete", "interrupt", "switch_segment", "update_segment", "manual"),
                            {"id": ident, "segmentId": ident, "title": field("string", "专注/片段标题"), "note": note,
                             "mode": choice("专注模式：IRON_CURTAIN=铁幕，POMODORO=番茄钟，FREE=自由；start 默认 IRON_CURTAIN", "IRON_CURTAIN", "POMODORO", "FREE"),
                             "type": choice("片段类型：FOCUS=专注，BREAK=休息，INTERRUPTION=中断；仅用于切换/更新片段", "FOCUS", "BREAK", "INTERRUPTION"),
                             "taskId": field("string", "本次专注关联的任务 id"), "relatedTaskId": field("string", "当前专注片段关联的任务 id"),
                             "relatedTaskIds": field("array", "关联任务 id 数组", items={"type": "string"}),
                             "plannedMinutes": field("integer", "计划专注时长（分钟）", minimum=0),
                             "breakMinutes": field("integer", "计划休息时长（分钟）", minimum=0),
                             "startedAt": instant("补录开始时间"), "endedAt": instant("补录结束时间"),
                             "limit": field("integer", "history 条数，默认 30", minimum=1)}))
    branches.append(variant("task", "operation=task；默认 list；其他动作必须 source/taskId；link_direction 提供方向关联 id",
                            ("list", "complete", "link_direction", "unlink_direction"),
                            {"source": choice("任务来自每日任务 daily 或特殊任务 special", "daily", "special"),
                             "taskId": field("string", "今日任务实例 id；先用 task/list 查询"),
                             "dreamId": field("string", "关联的 Dream id"), "goalId": field("string", "关联的 Goal id"),
                             "dreamMilestoneId": field("string", "关联的梦想 Milestone id")}))
    branches.append(variant("ritual", "operation=ritual；默认 list；start/get 的 id 是仪式定义 id，get_execution/step/complete/cancel 的 id 是执行 id；step 还需 stepId",
                            ("list", "get", "start", "get_execution", "step", "complete", "cancel"),
                            {"id": ident, "stepId": ident, "done": field("boolean", "片段是否完成"), "note": note}))
    branches.append(variant("dream", "operation=dream；默认 list；其他动作需 id；complete_goal 的 id 是 Goal id，complete_milestone 是 Milestone id",
                            ("list", "get", "complete_goal", "complete_milestone", "pause", "resume"), {"id": ident}))
    media = {"type": choice("媒体资源类别", "anime", "game", "item", "anime_session", "game_session"),
             "id": ident, "parentId": field("string", "Session 的父级 anime/game id；Session list/get/create/update 都需提供"),
             "mediaType": choice("item 的作品类型：BOOK=书籍，MANGA=漫画，MOVIE=电影，OTHER=其他；arguments.type 仍填 item", "BOOK", "MANGA", "MOVIE", "OTHER"),
             "title": field("string", "作品标题，创建作品必填"), "note": note,
             "status": choice("作品状态：PLANNED=计划，WATCHING/PLAYING/IN_PROGRESS=进行中（依次用于 anime/game/item），PAUSED=暂停，COMPLETED=完成，DROPPED=放弃", "PLANNED", "WATCHING", "PLAYING", "IN_PROGRESS", "PAUSED", "COMPLETED", "DROPPED"),
             "score": field("integer", "作品评分（不是饮食满意度）", minimum=0, maximum=10),
             "platform": field("string", "游戏平台"), "coverImage": field("string", "作品封面路径"),
             "progress": field("string", "游戏 Session 进度描述"),
             **{name: field("integer", description, minimum=0) for name, description in {
                 "totalEpisodes": "番剧总集数", "currentEpisode": "番剧当前看到第几集",
                 "episodeStart": "本次观看起始集数", "episodeEnd": "本次观看结束集数",
                 "basePlayTimeMinutes": "游戏在开始使用 LifeHUD 前已有的游玩时长（分钟），不填本次时长",
                 "durationMinutes": "本次观看/游玩的时长（分钟）"}.items()},
             **{name: instant(description) for name, description in {
                 "startedAt": "开始观看/游玩作品的时间", "finishedAt": "完成作品的时间",
                 "watchedAt": "本次观看番剧的发生时间", "startTime": "本次游戏开始时间",
                 "endTime": "本次游戏结束时间"}.items()}}
    branches.append(variant("media", "operation=media；默认 list；get/update 必须 id；仅传对应资源的字段；totalPlayTimeMinutes 为服务派生值，不传",
                            ("list", "get", "create", "update"), media, ("type",)))
    branches.append({"type": "object", "title": "legacy focus", "description": "仅兼容 operation=focus.start/focus.complete；新调用优先用 focus 和 action",
                     "properties": {"title": field("string", "focus.start 必填"), "related_task_ids": field("array", "旧版关联任务", items={"type": "string"}),
                                    "session_id": ident, "note": note}, "additionalProperties": False})
    return {"description": "按 operation 选择对应参数分支；所有业务字段直接放在 arguments，不能再嵌套 data/body。仅传已有事实，未知值省略。",
            "anyOf": branches}


def input_hint(operation: str, payload: dict) -> dict:
    branches = arguments_schema()["anyOf"]
    if operation == "record":
        selected = next((branch for branch in branches if branch["title"] == "record." + str(payload.get("type"))), None)
        return {"allowed_types": list(RECORD_PATHS), "allowed_actions": ["list", "get", "create", "update"],
                "fields": selected["properties"] if selected else {}, "example": deepcopy(MEAL_EXAMPLE),
                "instruction": "按字段说明修正参数；不要向用户索取工具字段名。"}
    if operation.startswith("context."):
        operation = "context"
    elif operation.startswith("focus."):
        operation = "legacy focus"
    return {"arguments_schema": next((branch for branch in branches if branch["title"] == operation), {}),
            "instruction": "按字段说明修正参数；不要向用户索取工具字段名。"}
