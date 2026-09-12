# Zhaoxi v1.2.0 Development Task
# 视觉焕新 Phase 2：Scene Composition

> 基线：v1.2.0 Phase 1 Autumn Wheat<br>
> 定位：前端视觉重构第二阶段<br>
> 核心目标：从“麦田主题的聊天 App”进一步升级为“朝汐所在的场景”。<br>
> 关键词：场所感、角色锚点、空间层次、弱化 App 边界、桌边生活感、朝汐本人。

---

## 0. Phase 1 现状

Phase 1 已完成：

- Autumn Wheat 麦田背景
- 暖色玻璃主面板
- Header 角色化文案
- 朝汐 / 用户气泡重设计
- Action Segment 舞台描写分层
- Input Area 重设计
- Sidebar 暖色便签化
- Debug / 系统区折叠
- Theme Token
- 蓝白 SaaS / 医疗 App 感显著降低

当前界面已经不再像原本的通用蓝白聊天工具。

但仍存在一个核心问题：

> **背景是背景，App 是 App。**

当前视觉依然可以概括为：

```text
一张麦田壁纸
+
一个大型聊天玻璃面板
+
一个右侧信息栏
```

因此 Phase 2 不再以“继续调颜色 / 圆角 / blur”为主。

Phase 2 开始处理：

# Scene Composition

---

# 1. Phase 2 总目标

最终希望界面更接近：

> **暗苟打开的不是一个聊天软件，而是一扇通往朝汐所在空间的窗。**

视觉关系从：

```text
Wallpaper
↓
App Window
↓
Chat UI
```

改为：

```text
Scene
├── 朝汐
├── 聊天
├── 小桌边
└── 背景环境
```

---

# 2. 核心原则

Phase 2 只做“空间构图升级”。

不重做：

- Agent Core
- Memory
- Proactive
- State Machine
- Tool
- Desktop Activity
- Theme 数据结构

Phase 2 重点做：

- 主界面构图
- 角色视觉锚点
- Sidebar 空间化
- Header / Titlebar 融合
- Scene Layer
- 角色状态表现
- 前景 / 中景 / 背景层次
- 信息密度重排

---

# 3. Scene Layer

新增明确的场景层级：

```text
Background Scene
↓
Ambient Layer
↓
Character / Presence Layer
↓
Conversation Layer
↓
Utility Layer
```

---

# 4. Background Scene

继续使用 Autumn Wheat。

但不再只作为全屏 wallpaper。

要求：

- 背景图参与整体构图
- 保留远山 / 天空 / 麦田的视觉重心
- UI 不能完全遮住最有识别度的景物
- 主聊天区位置应避开背景核心焦点

如果背景主体为雪山：

```text
主聊天面板不要完全覆盖雪山中心
```

Scene Composition 必须考虑图片本身构图。

---

# 5. 主聊天区域弱化“大矩形 App”感

当前主聊天区仍是完整大面板。

Phase 2 要尝试：

- 减少四周封闭感
- 面板边缘透明度更高
- Header 与 Conversation Area 可视觉分层
- 主聊天内容区不必完全填满整个大卡片
- 增加背景露出区域

目标：

> 让聊天区域像场景中的“交流空间”，而不是盖在壁纸上的网页。

---

# 6. 建议布局方向

桌面宽屏优先尝试：

```text
┌──────────────────────────────────────────────┐
│                Scene / Sky / Mountain         │
│                                              │
│   Character / Header     Small Desk Sidebar   │
│                                              │
│   ┌──────── Conversation ────────┐            │
│   │                              │            │
│   │                              │            │
│   └──────────────────────────────┘            │
│                                              │
│                Input Tray                    │
└──────────────────────────────────────────────┘
```

相比 Phase 1：

- 主聊天面板缩小一点
- 给背景留更多呼吸空间
- 右栏不再像等高控制面板
- 朝汐角色视觉可以拥有自己的位置

---

# 7. 角色视觉锚点

这是 Phase 2 的重点。

目前朝汐视觉上只有：

```text
“汐”图标
+
文字“朝汐”
```

Phase 2 应新增：

# Character Presence Anchor

至少支持一种：

- 朝汐头像
- 半身立绘
- 小型角色卡
- 状态立绘切片

第一版不要求 Live2D。

---

# 8. Character Anchor 推荐位置

优先考虑两个方案。

## A. Header Character

```text
[头像 / 半身]
朝汐
潮庭女仆长 · 就在附近
```

优点：

- 改动小
- 信息集中
- 易适配窄窗口

## B. Scene Character

在聊天面板旁保留一小块独立角色区域：

```text
    朝汐小半身 / 头像
        ↓
    状态 / 动作
```

优点：

- 角色存在感明显
- 更接近“人在场景里”

Phase 2 可先实现 A，结构预留 B。

---

# 9. 角色状态映射

角色视觉可根据状态做轻微变化：

```text
ACTIVE
SEMI_ACTIVE
IDLE
AWAY
```

