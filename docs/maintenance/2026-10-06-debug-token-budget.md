# Debug Token 与 Planner 追加预算设置

日期：2026-10-06。按用户最新要求，Token / Planner 预算控件仅放在 Web Dashboard 的“设置 / 运行观测 → 调试”，已从 Desktop 侧边栏“常用调试”移除。

## 行为

| 控件 | 含义 | 范围 |
| --- | --- | --- |
| 基础 Token 预算 | 一轮请求所有模型调用累计的输入与输出 Token 软上限 | 1,000–10,000,000 |
| 总硬上限 | Planner 追加后仍不能超过的总预算 | 1,000–10,000,000，不能小于基础预算 |
| 收尾预留 | 在基础预算内为最终回复保留的额度 | 0–1,000,000，必须小于基础预算 |
| Planner 追加上限 | 一次追加申请最多可批准的 Token 数，0 表示关闭追加 | 0–10,000,000 |

整组填写后点击“保存预算”，避免单项修改过程中出现暂时不合法的组合。立即保存到现有界面设置文件中的 `request_budget`，下一次前台请求生效；现有请求继续持有原来的不可变 BudgetPolicy。聊天、重新生成及确认续跑读取同一 Provider 请求预算；这不是单次模型输出的 `max_tokens`，也不是截图中的每日内部活动次数预算。

Planner 仍按既有运行时规则审批：接近预算警戒线、有真实进展且剩一项操作等条件必须满足，最多批准一次，批准额度同时受追加上限和总硬上限裁剪。本次未放宽这些规则，也未启用第二次追加。填写 0 时申请不能获得追加额度。

“恢复预算默认值”清除持久化覆盖值，恢复当前配置/环境变量推导的预算。通常默认基础 100,000、追加 25,000、收尾预留 8,000；硬上限按配置推导（默认 140,000）。不覆盖用户已有环境配置。

Dashboard 通过既有 SSE 设置事件刷新；正在输入的未保存预算不被其他设置事件或定时刷新覆盖。Desktop 不再显示预算控件，收到预算设置广播也不会访问不存在的表单元素。保存与恢复有状态提示。Core 尚未完全就绪时仍能显示配置预算；运行诊断 `/api/debug/budget-context` 显示当前有效预算。

## 接口与实现

- `GET /api/settings/budget` 返回当前有效的四项值。
- `PUT /api/settings/budget` 验证并保存整组值；严格整数校验与字段/组合范围校验，非法输入不写文件、不修改运行预算。
- `DELETE /api/settings/budget` 恢复当前配置默认值。
- 沿用界面设置的鉴权、原子文件替换、广播与启动恢复流程，局部修改其他 Debug 开关不会丢失预算覆盖。
- `settings_api.py` 更新 ResilientProvider 的下一次请求预算；`app.py` 启动时恢复，并让诊断读取有效策略。
- 预算表单仅保留在 `engineering.html`，`index.html` 已移除表单及专用样式。共用 `shell.js` 在表单不存在时跳过预算绑定、加载和刷新，Desktop 其他调试开关仍正常。没有新增配置文件、依赖或预算审批机制。

## 验收

后端专项 **78 项通过**：Web 设置、请求链路、Dashboard、Planner、预算审批/重试、Provider 预算诊断和 Desktop。

新增两项行为回归验证：保存后实际 Gateway 请求使用新策略；20,000 基础预算、23,000 硬上限、5,000 追加上限时最多批准 3,000；追加设 0 后批准额为 0；重建应用恢复覆盖，重置恢复自定义配置；鉴权失败、非整数、超范围和组合错误均不修改文件或实时策略。既有设置完整响应的测试断言同步增加 `request_budget: null`。

初次实现完成 21 项浏览器检查；按用户要求调整为仅 Dashboard 后，重新运行隔离 Edge 浏览器验收，**22 项通过**，检查预算仅在 Dashboard 出现、Desktop 表单缺席、Dashboard 保存/草稿保留/0 关闭追加/重载恢复/恢复默认，以及原有两端快捷调试行为。无页面 JavaScript 错误；主动请求均为模拟，真实模型调用与外部发送均为 0。Dashboard 控件截图已检查；Desktop 移除后的截图用于确认侧边栏不再展示预算设置。

测试命令：

```powershell
.venv/Scripts/python.exe -B -X utf8 -m pytest tests/web/test_quick_debug.py tests/web/test_web.py tests/web/test_dashboard.py tests/reliability/test_budget_policy.py tests/reliability/test_retry.py tests/models/test_budget_context_integration.py tests/planner tests/desktop/test_app.py -q -x --tb=short --basetemp=.pytest_cache/tmp-budget-debug-final
```

`node --check` 与 `git diff --check` 通过。所有临时文件放在 `.pytest_cache/`；未修改正式预算、运行数据库或重启正式实例。新增后端入口需完全退出托盘再重新启动以加载源码，之后预算调整不需要重启。

[结构化证据](evidence/2026-10-06-debug-token-budget.json) · [Desktop 侧边栏（无预算控件）](evidence/2026-10-06-budget-controls-desktop.png) · [Dashboard 控件截图](evidence/2026-10-06-budget-controls-dashboard.png)。
