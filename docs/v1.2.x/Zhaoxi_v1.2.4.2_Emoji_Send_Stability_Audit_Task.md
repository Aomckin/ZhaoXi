# Zhaoxi v1.2.4.x 表情包发送链路稳定性排查任务书

## 0. 任务定位

本任务不是继续增加新功能，而是对当前 **表情包发送链路进行一次完整、分层、可复现的稳定性排查**。

现状已经证明：

- 表情包库、`EmojiService`、`send_emoji`、会话图片消息、前端图片渲染都曾经至少成功过一次；
- 第一次测试时，`send_emoji` 实际调用成功、图片消息已进入会话历史，但前端当时没有正确渲染；
- 后续测试又出现模型口头声称“发了 emoji_0005”，但实际上没有调用 `send_emoji`；
- 曾经修过前端纯图片消息为空正文时的渲染问题；
- 曾经修过 CognitiveRouter 在进入 Agent 前看不到真实 Tool Manifest、无法知道“必须真实调用工具”的路由缺口；
- 当前仍不能确认整条链路已经稳定。

因此本任务的目标不是“再补一条针对某句话的 prompt 规则”，而是：

> 找出表情发送在 **工具层 / Agent 层 / CognitiveRouter 层 / 会话持久化层 / Gateway 层 / 前端渲染层 / 运行时刷新层** 中所有可能的不稳定点，并建立稳定、可观察、可回归验证的完整链路。

---

## 1. 已知现象

### 1.1 至少一次真实成功

曾经出现完整成功链路：

```text
模型决策
→ send_emoji
→ EmojiService 匹配
→ 独立图片消息
→ 会话持久化
→ 前端显示
```

因此不是“能力不存在”，而是“链路不稳定”。

### 1.2 曾经出现 Tool 成功但前端不显示

日志曾确认：

```text
send_emoji 调用成功
emoji_id = emoji_0005
images = ["/api/expression/emoji/emoji_0005"]
source = emoji
```

会话数据库也存在独立图片消息，但旧前端未正确渲染。

曾定位过两类问题：

- 桌面窗口仍运行旧版 `index.html`；
- 纯图片消息正文为空时，类似 `splitReply("")` 的逻辑返回空数组，导致整个消息节点不创建。

这些问题虽然修过，但必须重新纳入回归测试。

### 1.3 后续出现“口头发送但没有工具调用”

多次出现：

```text
“这次真发”
“还是那张 emoji_0005”
“三张连发”
```

但日志显示：

```text
没有 send_emoji tool call
没有新增图片消息
数据库没有新 emoji 记录
```

也就是说模型只是在文本里声称执行了发送动作。

### 1.4 已发现过 CognitiveRouter 缺口

实际链路：

```text
用户消息
→ CognitiveRouter
→ DIRECT / TOOL / WORKFLOW
→ Agent
→ send_emoji
```

问题曾发生在 CognitiveRouter：

- 路由器进入 Agent 前看不到真实 Tool Manifest；
- DIRECT 路径允许模型直接文本回答；
- 模型可能“知道表情存在”，却不知道当前请求需要真实副作用；
- 因此出现“嘴上说发了，实际零调用”。

已经尝试加入 `requires_tool_call` 并把运行时工具目录提供给认知路由器，但必须重新验证结构是否稳定，而不是仅对测试语句有效。

---

## 2. 排查原则

### 2.1 禁止继续对具体文字打补丁

不要新增类似：

```text
如果用户说“再来一张”
如果用户说“多发几个”
如果用户说“emoji_0005”
```

这种字符串特判。

本任务必须从结构上解决问题。

### 2.2 每层必须独立可验证

必须可以分别验证：

```text
EmojiService
send_emoji Tool
Agent Tool Execution
CognitiveRouter
Conversation Persistence
Gateway Output
Frontend Render
Runtime Reload
```

不要继续只靠自然聊天猜问题在哪一层。

### 2.3 “模型说发了”不算成功

