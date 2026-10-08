# 多轮模型调试仍在第三轮收口：工具额度修复

日期：2026-10-06。用户开启“允许多轮模型调用”，但第二轮 LifeHUD 查询成功后，第三轮仍记录“本轮停止新操作，整理已有结果”。

## 日志与根因

`.zhaoxi/logs/zhaoxi.log` 请求 `5b29ad1c-7b91-4eb9-8e52-5d54aba7d29e`：19:53:26 已启用调试，日志 `model_limit=8`；19:53:50 在第三轮前出现 `forced_finalization`，原因 `round_limit`。前台最终指标为模型三轮、工具两轮，预算状态 NORMAL，剩余比例 0.584775。截图的 agent #2 10774.23 ms、LifeHUD 536.13 ms、agent #3 36017.01 ms 与该请求完全对应。

开关已经生效，但原实现只将 `LoopSafety.model_limit` 放宽至总步数，`tool_limit` 仍为默认 2。第三轮满足工具次数限制条件，删去工具 schema，因而只能生成回复。此前回归覆盖了多次能力目录调用，却没有覆盖第三、第四次真实业务工具调用，这是实现与测试遗漏。

## 修复与最终含义

开启后同时将模型轮数上限设为 `max_steps`，业务工具轮数上限设为 `max_steps - 1`。默认八步即最多八轮模型、七轮业务工具，最后一步只整理结果；模型可以提前完成，并非必须用完八轮。关闭后仍沿用 Settings 的模型/工具上限，默认三轮模型、两轮工具。

配置在请求开始时形成 LoopSafety 快照，处理中切换开关不会改变已有请求。调试日志同时记录实际 `model_limit` 和 `tool_limit`。总步数、Provider 调用数、Token、收尾预留、整轮时限、权限确认、失败锁定、修复额度、无进展和未知写入保护保持原逻辑；它们仍可能提前结束请求。

## 验证

专项 **99 项通过**，覆盖 LoopSafety、FAST 升级、Debug 设置和 Agent 集成。新增回归在普通 STANDARD 与 FAST 升级路径分别连续执行四轮业务工具，第五步保留工具为空并拒绝模型继续操作；开关开启/关闭均验证重复工具失败仍强制收口。原有预算、权限、默认额度与请求快照回归继续通过。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m pytest tests/core/test_loop_safety.py tests/cognitive/test_fast_escalation.py tests/web/test_quick_debug.py tests/integration/test_agent.py -q -x --tb=short --basetemp=.pytest_cache/tmp-multi-round-tool-fix
```

未调用真实模型、重跑 LifeHUD 业务或重启正式实例。需完全退出托盘后重新启动加载本次 Python 修复；保存的调试开关继续保留。[结构化证据](evidence/2026-10-06-multi-round-tool-limit.json)。
