# 正文后追加主回复 JSON：混合输出校验

日期：2026-10-06。后续于 20:43 发起的对话出现正常正文后重复显示 reply/awareness JSON。

## 证据与根因

日志请求 `ad3bde32-f329-4a86-8f59-906153685040` 于 20:44:14.997 记录主回复 `encoding=text`、输入/正文均 544 字符、awareness 缺失并成功交付。以只读 SQLite 连接检查该时刻的会话 raw_reply：完整 reply/awareness/escalation 对象起于第 168 个字符，其 reply 有 166 字符；前缀去除首尾空白后与 reply 完全一致，对象后没有其他内容。

因此模型输出了“自然正文 + 重复正文的协议对象”。整段不满足 json.loads，既有异常分支只恢复以左花括号开头的协议，对带正文前缀的内容按普通文本放行。之后正常的分段处理把 JSON 拆成多个气泡，产生截图中的泄露与重复。这与 [裸工具参数问题](2026-10-06-tool-arguments-reply.md) 是同一解码边界上的另一种返回形状。

## 修复

整段 JSON 解析失败时，识别带 reply 与 awareness/escalation 的完整尾部对象。仅当前缀与对象的 reply 去除首尾空白后完全一致、对象后没有其他内容时，按 `mixed_json` 解码，沿用原来的正文与 awareness 处理，只交付一次正文。

前缀不一致、尾部夹杂内容或识别到不完整混合协议时，以 invalid_reply_protocol 拒绝，复用既有失败/仅补回复机制，不猜测哪一段内容才正确。普通 JSON、纯文本、已有截断协议恢复逻辑，以及放在有效 reply 字符串内的 JSON 示例保持原行为。已保存的历史气泡不自动修改。

## 验证

专项 **165 项通过**：LoopSafety、Decision Awareness、FAST 升级与 Agent 集成。新增回归覆盖 STANDARD / FAST 都只交付一次正文、awareness 正常解码、冲突/截断/尾部杂质拒绝，以及 reply 内完整协议示例仍能显示。对上述正式会话 raw_reply 进行只读离线解码，结果与对象中的 reply 完全一致，正文 166 字符，awareness 有效、mode NONE。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m pytest tests/core/test_loop_safety.py tests/decision/test_decision_awareness.py tests/cognitive/test_fast_escalation.py tests/integration/test_agent.py -q -x --tb=short --basetemp=.pytest_cache/tmp-mixed-reply-protocol
```

[脱敏证据](evidence/2026-10-06-mixed-reply-protocol.json) 仅包含尺寸、协议与匹配结果，不复制用户正文。没有真实模型请求、业务重放、数据库修改或正式重启。需完全退出托盘后重新启动加载；正式服务验收尚未执行。
