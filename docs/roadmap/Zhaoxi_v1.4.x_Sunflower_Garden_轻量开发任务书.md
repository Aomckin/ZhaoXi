# Zhaoxi v1.4.x · Sunflower Garden
## 轻量开发任务书

> 项目：**Zhaoxi / 朝汐**\
> 版本：**v1.4.x**（具体补丁版本待定）\
> 类型：**Frontend Visual MVP / Spatial UI / Visual Debt Repayment**
>
> 实施安排：**留到 v1.4 系列最后统一收口前端。** 先完成该系列其他功能；本任务暂缓，不作为下一补丁版本的开发任务。
>
> 上位设计：
>
> `Zhaoxi_v1.4.x_Sunflower_Garden_视觉概念草案.md`
>
> 本任务书目标：
>
> > **先把 Sunflower Garden 做出来一个“能看、能跑、能继续调”的版本。**
>
> 不追求一次定稿。

---

# 1. 总体目标

将当前 Desktop / Web 主界面从普通应用界面，改造成：

```text
朝汐的小房间
+
窗边花海
+
大窗式聊天区
+
浅木小桌
+
桌面功能元素
+
白天 / 黄昏 / 夜晚三态
```

第一轮重点不是“设计完成”，而是：

```text
先看到真实界面
→ 再根据截图挑刺
→ 再调
```

---

# 2. 第一版只做 MVP

本轮只要求：

```text
1. 统一 Design Tokens
2. 建立 Room / Window / Desk 三层空间
3. 聊天区放大并做成窗户感
4. 支持 DAY / DUSK / NIGHT
5. 小桌区域改成浅木桌感
6. 左上角色信息卡统一风格
7. 底部输入区统一风格
8. 右侧面板统一基础视觉
9. 加入蜡烛轻交互
10. 加入简化窗帘轻交互
11. 提供场景 Debug 手动切换
12. 保证现有聊天 / Debug / Presence / Dashboard 功能不坏
```

---

# 3. 本轮明确不做

```text
不重构 Agent Core
不改 Decision
不改 Memory
不改 Presence 逻辑
不改 Tool 行为
不改 Dashboard 信息架构
不做手机端
不做天气 API
不做地理位置
不做实时日出日落
不做复杂粒子系统
不做复杂拖拽
不做小游戏
不做 3D 房间
不新增大型前端框架
```

不要把 v1.4.x 做成整套前端重写。

---

# 4. 开发策略

优先：

```text
现有 DOM / 结构最小改造
+
CSS 重构
+
少量纯前端 JS
```

第一目标：

```text
视觉成立
```

第二目标：

```text
功能不退化
```

---

# 5. Design Tokens

先把新视觉收敛成统一变量。

建议：

```css
:root {
  --sg-bg-room: ...;
  --sg-bg-panel: ...;
  --sg-bg-panel-soft: ...;

  --sg-sunflower: ...;
  --sg-sunflower-soft: ...;
  --sg-sky: ...;

  --sg-wood: ...;
  --sg-wood-light: ...;
  --sg-wood-dark: ...;

  --sg-text-main: ...;
  --sg-text-soft: ...;
  --sg-border: ...;

  --sg-radius-sm: ...;
  --sg-radius-md: ...;
  --sg-radius-lg: ...;

  --sg-shadow-soft: ...;
  --sg-shadow-card: ...;

  --sg-gap-sm: ...;
  --sg-gap-md: ...;
  --sg-gap-lg: ...;
}
```

要求：

```text
所有 Sunflower Garden 新样式尽量基于 token
```

避免继续到处硬编码颜色。

---

# 6. 三时段场景

统一：

```text
DAY
DUSK
NIGHT
```

建议：

```html
<body data-scene="day">
```

或者等价 class / attribute。

场景切换只影响视觉：

```text
背景
房间光感
卡片透明度
阴影
窗框色温
桌面亮度
蜡烛表现
```

---

# 7. 时间段

第一版：

```text
06:00–17:00  DAY
17:00–19:00  DUSK
19:00–06:00  NIGHT
```

时间配置必须集中，不要散落 magic number。

---

# 8. 自动场景更新

页面加载：

```text
读取本地时间
→ 设置 scene
```

运行中：

```text
每隔几分钟检查一次
```

不需要每秒更新。

---

# 9. 场景 Debug

必须提供：

```text
自动
白天
黄昏
夜晚
```

手动模式优先于自动。

恢复自动后重新读取本地时间。

---

# 10. 背景资源位

建议统一目录：

```text
static/assets/sunflower-garden/
├─ day.webp
├─ dusk.webp
└─ night.webp
```

如果正式图片尚未准备好：

```text
先用渐变或临时占位图
```

不要阻塞开发。

---

# 11. DAY

白天：

```text
浅蓝天空
暖白室内
浅木桌
向日葵黄
高明度
低噪音
```

---

# 12. DUSK

黄昏：

```text
暖金
淡橙
少量粉紫
```

避免高饱和橙红。

目标是温暖，不是“火烧云主题”。

---

# 13. NIGHT

夜晚不能只是整体变暗。

需要：

