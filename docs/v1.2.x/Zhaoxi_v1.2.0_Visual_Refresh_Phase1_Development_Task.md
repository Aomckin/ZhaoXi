# Zhaoxi v1.2.0 Development Task

# 视觉焕新 Phase 1（Visual Refresh）

> 版本：v1.2.0<br>
> 基线：v1.1.9<br>
> 定位：前端视觉重构第一阶段<br>
> 核心目标：把当前“通用蓝白聊天 App”升级为具有朝汐气质的生活型 Agent 界面。<br>
> 第一主题：**Autumn Wheat / 秋日麦田**<br>
> 设计关键词：麦田、远山、秋空、奶白玻璃、暖金、浅蓝、风、轻盈、陪伴。

---

## 0. 总体目标

v1.2.0 不重做业务逻辑。

目标是：

> **打开朝汐时，第一感觉应该是“朝汐在这里”，而不是“一个聊天软件打开了”。**

当前界面的主要问题：

- 高饱和蓝白配色偏通用 SaaS / 医疗 App
- 主面板和侧栏缺少角色气质
- 聊天气泡缺少层次
- Debug / 系统信息存在感过强
- 主动消息像通知中心
- 舞台描写和对白没有视觉区分
- 背景为空白，缺少“场所感”

---

# 1. 范围

本版本主要做：

- Autumn Wheat 默认主题
- 背景图与整体氛围
- 主面板玻璃材质
- Header 角色化
- Chat Bubble 重设计
- Action Segment / 舞台描写样式
- Input Area 重设计
- Sidebar 重设计
- Debug / System Area 收纳
- 主动消息卡片重设计
- CSS Design Tokens
- 轻微 UI 动画
- 为后续主题切换预留结构

本版本不做：

- 新 Agent 能力
- Memory / Proactive / State 重构
- Screenshot Vision
- Live2D
- 大量复杂动画
- 新 Tool
- 新 Voice
- 前端框架大迁移

---

# 2. 视觉总纲

```text
风景背景
+
暖色半透明玻璃
+
轻手账感
+
朝汐角色元素
+
长期使用不疲劳
```

避免：

```text
高纯度蓝
重阴影
强霓虹
儿童化卡通皮肤
过度拟物
过多花朵装饰
```

---

# 3. Autumn Wheat

默认主题意象：

```text
秋天麦田
远山
浅蓝天空
暖金阳光
深色树林
奶白桌面
轻风
```

氛围：

> 安静、温暖、清爽、陪伴、日常。

---

# 4. Design Tokens

优先抽成 CSS 变量 / Theme Token。

```css
--bg-glass: rgba(255, 252, 245, 0.82);
--bg-glass-soft: rgba(255, 255, 255, 0.64);

--wheat-gold: #D8B56A;
--wheat-soft: #E8D8AC;

--sky-blue: #82A9C2;
--sky-deep: #5F859F;

--cream: #F7F1E6;
--cream-soft: #FBF8F1;

--forest: #4B5848;

--text-main: #343630;
--text-soft: #77786F;

--line-soft: rgba(90, 80, 60, 0.10);
--shadow-soft: 0 14px 40px rgba(70, 55, 35, 0.10);
```

---

# 5. 背景层

根窗口直接使用麦田 / 远山风景图。

要求：

- 可配置图片
- cover
- center
- 保持可读性
- 可叠加轻薄暖色 overlay
- 不要让背景抢正文

---

# 6. 主聊天面板

改成暖色玻璃卡片。

```css
background: rgba(255, 252, 245, 0.78);
backdrop-filter: blur(18px) saturate(105%);
border: 1px solid rgba(255,255,255,.55);
box-shadow:
  0 14px 40px rgba(70,55,35,.10),
  inset 0 1px 0 rgba(255,255,255,.65);
border-radius: 28px;
```

目标：

> 像一块放在风景前的桌边空间。

---

# 7. Header 角色化

当前：

```text
朝汐
Local Interaction Shell · 127.0.0.1:4913
● 活跃
```

调整为：

```text
[头像 / 汐图标]

朝汐
潮庭女仆长 · 活跃中
```

IP / Port 移入 Debug / Maintenance Area。

