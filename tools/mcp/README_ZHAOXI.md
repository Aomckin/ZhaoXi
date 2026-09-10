# Zhaoxi MCP ToolProvider

This directory contains the installed MCP servers and the MCP-specific adapter.
Zhaoxi Core only sees protocol-neutral `ToolProvider` instances and ordinary
`Tool` objects; it does not import MCP modules.

Enable the MCP Tool Package (the default server set is `filesystem`,
`everything-search`, `fetch`, and `time`):

```env
ZHAOXI_TOOL_MCP_ENABLED=true
```

Select a different subset and adjust startup timeout:

```env
ZHAOXI_TOOL_MCP_SERVERS=filesystem,time
ZHAOXI_TOOL_MCP_TIMEOUT_SECONDS=20
```

Available server ids are `everything-search`, `reference-everything`,
`filesystem`, `memory`, `sequential-thinking`, `fetch`, `git`, `time`, and
`playwright`. `reference-everything`, `memory`, `git`, and
`sequential-thinking` are disabled by default. Playwright is controlled
independently with `MCP_PLAYWRIGHT_ENABLED=true` (or
`ZHAOXI_TOOL_MCP_PLAYWRIGHT_ENABLED=true`). It runs in `--extension` mode and
connects to an existing Chrome or Edge session, so the Playwright Extension must
already be installed in that browser.

Filesystem access never defaults to the Zhaoxi project root. Its default is the
isolated `tools/mcp/data/filesystem/` directory. Override it with a semicolon
separated list of existing directories:

```env
MCP_FILESYSTEM_ALLOWED_DIRS=D:\shared\inbox;D:\shared\exports
```

The default sandbox cannot reach project `src/`, `tools/`, `.env`, `.zhaoxi/`,
databases, credentials, tokens, or secret configuration. Do not configure a
broad ancestor directory that contains those resources.

Everything search requires the Everything service and `es.exe`. Configure an
explicit absolute path when needed; otherwise Zhaoxi probes standard Everything,
Scoop, and winget portable-package locations:

```env
MCP_EVERYTHING_ES_PATH=C:\Program Files\Everything\es.exe
```
