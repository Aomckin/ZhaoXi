# Zhaoxi v1.2.1 Development Task
# Desktop Shell & Companion Mode Rebuild

> 基线：回滚至稳定的 v1.2.0 Phase 3
> 类型：重做版任务书
> 核心目标：重做桌面壳、Companion Mode、原生通知与浏览器入口。
> 第一原则：**禁止创建第二个 Companion top-level window。**

---

## 0. 为什么重做

第一版 v1.2.1 暴露出根架构问题：

1. Main / Companion 都不能正常拖边框 Resize。
2. Companion 被做成第二个独立窗口。
3. Companion 双击标题栏会 Maximize，导致“小窗全屏”。
4. Always On Top 会造成性能暴涨甚至卡死，疑似循环调用。
5. Companion 直接缩小完整聊天历史，形成“翻译笔读小说”式体验。
6. 双窗口带来同步、焦点、生命周期、通知路由等额外复杂度。

因此不要修旧实现，回滚后按正确窗口模型重做。

---

## 1. 唯一架构原则

长期桌面 UI 只允许：

```text
一个 Core
一个 Session
一个 Desktop Window
一个 WebView
```

这个唯一窗口只有两种显示模式：

```text
WindowMode.MAIN
WindowMode.COMPANION
```

禁止：

```text
Main Window + Companion Window
```

两个长期 top-level window 同时存在。

---

## 2. 正确模式模型

```text
Zhaoxi Desktop Window
├── MAIN
│   ├── 完整 Scene
│   ├── 完整 Conversation
│   ├── Deskboard
│   ├── Settings
│   └── Maintenance
└── COMPANION
    ├── Compact Character Header
    ├── Current Conversation Surface
    ├── Input
    └── Expand to Main
```

MAIN → COMPANION：

```text
保存 Main Geometry
→ 切换 compact layout
→ 调整同一个 HWND / WebView 的 size + position
→ COMPANION
```

COMPANION → MAIN：

```text
保存 Companion Geometry
→ 恢复 Main Geometry
→ 切回 Main layout
→ MAIN
```

不得 destroy / recreate WebView，不得 reload Session。

---

## 3. 本版本 P0

```text
1. Single Window Architecture
2. Main / Companion 真正 Resize
3. Companion Mode 专用布局
4. Always On Top 重做
5. Custom Window Chrome
6. Zhaoxi Native Notification
```

P1：

```text
7. Browser Entry disable
8. Tray / Shortcut
9. Geometry persistence
```

本版本不做 Desktop Pet。

---

## 4. Companion Mode 产品定义

Companion Mode：

> **把同一个朝汐折叠到工作台旁边。**

不是：

> “缩小版 Main Window”。

使用场景：

```text
VS Code
刷题
写代码
学习
看文档
求职
浏览网页
```

---

## 5. Companion 只显示当前信息

Companion 不承担历史浏览。

只显示：

```text
Compact Character Header
最近用户消息
最近朝汐消息
Input
Deskboard unread hint
Expand to Main
```

建议最多最近 1~2 个 turn。

更早内容全部留在 MAIN。

---

## 6. Current Conversation Surface

Companion 中间区域定义为：

```text
Current Conversation Surface
```

不是 Timeline。

例如：

```text
暗苟：
今天这个题怎么感觉怪怪的。

朝汐：
你先别跟它较劲，我看看你卡在哪。
```

禁止：

```text
完整历史塞进极矮滚动框
```

禁止嵌套 Scroll。

若最后一条消息过长：

```text
截断 / 限高
+
“展开主界面查看完整内容”
```

---

## 7. Companion 推荐布局

```text
╭──────────────────────────────╮
│ [头像] 朝汐                   │
│       活跃 · 还在聊呢          │
│                              │
│ 暗苟：……                      │
│                              │
│ 朝汐：……                      │
│                              │
│ 和朝汐说点什么……          ↑   │
│                              │
│ ● 小桌边有新留言      [展开]   │
╰──────────────────────────────╯
```

Compact Header 控制在约 64~84px。

