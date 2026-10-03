# v1.4.5 感知调试图片 URL 膨胀修复

2026-10-03，基于 v1.4.5 提交 `06e4878` 的源码补丁。

## 原因与实机证据

“感知调试 → 最近观察”展示的 `data:image/jpeg;base64,...` 是内嵌图片的 Data URL，逗号后是完整图片的 Base64 编码，不是远程网站地址。

只读检查正式库 1761 条观察：215 个独立媒体引用，无内嵌 Data URL 或 `base64://` 图片。`PerceptionStore.recent_observations()` 经 `MediaBlobStore.loads()` 还原图片，再由 `/api/perception/recent` 原样序列化，最后被前端 `JSON.stringify` 展示。实机接口最近 20 条观察含 8 段图片编码，最长 6655734 字符。膨胀发生在调试读取与传输阶段。

## 修复

- 新增 `inspect_recent_observations()`，直接读取观察 JSON，保留 `$media` 内容哈希、MIME 和字节大小，不读取或展开媒体 blob。
- 对旧记录中仍存在的内嵌图片递归返回 MIME、编码长度和 `payload_omitted` 摘要；附件及元数据也覆盖。普通文本和网络地址保留，读取不改写数据库。
- `/api/perception/recent` 使用该只读检查路径，并返回 `media_payloads_included: false`。原有鉴权、分页上限与最新排序保持有效。
- 业务读取和模型视觉输入继续获取完整图片；Provider 将其放入 `image_url` 图像块，未对看图链路截断或替换。

## 验证与生效

感知、Web 检查接口和图像回归 49 项通过。新增四项检查覆盖媒体 blob 不展开、旧图片嵌套摘要、原始记录不修改、最新排序 / 限额、接口鉴权以及完整图片进入 Provider 图像块。

同批正式库最近 20 条观察以只读方式生成紧凑检查 JSON：8 个图片引用，观察响应约 35 KB（34867 字节，不含快照）。未读取图片 blob、调用真实模型、发送外部消息或重启正式实例。聚合证据见 [验收记录](evidence/perception_inspector_url_patch.json)，不保存观察正文或图片。

本次修改 Python 后端，需退出并重新启动整个朝汐进程，再点击“最近观察”。已有 v1.4.5 全量 1169 / Node 78 与 wheel 验收属于基线提交；本补丁未重建安装包，也未自动提交。
