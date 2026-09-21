# Zhaoxi v1.2.4.2 表情发送稳定性审计报告

## 1. 最终根因

故障不是单点，而是两个彼此独立的断点叠加：

1. **执行契约断点**：CognitiveRouter 过去不知道运行时真实工具目录，也没有把“必须产生真实副作用”传给 Agent。于是某些轮次走 DIRECT，或进入 Agent 后模型只返回“已经发了”的文本，没有任何 `send_emoji` Tool Call。
2. **消息显示断点**：Tool 成功时会产生正文为空的独立图片消息；旧前端以文本分段数量决定是否创建节点，`text=""` 时没有节点。同时实时响应和历史恢复使用不同的数据整理/渲染路径，进一步造成“数据库里有、页面上没有”。桌面窗口继续持有旧静态资源时，会让已经修复的代码看起来仍未生效。
3. **Tool Choice 断点（真实桌面复测发现）**：12:34 的日志证明 Router 已正确返回 TOOL、`requires_tool_call=true`，且 `send_emoji` 已注册并暴露，但 DeepSeek 连续两次仍选择文本响应。仅靠 prompt 要求模型调用工具并不能构成执行保证。Router 现会同时返回经过运行时目录校验的 `required_tool`；Agent 对该请求使用 provider 的强制 function choice。若 Router 未指定具体工具，重试也使用 `tool_choice=required`，不再只是重复提示词。

因此第一次能成功，是因为当轮模型恰好调用了 Tool，且在刷新后的正确渲染路径上显示；后来失败则可能分别断在路由/执行层或纯图片渲染层。现在用运行时能力目录、通用执行契约、结构化 Tool 结果、统一消息模型和统一 Renderer 把这些偶然条件移除了。

## 2. 分层发现与修复

| 层 | 曾有问题 | v1.2.4.2 处理 |
|---|---|---|
| CognitiveRouter | 看不到真实 Tool Manifest；DIRECT 可口头完成副作用请求 | 从 `ToolRegistry.manifest()` 注入可用能力；新增通用 `requires_tool_call`；DIRECT + required 自动提升为 TOOL |
| Agent | required 请求仍可能零调用并正常结束；仅靠重试 prompt 仍可能连续返回文本 | Router 指定的工具通过 provider `tool_choice` 强制调用；无具体工具时重试使用 `required`；结束前仍验证 Tool Call |
| Tool / Message | Tool 只返回 matched，缺少发送后的消息凭证 | matched 后创建独立 image message，并回填 `status=sent`、`message_id`、`image_url` |
| 多图 | 缺少跨 Tool/消息/Gateway 的顺序回归 | 支持一个模型响应内多个 `send_emoji` 调用，每次生成独立消息，顺序保持 |
| Persistence | 需要证明图片字段能落库并恢复 | Debug 直发连续 10 次落入 SQLite，再从新 Store 实例恢复并核对全部消息 ID |
| Gateway | 实时响应和历史结构不统一；独立图片可能漏出 | `_message_view()` 同时服务实时 `output_messages` 与历史 session，固定输出 id/type/text/images/source/emoji_id |
| Frontend | 空正文纯图片不创建节点；实时与历史分叉 | `renderMessage()` 同时用于实时和历史；以 images 判断 image-only，空文本仍创建节点 |
| Runtime | 无法确认客户端是否仍加载旧资源 | Debug 展示 Frontend Build ID/Loaded At 与 Core Version/Started At |

## 3. 本轮实际修改文件

核心链路：

- `src/zhaoxi/cognitive/router.py`
- `src/zhaoxi/cognitive/coordinator.py`
- `src/zhaoxi/cli.py`
- `src/zhaoxi/core/agent.py`
- `src/zhaoxi/interfaces/gateway.py`
- `src/zhaoxi/interfaces/models.py`
- `src/zhaoxi/web/adapter.py`
- `src/zhaoxi/web/app.py`
- `src/zhaoxi/web/static/index.html`
- `src/zhaoxi/__init__.py`
- `pyproject.toml`

