# Zhaoxi v1.2.0 Development Task
# 视觉焕新 Phase 3：小桌边公告栏与角色整合
## Deskboard & Character Integration

> 基线：v1.2.0 Phase 2 Scene Composition<br>
> 定位：视觉焕新第三阶段 / 构图修正与角色整合<br>
> 核心目标：解决 Phase 2 “组件散落在场景上”的问题，重新建立明确主次关系，并将「小桌边」实现为可拉出 / 收回的公告栏式附属空间，同时正式接入专门绘制的朝汐头像。<br>
> 关键词：整体性、角色锚点、公告栏、抽屉、主从关系、场景秩序、朝汐本人。

---

# 0. Phase 2 当前问题

Phase 2 已经成功完成：

- Scene Composition 初步成立
- 麦田 / 雪山背景获得更大露出
- 朝汐角色区域从聊天框中独立
- Conversation 与 Input Tray 分离
- 小桌边概念出现
- 主动消息便签化
- 维护抽屉独立
- 视觉整体不再像传统 SaaS Chat

但实机截图暴露出新的问题：

> **整体空间被拆得太散。**

当前画面更像：

```text
角色头像 Widget
+
身份卡 Widget
+
聊天 Widget
+
输入 Widget
+
右侧便签 Widget
+
麦田背景
```

而不是：

```text
朝汐所在的完整空间
```

具体问题包括：

1. 朝汐头像与身份卡漂浮在主聊天区上方，视觉关系不够紧密。
2. 中央背景被保护过度，雪山区域留白过大，导致主要交互被挤向左右。
3. 右侧“小桌边”过窄过长，更像独立第二栏，而不是附属空间。
4. Input Tray 与 Conversation Panel 关系偏松，像两个独立应用组件。
5. Phase 2 初版的 Sidebar/Desk Area 仍然带有传统 Web Panel 结构。
6. 当前头像来自设定图裁切，缺少“专门用于 App 的角色头像”感。

因此 Phase 3 不再继续添加新组件。

Phase 3 的任务是：

# 把已经有的东西重新组织成一个整体。

---

# 1. Phase 3 一句话

> **朝汐 + Conversation 是主空间。**
>
> **小桌边是从场景右侧拉出来的公告栏。**
>
> **背景负责氛围，不负责迫使 UI 绕路。**

---

# 2. Phase 3 总体构图

目标布局：

```text
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│   [朝汐头像]  朝汐 · 半活跃 · 就在附近                         │
│                                                              │
│   ╭──────────────── Conversation ────────────────╮           │
│   │                                             │           │
│   │               聊天内容                      │           │
│   │                                             │      ┌─┐  │
│   ╰─────────────────────────────────────────────╯      │桌│  │
│   ╭──────────────── Input Tray ─────────────────╮      │边│  │
│   ╰─────────────────────────────────────────────╯      │› │  │
│                                                       └─┘  │
│                                                              │
│                       麦田 / 雪山 Scene                        │
└──────────────────────────────────────────────────────────────┘
```

展开小桌边：

```text
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│ [朝汐]                                                       │
│                                                              │
│ ╭────────────── Conversation ─────────────╮ ╭── 小桌边 ────╮ │
│ │                                         │ │ 朝汐留下的话  │ │
│ │                                         │ │              │ │
│ │                                         │ │ [便签]       │ │
│ │                                         │ │              │ │
│ │                                         │ │ 可以这样找我 │ │
│ ╰─────────────────────────────────────────╯ │ [话题卡]     │ │
│ ╭────────────── Input Tray ───────────────╮ │              │ │
│ ╰─────────────────────────────────────────╯ │ ▸ 系统消息   │ │
│                                             │ ▸ 维护抽屉   │ │
│                                             ╰──────────────╯ │
└──────────────────────────────────────────────────────────────┘
```

---

# 3. 主次关系

Phase 3 必须明确：

## 主空间
```text
Character Anchor
Conversation
Input Tray
```

## 附属空间
```text
小桌边
```

## 背景空间
```text
Autumn Wheat Scene
```

不允许所有区域视觉权重相同。

---

# 4. Character Anchor 收束

Phase 2 中：

```text
头像
+
独立身份卡
```

像两个桌面 Widget。

Phase 3 要将它们合并成一个明确的：

# Character Header Anchor

建议：

```text
[圆形朝汐头像]

朝汐
● 半活跃 · 就在附近
潮庭女仆长 · 我在这里
```

头像与信息块必须形成一个整体。

