# Zhaoxi v1.2.1 Development Task
# Desktop Presence Shell

> 版本：v1.2.1  
> 基线：v1.2.0 Visual Refresh Phase 3  
> 定位：桌面存在形态升级  
> 核心目标：让朝汐从“一个带 WebView 感的窗口”进一步变成真正属于她自己的 Windows 桌面应用，并增加轻量 Companion Window 作为工作台旁的陪伴形态。  
> 本版本不做完整 Desktop Pet，但必须为后续桌宠形态留下清晰边界。

---

## 0. 当前问题

v1.2.0 已经完成：

- Autumn Wheat 主场景
- Character Anchor
- 专用朝汐头像
- Conversation / Input Tray
- 小桌边 Deskboard
- 维护抽屉
- 主动留言
- 麦田场景视觉统一

当前主要问题已经不再是“主题不像朝汐”。

而是：

> **应用外壳仍然很像 WebView / 浏览器套壳。**

尤其：

```text
Windows 原生标题栏
+
朝汐自己的 Scene UI
```

形成明显割裂。

同时，主动消息主要依赖系统级通知时：

```text
朝汐的角色语气
↓
Windows Toast
```

会让视觉与交互重新跳回系统通知风格。

另外，当前如果只是想在刷题 / 写代码 / 看文档时和朝汐说两句：

```text
必须拉出完整 Main Window
```

成本仍然偏高。

因此 v1.2.1 开始处理：

# Desktop Presence Shell

---

# 1. 本版本三大核心

P0：

```text
1. Custom Window Chrome
2. Zhaoxi Native Notification
3. Companion Window
```

这三项优先级高于其他视觉修饰。

---

# 2. 三种桌面形态边界

未来朝汐可以有三种形态：

```text
Main Window
= 完整房间

Companion Window
= 工作台旁的小窗口

Desktop Pet
= 朝汐本人跑到桌面
```

本版本：

```text
实现 Main Window Shell 升级
实现 Companion Window
预留 Desktop Pet
```

不实现真正桌宠。

---

# 3. Main Window

Main Window 继续承担：

- 完整聊天
- Deskboard
- 设置
- Debug
- 系统消息
- 长聊天
- 复杂工具结果
- 全功能交互

v1.2.1 不重做 Main Scene 视觉。

只升级：

# Window Shell

---

# 4. Custom Window Chrome

移除或弱化：

```text
Windows 原生 Titlebar
```

实现：

# 自定义窗口标题栏

视觉建议：

```text
[朝汐 Logo / Avatar] 朝汐 ZhaoXi                    _  □  ×
```

或者更克制：

```text
朝汐 ZhaoXi                                         _  □  ×
```

必须与 Autumn Wheat Theme 融合。

---

# 5. Custom Chrome 功能要求

必须支持：

```text
拖动窗口
双击标题栏最大化 / 恢复
最小化
最大化
恢复
关闭
窗口 resize
Windows Snap
高 DPI
多显示器
```

不能为了视觉破坏基本 Windows 行为。

---

# 6. Frameless 调研

如果当前：

```text
pywebview / Desktop Shell
```

支持稳定 frameless：

优先使用。

如果 frameless 会破坏：

- Snap
- Resize
- Maximize
- 多显示器
- DPI

则：

> 允许保留最薄系统边界，仅隐藏传统标题栏主体。

稳定优先于纯视觉。

---

# 7. Window Control 区

自绘：

```text
_   □   ×
```

要求：

- hover 状态
- close 使用轻微危险色
- 与主题色协调
- 点击区域足够大
- 不做过度装饰

---

# 8. Titlebar Drag Region

明确划分：

```text
drag region
interactive region
window controls
```

避免：

- 点击头像拖窗口
- 点击按钮变成拖动
- 双击误触交互

---

# 9. Zhaoxi Native Notification

当前主动消息不应主要依赖：

```text
Windows Toast
```

v1.2.1 新增：

# 朝汐自己的 Notification Bubble

---

# 10. Notification 视觉

建议：

```text
右下角 / 当前显示器合适位置
```

卡片结构：

