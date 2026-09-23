"""Default metadata for existing tools; new tools may declare their own metadata."""

PERSISTENT_CORE = ("remember_memory", "update_memory", "search_memories", "request_tool_group", "inspect_tool_catalog")

TOOL_GROUPS: dict[str, tuple[str, ...]] = {
    "memory_search": ("search_memories",),
    "memory_admin": (
        "pin_memory", "forget_memory", "archive_memory",
        "reactivate_memory", "consolidate_memories",
    ),
    "archive": ("archive_search", "archive_list_documents", "archive_read"),
    "local_search": ("mcp_everything-search_search", "mcp_everything-search_get_file_info"),
    "filesystem_read": (
        "mcp_filesystem_read_text_file", "mcp_filesystem_read_file",
        "mcp_filesystem_read_multiple_files", "mcp_filesystem_read_media_file",
        "mcp_filesystem_get_file_info", "mcp_filesystem_list_directory",
        "mcp_filesystem_list_directory_with_sizes", "mcp_filesystem_directory_tree",
        "mcp_filesystem_search_files", "mcp_filesystem_list_allowed_directories",
    ),
    "filesystem_write": (
        "mcp_filesystem_write_file", "mcp_filesystem_edit_file",
        "mcp_filesystem_create_directory", "mcp_filesystem_move_file",
    ),
    "web": ("mcp_fetch_fetch",),
    "time": ("current_time", "mcp_time_get_current_time", "mcp_time_convert_time"),
    "calculator": ("calculator",),
    "lifehud": ("lifehud",),
    "expression": ("save_emoji",),
    "agenda": ("agenda_add", "agenda_update", "agenda_complete", "agenda_cancel", "agenda_list", "agenda_snapshot"),
    "working_notes": ("notes_add", "notes_update", "notes_resolve", "notes_delete", "notes_list", "notes_snapshot"),
    # Built-in developer utility. It is intentionally absent from normal turns.
    "echo": ("echo",),
}


GROUP_LABELS = {"memory_core": "长期记忆：记录、更新、检索", "memory_search": "记忆检索", "memory_admin": "记忆管理", "archive": "潮庭档案", "local_search": "本地文件搜索", "filesystem_read": "读取文件与目录", "filesystem_write": "修改文件与目录", "web": "网页读取", "time": "时间与时区", "calculator": "计算", "lifehud": "Life HUD", "expression": "本地视觉表达", "agenda": "近期日程", "working_notes": "朝汐便签", "debug": "钥匙柜查询与能力发现"}

TOOL_LABELS = {
    "remember_memory": "记住信息", "update_memory": "更新记忆", "search_memories": "搜索记忆",
    "pin_memory": "固定记忆", "forget_memory": "忘记记忆", "archive_memory": "归档记忆",
    "reactivate_memory": "恢复记忆", "consolidate_memories": "整理记忆",
    "archive_list_documents": "列出档案", "archive_search": "搜索档案", "archive_read": "读取档案",
    "mcp_everything-search_search": "搜索本地文件", "mcp_everything-search_get_file_info": "查看文件信息",
    "mcp_filesystem_read_text_file": "读取文本文件", "mcp_filesystem_read_file": "读取文件",
    "mcp_filesystem_read_multiple_files": "批量读取文件", "mcp_filesystem_read_media_file": "读取媒体文件",
    "mcp_filesystem_get_file_info": "查看文件信息", "mcp_filesystem_list_directory": "列出目录",
    "mcp_filesystem_list_directory_with_sizes": "列出目录及大小", "mcp_filesystem_directory_tree": "查看目录树",
    "mcp_filesystem_search_files": "在目录中搜索", "mcp_filesystem_list_allowed_directories": "查看允许目录",
    "mcp_filesystem_write_file": "新建或覆盖文件", "mcp_filesystem_edit_file": "按内容编辑文件",
    "mcp_filesystem_create_directory": "新建目录", "mcp_filesystem_move_file": "移动或重命名",
    "mcp_fetch_fetch": "读取网页", "current_time": "获取当前时间",
    "mcp_time_get_current_time": "查询时区时间", "mcp_time_convert_time": "转换时区时间",
    "calculator": "计算表达式", "lifehud": "查询 Life HUD", "echo": "调试回显",
    "request_tool_group": "临时携带钥匙组", "inspect_tool_catalog": "查看钥匙目录",
    "save_emoji": "收藏会话图片",
    "agenda_add": "添加日程", "agenda_update": "修改日程", "agenda_complete": "完成日程",
    "agenda_cancel": "取消日程", "agenda_list": "查询日程", "agenda_snapshot": "查看日程快照",
    "notes_add": "添加便签", "notes_update": "更新便签", "notes_resolve": "解决便签",
    "notes_delete": "删除便签", "notes_list": "查询便签", "notes_snapshot": "查看便签快照",
}

