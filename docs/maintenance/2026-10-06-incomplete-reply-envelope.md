# 正常 stop 下的残缺主回复

日期：2026-10-06。

## 已确认的证据

用户截图中的回复停在半句话。只读检查正式 session.db，最后回复的 content 和 raw_reply 都是同一段短文本，因此不是网页裁剪或气泡分段显示造成。

重新生成请求 `d26b1da4-8e66-408d-8061-1f73e2767827` 在 21:11:16 的日志记录：provider finish_reason=stop，output_tokens=1320；主回复 encoding=json、input_chars=341、body_chars=17、awareness=missing，却以 decoded 成功交付。原始 JSON 对象没有留存，不能确定其余内容的字段或模型为何提前结束，也不能恢复丢失的正文。Token 总量包含协议和可能的推理，不能据此推算完整正文长度。

## 修复边界

OpenAI Compatible Provider 在请求 main_reply schema 时，将该契约标记随 ModelResponse 传递；DeepSeek 将 schema 降级为 json_object 时仍保留此标记。

解码器对带此契约的主回复对象检查必填 awareness 非空、没有未知顶层字段，并拒绝残缺 JSON，避免从异常对象中单独截取 reply 后将其成功保存。普通兼容输出及未请求此契约的旧调用沿用既有行为；完整有效短回复不会因字数少而被拒绝。

无工具调用的最终返回若 finish_reason 为 length、max_tokens 或 content_filter，也按 invalid_reply_protocol 拒绝。存在工具调用时保持工具处理路径。

复用现有 bounded recovery：工具结果已完成且有普通轮次时，只补一次回复、禁止再次执行业务工具；已经进入 final-only 时显示明确的正文失败提示并保留结果。没有修改正式会话、重放业务操作或调用真实模型。当前进程需完全退出托盘再启动才能加载修复；正式运行验收未执行。

## 验证

214 项测试通过，包含模拟 HTTP provider 在 stop 下返回缺少 awareness 的主回复、DeepSeek JSON mode 降级后的契约保留、未知字段与残缺 JSON 拒绝、长度耗尽拒绝、有效两字符短回复接受，以及工具后恢复和 final-only 失败分支不保存半句、不重复调用工具。

```powershell
.venv/Scripts/python.exe -m pytest tests/decision/test_reply_completeness.py tests/decision/test_decision_awareness.py tests/models/test_openai_compatible.py tests/core/test_loop_safety.py tests/cognitive/test_fast_escalation.py tests/integration/test_agent.py -o addopts='' --basetemp=.pytest_cache/reply-completeness-final -q --tb=short
```

[脱敏证据](evidence/2026-10-06-incomplete-reply-envelope.json)。