```text
╭────────────────────────────╮
│ [朝汐头像]  朝汐             │
│                            │
│ 刚才写了挺久啦。             │
│ 停下来歇一下？               │
│                      22:41 │
╰────────────────────────────╯
```

---

# 11. Notification 风格

复用 Main Theme Token：

```text
奶白玻璃
麦金 accent
浅蓝
暖色阴影
朝汐 Avatar
```

禁止重新发明一套 Notification Theme。

---

# 12. Notification 动画

建议：

```text
slide + fade
180~260ms
```

退出：

```text
fade + slight slide
```

禁止：

- 弹跳
- 大缩放
- 强闪烁

---

# 13. Notification 分级

建议三种 presentation：

## AMBIENT

轻量提示：

```text
欢迎回来
我在附近
刚刚 Focus 结束
```

特点：

- 3~5 秒
- 自动消失
- 不要求交互

## CONVERSATION

真正主动找用户：

```text
刚才那个点我又想到一点……
```

特点：

- 保留更久
- 可点击
- 可进入 Companion Window
- 可提供“回复”

## IMPORTANT

系统 / 权限 / Tool 结果：

```text
权限确认
工具失败
重要状态变化
```

特点：

- 明确按钮
- 不自动快速消失
- 可打开 Main Window

---

# 14. Notification Action

至少支持：

```text
点击卡片
→ 打开 Companion Window
```

可选：

```text
[回复]
[稍后]
```

Phase 1 可先只实现：

```text
click -> Companion
```

---

# 15. Notification 与 Deskboard 联动

主动消息出现时：

```text
Native Notification
+
Conversation message
+
Deskboard note
```

三者属于同一条事件。

不能出现：

```text
三套重复业务逻辑
```

尽量复用：

```text
ProactiveMessage / Delivery Event
```

---

# 16. Windows Toast Fallback

保留 Windows Toast：

```text
fallback
```

仅当：

- Native Notification 初始化失败
- Desktop Shell 不可用
- 用户显式开启系统通知模式

默认优先：

# Zhaoxi Native Notification

---

# 17. Companion Window

新增：

# Companion Window

定位：

> 朝汐挂在用户工作台旁边的轻量陪伴窗口。

主要使用场景：

```text
VS Code
刷题
写代码
看文档
学习
求职
浏览网页
```

用户不需要拉出完整 Main Window。

---

# 18. Companion Window 与 Desktop Pet 的边界

Companion Window：

```text
有窗口边界
有输入框
有最近消息
可缩放
可停靠
偏工具
```

Desktop Pet：

```text
角色立绘
动作
气泡
点击
拖动
轻交互
不承担完整聊天 UI
```

本版本禁止把 Companion Window 做成桌宠。

---

# 19. Companion Window 内容

只保留：

```text
Character Header
状态
最近 1~3 条消息
Input
Deskboard unread indicator
Expand to Main Window
```

---

# 20. Companion Window 不做什么

不显示：

```text
完整聊天历史
Debug
原始 JSON
大段设置
完整 Deskboard
复杂工具页面
Archive
大型图片浏览
```

这些进入 Main Window。

---

# 21. Companion Layout

建议：

```text
╭──────────────────────────────╮
│ [朝汐] 半活跃 · 就在附近       │
│                              │
│ 刚才那个是不是还没弄完？       │
│                              │
│ ……如果在忙我就等你。           │
│                              │
│ 和朝汐说点什么……          ↑   │
│                     [展开]   │
╰──────────────────────────────╯
```

---

# 22. Companion Window 尺寸

建议默认：

```text
width: 340~420px
height: 420~560px
```

允许 resize。

最小：

```text
~300x320
```

最大不超过：

```text
Main Window 的意义范围
```

---

# 23. Companion Window 位置

支持：

```text
自由拖动
记住位置
```

启动时：

```text
恢复上次位置
```

若显示器变化：

```text
自动纠正回可见区域
```

---

# 24. Companion Window 停靠

Phase 1 至少支持：

```text
普通浮动窗口
```

可选：

```text
屏幕边缘轻吸附
```

例如距离：

```text
12~24px
```

时轻微吸附。

