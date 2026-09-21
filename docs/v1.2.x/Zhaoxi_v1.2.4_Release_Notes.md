# Zhaoxi v1.2.4 开发报告

日期：2026-09-17

## 完成内容

- 建立 `data/emoji/images/` 与 JSON 注册表，支持 PNG、JPG/JPEG、WebP、GIF；非法记录、缺失文件和损坏 JSON 均只禁用或跳过表情能力，不影响主进程。
- 新增 EmojiService：综合 description、tags、emotion 与 intensity 评分，低于阈值返回 `no_match`；最近历史降权，并在有替代候选时严格避免连续重复。
- 新增常驻表达工具 `send_emoji(intent, emotion?, intensity?)`。模型无需知道文件名，匹配结果会转换成 `source=emoji`、带 `emoji_id` 的独立 assistant 图片消息。
- 消息模型新增 `has_text`、`has_image`、`is_image_only`，会话存储保留图片消息的来源与表情 ID。
- Web 增加受控本地表情文件接口和响应中的增量消息列表，保证工具调用期间产生的图片消息能按顺序实时出现并在历史中恢复。
- 纯图片使用独立无气泡组件；文字加图片保持气泡。用户与 assistant 共用判断，支持多图、GIF、尺寸约束与点击预览。
- Debug 增加 Emoji Module 开关、Reload Registry、intent 测试以及 loaded/candidates/selected/recent 诊断。
- 项目运行时与包版本更新为 `1.2.4`。

## 配置

默认注册表为 `data/emoji/emoji_registry.json`。把图片放入 `data/emoji/images/`，并在注册表中使用相对路径登记。可通过以下集中配置调整：

```dotenv
ZHAOXI_EMOJI_ENABLED=true
ZHAOXI_EMOJI_REGISTRY_PATH=data/emoji/emoji_registry.json
ZHAOXI_EMOJI_RECENT_HISTORY_SIZE=5
ZHAOXI_EMOJI_CANDIDATE_LIMIT=5
ZHAOXI_EMOJI_MIN_MATCH_SCORE=0.4
```

仓库不附带具体表情资产，默认注册表为空；加入至少一条有效且启用的记录并 Reload Registry 后，`send_emoji` 才会变为可用。

## 验证

- v1.2.4 聚焦 Python 测试：45 passed；Web 输入合并与主动消息 Node 测试：16 passed。
- 全量测试：571 passed，1 skipped，另有 5 个来自分支创建前 v1.2.3 工作区的既有失败（人格文案断言 3 个、记忆写入确认策略断言 2 个）；本版本新增测试全部通过。
- 自动测试覆盖注册表加载与容错、proud/speechless 召回、无关语义 no_match、防连续重复、Tool 结构化返回、独立 image message、GIF 文件接口和无气泡 UI 分支。

尚未执行带真实表情资产和真实模型调用的人工桌面黑盒测试，因此本报告不把该项标记为已完成。
