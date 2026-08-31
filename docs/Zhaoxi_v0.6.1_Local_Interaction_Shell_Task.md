# Zhaoxi v0.6.1 · Local Interaction Shell 小型任务书

> 项目：**Zhaoxi / 朝汐**  
> 版本：**v0.6.1 · Local Interaction Shell**  
> 性质：开发期轻量交互壳  
> 目标：**给当前 Zhaoxi Core 套一个本地可日用、可黑盒测试的轻量聊天窗口，替代 PowerShell 作为主要人工交互入口。**
>
> 本版本不是正式 Presence v0.7，不追求桌面常驻、语音、Live2D 或完整产品化。
>
> 核心原则：
>
> **UI 只负责“看见朝汐”和“把话递给朝汐”，绝不复制 Agent 逻辑。**

---

## 1. 技术方向

优先采用：

```text
Local Web UI
+
Python 本地服务
```

推荐结构：

```text
Browser
   ↓
Local Web UI
   ↓
Interface Adapter
   ↓
Zhaoxi Core
   ↓
Memory / Planner / Permission / Workflow / Proactive / Tools
```

第一版可使用：

- FastAPI / 现有 Python Web 框架
- 原生 HTML + CSS + JS
- WebSocket 或 SSE 用于流式事件
- 若当前 Core 暂不支持流式回答，可先整段返回

不建议本版引入：

- Electron
- Tauri
- pywebview
- React/Vue 大工程
- Streamlit / Gradio 作为长期主界面

先把本地浏览器壳跑顺。

---

## 2. 启动方式

支持类似：

```bash
python main.py --web
```

启动后输出：

```text
Zhaoxi Local Shell
http://127.0.0.1:8765
```

端口配置化，例如：

```env
ZHAOXI_WEB_HOST=127.0.0.1
ZHAOXI_WEB_PORT=8765
```

默认只监听本机。

不得默认暴露到公网。

---

## 3. 主聊天界面

第一版只做必要内容：

```text
┌──────────────────────────────────────┐
│ 朝汐                                 │
│                                      │
│ 暗苟：今天 Focus 了多久？             │
│                                      │
│ 朝汐：今天有效 Focus 50 分钟……        │
│                                      │
│                          [ 输入框 ]   │
│                              [发送]   │
└──────────────────────────────────────┘
```

要求：

- 用户消息气泡
- 朝汐消息气泡
- Markdown 渲染
- 多轮滚动
- Enter 发送
- Shift+Enter 换行
- 请求中状态
- 禁止重复发送
- 保留当前 Session

---

## 4. Permission Card

这是本版最重要的 UI 能力之一。

当 Core 进入：

```text
WAITING_FOR_PERMISSION
```

不要让用户手输：

```text
/approve <id>
/deny <id>
```

而是显示：

```text
朝汐想执行：

结束当前 Life HUD Focus
权限：WRITE

[允许]  [拒绝]
```

要求：

- 卡片展示操作名称
- 展示权限级别
- 展示必要参数摘要
- `允许` 调用现有 Permission approve
- `拒绝` 调用现有 Permission deny
- 继续恢复原 Agent / Workflow
- 不在前端自行执行 Tool

开发者命令 `/approve` `/deny` 继续保留。

---

## 5. Agent Activity

PowerShell 中的：

```text
[MODEL]
[TOOL]
[COGNITIVE]
[httpx]
```

不要原样搬到主聊天区。

改为轻量状态：

```text
正在思考…
正在读取 Life HUD…
正在检查记忆…
正在执行 Workflow…
等待权限确认…
```

只展示人能理解的状态。

详细日志继续进入：

```text
terminal / log file / debug drawer
```

---

## 6. Debug Drawer

增加可折叠开发者面板，例如右上角：

```text
Debug
```

展开后可查看：

```text
Route: DIRECT / TOOL / PLAN / WORKFLOW
Agent Step
Tool Calls
Memory Hits
Planner Goal
Workflow Name
Permission State
Trace ID
Proactive Event
```

默认折叠。

普通聊天界面不得出现：

```text
raw JSON
Python dict
DSML
ToolResult
WorkflowResult
Traceback
```

---

## 7. Proactive Agent 对接

v0.6 已有 Proactive Agent，本版只做可视化入口，不重构主动逻辑。

当 Proactive Agent 产生 Delivery 时：

```text
INFO
NOTICE
IMPORTANT
URGENT
```

UI 需要能够显示通知卡片。

例如：