唯一成功标准：

```text
真实 Tool Call
+
真实 Image Message
+
真实持久化
+
真实 API/Gateway 输出
+
真实前端显示
```

任何一项缺失都算失败。

---

## 3. 建立统一 Trace ID

建议为每次用户请求生成：

```text
request_id / trace_id
```

例如：

```text
trace_id=chat_20260918_00123
```

并在整条链路中透传：

```text
CognitiveRouter
Agent
Tool
EmojiService
ConversationStore
Gateway
Frontend payload
```

目标：通过一个 `trace_id` 就能看到整次请求到底断在哪一层。

---

## 4. CognitiveRouter 排查

### 4.1 确认路由输入包含真实运行时能力

路由器必须知道当前运行时真实存在：

```text
send_emoji
save_emoji
```

以及能力说明。

不要只把工具名字硬编码进 prompt。应读取当前 Tool Registry / Tool Manifest 的真实结果。

### 4.2 `requires_tool_call` 契约

检查当前实现是否真正做到：

```text
用户请求具有真实副作用
→ requires_tool_call = true
→ 不允许 DIRECT 路径只返回文本
```

例如：

```text
发个表情包
再来一张
发几张试试
用刚才那个
```

如果当前上下文明确是在要求“执行发送”，必须属于真实执行请求。

### 4.3 设计应当通用

该机制不能只服务 emoji。

类似：

```text
发送表情
写入记忆
启动服务
创建文件
操作 LifeHUD
```

凡是用户要求“真的执行”而不是“解释怎么执行”，都应该能表达：

```text
requires_tool_call = true
```

### 4.4 路由日志

必须输出：

```text
trace_id
route = direct / tool / workflow
requires_tool_call = true / false
selected_workflow = ...
available_tools = [...]
reason = ...
```

---

## 5. Agent Tool Execution 排查

### 5.1 强制验证真实调用

若：

```text
requires_tool_call = true
```

则 Agent 最终回复前必须检查：

```text
tool_calls_count >= 1
```

否则不得正常宣称成功。

### 5.2 禁止“口头伪执行”

如果模型输出：

```text
“发了。”
“emoji_0005 给你。”
“三张连发！”
```

但没有真实 Tool Call：

```text
→ 判定 execution_incomplete
→ 不允许按成功回复
→ 触发一次明确的工具执行重试
```

### 5.3 重试最多一次

避免无限循环。

如果强制重试后仍无真实 Tool Call：

```text
tool_execution_failed
```

并记录日志。

### 5.4 Tool 返回必须结构化

`send_emoji` 成功建议：

```json
{
  "status": "sent",
  "emoji_id": "emoji_0005",
  "message_id": "...",
  "image_url": "/api/expression/emoji/emoji_0005"
}
```

失败：

```json
{
  "status": "no_match"
}
```

或：

```json
{
  "status": "error",
  "reason": "..."
}
```

Agent 不能只靠自然语言判断是否执行成功。

---

## 6. `send_emoji` Tool 独立排查

至少覆盖：

```text
1. 指定 intent 能匹配图片
2. 无匹配返回 no_match
3. disabled 表情不会被发出
4. 最近重复降权/防连续重复正常
5. 生成独立 assistant image message
6. source=emoji
7. emoji_id 正确
8. image url 正确
9. 会话持久化成功
```

---

## 7. 多张表情发送

用户已经实际提出过：

```text
“多发几个测试”
```

需要明确当前产品语义。

如果允许一轮多次 Tool Call，则必须验证：

```text
send_emoji(...)
send_emoji(...)
send_emoji(...)
```

并保证：

- 每张都是真实 Tool Call；
- 每张都是独立 image message；
- 顺序稳定；
- Gateway 不合并丢失；
- 前端全部渲染；
- 防重复仍有效。

如果当前架构不支持一轮多次工具调用，也必须明确限制，不允许模型声称“三张连发”。

---

## 8. Conversation Store 排查

