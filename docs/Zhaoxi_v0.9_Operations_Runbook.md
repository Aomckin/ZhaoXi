# Zhaoxi v0.9 运维与恢复手册

## 构建与安装

在干净的 Python 3.12+ Windows 10/11 环境中：

```powershell
python -m pip install -e ".[dev]"
.\scripts\build_release.ps1
.\scripts\install_windows.ps1 -Wheel .\dist\zhaoxi-0.9.0-py3-none-any.whl
```

需要当前用户开机自启时额外传入 `-EnableAutoStart`。安装脚本只修改当前用户环境；不会复制 `.env`、数据库或密钥。

卸载：

```powershell
.\scripts\uninstall_windows.ps1
```

卸载默认保留 `.zhaoxi` 中的数据库、备份、配置和日志。删除用户数据不属于卸载脚本职责，必须由用户另行明确执行。

## 启动诊断

- `GET /api/health`：仅检查进程和版本。
- `GET /api/diagnostics`：查看组件开关、进程指标和数据库健康摘要，不包含用户正文。
- 日志默认位于 `.zhaoxi/logs/zhaoxi.log`，按大小轮转。
- 权限审计默认位于 `.zhaoxi/audit/permission.jsonl`。

诊断顺序：先检查配置是否完整，再检查 storage 中是否有 `healthy=false`，最后使用响应 `trace_id` 对照日志。不得把 `.env`、数据库或原始审计文件直接作为公开问题附件。

## 备份

`BackupManager.create()` 对所有存在的 SQLite 数据库使用 Online Backup API，逐个执行完整性检查并生成 SHA-256 manifest。manifest 最后写入，是备份完成标志。默认保留 14 份。

备份期间允许读取和正常 SQLite 写入；外部 JSONL 文件以文件快照方式保存。备份目录必须使用专用目录，恢复器拒绝目录逃逸和未知数据项。

## 恢复

恢复前必须停止 Web/Desktop/CLI 写入。`BackupManager.restore(path)` 会：

1. 验证路径、manifest、文件大小、SHA-256 和 SQLite integrity；
2. 对当前状态再生成一份 safeguard backup；
3. 验证全部暂存副本；
4. 使用 SQLite Backup API 恢复数据库；
5. 返回 safeguard 路径，供必要时回退。

任何预检失败都不会替换当前数据。若进程在多库恢复期间被强制终止，使用返回的 safeguard 重新执行恢复。

## Provider 故障

- 408、429、502、503、504 和网络错误按 transient 处理；在有限次数内指数退避。
- 400、401、403、响应 schema 错误不重试，也不切换备用 Provider。
- transient 重试耗尽后才切换已配置的 fallback Provider。
- 连续失败达到阈值后熔断，冷却后进入 half-open 探测。
- 每个 Interface 请求有模型调用硬预算，超出后安全终止。

## 崩溃恢复边界

- Session 只恢复有界的 user/assistant 文本，不保存 Tool 原始 payload 和 metadata。
- Planner Goal、Plan、Step、Observation 和等待状态由 SQLite 恢复。
- Permission pending、冻结请求、一次性 grant、消费和撤销状态由 SQLite 恢复；TTL 不刷新。
- 不确定的外部写结果不得自动重放，应查询事实源或请求用户确认。
- Workflow、Proactive 和 Reflection 继续使用各自的 SQLite 幂等键和状态机。

## 安全边界

- Tool 参数有总大小、深度、集合和 URL 约束；默认拒绝 loopback、私网、link-local 和非 HTTP(S) URL。
- Tool 输出被标记为不可信并截断，不能覆盖 Permission 决策。
- 高风险动作必须通过 ToolExecutor 与 PermissionGateway；审计写入失败时操作失败关闭。
- 当前版本提供应用层权限、参数和审计边界，不宣称具备操作系统级沙箱。