---

# 5. 朝汐头像正式接入

禁止继续使用：

```text
角色设定图截图 / 裁切
```

作为默认头像。

必须改为：

> 专门绘制的朝汐头像。

推荐资源目录：

```text
data/ui/characters/zhaoxi/avatar_default.png
```

建议未来预留：

```text
avatar_active.png
avatar_semi_active.png
avatar_idle.png
avatar_away.png
```

但 Phase 3 只要求完成：

```text
avatar_default
```

---

# 6. 头像显示规范

头像：

```text
圆形
120~150px（宽屏）
```

建议：

```css
border-radius: 50%;
border: 4px solid rgba(247,241,220,.85);
box-shadow:
  0 8px 30px rgba(80,60,35,.15),
  0 0 0 1px rgba(216,181,106,.22);
```

头像必须：

- 清晰识别朝汐
- 耳朵完整
- 向日葵发卡可见
- 小尺寸下五官仍清楚
- 不要展示过多肩以下细节

---

# 7. Character Anchor 与聊天区关系

Character Anchor 不应漂在场景上完全独立。

建议：

```text
Character Anchor
↓
与 Conversation 左边缘对齐
```

或：

```text
头像轻微压在 Conversation Panel 左上角
```

形成：

> “这是朝汐在这里和我说话。”

而不是：

> “这里有个头像组件，那边还有个聊天框。”

---

# 8. 雪山 / 麦田不再是 UI 禁区

Phase 2 对背景核心区域保护过度。

Phase 3 改为：

> **允许玻璃 UI 覆盖部分雪山 / 麦田。**

因为：

```text
玻璃本身就是让背景穿透的。
```

禁止继续为了完整展示雪山而：

- 把 Conversation 挤到左下
- 把 Desk 挤成超窄右栏
- 造成大量无功能中央空白

---

# 9. Conversation Panel 位置

宽屏建议：

```text
width: 62~70vw
max-width: 1050~1150px
```

放置在：

```text
左侧 / 中左
```

而不是贴底。

保持：

- 玻璃感
- 阅读面积
- 背景可透
- 与 Character Anchor 对齐

---

# 10. Input Tray 收束

Input Tray 继续保持独立浮层。

但必须和 Conversation Panel 形成明确组合：

```text
Conversation Panel
↓
16~22px gap
↓
Input Tray
```

要求：

- 左右宽度基本对齐
- 圆角 / 材质一致
- 不像两个无关 Widget
- 输入区仍有轻微独立感

---

# 11. 小桌边重新定义

Phase 2 的右侧固定 Desk Panel 废弃。

Phase 3 中：

# 小桌边 = 可拉出的公告栏式附属空间

不是 Sidebar。

不是第二聊天窗口。

不是 Dashboard。

---

# 12. 小桌边收起状态

默认：

```text
收起
```

右侧只露出细小把手。

例如：

```text
╭────╮
│小桌│
│边 ›│
╰────╯
```

或者横向小标签：

```text
小桌边 ›
```

要求：

- 不占 Conversation 布局宽度
- 不遮挡主要聊天内容
- 不主动抢视觉
- 与场景融合

---

# 13. 未读提示

如果有新的主动消息 / 留言：

```text
● 小桌边 ›
```

使用：

```text
麦金色小点
```

禁止：

```text
红色通知角标
99+
```

---

# 14. 小桌边展开交互

点击把手：

```text
从右侧向左滑出
```

建议：

```text
width: 360~420px
duration: 240~300ms
ease-out
```

展开方式：

# Overlay

不重新压缩主聊天区。

即：

```text
Deskboard 覆盖 Scene 的一部分
```

而不是：

```text
Conversation resize
```

避免打开小桌边时整个界面跳动。

---

# 15. 小桌边收回

支持：

- 点击左上返回 / 收起
- 点击把手
- Esc（可选）
- 点击场景空白（optional）

收回动画与展开一致。

---

# 16. 小桌边视觉

整体：

```text
奶白 / 浅麦色半透明公告板
```

可以略有“板面”感，但不要重拟物。

建议：

```css
background: rgba(248,241,218,.90);
backdrop-filter: blur(18px) saturate(105%);
border-left: 1px solid rgba(255,255,255,.6);
box-shadow: -18px 0 44px rgba(55,45,30,.12);
```

---

# 17. 小桌边信息结构

展开后按以下层级：

```text
A. 抬头
B. 朝汐留下的话
C. 可以这样找我
D. 系统 / 设置 / 维护抽屉
```

