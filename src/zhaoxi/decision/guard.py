"""Conservative level and execution guard independent of the classifier."""

import re

from .models import DecisionContext, DecisionLevel, DecisionProposal, DecisionResult, is_directional_verdict


HIGH_IMPACT = re.compile(r"正式.{0,5}offer|两个.{0,5}offer|签约|跳槽|辞职|职业路线|长期.{0,8}(?:周末|项目|承诺|居住)|搬家|买房|大额|借款|贷款|账号安全|删除重要|重大合作", re.I)
UNKNOWN_FACTS = re.compile(r"(?:这个|那个).{0,5}offer.{0,4}(?:接|选|要不要)|offer.{0,4}(?:接吗|接不接)", re.I)
EXTERNAL_EFFECT = re.compile(r"发送|发给|删除|支付|付款|购买|签署|转账|改密码|公开发布")


def guard(proposal: DecisionProposal, context: DecisionContext, *, forced_level: DecisionLevel | None = None,
          tool_metadata: dict | None = None) -> DecisionResult:
    level = forced_level or proposal.level
    original = level
    reasons = []
    matched = {rule.id: rule for rule in context.matched_rules}
    selected = [matched[rule_id] for rule_id in proposal.rule_ids if rule_id in matched]
    if not selected and level == DecisionLevel.L0:
        level = DecisionLevel.L1
        reasons.append("L0 缺少明确匹配规则")
    if HIGH_IMPACT.search(context.user_request):
        level = DecisionLevel.L2
        reasons.append("长期或高影响事项")
    if UNKNOWN_FACTS.search(context.user_request) and not any(
        word in context.user_request for word in ("薪资", "城市", "岗位职责", "方向", "成长", "高薪", "低薪")
    ):
        level = DecisionLevel.L2
        reasons.append("Offer 关键条件不明")
    if proposal.conflicts:
        level = DecisionLevel.L1 if level == DecisionLevel.L0 else DecisionLevel.L2
        reasons.append("规则或事实冲突")
    if proposal.missing_information:
        level = DecisionLevel.L2 if len(proposal.missing_information) >= 2 or level == DecisionLevel.L1 else DecisionLevel.L1
        reasons.append("关键信息缺失")
    if proposal.uncertain or proposal.unknown_side_effects:
        level = DecisionLevel.L1 if level == DecisionLevel.L0 else DecisionLevel.L2
        reasons.append("判断或副作用无法确认")
    defaults = {rule.default for rule in selected}
    if len(defaults) > 1:
        level = DecisionLevel.L1 if level == DecisionLevel.L0 else DecisionLevel.L2
        reasons.append("匹配规则默认方向不一致")
    if level == DecisionLevel.L0 and (not selected or not all(rule.level_hint == DecisionLevel.L0 for rule in selected)):
        level = DecisionLevel.L1
        reasons.append("规则未明确授权 L0")
    if any(rule.level_hint == DecisionLevel.L2 for rule in selected):
        level = DecisionLevel.L2
        reasons.append("匹配规则要求本人判断")
    if level == DecisionLevel.L0 and selected:
        proposal.decision = selected[0].default
    if level == DecisionLevel.L2:
        proposal.decision = ""
        proposal.action = None
    elif not is_directional_verdict(proposal.decision):
        level = DecisionLevel.L2
        proposal.decision = ""
        proposal.action = None
        proposal.core_question = proposal.core_question or "你希望按哪个方向继续？"
        reasons.append("未获得可执行的方向性结论")
    metadata = tool_metadata or {}
    can_execute = (level == DecisionLevel.L0 and bool(selected) and all(rule.auto_execute for rule in selected)
                   and bool(metadata.get("auto_execute")) and metadata.get("risk_level") == "low"
                   and bool(metadata.get("reversible")) and not metadata.get("requires_confirmation")
                   and not EXTERNAL_EFFECT.search(context.user_request) and not proposal.conflicts
                   and not proposal.missing_information and not proposal.unknown_side_effects)
    return DecisionResult(**proposal.model_dump(exclude={"level"}), level=level,
                          verdict=proposal.decision if level != DecisionLevel.L2 else "交由用户决定",
                          can_auto_execute=can_execute,
                          constraints=["do_not_bypass_tool_permission", "do_not_send_external_message"],
                          upgraded_from=original if original != level else None, upgrade_reasons=reasons)
