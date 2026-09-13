(() => {
  "use strict";
  const validate = (plan, state, context, clock = Date.now()) => {
    if (!plan || !state) return { ok: false, code: "plan_not_found" };
    if (plan.expiresAt < clock) return { ok: false, code: "plan_expired" };
    if (state.state !== "ready") return { ok: false, code: "plan_not_ready" };
    if (plan.tabId !== context.tabId || plan.sessionId !== context.sessionId) return { ok: false, code: "page_changed" };
    if (plan.pageFingerprint !== context.pageFingerprint) return { ok: false, code: "page_changed" };
    if (plan.profileRevision !== context.profileRevision) return { ok: false, code: "profile_revision_changed" };
    return { ok: true, code: "ok" };
  };
  globalThis.ZhaoxiPlanPolicy = Object.freeze({ validate });
})();
