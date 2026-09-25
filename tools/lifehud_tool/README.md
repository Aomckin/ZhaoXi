# LifeHUD Tool 2.0 — Living I/O

First-party Zhaoxi adapter for reading and writing Life HUD facts, including contextual queries, life records, image attachments, Focus, tasks, journals, media, rituals and dreams. It registers **one** Tool, `lifehud`, and uses only Life HUD's public API. It never edits Life HUD storage directly.

## Enablement

Set `ZHAOXI_TOOL_LIFEHUD_ENABLED=true`. These package configuration keys accept `true` or `false` and default to enabled after the package itself is enabled:

| Environment variable | Capability |
| --- | --- |
| `ZHAOXI_TOOL_LIFEHUD_CONTEXT_ENABLED` | Agent Context reads |
| `ZHAOXI_TOOL_LIFEHUD_WRITE_ENABLED` | Business writes |
| `ZHAOXI_TOOL_LIFEHUD_IMAGE_ENABLED` | New image uploads |
| `ZHAOXI_TOOL_LIFEHUD_FOCUS_ENABLED` | Focus operations |
| `ZHAOXI_TOOL_LIFEHUD_MEDIA_ENABLED` | Media operations |
| `ZHAOXI_TOOL_LIFEHUD_DREAM_ENABLED` | Dream operations |
| `ZHAOXI_TOOL_LIFEHUD_RITUAL_ENABLED` | Ritual operations |

### On-demand Life HUD startup

For the local `http://127.0.0.1:8025` (or `localhost:8025`) server, the package probes `GET /api/agent/context/status` before its first API request. Local requests connect directly and ignore HTTP proxy environment variables. A healthy response continues immediately. A refused TCP connection or connect timeout starts Life HUD in the background using the project's Maven Wrapper and `spring-boot:run`; the Tool checks readiness every 400 ms for up to 8 seconds. A health response read timeout triggers a direct TCP port check, and startup occurs only if the port is also unreachable. The Tool then continues the original request. If the connection fails between the probe and the request, the Tool probes again, starts Life HUD if still needed, and retries the original request once. Read timeouts on the original request, HTTP errors and other network failures do not trigger a blind write retry.

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `ZHAOXI_TOOL_LIFEHUD_AUTOSTART_ENABLED` | `true` | Turn on local, on-demand startup |
| `ZHAOXI_TOOL_LIFEHUD_PROJECT_DIR` | Sibling `Life HUD` directory | Maven Wrapper project root |
| `ZHAOXI_TOOL_LIFEHUD_STARTUP_TIMEOUT_SECONDS` | `8` | Maximum readiness wait |
| `ZHAOXI_TOOL_LIFEHUD_STARTUP_POLL_SECONDS` | `0.4` | Readiness check interval |

Startup process output goes to `data/logs/lifehud-autostart.log` under Zhaoxi's working directory. A missing Wrapper, early process exit or readiness timeout returns a distinct Tool error. Custom or remote Life HUD URLs are queried normally and do not launch the local project.

The package retains its existing surface switches such as `*_WORKFLOW_ENABLED` and `*_PROACTIVE_ENABLED`. Capability group flags are loaded when the package is created and can be changed live in the Debug Tool cabinet.

## Tool schema

`operation` is closed to `context`, `record`, `journal`, `focus`, `task`, `ritual`, `media`, `dream`, plus the previous `context.*` and `focus.start`/`focus.complete` values for compatibility. Business parameters go in `arguments`; flat fields are also accepted at runtime.

| Operation | Actions / fields |
| --- | --- |
| `context` | `view=today` (default), `recent`, `status`, `focus`, `tasks`, `dreams`, `life`, `journal`, `media`, `growth`; `days` 1–30, `limit` 1–100 |
| `record` | `action=list|get|create|update`, `type=sleep|meal|exercise|check_in|life_record`; `id` for get/update |
| `journal` | `action=read|create|update`; `content`, `occurredAt`, `tags`, `images` |
| `focus` | `current|today|history|start|pause|resume|switch_segment|update_segment|complete|interrupt|manual` |
| `task` | `list|complete|link_direction|unlink_direction` |
| `ritual` | `list|get|start|get_execution|step|complete|cancel` |
| `media` | `list|get|create|update`; `type=anime|game|item|anime_session|game_session` |
| `dream` | `list|get|complete_goal|complete_milestone|pause|resume` |

For sleep, use `sleepType` for Life HUD's `type` field. For exercise, use `exerciseType`. For a generic life record, use `recordType` (`WATER`, `CAFFEINE`, `ALCOHOL`, `SUNLIGHT`, `SOCIAL`, `BODY_STATUS`, `OUTDOOR`, `CUSTOM`). For media `item`, use `mediaType`; Session creation requires `parentId`. Instant fields must be ISO-8601 with a timezone offset or `Z`. The Planner resolves natural-language times; the Tool checks their format.

Example:

```json
{"operation":"record","arguments":{"action":"create","type":"meal","mealType":"DINNER","time":"2026-09-24T19:00:00+08:00","description":"辣椒炒肉和米饭","images":["<current-message-image>"]}}
```

### Images and attachments

`images` accepts already uploaded `/uploads/...` paths, absolute local image paths readable by the Zhaoxi process, or PNG/JPEG/WebP/GIF base64 data URLs. The Tool validates files, limits each to 64 MB, uploads in order to `POST /api/images`, then writes the returned paths into the business record. Life HUD deduplicates identical image bytes using SHA-256. If any image fails, no business record is created. If images uploaded but the business write fails, the result includes `image_uploaded_but_record_failed`.

For a photo in the current user message, use `<current-message-image>` for the first image or `<current-message-image:2>` for the second (1-based index). The Agent passes these attachments to the Tool outside model-generated arguments and audit logs; the Tool uploads the original bytes. A caller may also pass a readable path or data URL. The parent's Tool argument limit is 50,000 characters, so ordinary photos should use the placeholder or a path.

Omitting `images` on update leaves existing images untouched; `images: null` also preserves them; `images: []` removes them. The Tool does no visual recognition. The multimodal model supplies descriptions and measured values.

## Permissions and reliability

Context and other reads need no confirmation. Ordinary writes are classified `WRITE`; the package defaults to allowing them once the Planner chooses a recordable user fact. The Planner must not infer numeric Check-in values from tone or ordinary chat. Deletes and purge are not in the allowed action routers. The Tool never exposes Growth/EXP/Level/achievement administration. The Debug Tool cabinet can switch capability groups immediately; overrides persist across restarts and Reset restores environment defaults.

Every business write is followed by a GET of the item or corresponding collection/context. The Tool returns structured `ok`, `operation`, `action`, `resource`, `data`, and `warnings` fields. `GET` may use bounded retries. Creates and other writes are sent once; a timeout returns an uncertain failure and requires querying before another create. `400`, `404`, and `409` are not retried. Image upload is content-deduplicated by Life HUD, but the business create following it is not.

Existing iron-curtain workflow calls and background Context sampling remain compatible. When Life HUD is unreachable, background sampling retains its 2, 5, 15, and 30 minute backoff.
