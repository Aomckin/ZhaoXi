# 代码臃肿检查

日期：2026-10-12。依据根目录 `AGENT.md` 的最小实现、边界校验和不吞异常规则。

本次只新增规则与审查记录，没有修改业务代码。扫描 `src/` 和 `tools/` 中 364 个 Python、JavaScript、CSS、HTML 文件，共 52,891 行；排除依赖、生成文件和 `tests/`、`test/` 目录。执行了 Python AST 结构与重复函数检查，并重点核对主循环、路由、FAST 上下文、重试和求职看板保存链路。这是结构扫描与重点审查，不是逐行证明所有代码都必要或多余，也未测量线上性能。

## 应优先处理的具体问题

### 1. 求职看板吞掉备注保存失败，界面与持久化状态可能不一致

- 位置：[dashboard.html](../../tools/career/dashboard/dashboard.html)，`editTimelineNote`，2231–2265 行。
- 证据：2248 行先修改 `entry.notes`；2251 行发起保存请求；2262 行 `.catch(() => {})`；2264–2265 行立即记录编辑并重新渲染。没有检查 HTTP 状态或服务端保存结果。
- 影响：断网、连接失败或服务端返回错误时，界面仍展示新备注，用户难以发现未保存。这是错误处理缺陷，比单纯文件过长更值得先修。
- 最小处理：等待请求并检查结果，保存成功后更新本地备注、记录和渲染；失败时显示错误并保留旧值。无需引入通用请求层。
- 验证：用合成岗位和拒绝的 `fetch` 执行原函数，确认保存失败后备注仍变成新值，渲染与日志各执行一次；没有请求真实服务。

### 2. 内部工具路由的宽泛回退掩盖配置和实现错误

- 位置：[router.py](../../src/zhaoxi/tools/router.py)，160–181 行；[agent.py](../../src/zhaoxi/core/agent.py)，883–890 行。
- 证据：`safe_resolve_tool_context` 捕获所有 `Exception`，丢弃异常对象，重新生成持久工具清单；Core 只记一句通用错误，没有原始异常或堆栈。内部参数 `mode="broken"` 产生的 `ValueError` 也会触发回退。
- 影响：配置错误、属性错误和路由实现错误被混成降级状态，定位困难；正常与回退路径还重复构建工具索引、schema 与诊断字段。回退本身再次调用相同 Registry 方法，不能保证覆盖它们的失败。
- 最小处理：无效 mode 直接失败；如果插件可用性检查确需隔离，放在插件边界保留具体错误，不用整个路由的宽泛兜底代替。
- 约束：现有 `tests/tools/test_tool_router.py` 明确测试无效 mode 回退，调整行为时应同步修改该契约；不能直接删掉而忽略调用方。

### 3. FAST 近期认知失败时静默丢失上下文

- 位置：[fast_chat.py](../../src/zhaoxi/core/fast_chat.py)，284–300 行。
- 证据：读取和渲染近期认知的整个代码段被 `except Exception: pass` 包住，`last_recent_context["errors"]` 仍为空。
- 影响：FAST 会继续生成缺少近期认知的回复，诊断却无法区分“没有内容”与“读取失败”。
- 最小处理：和现有 STANDARD 路径保持一致，记录 `errors["current_cognition"]`，保留可观测异常；是否继续回复应沿用既定降级政策。
- 现有实现可复用：[context.py](../../src/zhaoxi/core/context.py)，140–152 行，已经记录同类失败；无需增加新的异常包装类。

### 4. SDK 与 Core 重试循环重复，SDK 暴露了无效参数

- 位置：[sdk/retry.py](../../src/zhaoxi/sdk/retry.py)，14–42 行；[reliability/retry.py](../../src/zhaoxi/reliability/retry.py)，24–58 行。
- 证据：两份 `retry_async` 函数体的 AST 完全相同；SDK 的 `RetryPolicy.jitter_ratio` 没被 `delay()` 使用，而 Core 版本会校验并计算 jitter。
- 影响：同一重试算法需要维护两份；SDK 参数看起来支持随机抖动，实际没有效果。
- 最小处理：只保留一份无业务依赖的重试循环并复用。SDK 策略若只需要确定性退避，删除无效参数及调用；若公开契约要求 jitter，就统一其行为。
- 约束：两个策略默认 jitter 分别是 0 和 0.1，不能无条件互换。SDK 的公共依赖边界也应保留，不要为去重把整套预算与熔断实现导入 SDK。
- 验证：AST 对比确认循环重复；执行 SDK 策略确认 jitter 为 0 和 1 时第二次退避完全相同。当前 LifeHUD 调用明确传 0，未据此认定现有业务重试已出错。