```text
窗外深蓝
室内暖黄
木桌仍然温暖
文字保持清晰
```

原则：

> **房间暖，窗外冷。**

---

# 14. 空间骨架

概念结构：

```text
app-shell
├─ room-layer
├─ window-stage
│  └─ chat-area
├─ desk-layer
│  ├─ identity-card
│  ├─ input-area
│  └─ decorations
└─ side-panel
```

具体 DOM 不强制照搬。

---

# 15. Room Layer

负责：

```text
房间底色
主视觉背景
环境光
```

不承载业务交互。

如果使用 overlay，不能挡住输入、滚动和按钮。

---

# 16. Window Stage

聊天区改成：

> **房间里的大窗。**

第一版要求：

```text
聊天区域比当前更大
外框更像窗框
更舒展
减少普通白色卡片感
```

建议：

```text
浅木 / 暖白边框
柔和内阴影
半透明暖白聊天层
```

---

# 17. 可读性优先

三种场景都必须保证：

```text
消息文字清楚
聊天滚动正常
图片消息正常
表情正常
Action / Progress 正常
```

不能为了透明感牺牲可读性。

---

# 18. 聊天气泡

第一版只轻量统一：

```text
暖白
奶油白
浅天空蓝
柔和圆角
轻阴影
```

不要重写消息结构。

---

# 19. Desk Layer

小桌做成浅木桌感。

优先使用：

```text
低对比渐变
轻纹理
边框
阴影
```

无需真实高清木纹。

---

# 20. 左上角色信息卡

保留现有信息：

```text
头像
名称
Presence
状态
Core 连接
```

只改视觉。

目标：

> **从状态面板变成桌边小立牌。**

---

# 21. 输入区

目标：

> **桌面留言区 / 对话纸条。**

要求：

```text
更宽
与聊天窗自然对齐
暖白
轻阴影
发送按钮统一
```

不改变现有发送逻辑。

---

# 22. 右侧面板

保留现有结构。

只做视觉统一：

```text
圆角
卡片
按钮
留白
层级
```

目标：

```text
像同一房间里的侧边抽屉
```

不要大改信息架构。

---

# 23. Dashboard

本轮只统一：

```text
token
字体
圆角
按钮
卡片
状态色
```

不加花海大背景和场景化装饰。

---

# 24. 蜡烛轻交互

第一版状态：

```text
ON
OFF
```

点击切换。

ON：

```text
显示火苗
显示小范围暖光
```

OFF：

```text
隐藏火苗
关闭局部光
```

---

# 25. 蜡烛自动状态

建议初始：

```text
DAY   OFF
DUSK  OFF
NIGHT ON
```

用户手动切换后，前端优先保留手动状态。

实现保持简单。

---

# 26. 蜡烛持久化

使用：

```text
localStorage
```

不要写入：

```text
Core
Memory
后端 Settings
```

它只是视觉偏好。

---

# 27. 火苗动画

只允许：

```text
轻微晃动
轻微亮度变化
```

CSS animation 足够。

不要上 Canvas 或复杂粒子。

---

# 28. 窗帘轻交互

第一版：

```text
OPEN
HALF
```

点击切换。

无需真实拖拽。

---

# 29. 窗帘实现

推荐：

```text
左右装饰层
CSS transform
```

必须保证：

```text
不挡聊天点击
不挡滚动
不挡输入
```

---

# 30. 窗帘持久化

同样使用：

```text
localStorage
```

纯前端。

---

# 31. 窗外轻动态

本轮优先级低。

如果实现，只做：

```text
云慢移
背景微位移
光晕慢变化
```

如果不稳，可以直接跳过。

---

# 32. 减少动画模式

所有新动画尊重：

```css
@media (prefers-reduced-motion: reduce)
```

---

# 33. 装饰上限

第一版最多：

```text
1 个小向日葵 / 小盆栽
1 个蜡烛
窗帘
少量光斑
```

不要继续自动加家具和挂件。

---

# 34. 层级安全

所有装饰必须明确：

```text
z-index
pointer-events
```

装饰层不能抢功能层事件。

---

# 35. CSS 模块

建议单独新增：

```text
sunflower-garden.css
```

或现有工程中等价模块。

不要把大量新 CSS 继续全部塞回主页面。

---

# 36. JS 模块

建议：

```text
sunflower-garden.js
```

只负责：

```text
scene
candle
curtain
localStorage
debug scene override
```

不要处理聊天、Agent 或 Tool 业务。

---

# 37. 视觉与业务状态隔离

以下状态：

```text
Scene
Candle
Curtain
```

必须独立于：

```text
Presence
Activity
Decision
Memory
```

第一版不做联动。

---

# 38. Presence 不参与场景逻辑

例如：

```text
SLEEP
```

第一版不要自动：

```text
拉窗帘
熄灭蜡烛
```

以后再决定。

---

# 39. 资源失败回退

背景图片加载失败：

```text
回退到 token / CSS 渐变
```

不能白屏、黑块或出现 broken image。

---

# 40. 响应式

本版以当前 Desktop / Web 为主。

但不能只在单一分辨率可用。

至少检查：