不要实现复杂 Dock Manager。

---

# 25. Always On Top

Companion Window 支持：

```text
Always On Top
```

默认建议：

```text
可配置
```

例如：

```text
☑ 始终置顶
```

适合：

```text
VS Code / 浏览器旁边
```

---

# 26. Companion Window Focus

Companion Window 必须避免过度抢焦点。

主动消息出现时：

```text
不自动 Focus
```

只有用户点击：

```text
才获得输入焦点
```

---

# 27. Companion Window 与 Desktop Activity

朝汐自己的窗口输入：

```text
不得重新被 desktop_busy 错判
```

继续沿用：

```text
Zhaoxi foreground input 降权
```

Main / Companion 都属于：

```text
Zhaoxi Self Window
```

---

# 28. Companion Conversation

发送消息：

```text
使用现有 conversation session
```

不能创建：

```text
Main Session
Companion Session
```

两套独立对话。

Main 与 Companion：

# 同一会话

---

# 29. Conversation Sync

Main Window 与 Companion：

```text
共享
- message timeline
- ACTIVE state
- continuation
- memory extraction
```

Companion 只显示：

```text
最近少量消息
```

---

# 30. Companion Expand

提供：

```text
展开
```

点击：

```text
显示 Main Window
```

Main 打开后：

```text
保持当前对话位置
```

---

# 31. Main -> Companion

Main Window 提供：

```text
进入陪伴模式
```

可：

- 隐藏 Main
- 打开 Companion

建议用户不需要同时保持两者占据大量屏幕。

---

# 32. Window Mode Manager

建议抽象：

```text
WindowMode
MAIN
COMPANION
```

未来预留：

```text
PET
```

但 Phase 1 不实现 PET。

---

# 33. Single Active Visual Instance

朝汐逻辑仍是：

> 同一个朝汐，不是多个客户端人格。

Main / Companion：

```text
只是不同 UI 形态
```

不是多个 Agent Instance。

---

# 34. Window State

建议持久化：

```text
main:
  position
  size
  maximized

companion:
  position
  size
  always_on_top
```

保存到本地 UI config。

---

# 35. Tray 行为

系统托盘继续存在。

建议菜单：

```text
打开朝汐
打开陪伴窗口
隐藏全部
设置
退出
```

---

# 36. 关闭行为

明确：

```text
Main Close
```

根据现有逻辑：

```text
隐藏 / 最小化到托盘
```

或：

```text
退出
```

保持配置。

Companion Close：

```text
只关闭 Companion
不退出 Core
```

---

# 37. Native Notification Window

Notification 应为：

```text
独立轻量 top-level window
```

要求：

- 无传统标题栏
- 不显示任务栏图标
- 不抢焦点
- 支持多显示器
- 合适位置显示

---

# 38. Notification Queue

避免多个通知叠爆。

建议：

```text
最多同时显示 2~3 条
```

新通知：

- 堆叠
- 或排队

---

# 39. Notification Dedup

短时间相同内容：

```text
去重
```

避免：

```text
ACTIVE Beat
+
Proactive
+
System
```

重复提醒同一件事。

---

# 40. Notification Click

点击 Conversation Notification：

```text
open Companion
```

点击 Important：

```text
open Main
```

根据类型分流。

---

# 41. Theme Consistency

Main / Companion / Notification 必须使用同一：

```text
Theme Token
Character Asset
Status Color
Typography
```

---

# 42. Companion Theme

Companion 不需要完整麦田背景。

建议：

```text
奶白玻璃
+
极淡 Autumn Wheat tint
```

可选：

```text
顶部一小条景色
```

避免小窗口塞完整背景导致过花。

---

# 43. Avatar

复用：

```text
data/ui/characters/zhaoxi/avatar_default
```

不要单独再生成一套 Mini Avatar。

---

# 44. Status

Companion Header 显示：

```text
ACTIVE
SEMI_ACTIVE
IDLE
AWAY
```

但文案可简化：

```text
活跃 · 还在聊呢
半活跃 · 就在附近
```

---

# 45. Deskboard Unread

Companion 可以显示：

```text
● 小桌边有新留言
```