每次成功调用后，数据库必须存在真实消息记录。

至少确认：

```text
role = assistant
source = emoji
emoji_id
images
timestamp
message_id
```

重点测试：

```text
实时发送
→ 关闭客户端
→ 重启
→ 加载历史
→ 图片仍然存在
```

---

## 9. Gateway / API 输出排查

当前曾出现 `content`、`output_messages`、`images` 等不同字段并存的情况。

必须确认稳定契约，避免前端自行猜：

```text
content 为空时是不是还有图片
output_messages 里是不是还有 Tool 产生的独立消息
历史恢复是否又走另一套结构
```

建议统一成标准消息数组，例如：

```json
{
  "messages": [
    {
      "id": "...",
      "role": "assistant",
      "type": "text",
      "text": "..."
    },
    {
      "id": "...",
      "role": "assistant",
      "type": "image",
      "source": "emoji",
      "emoji_id": "emoji_0005",
      "images": ["/api/expression/emoji/emoji_0005"]
    }
  ]
}
```

目标：实时新增、Tool 产生的消息、历史恢复都尽量走同一消息模型。

---

## 10. 前端渲染排查

### 10.1 纯图片必须创建消息节点

禁止类似：

```js
if (!text) return;
```

直接吃掉 image-only message。

渲染应基于：

```text
has_text
has_image
is_image_only
```

### 10.2 实时与历史尽量共用 Renderer

检查：

```text
实时新增消息 Renderer
历史恢复 Renderer
```

是否存在两套逻辑。

尽量统一为：

```text
renderMessage(message)
```

避免：

```text
实时能显示，历史不能显示
```

或反过来。

### 10.3 增加前端版本识别

之前出现过桌面窗口仍加载旧前端的问题。

建议 Debug 显示：

```text
Frontend Build ID
Frontend Loaded At
Core Version
Core Started At
```

避免再次误判“代码改了但没生效”。

---

## 11. Runtime Reload 排查

明确：

```text
修改 Python Core → 是否必须重启
修改前端静态资源 → 是否必须刷新 / 重启桌面窗口
```

并把规则写进 Debug 或开发文档。

---

## 12. Debug 增加“表情包链路体检”

### 12.1 直发测试

按钮：

```text
[直发测试表情]
```

绕开 LLM：

```text
Debug
→ send_emoji / EmojiService
→ Conversation Store
→ Gateway
→ Frontend
```

用于验证基础通道。

### 12.2 模型测试

按钮：

```text
[让模型发送测试表情]
```

走完整：

```text
CognitiveRouter
→ Agent
→ send_emoji
→ ...
```

用于验证路由与 Agent。

### 12.3 最近一次 Emoji Trace

展示：

```text
Trace ID
Route
Requires Tool Call
Tool Called
Emoji ID
Message Persisted
Gateway Emitted
Frontend Received
Frontend Rendered
```

示例：

```text
trace_id: chat_00123
route: TOOL
requires_tool_call: true
tool_called: true
emoji_id: emoji_0005
persisted: true
gateway_emitted: true
frontend_received: true
frontend_rendered: true
```

---

## 13. 分层人工验收

必须按顺序做。

### Level 1：EmojiService

直接传 intent。

确认能稳定匹配。

### Level 2：`send_emoji` Tool

绕开 Agent 直接调用。

确认：

```text
Tool success
→ 会话落库
→ API/Gateway 能读到
→ 前端能看到
```

### Level 3：Agent 强制 Tool

输入：

```text
请实际调用 send_emoji 发送一张表情。
```

确认产生真实 Tool Call。

### Level 4：自然明确请求

例如：

```text
发张表情包
来一张
用刚才那张
```

确认路由正确。

### Level 5：上下文省略

例如：

```text
用户：发张表情
朝汐：...
用户：再来一张
```

第二句仍应结合上下文判断需要真实工具。

### Level 6：多张发送

```text
多发几个测试
```

验证当前产品定义下的多 Tool Call / 多图片消息。

