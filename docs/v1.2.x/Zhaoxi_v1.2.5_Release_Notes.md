# Zhaoxi v1.2.5 发布说明：Reply DSL 表情表达

## 版本结果

v1.2.5 将“发表情”从外部 Tool 动作重构为回复内容的一部分。Replyer 现在只表达所需属性：

```text
哼，我当然会啦。
[emoji:得意,邀功]
这次总看见了吧！
```

Core 统一解析为 `ReplySequence`，本地 Resolver 再选择真实资源，并按文本、表情、文本的原始顺序持久化和输出。

## 已完成

- 新增 `core/reply`：`TextSegment`、`EmojiSegment`、`ReplySequence`、Parser 与统一 Renderer。
- 支持空格、中文逗号、多表情、空 DSL、未闭合 DSL 和未知标签安全降级。
- `EmojiService.resolve_tags()` 使用标签命中、命中比例、候选特异性与 recent history 降权；不引入 embedding。
- 每轮上下文注入全部启用表情的 tags，不暴露 `emoji_id`、文件名或路径。
- 解析后的文本/表情段按顺序保存；表情段保存 `emoji_id` 与 `requested_tags`，历史恢复不重新匹配。
- Web Gateway 对实时输出和历史恢复返回相同的有序消息结构；旧 `source=emoji` 图片消息继续兼容。
- 无匹配表情只丢弃对应 EmojiSegment 并记录 `emoji_resolve_no_match`，正文继续输出。
- Debug Emoji 改为展示当前属性上下文、Raw Reply、解析段、请求标签、解析 ID 与 recent history。
- `send_emoji` 已从内置 Tool、Manifest、能力目录和模型强制 Tool Call 链路移除。
- `save_emoji` 保留为有真实本地副作用的 Tool，表情柜和资源接口继续使用。

## 兼容性

- Session schema 不需要破坏性迁移；新增字段由消息 JSON 自描述保存，旧记录缺省为空。
- 旧独立表情消息仍按原 `source=emoji`、`emoji_id`、`images` 字段显示。
- Raw Reply 只进入持久化和 Debug，不出现在普通 Gateway 消息视图中。

## 验证

- Parser、Resolver、顺序、上下文、Manifest 移除、持久化恢复及 Web Debug 均有自动化覆盖。
- 615 项 Python 测试通过、1 项跳过；35 项非 Playwright Node 测试通过；`compileall` 与 `git diff --check` 通过。
- Playwright 冒烟测试需要本机安装 `playwright` 后单独执行。