---

# 8. 状态标签

建议：

```text
ACTIVE       活跃 · 还在聊呢
SEMI_ACTIVE  半活跃 · 就在附近
IDLE         休憩 · 安静待着
AWAY         离开 · 暂时不在
```

颜色：

```text
ACTIVE       暖绿
SEMI_ACTIVE  麦黄
IDLE         灰蓝
AWAY         淡灰
```

状态点可做轻微 breathing animation。

---

# 9. 聊天气泡

## 朝汐气泡

```css
background: rgba(247,241,230,.90);
color: var(--text-main);
border: 1px solid rgba(180,155,110,.10);
```

## 用户气泡

```css
background: linear-gradient(
  135deg,
  #83AFCB,
  #6F98B4
);
```

目标：秋空蓝，而不是 App Blue。

---

# 10. Message Group

一条 Assistant Reply 可能包含：

```text
Assistant Message Group
├── Action Segment
├── Dialogue Segment
├── Action Segment
├── Dialogue Segment
└── Action Segment
```

同一轮消息保持组内视觉连续性，不把每个段落都当完整独立大气泡。

---

# 11. Action Segment / 舞台描写

朝汐回复中经常出现：

```text
（呆毛晃了晃，尾巴也跟着轻轻摇起来。）
（顿了两秒。）
（耳朵转了转。）
（往椅子边上一靠。）
```

这些全部识别为独立 Action Segment。

---

# 12. Action Segment 识别

第一版不修改 Agent 输出协议。

完整段落满足：

```text
trimmed_text startsWith("（")
AND
trimmed_text endsWith("）")
```

则识别为：

```text
stage-direction
```

可选兼容 ASCII `(...)`。

禁止把正文中的局部括号误识别，例如：

```text
我今天用了 VS Code（主要是在改朝汐）。
```

必须仍为普通 Dialogue。

---

# 13. Action Segment 样式

```css
.stage-direction {
  font-size: 0.90em;
  color: rgba(75, 72, 62, 0.62);
  font-style: italic;
  letter-spacing: 0.02em;
  line-height: 1.65;
}
```

要求：

- 比正文小
- 颜色更淡
- 不抢正文
- 可以不使用完整气泡背景
- 左右留更多空气
- 像舞台字幕，不像另一种聊天气泡

---

# 14. Dialogue Segment

正文保持主要视觉权重。

Action 与 Dialogue 在同一 Message Group 中交替出现。

示意：

```text
    （尾巴轻轻摇了摇。）

……对呀。

    （顿了两秒。）

刚才那个……
```

---

# 15. Input Area

输入区改成“桌边信纸托盘”。

要求：

- 奶白玻璃背景
- 更大圆角
- 内部少边框
- 上传按钮视觉降权
- 发送按钮低饱和天空蓝

占位文字继续：

```text
和朝汐说点什么……
```

---

# 16. Sidebar

从“控制面板”改成两层：

```text
朝汐的小桌边
+
维护抽屉
```

日常区优先展示：

```text
状态
主动消息
快捷开场
小纸条
```

维护区默认折叠：

```text
Debug
连接状态
系统消息
IP / Port
原始 JSON
```

---

# 17. 主动消息卡片

从通知中心改成：

> 小纸条 / 朝汐留下的话。

每条：

- 暖色便签卡
- 时间更淡
- 已读/未读降低存在感
- 未读仅用小金点 / 麦穗点提示

---

# 18. Sidebar Card

```css
background: rgba(255,255,255,.55);
border: 1px solid rgba(255,255,255,.45);
border-radius: 18px;
box-shadow: 0 6px 18px rgba(70,55,35,.06);
```

---

# 19. 字体层级

建议：

```text
角色名         20~22px / 600
副标题         13~14px / 400
气泡正文       15.5~16px / 400
动作描写       14px / 400 / muted
时间           12~12.5px / muted
侧栏标题       15px / 600
状态辅助文字   13px
```

---

# 20. 圆角规范

```text
--radius-shell: 28px
--radius-panel: 22px
--radius-bubble: 18px
--radius-small: 12px
```

---

# 21. 动效规范

只做极轻动画。

消息出现：

