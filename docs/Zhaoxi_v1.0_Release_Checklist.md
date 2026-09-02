# Zhaoxi 1.0 Release Checklist

## 自动化门禁

- [x] 全量 pytest 通过，单文件关键测试可独立运行。
- [x] `compileall` 与 `git diff --check` 通过。
- [x] Core/LifeHUD-Tool 源码、metadata、wheel 均为 `1.0.0`。
- [x] wheel 不包含 `.env`、数据库、日志、备份、音频、bytecode 或测试秘密。
- [x] wheel 在临时空目录安装并成功导入。
- [x] SHA-256 校验文件由构建脚本生成并与 wheel 一致。
- [x] 加速 soak 无无界响应缓存或会话增长。

## 用户旅程

- [x] 空配置进入 Setup Mode，诊断给出可执行下一步。
- [x] 对话、显式记忆、重启后检索通过。
- [x] Life HUD 开幕、权限确认、状态回读、落幕通过 Mock HTTP 契约验收。
- [x] 提醒与带证据 Reflection 生成、查询通过。
- [x] Provider/Life HUD 故障、权限拒绝与未知写结果不产生成功误报。

## Windows RC

- [x] Windows 10 主机完成临时空目录 wheel 安装、导入与 `--doctor` 检查。
- [x] Desktop/托盘/快捷键/Voice 可选依赖由自动化测试和启动诊断覆盖。
- [x] 未实测 Windows 版本记录在 Release Notes，不推断兼容性。

## 发布

- [x] README、CODEBASE_STATUS、Release Notes 和已知限制一致。
- [x] P0 为零；延期项均为用户可见的 P2。
- [ ] 仓库 commit 与最终构建 commit 尚待提交后记录。