```text
当前常用桌面尺寸
较窄窗口
```

过窄时可隐藏非关键装饰。

---

# 41. NIGHT 可读性

夜晚必须重点检查：

```text
文字
按钮
输入框
链接
Debug
错误提示
```

不能只顾氛围。

---

# 42. 性能约束

不能明显增加：

```text
首屏等待
CPU 占用
长期动画开销
内存
```

禁止：

```text
视频背景
60fps Canvas
持续 JS 动画循环
```

优先：

```text
CSS
WebP
低频 timer
```

---

# 43. 资源预算

背景优先：

```text
WebP / AVIF
合理压缩
```

不要直接塞超大 PNG。

---

# 44. 功能回归

至少确认：

```text
发送消息
FAST / STANDARD
图片消息
表情
聊天滚动
Presence
Current Activity
右侧 Debug
设置
Dashboard
Core 重启
```

---

# 45. Debug 视觉控件

建议放：

```text
常用调试 / Sunflower Garden
```

内容：

```text
场景：
[自动] [白天] [黄昏] [夜晚]

蜡烛：
[点亮 / 熄灭]

窗帘：
[打开 / 半合]

[重置视觉状态]
```

---

# 46. 重置视觉状态

清理：

```text
scene override
candle localStorage
curtain localStorage
```

恢复默认。

---

# 47. 页面截图验收

开发完成后至少输出：

```text
DAY 截图
DUSK 截图
NIGHT 截图
```

同一窗口尺寸。

第一轮主要看：

```text
空间是否成立
聊天窗像不像窗
木桌感是否成立
三时段区别是否明显
蜡烛是否自然
整体是否统一
```

---

# 48. 第一轮允许的问题

可以接受：

```text
颜色还要调
背景还要换
窗框还要改
木桌纹理还要调
装饰位置还要挪
```

这些就是下一轮优化内容。

---

# 49. 不允许的问题

不能接受：

```text
功能被挡
聊天无法滚动
输入框错位
NIGHT 看不清文字
场景切换闪屏
CPU 长期高占用
Debug 被装饰盖住
三场景切换时布局跳动
```

---

# 50. 推荐开发阶段

## Phase 1

统一 Design Tokens。

## Phase 2

完成：

```text
Room
Window
Desk
Side Panel
```

先用纯色 / 渐变。

## Phase 3

接入：

```text
DAY
DUSK
NIGHT
```

## Phase 4

加入：

```text
day / dusk / night 背景资源位
```

## Phase 5

实现蜡烛：

```text
ON / OFF
localStorage
CSS flame
```

## Phase 6

实现窗帘：

```text
OPEN / HALF
```

## Phase 7

收束右侧面板与 Dashboard 基础视觉。

## Phase 8

产出三张截图并暂停。

---

# 51. Codex 停止条件

完成 Phase 8 后：

> **停止继续自由美化。**

不要自行：

```text
增加天气
增加更多家具
增加更多动画
重做角色形象
重做 Dashboard
```

等待人工 Review。

---

# 52. 第一轮验收清单

```text
[ ] 主界面具备房间 + 窗边 + 木桌空间感
[ ] 聊天区比旧版更大
[ ] 聊天区具有窗户感
[ ] DAY / DUSK / NIGHT 可自动切换
[ ] Debug 可手动强制场景
[ ] NIGHT 可读性正常
[ ] 蜡烛可点亮 / 熄灭
[ ] 窗帘可 OPEN / HALF
[ ] 轻交互不依赖后端
[ ] localStorage 保存视觉偏好
[ ] 视觉状态不污染 Agent 状态
[ ] 现有聊天与 Debug 功能正常
[ ] Dashboard 至少完成 token 统一
[ ] 三时段截图完成
```

---

# 53. 最终交付

源码：

```text
Sunflower Garden CSS
Sunflower Garden JS
三时段资源槽
必要模板小改
Debug 视觉控件
```

文档：

```text
Zhaoxi_v1.4.x_开发记录.md
Zhaoxi_v1.4.x_Release_Notes.md
```

截图：

```text
day
dusk
night
```

---

# 54. 下一轮怎么做

第一轮出来后，暗苟再根据截图判断：

```text
哪里太挤
哪里太空
哪里太黄
哪里不像木桌
窗户感是否成立
装饰是否过量
夜晚是否舒服
黄昏是否漂亮
```

再开：

```text
v1.4.x 视觉调优补丁
```

或继续同版本迭代。

---

# 55. 核心开发思想

这一轮最重要的不是：

> **把前端一次设计好。**

而是：

> **先获得一个可以真正评价的东西。**

没有真实画面之前：

```text
设计讨论容易漂。
```

有真实画面以后：

```text
截图
→ 挑刺
→ 修改
```

才是这版最适合的开发方式。

---

# 56. 一句话收尾

> **先把朝汐的小屋搭出来。**
>
> **木桌先摆上，窗先开出来，花海先挂到窗外，晚上让蜡烛亮起来。**
>
> **不用第一天就装修到完美。**
>
> **等真的坐进去以后，再慢慢看哪里该挪、哪里该添、哪里该删。**