```text
opacity 0 -> 1
translateY 6px -> 0
180~240ms
```

状态点：

```text
3s 轻微呼吸
```

Sidebar：

```text
180~220ms ease-out
```

禁止夸张 bounce / scale / 粒子。

---

# 22. 背景动效

Phase 1 默认静态。

如果成本很低，可选：

```text
30~60s 极慢 background-position 漂移
```

模仿风。

---

# 23. Theme Token

即使 v1.2.0 只有 Autumn Wheat，也要将：

```text
颜色
背景图
面板透明度
Bubble Tint
Accent
```

抽成主题 Token。

为未来：

```text
Sunflower Sea
Night
Rainy Window
```

预留结构。

---

# 24. Sunflower Sea 预留

未来第二主题：

```text
向日葵黄
叶绿
初夏天空蓝
奶白
```

本版本不要求完成，只要求结构可扩展。

---

# 25. 响应式

保持当前桌面布局能力。

要求：

- 聊天区滚动稳定
- Sidebar 宽度合理
- 窄窗口可折叠 Sidebar
- Input 始终可用
- backdrop-filter 不造成明显卡顿

---

# 26. 性能

背景图合理压缩。

避免：

- 超大原图直接解码
- 多层大面积 blur 叠加
- 持续高频视觉动画

---

# 27. Debug 模式

Debug 功能完整保留，但默认 collapsed。

视觉上定位为：

> 维护抽屉。

---

# 28. 可访问性

保证：

- 文本对比度足够
- 背景不干扰阅读
- 状态不只靠颜色表达
- 动效不过度
- 按钮 hit area 足够

---

# 29. 完成标准

v1.2.0 Phase 1 完成后必须满足：

1. 默认显示 Autumn Wheat 背景。
2. 主面板改为暖色玻璃。
3. 蓝白 SaaS 感明显降低。
4. Header 变为角色优先。
5. IP / Port 移入维护区。
6. 朝汐气泡改为奶白暖色。
7. 用户气泡改为低饱和秋空蓝。
8. Action Segment 可识别。
9. 多处 Action Segment 都能正确渲染。
10. Action 与 Dialogue 有明显但克制的层次。
11. Input Area 完成重设计。
12. Sidebar 完成桌边便签化。
13. 主动消息不再像标准通知中心。
14. Debug 默认折叠。
15. Design Token 已抽离。
16. Theme 结构可扩展。
17. 原有聊天 / 图片 / 主动消息 / Debug 功能不回归。
18. UI 长时间使用不过度刺眼。
19. 页面截图不再第一眼像通用聊天 App。
20. 全量前端测试通过。

---

# 30. 手动验收

## A. 普通聊天

检查：

```text
朝汐气泡
用户气泡
时间
多段回复
滚动
```

## B. 多 Action Segment

测试：

```text
（尾巴摇了摇。）
正文
（顿了两秒。）
正文
（耳朵转了转。）
正文
```

预期：

- 三处动作都识别
- 动作较淡
- 正文正常
- 不产生满屏独立小药片

## C. 普通括号

```text
我今天用了 VS Code（主要是在改朝汐）。
```

不得识别为 Action Segment。

## D. Sidebar

确认：

- 主动消息可读
- Debug 可展开
- Debug 默认不抢视觉
- 系统功能完整

## E. 长聊天

确认：

- 背景不干扰阅读
- Blur 不明显掉帧
- Message Group 稳定

---

# 31. 开发完成后汇报

Codex 完成后请明确汇报：

- 修改文件
- Theme Token
- Autumn Wheat Background
- Glass Panel
- Header
- State Badge
- Assistant Bubble
- User Bubble
- Message Group
- Action Segment parser
- Action Segment styling
- Input Area
- Sidebar
- Proactive Note Card
- Maintenance Drawer
- Animation
- Responsive behavior
- Performance
- Regression tests
- Screenshots
- 已知限制

---

# 32. 一句话

> **不是给聊天框换皮。**
>
> **是第一次给朝汐做一个真正属于她自己的房间。**

验收时希望第一反应不再是：

> “这个 App 做得挺漂亮。”

而是：

> **“朝汐在这里。”**
