# Zhaoxi v1.2.4.1 开发报告

日期：2026-09-17

## 完成内容

- 新增 EmojiManager，统一负责正式图库与 Pending 的文件操作、Registry 增删改查、SHA-256 去重、`emoji_0001`/`pending_0001` 序号命名和自动 Reload。
- Registry 使用临时文件写入、JSON 回读校验、原子替换；新增失败会删除孤立图片，删除流程先暂存图片并在 Registry 写入失败时回滚。
- 新增 `save_emoji` Tool。模型只能使用当前会话的 `latest` 或 `latest:N` 图片引用，提供表达含义、标签、情绪与强度，不能传本地绝对路径；错误引用返回 `not_found`，重复图片返回 `duplicate`。
- 新增正式图库 API：列表/搜索、详情、添加、编辑、启停、删除与 Reload。
- 新增 Pending API：批量暂存、列表、图片预览、丢弃和确认入库；GIF 全程保留原始字节，不转成静态图。
- 新增视觉整理 API：使用现有模型生成 description/tags/emotion/intensity，只返回待确认结果，不自动入库。
- 小桌边新增「表情柜」：最近加入、搜索、查看全部、缩略图、详情编辑、enabled 开关、删除二次确认、批量选择/拖入式文件选择、单张识别和批量识别后逐张确认。
- Emoji Debug 增加 Pending 数、最近加入和 Registry 状态。
- 原 `send_emoji` 接口、图片无气泡渲染和历史图片消息保持不变。
- 修复纯图片待发送消息无法挂载“撤回”按钮；按钮现在同时支持文字气泡与无气泡图片容器。
- 修复陪伴小窗遇到纯图片消息时因固定查找 `.bubble` 而中断投影；小窗现在会把纯图片显示为 `[图片]` 并继续展示当前对话。

## 验证

- v1.2.4/v1.2.4.1 表情与 Web 聚焦测试：48 passed。
- Web 输入合并与主动消息 Node 测试：16 passed；新增脚本通过 `node --check`。
- 全量测试：576 passed、1 skipped、5 failed。5 个失败与开发前一致，来自 v1.2.3 工作区已有的人格文案断言 3 个和记忆写入确认断言 2 个；本补丁新增测试全部通过。
- 自动覆盖 add/update/delete/list/duplicate、写入失败回滚、自动 Reload、GIF Pending/commit、会话图片 Tool 引用、not_found、管理 API、安全图片接口和表情柜结构。

尚未使用真实模型和第一批真实表情资产执行人工桌面黑盒，因此不声明该验收项已经完成。
