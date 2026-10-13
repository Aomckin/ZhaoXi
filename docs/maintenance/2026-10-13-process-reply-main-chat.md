# 过程回复进入主聊天区

日期：2026-10-13。对应 V149-13。

## 排查结论

截图中 09:53 的“模型返回了过程回复”来自 Router。只读运行记录确认该调用只返回路由工具调用，`process_text` 为空，没有可显示的过程正文；后续 Agent 调用才给出最终回复。原观测层把所有非最终成功调用都发成过程回复事件，造成空正文也显示提示。

朝汐已有工具行动台词和中间回复通道。Provider 可以在工具续办元数据里保留 `reasoning_content`，但没有独立的 MaiBot 式思考回复发布模块。本补丁不读取或展示隐藏思考，也不额外生成思考正文。

## 修改结果

- 空正文仍计入调用和 Token 统计，停止发送“返回了过程回复”事件。Router 等非聊天调用有正文时标为“调用说明”，只用于行动记录。
- Agent / Planner 的可公开过程正文复用已有 `interim_reply` 通道，出现在主聊天区。真正返回的行动台词和过程正文不再等待长任务时间阈值；关闭开关、次数上限、180 字限制、协议内容过滤与重复检查继续生效。
- 回复协议成功解码后，只把自然 `reply` 正文交给过程通道，避免把 awareness 外壳发送到主聊天区。拒绝草稿和最终回复继续沿用原处理。
- 同一句行动台词已发送时，不因下一轮确认它是非最终调用而重复发送。主界面按请求及序号去重，拒绝旧请求和结束后的事件；旁观当前请求的主窗口可以显示过程正文，工程监控页不生成聊天气泡。
- 过程气泡仍是临时呈现，不写 Session、Memory 或 CurrentCognition；不增加模型调用或工具副作用。

## 验收

相关 Python 回归 715 项通过（1 条现有序列化警告），前端全量 117 项通过。隔离 Edge 浏览器 19 项检查通过，确认过程正文在最终回复前进入主聊天区、最终回复后无重复、监控页无聊天气泡；截图已目视检查，页面错误为 0。使用假 Provider，无真实模型调用或 QQ 发送。见 [验收证据](evidence/2026-10-13-process-reply-main-chat.json)。

运行命令：

```powershell
.venv\Scripts\python.exe -m pytest tests/observability tests/core tests/cognitive tests/cognitive_stream tests/interfaces tests/models tests/permission tests/planner tests/web -o addopts='' --basetemp=.pytest_cache/process-main-regression -q --tb=short
node --test (Get-ChildItem tests/web/*.test.cjs | ForEach-Object {$_.FullName})
node tests/web/action_trace_smoke.cjs
```

浏览器检查使用本地临时服务 9087，结束后已清理。正式 Core 未重启，未推送远端；需要重启 Core 并刷新界面加载。历史空事件不会被改写，过程气泡刷新后不作为持久聊天历史恢复。
