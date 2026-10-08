# 失败气泡重生成误绑 Heartbeat 主动消息

日期：2026-10-07。用户截图显示 22:22 的输入收到 HTTP 400 失败气泡，点击重生成却提示“只能重新生成当前最后一条普通回复”。

## 证据与根因

请求 `83dde4fc-c1a4-4995-950a-3dd6c793f2f7` 于 22:23:06.971 记录 provider_http_400。只读查看 22:23:06.995 保存的 local 会话：没有本次失败输入，最近用户消息仍在 22:05；末尾是 22:08 和 22:14 的两条 Heartbeat 主动投递，带 delivery_id。

失败模型路径可能在保存用户消息前抛错，Gateway 原有异常处理只保存模型已经加入的消息，未补留接收输入。前端错误气泡又从 /api/session 取最后一个 user/assistant 作为按钮目标，实际绑定到 22:14 的 Heartbeat。后端正确拒绝对主动投递进行普通回复重生成；不是隐藏工具回复占位，真正错误是失败输入缺失和按钮错绑。

## 修复

Gateway 聊天异常处理检查本轮是否已加入 USER；若未加入，补留原输入及图片，并保存本轮 request_id 与显示分段。已经接受的输入不会重复加入。用户消息的会话视图提供 request_id，前端失败按钮只查找本次 request_id 对应的用户消息。没有匹配项时不提供误导性的旧消息重试目标。

重生成保留原有最后一轮、主动投递和权限保护。工具完成后的恢复继续只补回复，成功写入不重放。正常重生成仍保留原用户消息 ID、时间与元数据。

## 验证与历史边界

Interfaces 与 Decision Awareness **109 项通过**；隔离 Node 前端测试 **2 项通过**。新增后端覆盖模型在接受输入前/后失败，两种情形均只保留一个输入，并可在旧 Heartbeat 后重生成当前请求。前端直接运行真实错误按钮函数，覆盖尾部主动消息不得抢占目标、当前请求缺失不得绑定历史 user/assistant。

```powershell
.venv/Scripts/python.exe -B -X utf8 -m pytest tests/interfaces tests/decision/test_decision_awareness.py -q -o addopts= -x --tb=short --basetemp=.pytest_cache/tmp-retry-ghost
& 'C:/Program Files/nodejs/node.exe' --test tests/web/retry_target.test.cjs
```

[脱敏证据](evidence/2026-10-07-retry-ghost-delivery.json) 不包含聊天正文。未修改正式会话数据库、重放输入、调用真实模型、外发或重启。当前历史失败输入未存入 local 会话，修复不会自动恢复该记录，需要重新发送；完全退出托盘再启动后加载新后端，页面刷新加载新前端。HTTP 400 的上游原因属于另一个问题，本记录没有将其判为已解决。
