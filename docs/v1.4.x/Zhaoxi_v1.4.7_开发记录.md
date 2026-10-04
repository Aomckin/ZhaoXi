# Zhaoxi v1.4.7 开发记录

2026-10-04，基于 `e039e5f` 的 v1.4.6 回复交付修复，按 [Decision Learning 任务书](Zhaoxi_v1.4.7_Decision_Learning_Decision_Journal_开发任务书.md) 实现。

## 信息与来源

明确用户准则在 `data/decisions/user_principles/`，判断经验在配置的 `decision_data_directory`，选择历史保持事件日志。三者没有互相覆写的路径，长期 Memory 不写入日记。

四条初始结构化索引来自已有决策资料；长期价值冲突条目改为引用用户《决策协议》的 L2 原文，避免把朝汐自己写的《先声》当成用户确认的原则。Archive Provider 只读取配置白名单内、解析后仍在 archive 根目录的 Markdown，每份最多 32000 字符、最多 8 个有界片段。查询原文可定位准则的原始节标题；来源区分 user_archive 与 agent_authored_archive。

第一版 User Principles 为只读。自然语言确认原则改变不会自动执行文件编辑；Owner 可修改结构化索引、保留来源，再让按需查询读取。Journal 冲突只生成 Review Candidate，至少两次独立冲突后展示，不更改原准则。

## 主回复和反馈

主回复 JSON 继续旁产 ChoiceFeedback、journal_ids、follow_up_policy 与含时区的 follow_up_after。只接受当前 scope 的候选 ID，或本轮实际工具读取的历史 ID；跨 scope / channel 拒绝。最近候选最多五条、三十天，若更早记录需要先按需检索或通过 Dashboard 选中。对象模糊时模型应不绑定；不能通过关键词把“挺好”硬绑为 GOOD。

反馈字段保留六种标准标签、原话、来源、时间和反馈 ID。结果反馈没有最终选项时保留原有 user_final_choice / overridden。反馈自动终止待回访；不会在前台调用第二个反馈分类器或反思模型。

v1/v2 兼容投影不重写旧事件。Choice History 缓存完整投影，变动后只读新增字节；文件被替换或截短时重建。坏尾行隔离后可继续追加。初次读取需重建索引，日常模型回复不查询整份 Journal / Principles。

## 后台反思与事务

Reflection 由 Internal Activity 从已有反馈取一条处理，不阻塞前台。输入限定为短决策摘要、建议、最终选择、反馈、引用、相关准则与日记、最多六条相关历史。复用现有 Provider，低温、关闭 thinking 的已有兼容参数、有界 JSON 输出和既有调用预算。

输出可为 NONE / CREATE / SUPPORT / REFINE / WEAKEN / CONFLICT / RETIRE。UNKNOWN 本地记为 NONE，不调用模型；不可归因不学习。普通任意 PICK 不因一次 GOOD/BAD 生成日记；反复 NO_DIFFERENCE 可通过反思形成降低决策成本的经验，PICK 创建需至少三个实际提供的独立证据。新条目先为 UNCERTAIN、置信度最多 0.65；单次 delta 限制为 ±0.15。模型引用未提供的选择、反馈目标或用户准则时拒绝提交。

Journal、Reflection 和 Revision 的共同提交写入 `decision_journal.jsonl` 同一事务事件。该文件为权威来源，另外两个 JSONL 是可派生的索引副本；副本写入失败不影响权威读取。反馈在模型等待期间改变、日记被人工编辑时拒绝过期提交。反思已提交而历史标记失败时，重试只修复标记，不再调用模型或重复强化。

LOCKED / PINNED 保留正文与置信度，允许追加证据。人工退役不参与检索；删除保留修订。Gardening 仅自动合并同域、正文、条件、例外完全一致的重复项，90 天未支持标记 STALE，180 天退役；人工项不动。语义冲突与条件修正交给反馈 Reflection 或人工编辑，不作关键词规则裁决。

## 回访与控制

NEVER / PASSIVE 不主动问；OPPORTUNISTIC 在之后同 scope 的自然聊天中由同一主回复选择是否顺便问，并记录 follow_up_asked_id；SCHEDULED 到期后由既有 Internal Activity 执行。允许到期后延后、不合适时安静跳过；超期记录 EXPIRED。手动“现在回访”可提前，但不能绕过 NEVER/PASSIVE、已反馈/已询问、Presence、安静状态、前台交互、最近主动消息与预算。

默认每天最多两次、最短六小时；每个决策最多主动问一次。自动和聊天中顺便问共享历史预算，遵守 Control Plane 的启停、Presence 策略与更严格的活动预算/间隔。投递前先保留 ASKED，避免未知发送结果后重复打扰；若投递失败需查看活动回执，不自动重新询问。

Presence 默认值：回访 ACTIVE/SEMI_ACTIVE 自动、IDLE 仅手动、AWAY/SLEEP 禁用；反思和维护 SEMI_ACTIVE/IDLE 自动、ACTIVE/AWAY 仅手动、SLEEP 禁用。复用前台抢占、失败回退和 Activity Receipt。主动回访通过已有私密 Proactive Inbox / NotificationSink 投递，未添加 QQ 主动发信或新 Scheduler。QQ Owner 私聊能按原 scope 接受反馈与顺便询问，跨频道反馈仍拒绝。

