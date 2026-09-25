# v1.2.8 Internal Activity 交付记录

记录日期：2026-09-25。本文记录已进入代码库的实现及验证边界；需求原文见 [开发任务书](Zhaoxi_v1.2.8_Internal_Activity_开发任务书.md)。运行时包版本仍为 `1.2.7`，本文不代表 v1.2.8 已正式发布。

## 已实现

- `src/zhaoxi/internal_activity/` 提供统一 Tick：根据启用状态、待处理信号、最短间隔、优先级和每轮预算选择活动；最近执行时间、结果、失败次数及待处理标记保存在 `.zhaoxi/internal-activity.db`。失败使用退避，重启后可恢复调度状态。
- Current Cognition 在累计对话达到启动或后续整理阈值时，由后台 Maintainer 整理近期观察。长期 Memory 维护、Agenda 时间状态维护和主动检查进入同一调度链路；具体业务写入仍由原服务完成。
- CLI 和 Web 启动后的后台循环驱动 Tick。维护抽屉的 Internal Activity Debug 显示各活动状态，支持运行 Tick 或单独手动触发四类活动。相关开关、阈值和预算列于 `.env.example`。
- 小桌边的近期状态标题改为「Current Cognition」，通过 `/api/recent-context` 读取 `current_cognition` 并定时刷新。活跃使用原头像，半活跃使用 `data/发呆.png` 对应资源，闲置/离开使用 `data/打盹.png` 对应资源；离开状态不再对头像额外降低饱和度。
- Debug 增加临时强制活跃、半活跃、离开三个按钮；再次点击已选状态恢复自动判断，新的用户聊天也会清除强制状态。

## 验证与限制

- Current Cognition 的本机数据库曾记录一次成功 `UPDATE`：2026-09-25 19:46:08（北京时间），版本 2，叙述长度 139 字符、观察项 12 条。此记录证明该次整理写入成功，不代表长期调度和内容质量已完成验收。
- 自动化测试覆盖调度、后台维护、Debug API、近期状态接口及头像状态映射。2026-09-25 执行 `python -m pytest tests/internal_activity tests/current_cognition tests/memory tests/proactive tests/web -q` 通过；`node --test tests/web/recent_context_board.test.cjs tests/web/avatar_states.test.cjs tests/web/interaction_badge.test.cjs` 共 8 项通过。
- 长时间常驻调度、真实桌面状态切换和多轮真实模型输出仍需后续人工观察。全量测试中若出现 Life HUD 包版本断言失败，应与本功能区分处理。

## 版本边界

[v1.2.9 Decision Layer 任务书](<Zhaoxi_v1.2.9_Decision Layer_Task.md>)只从旧 v1.2.8 文件改名并更新版本标记；本次没有实施其中的功能。
