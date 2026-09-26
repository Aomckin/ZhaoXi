# ZhaoXi v1.2.9 Release Notes

发布日期：2026-09-26。运行时、包元数据、CLI、Health 和 Debug 统一为 `1.2.9`。

## 当前稳定能力

- v1.2.8 Internal Activity 正式并入：后台按信号、间隔与预算维护 Current Cognition、长期记忆和 Agenda，并协调主动检查；状态持久化且可在维护抽屉查看。
- v1.2.9 Decision Layer 正式并入：明确决策意图时按需读取少量规则、日程、近期状态和相关长期记忆；Guard 固定 L0/L1/L2 的方向，主回复仅选择表达，记录判定与人工覆盖。首批规则未授权自动工具执行。
- Current Cognition 是当前唯一的近期认知状态来源；旧 STM 仅用于只读启动参考和备份恢复，Working Notes 仅用于历史备份恢复。
- Action Trace、请求预算、Context Debug、Tool 状态和错误归因保持 v1.2.7.x 基线。
- Agenda、长期 Memory、Tool Discovery、权限确认、Planner、Workflow 和 Emoji Reply DSL 保持现有行为。`save_emoji` 仍是工具，`send_emoji` 不再注册为工具。

## Structural Cleanup

`build_agent()` 从 CLI 移入 `bootstrap/runtime.py`，按 Model、Knowledge、Tools、Cognition、Proactive 和 Storage 拆分装配。Backup DataStore 集中注册，legacy 来源显式标记。Settings 仅标注旧字段的用途，不改变环境变量名称、数据路径或用户可见行为。

## 已知限制

Decision Layer 不能代替用户处理 L2 价值取舍，也不会自动改写正式决策规则。真实模型、Life HUD 与桌面主动行为依赖本机服务和配置；离线自动测试不能替代这些人工场景的验收。

下一阶段计划见 [未来开发计划](../roadmap/Zhaoxi_未来开发计划_26.09.21补全版.md)。本版本不包含该系统。

## 验收状态

- 2026-09-26：全量 Python 自动测试通过；新增装配、版本、DataStore、legacy Context 与 Emoji 路径回归测试通过。`python main.py --doctor` 返回 `version=1.2.9`、`status=ready`。
- 隔离数据目录中的真实模型普通对话冒烟在 Provider 网络连接阶段返回 `ConnectError: All connection attempts failed`，未获得模型回复。普通聊天、Life HUD Tool、Decision、Agenda、权限、主动心跳与桌面重启的真实服务人工场景仍需在模型端点可达后补验；此记录不将它们标为通过。
