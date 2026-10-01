# v1.4.3 开发记录与验收说明

2026-10-01 收尾：用户授权的代码补缺、正式离线迁移、备份恢复验证及本机启用已完成；桌面已用正常网络权限恢复运行，三种召回模式均使用百炼。Dogfooding 未开始。独立人工相关性标注和实际界面视觉验收仍无证据；并发测试期间候选生成曾超过本地耗时目标，最终重启的三模式均达本地目标。完整逐项判定见 [任务书核对](Zhaoxi_v1.4.3_任务书核对.md)。本轮按 v1.4.3 整理为本地版本提交，未推送或外部发布。

版本阅读入口：[版本说明](Zhaoxi_v1.4.3_Release_Notes.md)；早期预演证据另存 [阶段记录](Zhaoxi_v1.4.3_阶段记录.md)。

## 本轮新增修正

- Cluster Merge 加入 summary 信号；EXPLICIT_RECALL 依最佳簇置信度和领先幅度定向放宽，歧义查询保持多簇限制，Inspector 展示实际限制。
- 维护队列持久化阶段名，按名称恢复并兼容旧整数检查点；支持新增阶段，失败互不阻断，运行中断写入保持 uncertain、不自动重放。
- 外部可信 Owner 消息通过共享 Gateway 排队，0.5 秒窗口最多八条合批；显式记住、本地 Owner、外部 Owner 依次优先，有界队列、请求/事件去重及前台让路。每条候选证据映射到实际输入；多事件上下文来源明确标记。
- Inspector API 与界面补充写入原因、证据引用、热度历史和指定记忆的排除解释；仅暴露允许的元数据字段。
- 实测 2274 字长输入时，CommandCode 网关仍忽略关闭思考，3800 有效输出预算被全部消耗而无正文。后台提取的思考预留改为最多 6000，正文预算保留 1000/1800；只在该网关的 DeepSeek 叶子请求增加，普通前台不启用。修复后四事件合批及长输入均 stop，写入 3/2 条，耗时 22.59/25.62 秒，reasoning tokens 3427/4451。合成文本、临时数据库，无真实对话或业务写入。参考 [DeepSeek 思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)；网关行为以本机响应实测为准。报告 `batch-llm-validation.json`。

## 质量口径与局限

冻结原基线和 1025 条快照，按查询准则复核前后 Top-K 合并池共 94 条。复核者是 Codex 开发代理，不是独立人工；未穷尽全库 gold。原固定 ID 标签保留：Recall@6 0.8000 → 0.8250，Precision@6 0.2833 → 0.3000，MRR 0.9000 → 0.8250。复核池口径：Recall@6 0.6207 → 0.7231，Precision@6 0.5667 → 0.6833，MRR 1 → 1，平均拒绝噪声 2.6 → 1.0；脚本门槛通过。两种口径同时输出，不用重标结果抹掉原下降。

QQ 接入原标签遗漏了前列相关原则/状态，已按统一准则记录判断；没有针对 ID 调权。复核池 Recall 不等于全库 Recall。脚本 `scripts/accept_memory_v143.py` 只读取本地缓存及快照，门槛失败退出码 1。协议、标签、私有原文和报告位于 `.zhaoxi/memory-v143-review-protocol.json`、`memory-v143-reviewed-labels.json`、`memory-v143-reviewed-acceptance/`。

## 正式迁移与启用

用户从托盘退出后，完成 17 个数据库及媒体文件备份；逐项校验 SHA-256 / SQLite integrity，记忆备份另恢复至隔离路径，1029 条 ID、正文、状态一致。备份保留于 `.zhaoxi/v143-release-20261001/offline-backup/`，不覆盖当前库。

原记忆库已正式发布迁移：1029 条，1024 条有效语义向量，1020 条复用兼容快照，五条 FORGOTTEN 排除，最大簇 80。迁移按内容 hash / model / version / dimensions 验证向量，不从旧快照覆盖原库新增记录。配置仍为百炼 `text-embedding-v4` / version `1` / 1024 维。

| 数据库 | 迁移前字节 | 图片迁移与 VACUUM 后字节 |
| --- | ---: | ---: |
| Experience | 198422528 | 3039232 |
| Perception | 146292736 | 2764800 |
| Session | 61145088 | 102400 |

共享媒体 164 个 blob、157670215 字节、351 个引用；保留可复用文件，不能只按 SQLite 大小宣称总磁盘节省。三库 freelist 均为零。报告目录 `.zhaoxi/v143-release-20261001/`：`memory-cli.json`、`media-and-vacuum.json`、`backup-restore-verification.json`。

本机 `.venv` editable 元数据从旧 0.7.1 更新为 1.4.3；实际桌面 health 及包版本 1.4.3。首次由工具网络沙箱启动出现 ConnectError 后已退出重启到正常权限，三种模式的 embedding_status 均 available / error null。实际 API 未发送聊天或外部消息，报告 `runtime-verification.json`。最后思考预算修改也已通过受控正常退出/重启加载。

## 最新自动验证与性能

- 最终代码完整 Python：895 passed / 1 skipped / 1 依赖弃用警告，198.21 秒，已包含最后有限思考预算修复；此前相关 Provider / Memory 63 项也通过。
- Node：57 passed；实际可执行内联 JS 语法检查通过。Inspector 覆盖三模式、证据和字面 HTML、指定 ID、空/错误、簇及数据库诊断。
- 最终 wheel：`.zhaoxi/v143-close-wheel/zhaoxi-1.4.3-py3-none-any.whl`；SHA-256 `f8d41cce04654aef2326eb2129a4b26a4a0e75a19de3f1176a072d90692c57e0`；包内源文件与最后代码核对。本机采用 editable 源码运行，wheel 未外部发布。
- 历史缓存向量十查询候选生成最高 80.202 ms，重排最高 22.923 ms；恢复桌面首次冷查询候选生成 428.426 ms，该次后两模式 72.434 / 92.986 ms。最终加载全部修复并重启后，三种模式分别为 92.396 / 69.175 / 89.188 ms，重排 20.4 / 17.272 / 27.975 ms。不含百炼网络耗时；最终实测达到本地目标，保留此前并发负载下 428 ms 的异常值，不能保证所有负载无条件达标。
- 浏览器 localhost 被环境阻止，原生 UI 控制不可用；前端功能与实际桌面接口已验证，视觉和真人交互未验收。

## 续接

Dogfooding 未开始，不代替用户生成 5–7 天观察结论；后续关注热度饱和、簇膨胀、提取 length、召回噪声及 Current Cognition 污染。人工质量 gold、实际视觉体验和并发负载性能边界如实保留。LifeHUD 目录的并行用户改动未回退或覆盖。

```powershell
python -m pytest -q
node --test tests/web/*.test.cjs
python scripts/accept_memory_v143.py
```

测试临时目录默认使用 `.zhaoxi/test-tmp`，pytest 缓存使用 `.zhaoxi/test-cache`；单独指定 `--basetemp` 时也应放在 `.zhaoxi/` 下。本轮根目录遗留的 41 个测试目录及缓存已归档至 `.zhaoxi/test-artifacts/root-cleanup-20261001/`，保留数据以便追溯。

最后一条依赖本机冻结旧报告、快照、查询缓存和复核标签；缺少文件时须先准备对应输入，不会请求外部接口。迁移/回滚命令见根 README。
