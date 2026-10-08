# LifeHUD 参数 JSON 泄露到最终回复

日期：2026-10-06。

## 日志与根因

请求 `ca3599c0-5cb6-4fa8-8ccd-6eaab78128d1` 于 19:59:04 开始，两轮 LifeHUD 工具执行后，19:59:41 第三轮进入 `round_limit` 收口，工具 schema 被移除。第三轮模型于 20:00:01 返回，`tool_call_count=0`、`finish_reason=stop`，主回复协议日志却记录 `encoding=text`、正文 231 字符、`status=decoded`。与截图的裸 `operation/arguments` 对象对应。

模型把计划中的操作参数写进 content；主回复解码器兼容普通文本/JSON，对没有 reply、awareness 或 escalation 字段的对象直接放行，导致内部工具参数进入用户气泡。不是前端把原生工具结果当正文渲染。截图这段对象没有作为原生工具调用执行；前两次工具成功不代表对象中拟议的餐食创建成功，此次没有重放或查询正式业务数据。

这轮仍在第三轮提前收口，与此前工具额度未同步放宽的日志一致。该额度修复见 [多轮调试工具额度修复](2026-10-06-multi-round-tool-limit.md)，需要完全退出托盘后重启加载。

## 修复行为

在主回复协议解码器中，拒绝没有 reply 字段、包含字符串 operation 或 name 加对象 arguments 的裸工具动作封套，记录 `encoding=tool_arguments`、`invalid_reply_protocol`。不推断工具名、不把 JSON 转为工具调用，也不执行其中拟议的写入。

复用已有无正文恢复：工具执行后、预算和轮次允许时最多补一次无工具的回复；若已进入收口，则返回已确认工具结果及正文失败提醒。正常 JSON 值与数据对象继续兼容；需要向用户展示工具 JSON 示例时，可作为 reply 字符串的内容返回。此次校验位于 owner 的主回复协议路径，不改其他协议或工具执行器。

收口提示同时明确工具参数不能替代正文，JSON 示例应放在 reply 字段内。校验在模型输出进入回复提交前进行，因此被拒绝的原始对象不写入 assistant 会话消息。

## 验证与边界

专项 **159 项通过**，范围为 LoopSafety、Decision Awareness、FAST 升级、Agent 集成。新增回归覆盖裸对象/JSON 代码块、仅补回复/最终结果兜底两条路径、已成功工具只执行一次、错误对象不进入会话，以及普通 JSON 和 reply 内 JSON 示例兼容。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m pytest tests/core/test_loop_safety.py tests/decision/test_decision_awareness.py tests/cognitive/test_fast_escalation.py tests/integration/test_agent.py -q -x --tb=short --basetemp=.pytest_cache/tmp-reply-tool-json
```

[脱敏结构化证据](evidence/2026-10-06-tool-arguments-reply.json) 仅保留协议、次数与时序，不复制照片、餐食内容或完整会话。未调用真实模型、重放 LifeHUD、修改历史气泡或重启正式实例；源码修复需完全退出托盘后重新启动，正式服务验收仍未执行。