点击：

```text
打开 Main Window Deskboard
```

不在 Companion 展开完整 Deskboard。

---

# 46. Shortcut

建议增加全局快捷键：

```text
Toggle Companion Window
```

具体组合键走配置，不写死。

---

# 47. 快速唤起

目标体验：

```text
正在 VS Code
↓
快捷键
↓
Companion Window 出现
↓
说一句
↓
快捷键 / Esc 收起
```

这是 v1.2.1 的核心使用价值之一。

---

# 48. Input Focus 快捷键

Companion 显示时：

```text
快捷键可直接聚焦输入框
```

避免先用鼠标点。

---

# 49. Notification Reply（Optional）

如果实现成本低：

Notification Bubble 可提供：

```text
回复
```

点击：

```text
展开 Companion 并 focus input
```

不在 Notification 内直接嵌套完整输入框。

---

# 50. 自定义 Titlebar 与主题关系

Titlebar 背景可：

```text
transparent / scene-aware
```

Window Controls 放在：

```text
Theme Scene 上层
```

不要再出现：

```text
系统色标题栏
+
麦田界面
```

的割裂。

---

# 51. Windows Snap 验收

Custom Chrome 必须验证：

```text
Win + ← / →
拖到屏幕边缘
拖到顶部最大化
```

如果 Frameless 方案破坏 Snap：

> 优先修复或退回兼容方案。

---

# 52. 高 DPI

验证：

```text
100%
125%
150%
175%
200%
```

至少不出现：

- 控件错位
- titlebar hitbox 偏移
- notification 坐标错乱

---

# 53. 多显示器

验证：

- Main 在副屏
- Companion 在主屏
- Notification 出现在正确当前显示器
- 拔掉显示器后窗口回到可见区域

---

# 54. 本版本不做 Desktop Pet

明确禁止顺手开发：

```text
桌宠动画
桌面走动
角色拖拽
宠物碰撞
Live2D
Sprite
桌面角色气泡
```

这些留给：

# Future Desktop Pet

---

# 55. 为 Desktop Pet 预留接口

可以抽象：

```text
PresenceSurface
```

例如：

```text
MAIN
COMPANION
NOTIFICATION
future: PET
```

但不要为了未来做大型架构重构。

---

# 56. 事件流建议

主动消息：

```text
Proactive / Beat
↓
Message Delivery
↓
UI Presentation Router
├── Main Timeline
├── Deskboard Note
├── Native Notification
└── Companion Preview
```

避免每个 UI 单独消费 Core 逻辑。

---

# 57. Presentation Router

建议新增轻量：

```text
PresentationPolicy
```

根据：

```text
message type
window visibility
interaction state
importance
user settings
```

决定：

```text
Native Notification?
Companion?
Main?
Toast fallback?
```

第一版规则保持简单。

---

# 58. 建议默认规则

如果 Main Window 正在前台：

```text
不弹 Native Notification
```

只显示：

```text
Conversation
```

如果 Companion 前台：

```text
直接在 Companion 显示
```

如果两者都隐藏：

```text
Native Notification
```

这样避免重复轰炸。

---

# 59. Notification Suppression

以下情况不显示额外浮窗：

```text
Main visible + focused
Companion visible + focused
刚刚已有同消息展示
```

---

# 60. Settings

新增 UI 设置：

```text
桌面通知
  [x] 使用朝汐通知浮窗
  [ ] 同时使用 Windows 系统通知

陪伴窗口
  [x] 记住位置
  [ ] 始终置顶
  [ ] 启动时自动打开
```

---

# 61. Companion Auto Open

默认：

```text
false
```

用户显式开启才：

```text
Zhaoxi startup
↓
Companion auto open
```

---

# 62. Notification Lifetime

建议：

```text
AMBIENT: 4~6s
CONVERSATION: 8~15s
IMPORTANT: persistent / until action
```

具体可配置。

---

# 63. Native Notification Hover

鼠标 hover：

```text
暂停自动消失计时
```

离开继续。

---

# 64. Notification Accessibility

需要：

- 可点击
- 键盘关闭
- Esc
- close button
- 文本对比度足够

