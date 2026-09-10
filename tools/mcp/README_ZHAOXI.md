# Zhaoxi MCP ToolProvider

This directory contains the installed MCP servers and the MCP-specific adapter.
Zhaoxi Core only sees protocol-neutral `ToolProvider` instances and ordinary
`Tool` objects; it does not import MCP modules.

Enable all installed servers:

```env
ZHAOXI_TOOL_MCP_ENABLED=true
```

Select a subset and adjust startup timeout:

```env
ZHAOXI_TOOL_MCP_SERVERS=filesystem,time,playwright
ZHAOXI_TOOL_MCP_TIMEOUT_SECONDS=20
```

Available server ids are `everything-search`, `reference-everything`,
`filesystem`, `memory`, `sequential-thinking`, `fetch`, `git`, `time`, and
`playwright`. Filesystem access defaults to the Zhaoxi process working directory.
The Everything search server additionally requires the Everything service and
`es.exe`. Zhaoxi resolves `ES_PATH`, standard Everything locations, Scoop, and
winget portable-package installs automatically.
