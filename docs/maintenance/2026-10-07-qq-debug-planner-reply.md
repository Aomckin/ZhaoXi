# QQ 群聊 @ 不回复：外部 Planner 失败兜底

日期：2026-10-07。用户报告 Debug 开启禁用 FAST_CHAT 后 QQ 无回复，并确认发生于群聊 @ 朝汐。

## 今晚日志与判断

只读检查日志和感知数据库：20:40:32.536930 收到一条 QQ Owner 群聊消息，包含 mention/text；该观察记录为 FAILED。20:41:34.945 日志记录 `PERCEPTION direct failed type=TimeoutError`。本路径的外部 Planner 受 60 秒 wait_for 限制，异常直接进入 ingest 总异常处理并返回 None，因而没有生成可发送的回复。

群聊本来不符合 FAST_CHAT 的 Owner 私聊文本条件；禁用 FAST_CHAT 开关不改变群聊路由。检查时保存的开关已为 false，日志也未记录当时开关快照，因此不能将超时归因于该开关。代码可确认的是 Planner 超时会丢失 Owner 定向回复；用户报告的开关状态用于新增群聊回归场景。

此外，Owner 私聊文本在禁用 FAST_CHAT 时跳过快捷门控，却重新经过外部 Planner 的回复准入；原有 Debug 回归关闭了 external_cognition_enabled，没有覆盖正式开启外部认知的情形。

## 修复

- Owner 私聊文本在强制非 FAST_CHAT 时直接进入标准频道回复，不额外经过 Planner 准入。只选择通道，不开放业务写入或外部行动权限。
- Owner 定向消息的外部 Planner 超时、ProviderError 与已有 JSON/校验错误统一降级到标准频道回复；不应用失败 Planner 的认知或记忆候选。日志明确标记 `direct planner failed ... fallback=owner_reply`，区别于回复阶段失败。
- 群聊仍经过 Planner，正常返回 reply=false 时继续不回复。非 Owner 回复守卫、冷却规则、外部输出边界和标准模型失败处理保持现有逻辑。Planner 60 秒等待上限没有缩短，降级不保证上游模型服务持续可用。

## 验证与边界

感知、FAST 升级与 Debug 专项 **74 项通过**。新增覆盖 private/group 的 Planner TimeoutError 与 ProviderError 仍交付标准受限回复、不应用候选、观察转为 PROCESSED；群聊用例明确开启强制非 FAST_CHAT。更新 Debug 私聊回归为 external_cognition_enabled=true，并证明无需 Planner 调用。另验证禁用 FAST_CHAT 的群聊仍尊重 Planner 的正常不回复决策。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m pytest tests/perception tests/cognitive/test_fast_escalation.py tests/web/test_quick_debug.py -q -o addopts= -x --tb=short --basetemp=.pytest_cache/tmp-qq-debug-standard-final
```

[脱敏证据](evidence/2026-10-07-qq-debug-planner-reply.json) 不包含账号、群号或消息正文。未修改正式数据库、重放生产消息、调用真实模型、外发 QQ 或重启正式实例。修复需完全退出托盘再启动加载；没有实际 QQ 服务验收，源码尚未提交。