---

# 65. Main Window 视觉验收

Main Window 打开后：

> 不应该再明显看到“Windows 原生标题栏 + App UI”两层视觉。

---

# 66. Companion 视觉验收

远看应该更像：

> 一个小型角色陪伴窗口

而不是：

> Main Window 缩小 40%。

---

# 67. Companion 实际场景验收

打开：

```text
VS Code
```

将 Companion 放在右侧。

连续工作 20~30 分钟。

要求：

- 不挡主要编辑区
- 可快速发一句话
- 不需要打开 Main
- 主动消息能自然进入 Companion
- 不抢焦点
- Always On Top 可用

---

# 68. Notification 场景验收

Main / Companion 全隐藏。

触发一次主动消息。

预期：

```text
右下 / 当前显示器
出现朝汐自己的通知
```

点击：

```text
Companion 打开
```

而不是：

```text
整个 Main Window 突然弹出
```

---

# 69. Main Focus 验收

Main Window 当前正在使用。

触发主动消息。

预期：

```text
不额外弹 Native Notification
```

避免自己通知自己。

---

# 70. Windows Toast Fallback 验收

关闭 Native Notification 或模拟初始化失败。

预期：

```text
Windows Toast 仍可正常 fallback
```

---

# 71. 测试范围

新增 / 更新测试至少覆盖：

## Window Chrome
- minimize
- maximize
- restore
- close
- drag state

## Companion
- open
- hide
- restore position
- resize config
- always-on-top state
- conversation sync

## Notification
- display
- timeout
- click
- suppression
- fallback
- queue

## Presentation
- main focused
- companion focused
- all hidden

---

# 72. 不允许业务回归

必须保持：

```text
Memory
Archive
Proactive
Beat
Desktop Activity
Deskboard
Message Timeline
Image upload
Settings
Debug
```

均正常。

---

# 73. 完成标准

v1.2.1 完成必须满足：

1. Main Window 不再明显使用传统 Windows Titlebar 视觉。
2. 自定义 Chrome 支持正常窗口操作。
3. Snap / DPI / resize 基本可用。
4. Native Notification 成为默认朝汐通知形式。
5. Windows Toast 保留 fallback。
6. Main 前台时不重复弹通知。
7. Companion Window 可独立打开 / 关闭。
8. Companion 共享 Main Conversation。
9. Companion 只显示少量最近内容。
10. Companion 可快速输入。
11. Companion 支持位置记忆。
12. Companion 支持可配置 Always On Top。
13. Notification 点击可打开 Companion。
14. Deskboard 未读可在 Companion 提示。
15. Main / Companion / Notification 使用统一 Theme。
16. 朝汐 Avatar 统一复用。
17. Core 不因 UI Window Mode 产生多实例。
18. Desktop Activity 正确识别 Main / Companion 为 Zhaoxi 自身窗口。
19. Tray 可打开 Main / Companion。
20. 全量测试通过。
21. 实机在 VS Code 旁连续使用时，Companion 有实际价值。
22. 不实现完整 Desktop Pet。

---

# 74. 开发完成后汇报

请明确汇报：

- Custom Window Chrome
- Frameless / Compatibility Strategy
- Window Controls
- Snap / DPI
- Native Notification
- Notification Type
- Notification Routing
- Windows Toast Fallback
- Companion Window
- Companion Layout
- Conversation Sync
- Always On Top
- Position Persistence
- Tray
- Global Shortcut
- Presentation Policy
- Theme Reuse
- Desktop Activity Self Window
- Tests
- Manual Verification
- Known Limitations
- Desktop Pet Future Boundary

---

# 75. v1.2.1 一句话

v1.2.0 做的是：

> **给朝汐做了一个属于她自己的房间。**

v1.2.1 要做的是：

> **让朝汐学会从房间里走到暗苟的工作台旁边。**

Main Window 是她的房间。

Companion Window 是她搬到工作台边的小椅子。

Notification 是她隔着一点距离喊暗苟一声。

至于 Desktop Pet：

> **等以后真的需要时，再让朝汐本人从窗口里跑出来。**
