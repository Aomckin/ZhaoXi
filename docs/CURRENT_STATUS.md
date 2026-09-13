# v1.2.2 当前状态与使用说明

2026-09-13 v1.2.2：修复 v1.1.9 遗留的广记描述与动态能力发现问题。三把 Memory Core 与目录/发现两把钥匙默认常驻；统一 Manifest、能力解析及按轮加载，最多两次扩展；Debug 可实时启停、Force Expose 和恢复默认，override 持久化。详见 [v1.2.2 报告](Zhaoxi_v1.2.2_Release_Notes.md)。

2026-09-13 v1.2.1：单窗口 MAIN / COMPANION、原生八向缩放、独立 geometry、一次性置顶与临时通知。陪伴模式按用户要求移除头像抬头，输入栏仅保留文字和发送。浏览器 UI 默认关闭，开发可设置 `ZHAOXI_DEV_BROWSER_UI=true`。完整实现与验收边界见 [v1.2.1 报告](Zhaoxi_v1.2.1_Release_Notes.md)。

以下保留 v1.2.0 阶段记录。

2026-09-12 Phase 3：已使用 `data/ACTIVE头像.png` 的专用头像；小桌边在所有窗口尺寸下默认收起，通过右侧把手打开。系统消息、设置、维护抽屉位于公告栏下方；新的主动留言点亮金点，不自动展开，可见后沿用现有 activate 接口确认已读。最新布局及验收见 [Phase 3 报告](Zhaoxi_v1.2.0_Phase3_Release_Notes.md)。

窗口、托盘、网页和快捷方式已统一为向日葵图标。运行中的图标需彻底退出托盘后重启加载；项目快捷方式由 `scripts/create_desktop_launcher.ps1` 生成，使用 `sunflower.ico`。

阶段记录：[Phase 1](Zhaoxi_v1.2.0_Release_Notes.md) / [Phase 2](Zhaoxi_v1.2.0_Phase2_Release_Notes.md)。当前行为以 Phase 3 和本页为准。

## v1.1.x 业务与设置基线

本节保留截至 2026-09-10 的业务基线；上方视觉状态更新于 2026-09-12。旧版本报告中的测试数字、预算和未完成事项属于当时记录；当前行为以本页及代码为准。原始开发任务书保留，不改写为验收报告。

## 动态 ToolProvider 与 MCP

Core SDK 1.1 新增协议无关的 `ToolProviderProtocol`。Provider 产生的每个 Tool 独立进入现有 Registry；Agent、Planner、Workflow 不感知来源。Registry 支持运行时原子刷新，并在 CLI/Web 退出时统一关闭 Provider。

MCP 实现只存在于 `tools/mcp/`：stdio JSON-RPC Client、Server 进程生命周期、MCP inputSchema 校验与 Zhaoxi Tool Schema 适配、MCP annotations 权限映射均不进入 Core。当前本机安装 9 个 Server，合计发现 78 个 Tool。

默认不启用。启用全部或部分 Server：

```dotenv
ZHAOXI_TOOL_MCP_ENABLED=true
ZHAOXI_TOOL_MCP_SERVERS=filesystem,time,playwright
ZHAOXI_TOOL_MCP_TIMEOUT_SECONDS=20
```

Filesystem 默认仅开放朝汐启动工作目录；Memory 数据与 Playwright 输出写入 `tools/mcp/data/`。Everything 文件搜索 MCP 已安装但仍要求系统提供 `es.exe`。

## 界面设置

- 输入合并：0–30 秒，默认 15 秒，0 关闭。只合并模型请求，每次发送的气泡、时间和图片归属独立保存。旧记录缺少发送边界，无法可靠拆回。
- 分段回复间隔：滑条 0–15 秒，实际间隔为该值到两倍该值；默认 5–10 秒，0 立即显示。
- v1.1.9 起，两项时间设置同时持久化到 `.zhaoxi/interface-settings.json`，重启 Core 或浏览器存储丢失后仍可恢复；旧 `localStorage` 值保留为兼容回退。
- 模型思考：当前支持官方 DeepSeek API。开启/关闭实际发送 thinking.type=enabled/disabled，主模型后续调用生效，已发出的请求不改变。普通聊天、Beat 和共享主模型的后台任务均使用该设置。备用模型保持自身默认行为。
- 未设置思考开关时保留服务端默认，不强制更改。开关保存于 .zhaoxi/model-settings.json，重启保留；其他接口显示不支持。思考文本不显示在聊天界面；工具调用需要的 reasoning_content 随内部消息保存并回传。
- 主动回复进入普通聊天气泡，沿用分段速度；任务完成、到期提醒、模板 inbox 通报及 system.* 通知仅显示在右侧系统消息区；已有历史记录按事件来源重新分类，不凭正文关键词猜测。“可以这样找我”、系统消息、设置、Debug 均可折叠。
- Debug 的“戳一戳”立即请求一次 Beat，可跳过静默、冷却、输入忙碌及夜间条件；模型仍可选择沉默。请求处理中、明确阻断和主动功能关闭仍生效。
- Debug 的“重启 Core”已对 EventSource 长连接设置有界优雅关闭，不再因事件流持续连接而固定触发停止超时。

## ACTIVE Beat 与桌面判断

常规 Beat 静默阈值 180 秒、决策冷却 300 秒。每会话初始主动预算 2，上限 3；发送扣除，用户有效回应补充，模型沉默不扣除。LOW 不自动硬阻断，BLOCKED 阻断。

鼠标高频不单独触发 busy。键盘默认阈值 120 次/分钟，20 个有效输入分钟后结合个人 P80；统计 P50/P80/P95，最多 1440 个输入分钟，仅在内存保留。1m/5m < 0.6 或停止键盘超过 15 秒解释为刚停下来。朝汐自身窗口排除输入 busy。

Beat 硬性 desktop_busy 还要求新鲜样本及 1m、5m 同时达到 max(240, 自适应阈值, P95)。普通高输入交由模型结合上下文判断。

每次 Beat 最多一次模型调用；总预算 **32000 Token**，生成上限 **16000 Token**，请求等待上限仍为 30 秒。JSON 模式加严格字段校验，兼容完整 JSON 代码块。失败维持有界冷却，不以残缺正文投递。

## 日志与已确认问题

BEAT 日志含调度、Gate、输入证据、模型 action/confidence、失败阶段和投递结果。provider_error_code 区分预算、传输等错误，不再仅凭 SILENT 推测。

- 14:40 后四次旧日志仅能确认模型阶段失败，无法还原具体异常。
- 19:47:13 实机记录 COMMENT、delivered=true。
- 20:13:02 实机明确 provider_token_budget_exhausted，原 4000 总预算错误压制响应。
- 20:22:40、20:23:49 返回 finish_reason=length 且无可见正文；原 1200 生成限制已提高。
- LifeHUD 取消超时绕过退避已修复；其 502 不等同于 Beat 未调度或模型选择沉默。

详细历史证据见 [ACTIVE 排查记录](ACTIVE_Beat_Diagnostics_Fix.md)。隔离真实模型成功不替代全部 UI 长时场景验收。最新自动测试结果见此次开发回复；历史报告中的数量不代表当前测试总数。

## 技术依据

[DeepSeek 思考模式官方文档](https://api-docs.deepseek.com/guides/thinking_mode/)：思考开关参数及工具调用的 reasoning_content 回传要求。
