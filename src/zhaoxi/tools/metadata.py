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
    # Built-in developer utility. It is intentionally absent from normal turns.
    "echo": ("echo",),
}


GROUP_LABELS = {"memory_core": "长期记忆：记录、更新、检索", "memory_search": "记忆检索", "memory_admin": "记忆管理", "archive": "潮庭档案", "local_search": "本地文件搜索", "filesystem_read": "读取文件与目录", "filesystem_write": "修改文件与目录", "web": "网页读取", "time": "时间与时区", "calculator": "计算", "lifehud": "Life HUD", "debug": "钥匙柜查询与能力发现"}

TOOL_GROUPS["memory_core"] = ("remember_memory", "update_memory", "search_memories")
TOOL_GROUPS["debug"] = ("request_tool_group", "inspect_tool_catalog")
