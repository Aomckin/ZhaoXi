# LifeHUD-Tool

Independent first-party Tool package for the read-only Life HUD Agent Context API and the explicitly permissioned Focus start/complete API.

Zhaoxi registers exactly one Tool named `lifehud`. Its closed `operation` enum selects the supported capability. This package never reads or modifies Life HUD internal files or databases.

The package targets public Zhaoxi SDK `>=1,<2` and explicitly declares Tool, Workflow, Router Hint, Proactive, Reflection, and State Signal capabilities. Packages are discovered but disabled by default; set `ZHAOXI_TOOL_LIFEHUD_ENABLED=true` to activate this package. Each surface can then be disabled independently with `ZHAOXI_TOOL_LIFEHUD_*_ENABLED`; disabling the package performs no Life HUD network access.

When Life HUD is unreachable, background sampling backs off through 2, 5, 15, and 30 minute intervals and automatically resumes after a successful sample.