### 5. 权限续跑中保留不可达分支和重复条件

- 位置：[agent.py](../../src/zhaoxi/core/agent.py)，1549–1579 行。
- 证据：先处理 `position not in approved_positions`，再处理 `stop`，此后 `elif position in approved_positions` 必然成立；1570–1575 行最后的 `else` 无法到达。1578 行的 `elif not stop` 在前一条件为假时也必然成立。
- 最小处理：把 1553 行改为 `else` 并删除不可达拒绝分支；1578 行使用 `else`。保留批次位置校验、权限批准、停止条件和工具结果断言。
- 判断：这是可以局部删除的冗余，无需拆函数或引入权限状态框架。

## 维护热点：有复杂度，但不能仅凭行数删代码

### 6. Agent 主循环同时维护执行、预算、回复恢复和诊断

- 位置：[agent.py](../../src/zhaoxi/core/agent.py)，952–1511 行，`_run_loop` 共 560 行；整个文件 1,783 行。
- 具体负担：预算状态、`final_only`、工具轮数、回复恢复标记和 Trace 更新交织。单轮内还多次调用 `registry.manifest()`；schema 构建时逐工具调用 `usable()`，后者又构建完整 manifest。
- 最小方向：先处理上面的死分支；再核对预算/停止状态是否可以直接使用既有 `LoopSafety`，避免多个标记分别表达相同决定。只有确认同一阶段 Registry 不变时才复用局部清单，不增加全局缓存。
- 验收重点：工具副作用只执行一次、权限暂停续跑、预算停止、回复恢复。这里的模型协议与权限检查属于边界保护，不能按“防御代码”批量删除。重复遍历是优化候选，尚未证明它是实际性能瓶颈。

### 7. Web 入口与求职看板承担过多职责

- [web/app.py](../../src/zhaoxi/web/app.py)：984 行，`create_app` 共 868 行。已有独立 API router，但主函数仍包含诊断、认知调试、工具控制、反思、聊天、会话和语音等路由。后续修改某一组路由时，可沿用已有 router 方式集中维护，避免创建新通用框架或一次性全面拆分。
- [dashboard.html](../../tools/career/dashboard/dashboard.html)：4,031 行，混合样式、界面、CSV 解析、岗位过滤、时间线、外部公司和编辑保存逻辑。只有拆分能解决明确维护问题时再移出对应脚本；文件大本身不是过度工程证据。当前应先修第 1 项保存失败。
- 不宜顺手删掉所有 `getattr`：Web 支持 `StartupUnavailableAgent`，部分服务也确实可选。要区分这些实际契约与内部对象已经保证存在的字段。

## 不应作为减肥目标的现有保护

- Pydantic 工具输入校验、模型输出解析、网络超时及 HTTP 状态检查：实际信任边界。
- 权限批准、不可重复写入、未知执行结果、备份及离线迁移：防止越权或数据损失。
- `RuntimeService`：当前用于保持旧 `agent.<service>` API，并只存储一份值；移除要迁移真实调用方，不能仅因存在转发层就判定多余。
- Tool/插件边界把失败转成带错误信息的结果：与内部 `except: pass` 不同，应审查诊断是否充分，而不是一律禁止边界隔离。

## 本次验证与建议顺序

离线回归：`tests/tools/test_tool_router.py`、`tests/core/test_recent_context.py`、`tests/reliability/test_retry.py`，**13 项通过**。另外运行了备注保存失败的合成复现，以及重试循环 AST 对比和 SDK jitter 检查。没有运行全量测试、真实模型、QQ、正式数据库操作或线上性能测试；这些结果不代表尚未实施的整改已经通过验收。

建议顺序：备注保存错误 → FAST 静默失败 → 权限死分支 → 路由错误契约 → 重试去重；主循环和前端拆分随明确需求逐步处理。
