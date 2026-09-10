# v1.1.8 当前状态与使用说明

本页汇总截至 2026-09-10 的实际实现。旧版本报告中的测试数字、预算和未完成事项属于当时记录；当前行为以本页及代码为准。原始开发任务书保留，不改写为验收报告。

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
- 分段回复间隔：滑条 0–15 秒，实际间隔为该值到两倍该值；默认 5–10 秒，0 立即显示。两项时间设置存于浏览器本地。
- 模型思考：当前支持官方 DeepSeek API。开启/关闭实际发送 thinking.type=enabled/disabled，主模型后续调用生效，已发出的请求不改变。普通聊天、Beat 和共享主模型的后台任务均使用该设置。备用模型保持自身默认行为。
- 未设置思考开关时保留服务端默认，不强制更改。开关保存于 .zhaoxi/model-settings.json，重启保留；其他接口显示不支持。思考文本不显示在聊天界面；工具调用需要的 reasoning_content 随内部消息保存并回传。
- 主动回复进入普通聊天气泡，沿用分段速度；任务完成、到期提醒、模板 inbox 通报及 system.* 通知仅显示在右侧系统消息区；已有历史记录按事件来源重新分类，不凭正文关键词猜测。“可以这样找我”、系统消息、设置、Debug 均可折叠。
- Debug 的“戳一戳”立即请求一次 Beat，可跳过静默、冷却、输入忙碌及夜间条件；模型仍可选择沉默。请求处理中、明确阻断和主动功能关闭仍生效。

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