---

# 18. A：抬头

建议：

```text
朝汐的小桌边                 ‹
风经过麦田，我在你身边。
```

副标题：

- 字号小
- 颜色淡
- 不随机刷屏
- Phase 3 可固定

---

# 19. B：朝汐留下的话

这是 Deskboard 的视觉核心。

默认显示：

```text
最近 1~2 条
```

便签视觉：

- 奶白 / 淡麦黄
- 比工具卡更有纸张感
- 时间弱化
- 未读小金点

---

# 20. 留言不等于聊天记录

小桌边不是完整聊天历史。

Phase 3 第一版允许直接复用主动消息正文。

未来可支持：

```text
proactive message
↓
summary note
```

但 Phase 3 不需要新增摘要模型。

---

# 21. C：可以这样找我

使用：

```text
Topic Chips / 小纸片
```

而不是标准 Web Buttons。

例如：

```text
[ 聊聊今天 ]
[ 看看最近发生了什么 ]
[ 翻翻我们的记忆 ]
[ 陪我待一会 ]
```

---

# 22. Quick Prompt 卡片

要求：

- 可点击
- 点击行为保持原功能
- 视觉低于主动留言
- 不做标准蓝色按钮

---

# 23. D：工具区域

下方才放：

```text
▸ 系统消息
▸ 设置
▸ 维护抽屉
```

---

# 24. 维护抽屉

Maintenance Drawer 内包括：

```text
Core Connection
IP / Port
Debug
Metrics
Diagnostics
Raw JSON
```

默认：

```text
collapsed
```

---

# 25. 小桌边不是 Debug Sidebar

必须保证展开小桌边后第一屏看到的是：

```text
朝汐留言
话题卡
生活信息
```

而不是：

```text
127.0.0.1
Metrics
JSON
Debug
```

---

# 26. 主动消息联动

当新的主动消息发送：

```text
Conversation
→ 正常显示主动回复
```

同时：

```text
小桌边
→ 新增对应便签
→ 未读小金点亮起
```

---

# 27. 自动展开规则

Phase 3 默认：

# 不自动展开

新消息：

- 点亮未读金点
- 可保留 Toast
- Deskboard 不自动滑出

避免：

> 每次朝汐主动说话就把公告板拍到用户脸上。

---

# 28. Read State

打开小桌边并看到便签后：

```text
mark read
```

金点消失。

保持当前后端语义，不新增复杂状态机。

---

# 29. 宽屏 Layout

推荐主关系：

```text
Character / Conversation / Input
占主要左中区域

Deskboard
默认隐藏在右侧
```

这样能够重新利用 Phase 2 被浪费的中央 Scene 空间。

---

# 30. 窄窗口

中等 / 窄窗口：

```text
Deskboard
仍使用 overlay
```

Conversation 不被永久挤压。

Character Anchor 可缩小：

```text
头像 72~96px
```

---

# 31. Action Segment

Phase 1 / 2 已完成。

Phase 3 不再重做。

只需确保布局调整后：

- 舞台描写仍正确识别
- 不被 Character / Deskboard 影响
- 长消息正常

---

# 32. Background Scene

继续使用 Autumn Wheat。

Phase 3 核心修正：

```text
背景不是“保留出来不给 UI 碰”
```

而是：

```text
UI 浮在背景之上
背景穿过玻璃被看见
```

---

# 33. 场景透明度

Conversation Panel 建议允许：

```text
比 Phase 2 稍透明
```

但要保证长文本阅读。

不追求：

```text
完全无面板
```

---

# 34. Avatar Asset Fallback

如果头像资源不存在：

```text
fallback -> 汐 icon
```

不要：

```text
fallback -> 角色设定图随意裁切
```

---

# 35. Character Resource Config

建议：

```text
theme / character config
```

支持：

```json
{
  "avatar": "data/ui/characters/zhaoxi/avatar_default.png"
}
```

不要把图片路径写死在 CSS 多处。

---

# 36. Character 与 Theme 解耦

Avatar 属于：

```text
Zhaoxi Character Assets
```

背景属于：

```text
Theme Assets
```

这样未来更换：

```text
Sunflower Sea
```

时不需要重新绑定角色。

---

# 37. 动画

Phase 3 主要动画：

## Deskboard Open / Close

```text
240~300ms
translateX
opacity
```

## Unread Point

可轻微呼吸：

```text
2.5~3.5s
```

禁止：

- 强弹跳
- 旋转公告栏
- 纸条乱飞