```text
[NOTICE]
朝汐：当前铁幕已经持续较长时间，要看看状态吗？
```

要求：

- 主动消息与普通回复视觉上可区分
- Quiet / Night Mode 下遵守 Core 原有策略
- UI 不自行判断是否应该提醒
- 所有主动决策仍来自 Zhaoxi Core

---

## 8. Session

第一版至少支持：

```text
当前会话
清空会话
```

可选：

```text
新建 Session
切换 Session
```

若现有 Session Store 已支持多会话，则接入。

不要为了 UI 重写 Session 系统。

---

## 9. 接口边界

前端只允许调用统一 Interface API，例如概念上：

```text
POST /api/chat
POST /api/permission/{id}/approve
POST /api/permission/{id}/deny
GET  /api/session
GET  /api/activity
WS   /api/events
```

具体路径可调整。

禁止：

```text
前端直接调用 Life HUD
前端直接访问 Memory DB
前端直接执行 Tool
前端自己判断 Planner / Workflow
```

所有能力必须经过 Zhaoxi Core。

---

## 10. UI 风格

第一版只做：

- 干净
- 浅色
- 蓝白系
- 信息层级清楚
- 少量犬娘 / 朝汐气质

不要把时间耗在：

- 大型动画
- Live2D
- 复杂主题系统
- 大量设置页
- 视觉特效堆叠

先做到：

> **比 PowerShell 舒服十倍，但工程量只增加一点点。**

---

## 11. 错误体验

遇到：

```text
Provider Error
Life HUD Offline
Tool Error
Planner Error
Workflow Error
Permission Error
```

主界面只显示：

```text
朝汐：这次操作没成功，原因是……
```

详细错误放 Debug Drawer / log。

页面不得白屏。

一次请求失败后仍能继续聊天。

---

## 12. 黑盒测试场景

### Case A：普通聊天

```text
“你是谁？”
```

要求：

- 正常自然语言回复
- 无 Debug 垃圾进入聊天区

### Case B：Life HUD 查询

```text
“今天 Focus 了多久？”
```

要求：

```text
UI：正在读取 Life HUD
↓
Core 调 Tool
↓
自然语言回复
```

### Case C：Permission

```text
“把当前专注结束掉。”
```

要求：

```text
Permission Card
→ 点击允许
→ 原流程继续
→ Tool 执行
→ 最终自然语言结果
```

### Case D：拒绝

同样触发写操作：

```text
→ 点击拒绝
→ Tool 不执行
→ 朝汐正常说明
```

### Case E：Planner

复杂请求：

```text
“帮我看看最近几天的状态并总结一下。”
```

要求：

- Planner / Tool 能正常运行
- Activity 区能看到阶段变化
- 聊天区只显示最终自然语言

### Case F：Proactive

使用 Fake Clock / 测试事件触发一条主动通知。

要求：

- UI 能接收并显示
- 不需要刷新页面
- 主动消息不污染当前输入状态

---

## 13. 自动测试

至少补：

```text
1. Web Chat → Core 正常调用
2. Permission approve / deny
3. Core Error → HTTP/API graceful response
4. Proactive Event → UI event channel
5. Session clear
6. raw internal object 不进入普通 response
```

UI E2E 可保持轻量，不要求本版大规模浏览器自动化。

---

## 14. 本版不做

明确不做：

- 正式桌面客户端
- 系统托盘
- 开机自启
- 全局快捷键
- 语音唤醒
- STT / TTS
- Live2D
- QQ 接入
- 手机端
- 多用户
- 公网部署
- 登录鉴权体系
- 文件上传大系统
- 完整设置中心
- 重构 Zhaoxi Core

这些属于后续 Presence / Interface 路线。

---

## 15. 完成标准

v0.6.1 完成后，暗苟酱应可以主要通过本地页面完成：

```text
聊天
↓
查询 Tool
↓
Planner
↓
Workflow
↓
Permission
↓
Proactive Notification
```

而不需要一直盯 PowerShell。

PowerShell 从：

> 主要交互界面

降级为：

> 日志与开发调试窗口。

---

## 16. 版本定位

```text
v0.6
朝汐开始拥有主动性。

v0.6.1
给现在的朝汐一个真正能住进去的本地小房间。

v0.7
再正式处理 Presence：
桌面常驻、语音、多入口与长期交互体验。
```

> **这版不是做漂亮外壳。**
>
> **这版是给 Agent 黑盒测试和日常使用建立一个真正的人类界面。**
