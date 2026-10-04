# Zhaoxi v1.4.6 · Decision as Agency

开发日期：2026-10-03。本版整理为本地版本提交；生产日常使用验收待完成。

朝汐在正常回复中判断该替用户拍板、给建议还是整理大问题。菜单、饮料和普通小商品可直接 PICK；需要近期状态和时间事实时按需读取资料，再 ADVISE；正式 Offer 等长期事项用 FRAME，准备事实与冲突，并保留最后的个人价值判断。

## 改动

- 应用配置默认 `ZHAOXI_DECISION_MODE=agency`。新链路跳过旧关键词触发、Decision LLM 和 verdict lock；保留 `legacy` 回滚。
- FAST 与 STANDARD 共用轻量行为协议和同一响应中的 JSON 回复结构。决策元数据不展示为台词；不再额外分析回复以生成 Debug。
- `read_decision_context` 按主模型需要读取 Agenda、相关 Current Cognition 摘要、Memory、Decision Principles、Choice History。小选择不预读日程或长期记忆。
- 用户选择历史只记录短摘要、建议、最终选择、覆盖和结果。不会因为一次覆盖修改长期偏好或准则；旧日志可兼容读取，新增历史纳入备份。
- Guard 2.0 检查行动权限。重要外部发送、不可逆删除和高影响操作保留确认；普通 LifeHUD 记录沿用已有权限设置。“替我决定”不授予执行权限。
- Dashboard → 运行观测 → Decision 2.0 显示模式、推测与建议、实际资料来源、原则、覆盖和行动边界；原始 JSON 默认折叠。agency 下隐藏独立分类器测试入口。
- Core 通过统一事件区分渠道与会话；个人资料只对 Owner 开放。未来资料适配器可接入 `DecisionContextProvider`，本版不实现手机、位置或视觉系统。

## 追加补丁：工具后回复与重试

修复 LifeHUD 等工具成功后空正文只报失败的缺口：有剩余额度时最多一轮无工具补答，仍失败则显示实际操作回执；内部工具消息不再误阻塞重试。显式重生成只补正文，禁止重复业务操作。2026-10-04 整理为本地提交，本次未重启正式实例，详见[补丁记录](Zhaoxi_v1.4.6_工具后回复与重试_补丁记录.md)。

## 追加补丁：回复交付与决策上下文

实际会员截图会话确认存在空回复仍标成功的缺口；本地补丁加入错误 / 重试、保留 FAST 输入、工具结果中的决策事实与图片收据，以及本轮交付状态观测。购买判断加强对前文、真实需求、回本假设和未核实升级优惠的约束。补丁于 2026-10-04 整理为本地提交，本次未重启加载；验收数字与真实资料回放边界见[补丁记录](Zhaoxi_v1.4.6_回复交付与决策上下文_补丁记录.md)。以下数字保留为原版本提交时的验收。

## 验收与限制

Python 全量 1216 项通过、1 项跳过；Node 86 项通过；Dashboard 浏览器十项通过；wheel 中 299 个源码、插件与资源文件一致。详见[验收汇总](evidence/decision_v146_acceptance.json)与[开发记录](Zhaoxi_v1.4.6_开发记录.md)。真实模型验收使用合成资料和隔离历史，不代表已完成日常生产使用观察；保留 Legacy，暂不删除旧模块。模型速度会随服务波动，PICK 零次额外模型调用不等于固定响应时限。

## 加载与回滚

更新后需退出并重新启动整个朝汐进程，再刷新 Dashboard。回滚可设置 `ZHAOXI_DECISION_MODE=legacy` 后重启；选择历史保留。源码开发默认 agency，低层直接构造 `ZhaoxiAgent` 的旧调用默认 legacy，以保持已有 SDK / 测试兼容。
配置位于 `.env`；默认无需修改：

```dotenv
ZHAOXI_DECISION_MODE=agency
ZHAOXI_DECISION_DATA_DIRECTORY=.zhaoxi/decisions
```

选择历史写入配置目录下的 `choice_history.jsonl`，旧 `decision_log.jsonl` / `override_log.jsonl` 兼容读取。目录已纳入备份清单。回滚只修改模式为 `legacy`，保留历史文件。