### Level 7：历史恢复

成功发送后：

```text
关闭朝汐
重启
重新打开会话
```

确认图片仍显示。

---

## 14. 必须增加的自动测试

### CognitiveRouter

```text
明确要求发送表情
→ requires_tool_call=true
```

上下文：

```text
上一轮刚讨论表情
用户：“再来一张”
→ requires_tool_call=true
```

非执行：

```text
“send_emoji 是干嘛的？”
→ requires_tool_call=false
```

### Agent

```text
requires_tool_call=true
+
模型仅返回文本
→ 不得判定成功
→ 触发工具重试
```

### Gateway

覆盖：

```text
text + image
image only
multiple image messages
history restore
```

### Frontend

验证：

```text
image-only text=""
仍创建消息节点
```

以及实时 image / 历史 image 渲染一致。

---

## 15. 清理旧临时补丁

本轮完成后检查并删除：

- emoji 专用关键词字符串特判；
- `emoji_0005` 等具体编号判断；
- “再来一张”“多发几个”等硬编码；
- 重复前端 image fallback；
- 重复 Tool 调用兜底；
- 已被统一机制替代的临时逻辑。

目标不是更多补丁，而是 **更少但更稳定的规则**。

---

## 16. 本任务不要做

不要：

- 增加新表情包功能；
- 改表情柜 UI；
- 接 AI 作画；
- 调整角色 Prompt 风格；
- 无证据重写 EmojiService 检索算法；
- 扩展 v1.3 外界信息适配层；
- 继续为单个测试语句堆 prompt。

只稳定：

```text
用户意图
→ 路由
→ Agent
→ Tool
→ Emoji
→ Message
→ Persistence
→ Gateway
→ Frontend
```

---

## 17. 最终验收标准

- [ ] Debug 直发测试表情 10 次全部成功；
- [ ] Agent 强制发送 10 次全部产生真实 Tool Call；
- [ ] “发张表情包”自然请求稳定；
- [ ] “再来一张”上下文省略请求稳定；
- [ ] “多发几个”行为与当前产品设计一致；
- [ ] 不再出现“文字声称发送但没有 Tool Call”；
- [ ] 不再出现 Tool 成功但 Gateway 丢失；
- [ ] 不再出现 Gateway 有图片但前端不建节点；
- [ ] 不再出现实时能看、历史恢复看不到；
- [ ] 不再因桌面窗口加载旧前端造成误判；
- [ ] 每次失败都能通过 trace_id 定位到具体层；
- [ ] 删除针对固定文案的临时补丁；
- [ ] 自动测试通过；
- [ ] 完成至少一次真实桌面端连续 30 分钟探索性聊天测试。

---

## 18. Codex 最终交付报告

完成后必须输出一份排查报告，包括：

```text
1. 最终根因
2. 曾经存在的不同 bug 分别属于哪一层
3. 本轮实际修改了哪些文件
4. 哪些旧补丁被删除
5. 最终消息链路图
6. 新增了哪些日志 / trace
7. 自动测试结果
8. 人工测试结果
9. 仍存在的已知限制
```

不要只写：

```text
“已修复，测试通过”
```

必须解释：

> 为什么第一次能成功、为什么后来会失败、现在为什么能够稳定成功。

---

## 19. 目标状态

最终应该形成一条可解释、可观测、可回归的稳定链路：

```text
用户：“再来一张表情包”
        ↓
CognitiveRouter
route=TOOL
requires_tool_call=true
        ↓
Agent
真实调用 send_emoji
        ↓
EmojiService
匹配 emoji
        ↓
ConversationStore
写入独立 image message
        ↓
Gateway
返回标准 message array
        ↓
Frontend
统一 renderMessage()
        ↓
图片真正出现在用户眼前
```

而不是：

```text
朝汐：“发了！”
        ↓
实际上什么都没发生
```

本任务完成后，再继续正常探索性测试，不再靠临时字符串补丁维持表情发送。
