(() => {
  "use strict";
  const J = globalThis.ZhaoxiJobApplication;
  const BLOCKED_TYPES = new Set(["file", "submit", "button", "reset", "image", "action"]);
  const BLOCKED_ACTION = /提交申请|最终提交|确认投递|立即申请|确认申请|apply\s*now|submit\s*application/i;
  const DECLARATION = /有关声明|本人声明|诚信声明|背景调查|背调|合规问答|违法|犯罪|不良行为|纪律处分|竞业限制|利益冲突|亲属回避|真实性承诺|签字确认/i;
  const SENSITIVE = /身份证|护照|证件号码|证件号|社会保障|社保|银行卡|家庭信息|家庭情况|家庭成员|社会关系|亲属|父亲|母亲|配偶|子女|紧急联系人|政治面貌|健康状况|疾病|婚姻状况|户籍|户口|籍贯|生源地|详细地址|当前薪资|期望薪资/i;

  J.classifyRisk = (field, definition) => {
    const text = J.normalizeText([
      field.label, field.section, field.placeholder, field.nameHint, field.idHint,
      definition?.label, definition?.section
    ].filter(Boolean).join(" "), 500);
    if (BLOCKED_TYPES.has(field.controlKind) || BLOCKED_ACTION.test(text)) return "prohibited";
    if (definition?.sensitivity === "declaration" || DECLARATION.test(text)) return "declaration";
    if (definition?.sensitivity === "sensitive" || SENSITIVE.test(text)) return "sensitive";
    return definition?.sensitivity || "personal";
  };

  J.decideCandidate = ({ field, definition, confidence }) => {
    const risk = J.classifyRisk(field, definition);
    const reasons = [];
    if (risk === "prohibited") return { risk, decision: "blocked", reasons: ["prohibited_control"] };
    if (risk === "declaration") return { risk, decision: "manual_declaration", reasons: ["declaration_requires_user"] };
    if (risk === "sensitive") return { risk, decision: "manual_sensitive", reasons: ["sensitive_requires_user"] };
    if (field.hasCurrentValue) return { risk, decision: "existing_value_preserved", reasons: ["existing_value_preserved"] };
    if (!field.enabled || !field.visible) return { risk, decision: "unsupported", reasons: ["not_interactable"] };
    if (confidence < 0.85) return { risk, decision: "needs_review", reasons: ["confidence_below_threshold"] };
    return { risk, decision: "auto_fill", reasons };
  };
})();