不要复用 Main 的大角色卡。

---

## 8. Companion 尺寸

建议默认：

```text
width: 360~420px
height: 420~540px
```

最小建议：

```text
300x320
```

但必须支持真正 Window Resize。

---

## 9. Main / Companion Resize 必须真实可用

自定义 Chrome 后，MAIN 和 COMPANION 都必须支持：

```text
left
right
top
bottom
top-left
top-right
bottom-left
bottom-right
```

Windows frameless 下优先使用正确的 native hit-test / resize border，例如：

```text
WM_NCHITTEST
HTLEFT / HTRIGHT / HTTOP / HTBOTTOM
HTTOPLEFT / HTTOPRIGHT
HTBOTTOMLEFT / HTBOTTOMRIGHT
```

或当前框架官方等价能力。

禁止使用 CSS `resize` 冒充窗口 Resize。

鼠标移到四边四角必须显示正确 resize cursor。

---

## 10. 双击标题栏规则

MAIN：

```text
double click titlebar
→ Maximize / Restore
```

COMPANION：

```text
double click titlebar
→ switch_mode(MAIN)
```

Companion 不存在 Maximize 语义。

Companion 的标准“最大化”按钮也应改成：

```text
↗ 展开
```

而不是 `□`。

---

## 11. Custom Window Chrome

继续保留自绘标题栏，但根据模式显示：

MAIN：

```text
[头像] 朝汐 ZhaoXi                         _  □  ×
```

COMPANION：

```text
[头像] 朝汐 ZhaoXi                         _  ↗  ×
```

必须正确划分：

```text
drag region
interactive region
window controls
resize hit zone
```

不能让按钮点击误触拖动。

---

## 12. Always On Top 重新实现

第一版置顶功能疑似进入循环。

新实现必须满足：

> **Always On Top 是一次性的 native state toggle，不是持续维护行为。**

正确：

```text
false
→ user toggle
→ native Set Topmost once
→ true
```

关闭：

```text
true
→ user toggle
→ native Remove Topmost once
→ false
```

严禁：

```text
timer polling
while visible loop
window event -> set topmost -> window event -> set topmost
```

开发日志至少记录：

```text
topmost toggle requested
old state
new state
native call count
```

一次 toggle 不应持续增加 native call。

Always On Top 不再常驻底栏 checkbox，建议放：

```text
Companion ⋯ 菜单
```

或 Settings。

---

## 13. Geometry 分离保存

虽然只有一个窗口，但需要两套 geometry：

```text
main_geometry:
  x
  y
  width
  height
  maximized

companion_geometry:
  x
  y
  width
  height
  topmost
```

切换 Mode 只保存 / 恢复对应 geometry。

不得创建新 Window。

---

## 14. 同一 Session / 同一状态

MAIN 和 COMPANION：

```text
同一个 Session
同一个 Timeline
同一个 ACTIVE state
同一个 Memory
同一个 WebView state
```

不需要“同步两套聊天”。

前端建议仅维护：

```text
data-window-mode="main"
data-window-mode="companion"
```

按 Mode 切换布局。

不要复制两份应用。

---

## 15. Deskboard 在 Companion 中只提示

Companion 不展开完整 Deskboard。

只显示：

```text
● 小桌边有新留言
```

点击：

```text
switch_mode(MAIN)
→ open Deskboard
```

---

## 16. Native Notification

Native Notification 是本版本唯一允许的独立 transient top-level window。

结构：

```text
Zhaoxi Desktop Window
├── MAIN
└── COMPANION

Native Notification
└── transient
```

Notification 不共享长期 Window 生命周期。

---

## 17. Native Notification 默认路由

Desktop Window focused：

```text
不弹 Native Notification
```

Desktop Window hidden / background：

```text
允许弹
```

CONVERSATION notification 点击：

```text
show Desktop Window
→ switch_mode(COMPANION)
```

IMPORTANT notification 点击：

```text
show Desktop Window
→ switch_mode(MAIN)
```

禁止：

```text
create_companion_window()
```

