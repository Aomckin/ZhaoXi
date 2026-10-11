# 17:15 回复 JSON 放行与群聊空搜索补修

日期：2026-10-11（Asia/Shanghai）。状态：源码修复及隔离回归完成；正式实例未重启，真实模型日用复验待进行。

## 生产证据

用户请求“虚拟桌宠模拟器，去回想一下”，request_id 为 c46ea047-7d90-43e0-961a-e5491ab072af。只读核查 zhaoxi.log 和 session.db：

- 17:15:10 开始。前三次 search_memories 及一次 read_social_context 原文回查成功。
- 17:16:23 / 17:16:25 的两次群聊条件搜索返回 not_found，被计作执行失败并锁定工具，设置 tool_failure_limit。后续同批回查及记忆检索被阻断（日志 5694、5699、5702、5704）。
- 17:16:35 最终响应 finish_reason=stop，无工具调用；main_reply_protocol 把 22 字符判为普通 text，status=decoded、awareness=missing（日志 5733）。随后响应记为 succeeded、repair_round=0；会话保存的 assistant 正文确为 {"type":"json_object"}。
- 全程约 86 秒，最终任务 partial_success。未保存完整上游原始响应，不能据此断言配置对象是由模型、兼容服务还是中间转换引入。

## 根因及修复

### 完整 JSON 不能证明正文完整

_decode_reply_object 在 JSON 没有 reply、也没有若干已知协议字段时，仍走旧的 literal JSON 文本回退，绕开 main_reply_contract。此前只拦截截断 JSON、缺少 awareness 和裸工具参数，遗漏合法 JSON 的错误形状。

在已声明主回复契约时，所有缺少 reply 的 JSON 对象、数组、标量都以 invalid_reply_protocol 拒绝；截断数组也不作为普通文本交付。普通旧路径的 literal JSON 兼容保留；需要给用户展示 JSON 时，可以放在有效 reply 字符串中。没有修改工具调用或辅助决策字段校验。

STANDARD 会由原有恢复路径在预算允许时最多补修一次，只生成正文，不调用/重放工具；补修仍失败或步骤/预算不足时，明确保留失败及已执行结果，不把 JSON 当成功正文。FAST 使用相同解析检查拒绝异常，继续沿用既有失败处理，不增加 FAST 的自主工具或额外修复策略。

### 条件搜索没有命中是查询结果

SocialTraceReader.search 在查询成功且没有匹配项时返回 not_found；工具原先只把 complete / partial 认作成功。LoopSafety 因而把正常未命中计入重复工具失败，并提前禁止后续探索。

仅在条件搜索（未指定 reference）且 status=not_found 时返回 success=true、error=null、result_code=empty。数据继续携带 not_found、空 records、total_records=0 及“没有命中不代表群内从未发生”的提示，让主模型知道没有查到证据。补充工具描述，允许根据已知线索调整条件或读取其他资料，不伪造命中。

按明确 reference 读取缺失原文仍失败；权限拒绝、参数校验、输出预算和真实执行异常也保持原处理。没有放宽群/插件隔离，没有修改失败次数、无进展、模型/工具轮次或 Token 预算限制。

## 验证

- 768 项相关 Python 回归通过，覆盖 Core、Decision、CognitiveStream、Cognitive、Interfaces、Permission、Models 和 Web；仅现有 Starlette TestClient 弃用提示。
- 其中专项范围 109 项通过，与上面重叠。新增 32 个参数化案例：主回复/FAST 的错误 JSON 形状、DeepSeek JSON mode 与标准 schema Provider 边界、合法 reply 内展示 JSON、Owner/QQ 群范围内空搜索及跨群拒绝、实际空搜索后同批记忆检索不被阻断，以及异常收尾补修成功/失败/无剩余步骤。
- 组合回归复现“两次空搜索 → 真实后续记忆检索 → 配置 JSON → 一次纯正文补修”，确认工具只执行一次、错误正文不保存、无 tool_failure_limit 误触发。
- git diff --check 通过。测试使用临时数据库、真实本地检索实现及假 Provider / MockTransport，未请求真实模型、读取业务 API 或写生产数据。

## 加载与限制

需重启正式 Core/Desktop 加载后端解析和工具结果修复。已经保存的旧异常回复不自动删除或改写；本次不重放 17:15 的请求。

本补丁解决本地错误交付和空搜索误终止，不证明上游不会再次返回异常结构。上游再次出错会进入受预算约束的恢复或明确失败；正常空结果也不保证后续搜索必能找到资料。
