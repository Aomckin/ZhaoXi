# Desktop 实时主动消息无法引用补修

日期：2026-10-11（Asia/Shanghai）。用户报告：17:13 主动消息已经显示完整，右键引用仍提示“这条消息发送完成后才能引用”。

## 证据与根因

只读日志 zhaoxi.log:5520 显示 17:13:58.877 Beat delivered=true，模型 finish_reason=stop。只读 session.db 核对同一消息已保存，message_id 为 96c35e4aada545ce9a6adbf8abed1708，delivery_id 为 beat-1791710019.474582-1。未改写该记录。

主动消息 SSE 使用 delivery_id，实时 drainDeliveries 原先只把正文和时间传给 sendReply，漏掉引用所需的会话 message_id。MessageTools.quote 因气泡没有 messageId，与待发送消息走同一提示。后端已发送和保存成功；“发送中”是前端误判。刷新后的会话恢复使用 renderMessage，原本能带回真实 ID，实时到达这一分支没有被此前引用验收覆盖。

## 修复

实时主动消息按 delivery_id 读取当前会话原消息，沿用 renderMessage 的分段和节奏；所有分段绑定真实 message_id，可以即刻右键引用、显示只读引用条并定位原消息。主动消息不提供重新生成按钮；保留忙碌/未发送输入的排队、到达去重及刷新恢复。

若会话读取暂时失败，主动正文仍显示，不凭前端构造来源 ID。缺来源 ID 的消息提示“原消息标识尚未同步，请刷新后再引用”，待发送消息保留原提示。恢复会话后可读取真实来源；不额外调用模型。

## 验证与加载

- 300 项 Python 回归通过（Web 引用、Web、Desktop 入口、Interfaces、Proactive、Desktop）；其中引用专项 14 项。新增用真实 Delivery 存储同步原消息、连续读取 ID 不变及原消息引用进入模型上下文的测试。
- 24 项 Node 回归通过，覆盖主动通知及分段渲染；新增实时 delivery ID 精确匹配、读取失败不丢正文/不造 ID、待输入排队和重复事件去重。
- 隔离 Edge 完整 Desktop 页面验收通过：三段主动消息即时带相同真实 ID，右键只读引用、定位、无重生成按钮、刷新后保持 ID 和去重；既有历史分段、普通回复、发送指针、合并输入和陪伴窗口验收也通过，未发生页面脚本错误。检查截图 .pytest_cache/proactive-reference-live.png。
- git diff --check 通过。测试使用模拟 API、临时会话和假 Agent，未发送生产消息、调用真实模型或重启正式程序。

本次为静态界面修复，重新加载 Desktop 页面后生效；现有 17:13 消息会从会话恢复真实 ID。无需删除或重发主动消息。

此前 17:15 调查确认的“缺正文 JSON 被当文本放行”和“搜索无命中触发全局强制收尾”仍是独立待修项，本次没有修改那两条后端路径。
