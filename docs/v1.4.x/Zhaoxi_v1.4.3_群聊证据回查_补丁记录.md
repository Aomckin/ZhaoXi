# v1.4.3 群聊证据回查补丁记录

2026-10-01。承接 External Provenance Integrity 补丁，补齐「群聊信息如何进入上下文、是否抽象、能否追到原消息」审计发现的缺口。版本仍为 `1.4.3`，不增加依赖，不重建业务库或百炼向量。自动测试使用隔离数据库，产物置于 `.zhaoxi/`；本轮未重启实际桌面进程、未发送 QQ 消息。

## 信息进入与抽象层级

| 路径 | 模型看到的内容 | 回查能力 |
| --- | --- | --- |
| 定向群消息 / Owner 发言 | 当前消息正文与来源；Owner 身份保持 USER，其他人保持 EXTERNAL | 以 event_id 或 QQ raw_ref 读取原消息 |
| 普通群消息 → Perception Batch | 默认窗口或条数触发语义摘要；摘要正文由 `[sN]` statements 生成 | 每句引用实际 observation_id，再映射到 QQ raw_ref |
| 时间线 L1 / L2 压缩 | 前三条消息的有界摘录，明确标记 `[sN]`；属于机械压缩 | 摘录关联 source_event_ids；整段可展开全部源消息 |
| 既有旧摘要 | 保留旧概括 | 仅整批追溯，不补造逐句证据 |

摘要器输入保留发言者、角色及消息 ID。接受模型输出前校验每句的引用确实在本批可见消息中；引用缺失、未知、生成失败或超时，降级为带引用的原文摘录。无引用的独立 summary 不作为正文。每批限制同来源、同会话及同插件；输入最多 8000 字、单消息摘要片段 300 字、输出正文 1200 字。摘要覆盖有界，不等于看完全部原文；整批引用仍保存全部消息。

这些校验证明引用存在，不能保证模型的每句概括语义完全正确。涉及原话、争议细节和历史图片，Prompt 要求回查证据。群友和摘要仍属于外部数据，不能成为 Owner 本人事实。

## 模型与 Debug 回查

新增常驻 READ 工具 `read_social_context`。来源渲染包含紧凑 `SocialTrace` ref，工具支持 event_id、QQ raw_ref、TimelineUnit ID；可指定 `statement_id=s1` 展开某句证据。返回逐条原文、发言者、来源会话、插件、发生时间、原消息引用、图片缓存状态、消息段类型和缺失引用。

- 原文分页使用 `offset` 与 `text_offset`，长文字尾部不丢失；工具输出在预算内保持有效 JSON 和下一页游标。
- 最多展开 500 个引用、8 层摘要；截断和缺失显式返回，不把摘要替代为原话。
- 同轮 TimelineUnit 中的工具和回复记录不充当群友原消息；回查只展开输入消息和群聊摘要。
- Desktop 的本地授权会话可回查群聊；外部回复必须同时匹配 channel、session、conversation_id、source_plugin。私聊、私人资料和跨群证据不能通过该工具读取。
- 外部受限回复只放行此 READ 工具，其他工具不开放；工具被禁用时不暴露或执行。FAST / Router 保留群聊摘要，FAST 遇到证据需求升级 STANDARD。
- Snapshot Planner 现在携带该摘要的真实 trigger 和 public 会话边界，避免空上下文把摘要过滤掉。

Debug「群聊原文回查」支持 ref、可选句 ID 和下一页，使用安全文字展示；API 为 `/api/debug/cognitive-stream/social-trace`，沿用 Desktop token 验证。来源 Inspector 展示回查 ref 和逐句证据。内部 SocialTrace 标签从对用户的回复移除。

## 原始消息、连发合并与图片

QQ 解码保留收到的 OneBot payload。回查文字从原始 message 段读取，因此不受普通规范化正文 20000 字上限影响；语音等非文本段仅报告类型，完整协议载荷留在事件 metadata，不假装已转写。

新连发合并保留每条 raw_observation，包括独立文本、消息 ID、发言者、时间与图片。缓存图片回填到对应原消息。旧合并记录没有这些边界时标记 `merged_legacy`，只返回已保存的合并正文与全部引用，不能还原独立消息。

复查确认 QQ 插件原本已缓存普通群图片，并非只保存 URL。此次完善其他 adapter 的 Ambient 图片处理、缓存图在 file 字段的兼容、合并原消息图片对应关系及缺失缓存降级。`include_images=true` 每页最多附加两条消息、每条两张缓存缩略图，作为历史 attention 图片携带 ImageProvenance 进入下一轮模型输入，不冒充本轮新图。回查不联网下载失效 URL；缓存缺失或损坏显示 unavailable，保留可读原文。

## 证据保存期限

Experience 原有工具 7 天、非 Owner 30 天、Owner 90 天规则保留；增加引用保护：尚存的群摘要或缓存 TimelineUnit 递归保护对应原消息。TimelineUnit 自最后生成起 30 天过期，单纯回查不会续期；摘要和缓存均到期后释放证据保护。

Perception 清理在 Experience 清理后进行，尚被有效摘要引用的 Observation、Snapshot 与 Batch 不被提前删除。不是永久保存；已过期删除的历史原文无法恢复，回查明确报告 missing_refs。共享媒体继续采用内容寻址，不在 SQLite 重复内联图片。

## 验证与边界

- 最终完整 Python 回归：960 passed、1 skipped，193.24 秒；保留既有 FastAPI / Starlette 依赖弃用警告。
- 群聊追溯专项：20 passed，3.15 秒。
- Web Node：61 passed；可执行内联 JavaScript 的 `node --check` 通过。
- Git 暂存差异空白检查通过；根目录无 `.pytest-tmp*` 测试目录。

测试覆盖逐句引用、无效引用降级、批次及插件边界、跨群/私聊拒绝、旧摘要粒度、连发边界、长原文尾部、输出预算分页、缓存图片实际模型输入、缓存缺失降级、FAST/Router、Snapshot Planner、引用保护及到期释放、API 认证与参数、Web 文字转义与翻页。Case A–J golden 更新只增加回查标签，正文、角色和既有来源规则保持测试覆盖。

隔离链路采用 fake provider，证明工具结果与历史图片能够进入模型请求；不等于真实模型一定主动正确使用工具。桌面需加载补丁并刷新前端后，再进行真实 NapCat / Desktop 会话与视觉验收。Dogfooding、独立人工相关性标注的原有边界仍保留。

本地日志：`.zhaoxi/social-full-final.log`、`.zhaoxi/social-trace-final.log`、`.zhaoxi/social-node-final.log`。复跑：

```powershell
python -m pytest -o addopts='' --basetemp=.zhaoxi/test-tmp -q
node --test tests/web/*.test.cjs
```