## 管理页、隐私与备份

“判断与成长”包含近期选择、结果反馈、待回访、日记、明确准则和反思/复查记录。所有字符串使用 textContent；技术数据折叠。提供 feedback、reflect 入队、follow-up ask/skip/cancel、Journal CRUD/retire API，准则只读 API；沿用本地管理认证与 Action Receipt。

仅 Owner 私密会话能读写学习数据，PUBLIC / SOCIAL / 群会话即使错误标为 owner 也拒绝。Channel 独立，不依赖 Desktop 类型。Backup Registry 加入 journal/reflection/revision 和用户准则目录。除四份初始索引外，新增私人原则文件默认不纳入 Git；运行时反馈/日记均在已忽略的 `.zhaoxi`。

## 任务书核对

| 阶段 | 实现与边界 |
| --- | --- |
| 1 数据模型 | schema v3、六种反馈、四种策略、Journal/Reflection 类型；旧 v1/v2 兼容 |
| 2 用户准则 | 独立只读索引、白名单 Archive、来源与原文节定位 |
| 3 判断日记 | CRUD、检索、修订、人工锁定/固定/退役 |
| 4 反馈 | 同轮自然反馈、Dashboard 手工录入、scope 隔离、追加事件 |
| 5 反思 | 既有后台活动执行、七种动作、证据验证、失败隔离和幂等恢复 |
| 6 回访 | 同轮策略、自然聊天顺便问、到期 Inbox、Presence/冷却/预算 |
| 7 维护 | 完全相同项合并、stale/退役、人工保护；语义修正依赖反思/人工 |
| 8 上下文 | user_principles / decision_journal 按需查询，principles 兼容映射 |
| 9 Dashboard | 人类可读管理页、手工动作回执、依据与修订展开 |
| 10 Dogfooding | 五个真实模型隔离场景抽验；长期生产 A–F 观察尚未完成 |

## 验证与保留的失败

全量 Python **1298 passed、1 skipped**（239.64 秒），只有已有 Starlette/httpx 弃用警告。后续原文定位、回访 Control Plane 一致性、SOCIAL 边界及 Override 保留调整以最终专项 **130 passed**（4.37 秒）复验。Node **91 passed**。真实 HTTP、管理会话和 headless Edge 的 **9 项浏览器检查通过**，包括反馈、后台队列回执、日记生成、锁定、证据展开、原文来源、未认证 API 和脚本错误；截图在 `.zhaoxi/v147-decision-learning.png`。

真实模型最终五项合成场景全部通过：FAST PICK、明确自然结果反馈、不关联普通闲聊、GOOD 支持日记、三次 NO_DIFFERENCE 学习决策成本。每项 generate 调用一次；Reflection 调用属于后台反思，不是 PICK 的额外分析。计数不包含 Provider 传输尝试。脚本显式运行，使用现有模型配置和独立合成历史，不调用生产业务工具或读取真实用户记忆。

保留失败证据：首次沙箱网络传输失败；其后两轮自然反馈只生成回应，漏写 feedback 字段。补齐候选旁的同轮反馈协议与 schema 描述后最终通过，没有新增分类器或补问模型。模型仍可能漏报元数据、把台词说成过强的长期承诺、给 PICK 添加多余解释；这次抽验不能证明所有自然反馈都会正确捕获，Dashboard 可手动补录。长期使用仍需观察。

最终 wheel 与源码逐字节核对、compileall 和 git diff --check 的结果见 [自动验收汇总](evidence/decision_v147_acceptance.json)；浏览器证据见 [浏览器验收](evidence/decision_v147_browser_acceptance.json)，真实模型与失败尝试见 [真实模型验收](evidence/decision_v147_live_acceptance.json)。

本轮只改源码与隔离验收，未重启正式实例。退出后重新启动朝汐，并刷新 Dashboard 加载 v1.4.7；学习可通过 `ZHAOXI_DECISION_LEARNING_ENABLED=false` 关闭。当前用户准则与 archive 是本地资料，wheel 不携带个人 archive/准则，安装环境应配置对应目录。

## 回复分组补丁（2026-10-04）

截图对应的本地会话中，同一次模型回复因表情 DSL 被保存为两段正文，共用 reply_group_id。前端只按每条 output message 建组，未使用这个 ID；后端重新生成也只检查单条消息，点击首段或中间表情会把同组后半段视为后续回复而拒绝。段落气泡拆分保留，同一次回复现在共用整个展示组和重试按钮。

实时输出、刷新恢复及 Inbox 激活统一使用回复组；重新生成接受最新普通回复组中的任意一段，一次替换整组。工具操作完成后的重试隐藏整组旧正文并保留工具结果，避免残留旧段或重复操作。图片末段也保留重试入口；后续有新用户消息或主动消息时仍拒绝重试旧回复。

修复前首段和中间表情两项回归失败，修复后 Python **95 passed**、Node **94 passed**、headless Edge **5 项通过**，未调用真实模型。安装包重新生成并逐字节核对 293 个源码资源，compileall 与 git diff --check 通过。见 [回复分组修复证据](evidence/reply_group_v147_patch.json)。生产会话只读检查，未改写历史或重启正式实例；重启后刷新页面加载补丁，已有 reply_group_id 的历史自动按组恢复。