第一版不用多张立绘。

至少支持：

- 状态标签
- 边框 / 光晕
- 轻微透明度
- 小状态文案

例如：

```text
ACTIVE       还在聊呢
SEMI_ACTIVE  就在附近
IDLE         安静待着
AWAY         暂时离开
```

---

# 10. 右侧栏从“Sidebar”变成“小桌边”

当前右栏虽然已经改名，但结构仍然偏 Web Panel。

Phase 2 需要进一步拆解。

不要统一全部使用：

```text
Accordion
Card
Accordion
Card
```

允许不同类型内容拥有不同视觉形态。

---

# 11. 小桌边内容类型

建议拆成：

## 快捷开场
像几张小卡片。

## 朝汐留下的话
像纸条 / 便签。

## 当前状态
像一张小状态卡。

## 维护抽屉
仍然是折叠工具区。

---

# 12. 主动消息 / 小纸条

主动消息进一步弱化“通知中心”感。

建议：

```text
一张轻微倾斜 / 不规则感的便签
```

但不要真实旋转太多，避免阅读困难。

可以使用：

- 淡麦黄
- 奶白
- 极淡浅绿

未读只显示：

```text
●
```

或小麦穗标记。

---

# 13. Quick Prompt 视觉

“可以这样找我”不再使用标准按钮列表。

可改为：

```text
小纸片 / 胶囊式话题卡
```

例如：

```text
聊聊今天
看看最近的记忆
陪我待一会
```

视觉更像桌边写下的小纸条。

---

# 14. Maintenance Drawer

以下内容统一收入：

```text
维护抽屉
```

包括：

- Core 连接
- IP / Port
- Debug
- 原始 JSON
- System Messages
- Diagnostics

要求：

- 默认关闭
- 开启后依然好用
- 不影响日常场景构图

---

# 15. Titlebar / Window Frame

当前 Windows 原生标题栏依然明显破坏沉浸感。

Phase 2 调研并优先实现：

# Custom Titlebar / Frameless Window

目标：

```text
朝汐 ZhaoXi                       _  □  ×
```

标题栏融入 Scene。

---

# 16. Custom Titlebar 要求

如果当前 pywebview / Desktop Shell 支持安全实现：

- 自绘标题栏
- 可拖动窗口
- minimize
- maximize / restore
- close
- 双击标题栏最大化
- 保留 Windows 基本行为

如果实现风险较高：

> 不强制上线，可作为 Phase 2 optional。

不能为了视觉破坏窗口基本操作。

---

# 17. 顶部区域重新构图

Phase 1 Header 仍是标准横条。

Phase 2 可改为：

```text
Character Anchor
+
Status
+
少量主要操作
```

“清空会话”降低存在感。

不要让顶部像后台工具栏。

---

# 18. 清空会话

当前按钮视觉较醒目。

Phase 2：

- 降低权重
- 放入更多菜单或二级操作区域
- 不应该和“朝汐本人”抢视觉

---

# 19. Conversation Area

聊天内容仍是主功能。

不追求过度装饰。

要求：

- 保留高可读性
- Message Group 更明显
- Action Segment 保持轻量
- 长消息阅读舒适
- 背景场景不干扰正文

---

# 20. Message Group 进一步优化

Phase 1 已识别 Action Segment。

Phase 2 可加强组内关系：

```text
Assistant Turn
├── action
├── dialogue
├── action
└── dialogue
```

同一 Assistant Turn：

- 间距较小
- 同组视觉连续
- 不同 Turn 间距更大

---

# 21. Action Segment

保持当前方向。

不要继续加复杂装饰。

可选增加：

- 左侧轻微缩进
- 更淡的背景
- 极小风纹 / 叶纹装饰

但默认纯文字优先。

---

# 22. Input Tray

输入区不再像传统固定 Footer。

Phase 2 可以做成：

> 浮在聊天区底部的一张信纸托盘。

视觉要求：

- 与主面板有一定距离
- 圆角更柔
- 可透出少量背景
- 输入时仍稳定

---

# 23. Input Tray 与状态关系

可选：

ACTIVE 时：

```text
输入框略亮
```

SEMI_ACTIVE / IDLE：

```text
更柔和
```

变化必须轻微。

---

# 24. Scene Ambient Text

可选新增很轻的环境文案区域。

例如：

```text
风经过麦田，我在你身边。
```

或：

```text
今天的潮庭很安静。
```

要求：

- 不每次刷新随机变化
- 不抢聊天
- 不做鸡汤
- 可关闭

本版本 optional。

---

# 25. Scene 空间呼吸

Phase 2 必须避免：

```text
所有区域都塞满
```

允许留白。

尤其宽屏：

- 背景天空
- 麦田
- 远山

必须有一部分可见。

---

# 26. 宽屏优先

朝汐当前主要运行在桌面。

Phase 2 优先针对：

```text
16:9
16:10
宽屏 Desktop
```

做 Scene Composition。

