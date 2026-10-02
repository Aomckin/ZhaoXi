# v1.4.4 群聊历史搜索与旧证据衔接补丁

日期：2026-10-02。承接 [群聊证据回查](Zhaoxi_v1.4.3_群聊证据回查_补丁记录.md)。版本仍为 1.4.4。

## 补齐的行为

`read_social_context` 增加条件搜索模式：不提供 reference，改用 query（正文中的字面关键词）、group_id（QQ 群号）、source_plugin 和 since / until（带时区的 ISO 8601 时间）。可以只指定群号查看已保存消息；开始时间包含、结束时间不包含。

搜索覆盖 Experience 和仍在 Perception 保存的群消息，不再依赖 Attention 的近 30 天最新 200 条候选。数据库按条件筛选、按原消息引用去重，再按发生时间从新到旧分页。正文来自已保存原协议的 text / at 段；旧记录没有原协议时使用已保存正文。查询不匹配昵称、协议元数据或摘要，也不执行语义搜索。关键词中的 %、_、引号按普通文字处理。

按 ref 展开时，Experience 未找到的原消息、observation:<id> 或 snapshot:<id> 可只读回查 Perception。虚拟证据保留原记录的发言者、时间、群、插件与信任信息，返回 evidence_store=perception；不会把历史消息重新追加到 Experience、改变维护游标或触发记忆提取。两库都有记录时沿用 Experience 的权威记录，旧 observation ID 也不能绕过其隐私分类。

旧摘要没有逐句证据时仍只支持整批展开。只有保存过的 statements 才提供逐句回查；不根据旧概括生成事后引用。已删除的记录继续明确报告缺失，不联网补拉 NapCat 历史。

## 模型调用示例

```json
{
  "query": "聚餐",
  "group_id": "123456",
  "since": "2026-09-27T00:00:00+08:00",
  "until": "2026-10-03T00:00:00+08:00",
  "limit": 8,
  "include_images": true
}
```

结果 records 包含 reference、event_id、raw_ref、content、provenance、evidence_store、raw_payload_available、图片状态及文字截断信息。长正文中的匹配位置另返回 match_text_offset，可以用 text_offset 读取命中处。继续搜索时保留原条件，传入 next_offset / next_text_offset；也可用结果中的 reference 单独展开原消息。

reference 模式与搜索条件分开使用；statement_id 仅用于 reference 模式。默认每页 8 条、最多 20 条；输出仍受工具预算限制。offset 最大 200000，text_offset 最大 200000。已有图片回查限制保持：每次最多 2 条消息、每条 2 张缓存缩略图，作为历史图片进入下一轮模型请求。工具停用时仍不暴露或执行。

FAST 的指引加入群聊历史搜索的工具升级；STANDARD 和受限 QQ 回复复用已有 READ 工具，无需开放其他工具。系统上下文说明没有 ref 时先搜索，不能把空结果解释为群里从未发生过。

Debug 的「群聊原文回查」增加关键词、群号、开始/结束时间与「搜索群消息」。原展开按钮保持按 ref 读取；翻页保留模式与条件，修改条件后从头查询。API 仍为 /api/debug/cognitive-stream/social-trace，沿用 token 认证，原文仅用 textContent 展示。

## 权限与保留期限

本地 Desktop，以及有效 Owner 的 Web / CLI / Voice 会话可以搜索保存的群历史。QQ 调用必须有当前群和插件身份，搜索条件从当前 turn 收紧；参数不能扩大到其他群、插件或私聊。未知插件身份的旧记录可在本地查看，不授予外部跨来源读取。其他渠道与未知会话按既有边界拒绝。

搜索只返回群消息原文，不把工具结果、摘要或私有事件混入原消息。Perception 中的 IGNORED 消息不作为历史证据开放。不存在的 Perception 库不会被创建，只有 Ledger 的库也可正常降级。

保存期限沿用原配置：Perception 默认 168 小时；Experience 通常非 Owner 30 天、Owner 90 天，仍受有效摘要与时间线的引用保护。回查不会续期；此次未迁移数据库、补造原协议或修改保留策略。媒体仍从共享内容寻址缓存读取，缺失缓存保留文字并报告 unavailable。

## 验证

真实库只读核验：此前没有 Experience 索引的 **590 条原消息全部可读**，**66 条旧摘要全部可展开**，缺失引用为 0。两个群分别搜索到 37 / 1630 条保存消息，单页查询约 80 ms；这些数量代表核验时快照。此核验没有向群发消息，也没有调用真实模型。汇总见 [补丁验收证据](evidence/social_history_search_acceptance.json)。

自动测试覆盖超过 200 条近期事件时的旧消息查询、正文筛选、去重分页、时区边界、长原协议尾部、跨群/跨插件/私聊拒绝、既有隐私分类、旧摘要粒度、历史图片实际进入合成模型输入、缺失缓存、只读降级、API 认证和前端翻页。

Python 全量 **1071 通过、1 跳过**（系统无法创建符号链接）；Node **66 通过**。最后的旧 observation 隐私分类衔接调整后，另跑认知链路 **116 通过**。编译与差异检查通过；保留既有 Starlette/httpx 弃用提示。详细结果在验收证据中记录。加载补丁需要重启 Core 并刷新前端；真实模型主动选用工具及桌面交互仍需实机观察。本补丁整理为本地版本提交，未推送或外部发布；其他既有工作区修改保留。