TOOL_USAGE = {
    "remember_memory": "保存值得长期记住的信息。", "update_memory": "修正或补充已有记忆。",
    "search_memories": "按内容查找长期记忆。", "pin_memory": "让重要记忆保持活跃。",
    "forget_memory": "按用户要求忘记指定记忆。", "archive_memory": "把记忆移入归档状态。",
    "reactivate_memory": "重新启用已归档或休眠的记忆。", "consolidate_memories": "把相关记忆整理成更稳定的知识。",
    "archive_list_documents": "查看潮庭档案中的文档列表。", "archive_search": "在潮庭档案正文中搜索。",
    "archive_read": "读取指定档案内容。", "mcp_everything-search_search": "使用 Everything 快速查找本机文件。",
    "mcp_everything-search_get_file_info": "查看搜索结果的路径和文件属性。",
    "mcp_filesystem_read_text_file": "读取允许目录内的文本文件。", "mcp_filesystem_read_file": "读取允许目录内的文件。",
    "mcp_filesystem_read_multiple_files": "一次读取多个允许目录内的文件。", "mcp_filesystem_read_media_file": "读取允许目录内的图片或音频。",
    "mcp_filesystem_get_file_info": "查看文件或目录的大小、时间等属性。", "mcp_filesystem_list_directory": "查看目录中的文件和子目录。",
    "mcp_filesystem_list_directory_with_sizes": "列出目录内容并显示大小。", "mcp_filesystem_directory_tree": "生成目录层级结构。",
    "mcp_filesystem_search_files": "按名称在允许目录中搜索文件。", "mcp_filesystem_list_allowed_directories": "查看当前允许访问的目录。",
    "mcp_filesystem_write_file": "新建文件或完整覆盖已有文件。", "mcp_filesystem_edit_file": "按原文匹配并修改文本文件。",
    "mcp_filesystem_create_directory": "在允许目录内创建文件夹。", "mcp_filesystem_move_file": "移动文件或修改文件名。",
    "mcp_fetch_fetch": "获取网页正文供朝汐阅读。", "current_time": "获取本机当前日期和时间。",
    "mcp_time_get_current_time": "查询指定时区的当前时间。", "mcp_time_convert_time": "在两个时区之间换算时间。",
    "calculator": "进行可靠的数学计算。", "lifehud": "读取任务、专注、饮食、睡眠等 Life HUD 数据。",
    "echo": "原样返回输入，仅用于开发调试。", "request_tool_group": "按当前任务临时加载一组钥匙。",
    "inspect_tool_catalog": "查看当前有哪些钥匙组可用。",
    "save_emoji": "把用户明确指定的会话图片收藏到表情柜。",
    "agenda_add": "记录事件、时间窗口、截止、主线或期待。", "agenda_update": "调整已有近期日程。",
    "agenda_complete": "将近期事项标记完成。", "agenda_cancel": "取消近期事项。",
    "agenda_list": "查询近期日程及 ID。", "agenda_snapshot": "读取压缩日程上下文。",
    "notes_add": "保守记录持续工作的近期现场。", "notes_update": "更新已有工作便签。",
    "notes_resolve": "让已解决便签退出常驻上下文。", "notes_delete": "永久删除短期便签。",
    "notes_list": "查询工作便签及 ID。", "notes_snapshot": "读取压缩工作便签上下文。",
}

TOOL_GROUPS["memory_core"] = ("remember_memory", "update_memory", "search_memories")
TOOL_GROUPS["debug"] = ("request_tool_group", "inspect_tool_catalog")
