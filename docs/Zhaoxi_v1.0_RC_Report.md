# Zhaoxi 1.0 RC 验证记录

> 日期：2026-09-02  
> 分支：`v1.0`  
> 主机：Windows 10 Pro 10.0.19045，Python 3.13.0

## 自动化结果

- `python -m pytest`：240 passed，唯一 warning 为 Starlette TestClient/httpx 的上游弃用提示。
- `python -m compileall -q src tools tests scripts`：通过。
- `git diff --check`：通过；仅显示 Git 的 LF→CRLF 工作区提示。
- 加速 soak：500 次并发分批请求；响应缓存保持 25，会话保持 20。
- PowerShell 构建、安装和卸载脚本语法解析：通过。

## 产物验证

- `zhaoxi-1.0.0-py3-none-any.whl`
- `zhaoxi_lifehud_tool-1.0.0-py3-none-any.whl`
- `SHA256SUMS.json`

构建脚本会清理旧 wheel 与 LifeHUD-Tool 构建缓存，拒绝包含用户数据、秘密、日志、音频或 Python bytecode 的 wheel。两个 wheel 已安装到临时空目录并从该目录成功导入，版本均为 1.0.0。

## 纵向闭环

- 首次启动：缺配置进入 Setup Mode，`--doctor` 给出无密钥的可执行提示。
- 记忆：显式保存后从新 Agent/SQLite 实例检索并注入上下文。
- Life HUD：公开 HTTP Mock 契约覆盖铁幕开幕、动态权限、状态回读、落幕及外部失败。
- Proactive/Reflection：提醒调度与带 Memory/Life HUD evidence 的回顾生成、历史查询通过。
- 恢复：v1.0 新数据备份后继续修改，再恢复旧快照；恢复前 safeguard 可验证。

## 安全与隐私

- 审计不可写时在 Tool 执行前失败关闭。
- ToolResult prompt injection 无法绕过 WRITE 权限确认。
- 不确定写结果进入 `needs_reconciliation`，不自动重放。
- SSRF、路径逃逸、超深和超大 Tool 参数被拒绝。
- Setup diagnostics、Web diagnostics、capabilities 与 Reflection safe view 不包含测试密钥或原始 evidence excerpt。

## 未实测与延期

- 未在 Windows 11 实机运行；不据此推断兼容性。
- 未执行会修改当前用户 Python 安装和 HKCU 自启项的真实安装/卸载脚本；使用临时空目录完成等价 wheel 安装验证，脚本边界由自动化和语法解析覆盖。
- 代码签名、自动更新、操作系统级 Tool Sandbox、通用 Files/Calendar/GitHub 写工具属于 P2。