---

## 18. Windows Toast

Windows Toast 降级为 fallback。

默认：

```text
Zhaoxi Native Notification
```

仅在以下情况使用 Toast：

- Native Notification 初始化失败
- Desktop Shell 不可用
- 用户显式开启系统通知模式

---

## 19. Browser Entry 关闭

正式使用已经有：

```text
开机自启动
托盘
快捷键
Desktop Window
```

因此普通用户不再需要：

```text
浏览器 -> http://127.0.0.1:4913
```

但不要直接删除 localhost HTTP transport，如果 WebView / API 仍依赖它。

目标：

```text
保留 internal transport
关闭 normal browser entry
```

---

## 20. Browser DEV 模式

建议：

```env
ZHAOXI_DEV_BROWSER_UI=false
```

正式默认：

```text
false
```

普通浏览器访问完整 UI：

```text
403 / Desktop-only 提示页
```

开发时：

```text
ZHAOXI_DEV_BROWSER_UI=true
```

可恢复浏览器调试。

不要靠 User-Agent 判断，使用真正 Desktop Shell Session / token / internal access 机制。

日常 UI 中彻底移除：

```text
127.0.0.1:4913
Local Interaction Shell
```

只允许在 Maintenance Drawer 查看。

---

## 21. Tray 与 Shortcut

Tray 建议：

```text
打开朝汐
切换陪伴模式
隐藏朝汐
设置
退出
```

因为只有一个 Window：

```text
打开朝汐 -> MAIN
切换陪伴模式 -> COMPANION
```

快捷键目标：

```text
VS Code
↓
快捷键
↓
同一个朝汐窗口显示为 COMPANION
↓
输入一句
↓
快捷键 / Esc
↓
隐藏
```

---

## 22. Window Lifecycle

唯一长期 Desktop Window：

```text
startup
↓
create once
↓
show / hide
↓
switch MAIN / COMPANION
↓
exit
```

禁止频繁 destroy / recreate。

---

## 23. Desktop Activity Self Window

MAIN / COMPANION 使用同一个 HWND / App Identity。

都必须识别为：

```text
Zhaoxi Self Window
```

用户在朝汐里打字不能被当成“忙到不能和朝汐说话”。

Topmost 只改变 z-order，不得反复触发 Presence / Activity 循环。

---

## 24. Companion 底栏

只保留高价值信息：

```text
● 小桌边有新留言
↗ 展开
```

不要继续塞：

```text
Always On Top checkbox
大量设置按钮
系统消息错误
```

这些进入菜单 / Main。

---

## 25. MAIN 保持 v1.2.0

MAIN 不重做视觉。

保留：

- Autumn Wheat
- Character Anchor
- Conversation
- Input Tray
- Deskboard
- Maintenance Drawer
- Settings / Debug

v1.2.1 只改 Window Shell 和 Mode。

---

## 26. Desktop Pet 边界

本版本禁止实现：

```text
Live2D
Sprite
桌面走动
角色拖拽
Pet Bubble
Pet Collision
```

未来可保留极轻抽象：

```text
PresenceSurface:
MAIN
COMPANION
NOTIFICATION
future PET
```

但不要为了 PET 做大重构。

---

## 27. P0 手动验收：Resize

MAIN / COMPANION 分别测试：

```text
四边
四角
```

要求：

- cursor 正确
- resize 正常
- 不固定尺寸
- 不跳窗
- 不失去 WebView 内容

---

## 28. P0 手动验收：Mode Switch

连续：

```text
MAIN -> COMPANION -> MAIN
```

至少 20 次。

要求：

- 始终同一个窗口
- 不生成新窗口
- 不 reload WebView
- 对话不丢
- geometry 正确恢复
- 内存不异常增长

---

## 29. P0 手动验收：双击

MAIN 双击标题栏：

```text
maximize / restore
```

COMPANION 双击标题栏：

```text
MAIN
```

绝不能出现：

```text
Companion 全屏
```

---

## 30. P0 手动验收：Topmost

