# Zhaoxi 1.0 Release Notes

## 核心能力

- 统一的对话、Memory、Planner、Workflow、Permission、Proactive 与 Reflection Core。
- CLI、只监听 loopback 的 Web Shell，以及 Windows Desktop/Voice 可选入口。
- 首次启动诊断、Setup Mode、能力目录和无用户正文的运行诊断。
- 独立 LifeHUD-Tool 1.0：Core 只看到一个 `lifehud` Tool，按 operation 动态解析读写权限。
- Daily、Weekly、Monthly、Seasonal Reflection，支持 Memory 与 Life HUD 只读证据。

## 安装与数据策略

v1.0 按全新安装交付，不承诺迁移早期版本产生的人工测试数据。若旧 `.zhaoxi` 测试目录导致 schema 或健康检查失败，请先将该目录移到安全位置，再重新启动。安装和卸载脚本默认不删除用户数据。

## 安全边界

- 写操作继续经过 PermissionGateway；不确定写结果不会自动重放。
- Web/Desktop API 默认仅监听本机，Desktop 使用每次启动随机会话令牌。
- 诊断、metrics 与能力目录不包含用户正文、密钥或原始 Reflection evidence。
- LifeHUD-Tool 只调用公开 HTTP API，不读取 Life HUD 内部文件或数据库。

## 已知限制

- 代码签名、自动更新和操作系统级 Tool Sandbox 未包含在 v1.0。
- 通用 Files、Calendar、GitHub 写工具不属于本版范围。
- Voice 输入与 Desktop 依赖为可选组件；不可用时 CLI/Web 仍可运行。
- Windows 版本兼容性以实际 RC 冒烟记录为准，未实测环境不作保证。