回归测试：

- `tests/cognitive/test_integration.py`
- `tests/expression/test_emoji_service.py`
- `tests/interfaces/test_gateway.py`
- `tests/web/test_emoji_ui.py`

本仓库当前还有 v1.2.4/v1.2.4.1 的既有未提交改动；本次没有回滚或覆盖它们。

## 4. 已删除的旧临时补丁

- 删除基于“再来一张”“多发几个”等具体表述判断表情执行的专用逻辑。
- 删除对固定 `emoji_0005` 文本承诺的判断。
- 不再为实时图片和历史图片各维护一套 Renderer。
- Agent 的 required-tool 重试是通用执行契约，不依赖 emoji 名称、编号或用户固定文案。

## 5. 最终消息链路

```text
user request + trace_id
  -> CognitiveRouter(runtime manifest, recent context)
  -> route=TOOL + requires_tool_call=true
  -> Agent (zero call cannot report success; retry at most once)
  -> send_emoji
  -> EmojiService match / no_match
  -> independent assistant image Message
  -> SessionStore
  -> Gateway._message_view / output_messages
  -> frontend renderMessage
  -> frontend trace acknowledgement
```

## 6. 日志与 Trace

路由日志包含：route、requires_tool_call、selected workflow、available tools、reason；Correlation Context 继续提供请求 trace_id。

最近一次 Emoji Trace 包含：

- `trace_id`
- `route`, `requires_tool_call`, `selected_workflow`, `available_tools`
- `tool_called`, `tool_calls_count`, `tool_status`
- `emoji_ids`, `message_ids`, `image_message_created`
- `persisted`, `gateway_emitted`
- `frontend_received`, `frontend_rendered`

Debug 提供“直发测试表情”“让模型发送测试表情”和最近 trace 查看；前端真正处理图片后才回写 received/rendered。

## 7. 自动测试结果

- 表情相关 Python 回归：**58 passed**（包含两个兼容性回归用例）。
- Debug 直发：**10/10**，十个唯一 message_id，全部持久化，并从 SQLite 恢复后逐一一致。
- 单轮三次 Tool Call：**3/3** 独立 image message，顺序为 Tool Call 顺序，Gateway 实时与历史结构一致。
- 前端静态契约：验证 image-only 空文本节点、统一 `renderMessage()`、版本标识和 Debug 按钮。
- Node 单元测试：输入合并/回复分段 **22 passed**；桌面 Playwright 用例未运行，当前 `node_modules` 缺少 `playwright`。
- `git diff --check`：通过，仅有 Windows CRLF 提示。
- 全量 Python 回归：首次运行发现 7 个失败；其中 2 个是本次路由日志对测试 Stub 的兼容问题，已修复并通过。剩余 5 个涉及既有角色 YAML 编码断言和记忆写入确认策略，不属于表情链路，本次未擅自修改。

## 8. 人工测试结果

本轮完成了 TestClient/API 级的直发、持久化、历史恢复和 trace 回执验证。没有执行真实桌面端连续 30 分钟聊天，也没有用当前真实模型连续强制发送 10 次；因此这两项不能标记为完成。

## 9. Runtime 刷新规则与已知限制

- 修改 Python Core：必须重启 Core/桌面进程。
- 修改 `index.html`/静态资源：至少刷新页面；桌面壳若缓存旧页面，应完全关闭并重开窗口。
- 先对照 Debug 中的 Core Version/Started At 和 Frontend Build ID/Loaded At，再判断修复是否加载。
- 路由判断仍由模型完成，但现在有运行时目录和 `requires_tool_call` 契约兜底；真实模型的连续 10 次稳定率仍需桌面人工验收。
- Playwright 桌面自动化依赖尚未安装，因此没有宣称完成真实桌面渲染自动化。
- 30 分钟探索性聊天是发布前剩余人工门槛。