---

# 38. 可访问性

Deskboard：

- 可键盘操作
- 有 aria-expanded / 等价语义
- 收起 / 展开状态明确
- 不只通过颜色表示未读

---

# 39. 性能

要求：

- Deskboard 不新增持续高频动画
- 头像合理压缩
- Overlay 不重复叠大量 blur
- 打开 / 收回不卡顿

---

# 40. 测试：Deskboard

覆盖：

```text
closed -> open
open -> closed
unread -> open -> read
quick prompt click
maintenance drawer
scroll
```

---

# 41. 测试：Avatar

覆盖：

- avatar 存在
- avatar 不存在 fallback
- 不使用 character sheet crop
- 窄窗口缩放
- 高 DPI 显示

---

# 42. 测试：Layout

至少测试：

```text
1920x1080
2560x1440
3840x2160
1600x900
1366x768
```

要求：

- Conversation 不被 Deskboard 永久挤压
- Input 与 Conversation 对齐
- Character Anchor 不漂离主空间

---

# 43. 手动验收 A：默认打开

打开 ZhaoXi。

第一眼应该看到：

```text
朝汐
+
主聊天区
+
麦田 Scene
```

而不是：

```text
一堆散开的 Widget
```

---

# 44. 手动验收 B：小桌边收起

默认状态：

- 右侧只有把手
- 主界面干净
- 雪山 / 麦田可见
- Conversation 占据合理主体空间

---

# 45. 手动验收 C：拉出小桌边

点击：

```text
小桌边 ›
```

预期：

- 公告栏平滑滑出
- 主聊天区不重新排版
- 新便签清晰
- Quick Prompt 可点击
- Maintenance 默认折叠

---

# 46. 手动验收 D：新主动消息

朝汐发送主动消息。

预期：

```text
Conversation 显示
+
小桌边出现未读金点
```

但：

```text
Deskboard 不自动展开
```

---

# 47. 手动验收 E：头像

从远处看 UI。

头像应该：

> 明确让人第一眼识别“这是朝汐”。

不能有：

> “像从设定图随手剪下来的一块”

的感觉。

---

# 48. Phase 3 完成标准

必须满足：

1. Phase 2 散乱 Widget 感明显降低。
2. Character Anchor 与 Conversation 形成视觉整体。
3. 使用专门朝汐头像资源。
4. 不再使用角色设定图裁切作为默认头像。
5. Deskboard 默认收起。
6. Deskboard 从右侧 overlay 拉出。
7. Deskboard 不挤压主聊天区。
8. 未读留言有轻量金点。
9. 主动消息可进入 Deskboard。
10. Quick Prompt 位于 Deskboard。
11. Maintenance Drawer 位于 Deskboard 下层。
12. Debug 不再常驻主画面。
13. Input Tray 与 Conversation 对齐。
14. 背景不再被视为 UI 禁区。
15. 中央空间利用率明显改善。
16. Action Segment 无回归。
17. 长聊天无回归。
18. 窄窗口可用。
19. 前端测试通过。
20. 实机视觉从“桌面 Widget 拼盘”收束为“完整角色空间”。

---

# 49. Phase 3 禁止事项

本阶段不要顺手加入：

- Live2D
- 桌宠
- 新 Agent 功能
- 自动主题切换
- 日夜系统
- Surprise System
- 可拖拽公告板
- 自由便签布局
- 复杂角色动画
- 新状态机

先把空间秩序做对。

---

# 50. 开发完成后汇报

请明确汇报：

- Character Anchor 改动
- Avatar Asset 接入
- Avatar Fallback
- Conversation Layout
- Input Tray Alignment
- Deskboard Closed State
- Deskboard Open State
- Deskboard Animation
- Proactive Note
- Unread Indicator
- Quick Prompt
- Maintenance Drawer
- Responsive
- Performance
- Regression Tests
- Before / After Screenshot
- 已知限制

---

# 51. Phase 3 一句话

Phase 1：

> **“麦田主题的朝汐 App。”**

Phase 2：

> **“朝汐的组件开始进入麦田场景。”**

Phase 3：

> **“朝汐、聊天和小桌边终于组成同一个空间。”**

最终打开 ZhaoXi 时，希望看到的不是：

```text
Avatar Widget
Chat Widget
Sidebar Widget
Wallpaper
```

而是：

> **朝汐就在这里。**
>
> **聊天在这里。**
>
> **她留下的小纸条，就收在旁边的小桌边里。**