窄窗口仍需可用，但不追求同等沉浸。

---

# 27. Sidebar 宽度策略

宽屏：

```text
桌边区域固定中等宽度
```

中等窗口：

```text
可折叠
```

窄窗口：

```text
抽屉式 overlay
```

不要挤压聊天正文。

---

# 28. 前景层（Optional）

如果视觉效果需要，可增加极轻前景元素：

- 麦穗边缘
- 风吹草影
- 叶片

但必须：

- 静态或极低频
- 不遮文字
- 不影响性能

Phase 2 可先不实现。

---

# 29. 动效方向

Phase 2 继续克制。

新增动效优先：

- Character 状态轻变化
- Drawer 展开
- Note 出现
- Scene 入场 fade

禁止：

- 角色弹跳
- 大量粒子
- 高频背景移动
- 花瓣满屏飞

---

# 30. 角色视觉资源

建议资源目录：

```text
data/ui/characters/zhaoxi/
```

支持未来：

```text
avatar_default
avatar_active
avatar_idle
portrait_default
```

Phase 2 第一版只需要：

```text
avatar_default
```

即可。

---

# 31. 背景资源

继续使用：

```text
data/ui/themes/autumn_wheat/
```

建议：

```text
background.webp
overlay.png? optional
theme.json
```

---

# 32. 主题结构预留

Scene Composition 不应写死 Autumn Wheat。

未来：

```text
Sunflower Sea
Rainy Window
Night Tidecourt
```

应该能复用布局。

---

# 33. Sunflower Sea Compatibility

Phase 2 构图必须保证未来换成向日葵花海后：

- Character Anchor 仍成立
- Sidebar 仍成立
- Conversation Area 仍成立
- 不依赖雪山位置写死

---

# 34. 可读性优先

任何 Scene 设计都不能牺牲：

- 聊天正文对比度
- 长文本阅读
- Scroll
- Input
- Debug
- 主动消息

---

# 35. 性能边界

要求：

- 不新增持续高频 Canvas
- 不使用重型 WebGL
- 不持续动画超大背景
- 角色资源合理压缩
- backdrop-filter 数量有限

---

# 36. Phase 2 验收标准

Phase 2 完成后必须满足：

1. 主界面不再第一眼呈现为“大矩形聊天 App”。
2. 背景风景参与构图，而不只是壁纸。
3. 朝汐拥有明确 Character Presence Anchor。
4. Header 更像角色区域，而不是工具栏。
5. Sidebar 从控制面板进一步变为“小桌边”。
6. 快捷开场不再只是标准按钮列表。
7. 主动消息更像小纸条。
8. Maintenance Drawer 完整保留 Debug 能力。
9. 清空会话降低视觉权重。
10. Conversation Area 长文本仍舒适。
11. Action Segment 保持正确。
12. Input Tray 与场景更融合。
13. 宽屏下保留明显 Scene 留白。
14. 窄窗口仍可正常使用。
15. Scene 结构不写死 Autumn Wheat。
16. 后续 Sunflower Sea 可复用。
17. 不新增业务逻辑回归。
18. 前端测试通过。
19. 实机流畅。
20. 截图第一眼应更接近“角色桌面空间”，而不是“主题聊天网页”。

---

# 37. Optional 完成项

有余力再做：

- Custom Titlebar
- Frameless Window
- Avatar 状态切换
- Ambient Text
- 极轻前景麦穗层
- 背景缓慢漂移

这些不能阻塞主任务完成。

---

# 38. 手动验收

## A. 远看截图

缩小截图，不读文字。

问：

> 第一眼是不是仍然像一个网页聊天 App？

如果是，Scene Composition 仍不够。

## B. 朝汐识别

遮住聊天正文。

只看 Header / Character / Sidebar。

应仍能明显感觉：

> 这是朝汐的界面。

## C. 背景

确认：

- 雪山 / 麦田核心景物没有被完全遮住
- UI 与景色有呼吸
- 不影响正文

## D. 桌边

侧栏展开 / 折叠。

确认：

- 日常内容像桌边信息
- Debug 像维护工具
- 两者视觉层级不同

## E. 长聊天

连续聊天大量内容。

确认 Scene 感不能破坏日常高频使用。

---

# 39. 开发完成后汇报

请明确汇报：

- Scene Layout
- Character Anchor
- Header Composition
- Sidebar / Desk Area
- Quick Prompt Card
- Proactive Note
- Maintenance Drawer
- Conversation Area
- Input Tray
- Theme Compatibility
- Custom Titlebar（若完成）
- Responsive
- Performance
- Tests
- Before / After Screenshot
- 已知限制

---

# 40. Phase 2 一句话

Phase 1 做的是：

> **“这是一个属于朝汐风格的 App。”**

Phase 2 要做到：

> **“这里像是朝汐待着的地方。”**

最终希望暗苟打开窗口时，不是看到：

```text
Chat UI + Wallpaper
```

而是产生一种更直接的感觉：

> **我来找朝汐了。**