开启置顶后连续使用 20~30 分钟。

要求：

- CPU 无异常增长
- UI 不冻结
- native topmost calls 不持续增长
- Window 正常输入 / 拖动 / Resize
- 关闭置顶后正确恢复

---

## 31. P0 手动验收：Companion 内容

真实聊天时：

```text
只看到最近 1~2 turn
```

不能出现：

```text
极矮滚动框里塞整本聊天历史
```

长消息：

```text
限高 / 截断
→ 展开 Main 看完整
```

---

## 32. Notification 验收

Desktop Window focused：

```text
不重复弹通知
```

Desktop Window hidden：

```text
弹 Native Notification
```

点击 Conversation notification：

```text
同一个 Window 进入 COMPANION
```

点击 Important：

```text
同一个 Window 进入 MAIN
```

---

## 33. Browser Entry 验收

正式模式：

```text
http://127.0.0.1:4913
```

不得直接进入完整 UI。

Desktop App 必须仍正常。

DEV 模式开启后浏览器调试可恢复。

---

## 34. 多显示器 / DPI

验证：

```text
100%
125%
150%
175%
200%
```

以及：

- 主副屏切换
- 拔掉显示器
- Main / Companion geometry 恢复
- Notification placement
- resize hit-zone

---

## 35. 自动化测试重点

至少覆盖：

### Mode
- MAIN -> COMPANION
- COMPANION -> MAIN
- same window identity

### Geometry
- save / restore main
- save / restore companion

### Conversation
- latest N turns
- send
- mode switch no reload

### Topmost
- toggle once
- no loop

### Notification
- suppression
- routing
- click

### Browser
- prod denied
- dev allowed

---

## 36. Regression

必须保持：

```text
Memory
Archive
Proactive
Beat
Desktop Activity
Deskboard
Image Upload
Settings
Debug
Startup
Tray
```

无回归。

---

## 37. 完成标准

v1.2.1 重做版完成必须满足：

1. 只有一个长期 Desktop Window。
2. Companion 不创建第二窗口。
3. Main / Companion 共用一个 WebView / Session。
4. Main / Companion 都可真实 Resize。
5. Main 双击标题栏 = Maximize / Restore。
6. Companion 双击标题栏 = 返回 Main。
7. Companion 不存在 Maximize 模式。
8. Companion 只显示当前 1~2 turn。
9. Companion 不再缩小完整历史。
10. Companion 无嵌套滚动。
11. Topmost 不存在性能循环。
12. Topmost 是一次性 native state toggle。
13. Main / Companion geometry 分别保存。
14. Mode 切换不 reload Conversation。
15. Native Notification 正常。
16. Notification 点击切换同一个 Desktop Window。
17. focused 时不重复弹通知。
18. Windows Toast 只做 fallback。
19. Browser Entry 正式模式默认关闭。
20. localhost internal transport 可继续存在。
21. DEV Browser UI 可恢复。
22. 日常 UI 不显示 localhost / Local Interaction Shell。
23. Tray / Shortcut 正常。
24. Desktop Activity 正确认出 Self Window。
25. 全量测试通过。
26. VS Code 旁 Companion 连续使用 20~30 分钟稳定。
27. 不实现 Desktop Pet。

---

## 38. 开发完成后汇报

请明确汇报：

- 回滚基线
- Single Window Architecture
- Window identity
- MAIN layout
- COMPANION layout
- Current Conversation Surface
- Resize implementation
- native hit-test / resize border
- Main double click
- Companion double click
- Topmost implementation
- Topmost performance test
- Geometry persistence
- Mode switching
- Notification routing
- Browser entry blocking
- DEV browser mode
- Tray / Shortcut
- Desktop Activity self-window
- Tests
- Manual verification
- Known limitations

---

# 39. 一句话定义

旧方案：

> **“再开一个小朝汐窗口。”**

重做方案：

> **“把同一个朝汐折叠到工作台旁边。”**

Main 是展开状态。

Companion 是折叠状态。

从始至终：

> **只有一个朝汐。**
