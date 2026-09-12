(() => {
  "use strict";
  const J = globalThis.ZhaoxiJobApplication;

  const sectionAliases = {
    basic: /基本信息|个人信息|个人资料|基本资料/i,
    job_preference: /求职意向|应聘信息|职位申请/i,
    education: /教育|学历|在校/i,
    work: /工作经历|任职经历|职业经历/i,
    internship: /实习|实践经历/i,
    project: /项目|课题/i,
    family: /家庭|家属|亲属/i,
    declarations: /声明|合规|背景调查|附加问题/i
  };

  const profileHasPath = (catalog, path) => catalog.some((item) => item.path === path && item.hasValue);
  const scoreDefinition = (field, definition) => {
    const label = field.normalizedLabel;
    const aliases = definition.aliases.map(J.normalizeKey).filter(Boolean);
    let confidence = 0;
    if (aliases.includes(label)) confidence = 0.96;
    else if (label && aliases.some((alias) => label.includes(alias) || alias.includes(label))) confidence = 0.88;
    else {
      const signals = J.normalizeKey([field.placeholder, field.nameHint, field.idHint].join(" "));
      if (aliases.some((alias) => alias.length >= 3 && signals.includes(alias))) confidence = 0.84;
    }
    const expectedSection = sectionAliases[definition.section];
    if (confidence && expectedSection?.test(`${field.section} ${field.nearbyText}`)) confidence = Math.min(0.99, confidence + 0.03);
    if (definition.section === "basic" && /家庭|紧急联系人|证明人|推荐人/.test(`${field.section} ${field.nearbyText}`)) return 0;
    if (definition.section !== "family" && /家庭信息|家庭情况/.test(field.section)) return 0;
    return confidence;
  };

  const bestDefinition = (field, profileCatalog) => {
    const candidates = J.FIELD_CATALOG.map((definition) => ({ definition, confidence: scoreDefinition(field, definition) }))
      .filter(({ definition, confidence }) => confidence > 0 && (definition.key.includes("*") || profileHasPath(profileCatalog, definition.key)))
      .sort((left, right) => right.confidence - left.confidence);
    return candidates[0] || null;
  };

  J.buildLocalPlan = (inspection, profileCatalog) => {
    const candidates = [];
    for (const field of inspection.fields) {
      const match = bestDefinition(field, profileCatalog);
      if (!match) {
        candidates.push({
          candidateId: J.randomId("cand"), fieldRuntimeId: field.runtimeId,
          fieldFingerprint: field.fingerprint, profilePath: "", fieldLabel: field.label,
          section: field.section, controlKind: field.controlKind,
          controlAdapterId: field.controlAdapterId, mappingSource: "local_rule",
          confidence: 0, risk: J.classifyRisk(field), decision: "needs_review",
          reasonCodes: ["unresolved_local_mapping"]
        });
        continue;
      }
      const safety = J.decideCandidate({ field, definition: match.definition, confidence: match.confidence });
      candidates.push({
        candidateId: J.randomId("cand"), fieldRuntimeId: field.runtimeId,
        fieldFingerprint: field.fingerprint, profilePath: match.definition.key,
        fieldLabel: field.label, section: field.section, controlKind: field.controlKind,
        controlAdapterId: field.controlAdapterId, mappingSource: "local_rule",
        confidence: match.confidence, risk: safety.risk, decision: safety.decision,
        reasonCodes: safety.reasons
      });
    }
    return candidates;
  };

  J.planSummary = (candidates) => candidates.reduce((summary, candidate) => {
    summary[candidate.decision] = (summary[candidate.decision] || 0) + 1;
    summary.total += 1;
    return summary;
  }, { total: 0, auto_fill: 0, needs_review: 0, manual_sensitive: 0, manual_declaration: 0, preserve_existing: 0, unsupported: 0, blocked: 0 });

  J.applyPlanCandidates = async (candidates, valuesByPath) => {
    const results = [];
    for (const candidate of candidates) {
      if (candidate.decision !== "auto_fill") continue;
      const element = J.findRuntimeElement(candidate.fieldRuntimeId);
      const adapter = J.CONTROL_ADAPTERS.find((item) => item.id === candidate.controlAdapterId);
      const value = valuesByPath[candidate.profilePath];
      if (!element || !adapter || value == null || value === "") {
        results.push({ candidateId: candidate.candidateId, status: "failed", reason: "target_or_value_missing" });
        continue;
      }
      const attempt = await adapter.fill(element, value, candidate);
      const verification = attempt.ok ? await adapter.verify(element, value, candidate) : { ok: false };
      results.push({
        candidateId: candidate.candidateId,
        fieldLabel: candidate.fieldLabel,
        status: attempt.ok && verification.ok ? "filled" : "failed",
        reason: attempt.code || (verification.ok ? "" : "verification_failed")
      });
    }
    return results;
  };
})();
