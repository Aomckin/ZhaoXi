(() => {
  "use strict";
  const J = globalThis.ZhaoxiJobApplication;
  const RUNTIME_ATTR = "data-zhaoxi-ja-field";
  const skippedTypes = new Set(["hidden"]);

  const isVisible = (element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0" && rect.width > 0 && rect.height > 0;
  };
  const optionsFor = (element) => {
    if (element instanceof HTMLSelectElement) {
      return Array.from(element.options).slice(0, 100).map((option) => ({ value: J.normalizeText(option.value, 100), label: J.normalizeText(option.textContent, 100) }));
    }
    const container = element.closest("[role='radiogroup'],.ant-radio-group,.el-radio-group,.ant-form-item,.el-form-item");
    return Array.from(container?.querySelectorAll("label,[role='option']") || []).slice(0, 100)
      .map((item) => ({ value: "", label: J.normalizeText(item.textContent, 100) })).filter((item) => item.label);
  };
  const safeCurrentState = (element, adapter) => {
    const value = adapter?.read(element);
    return { hasCurrentValue: Boolean(J.normalizeText(value, 2)) };
  };

  J.scanPage = async () => {
    const selected = J.selectPageAdapter();
    const adapter = selected.adapter;
    const seen = new Set();
    const fields = [];
    for (const root of adapter.scanRoots(document)) {
      for (const element of root.querySelectorAll(J.CONTROL_SELECTOR)) {
        if (seen.has(element)) continue;
        seen.add(element);
        const inputType = (element.getAttribute("type") || "").toLowerCase();
        if (skippedTypes.has(inputType) || element.closest("#zhaoxi-job-application-review")) continue;
        const controlAdapter = J.selectControlAdapter(element);
        if (!controlAdapter) continue;
        const pageContext = adapter.extractFieldContext(element);
        const control = controlAdapter.describe(element);
        const runtimeId = element.getAttribute(RUNTIME_ATTR) || J.randomId("fld");
        element.setAttribute(RUNTIME_ATTR, runtimeId);
        const identity = [
          location.origin, location.pathname, pageContext.section, pageContext.label,
          element.getAttribute("name"), element.getAttribute("id"), control.kind
        ].join("|");
        fields.push({
          runtimeId,
          fingerprint: await J.sha256(identity),
          label: pageContext.label,
          normalizedLabel: J.normalizeKey(pageContext.label),
          section: pageContext.section,
          nearbyText: pageContext.nearbyText,
          placeholder: J.normalizeText(element.getAttribute("placeholder"), 120),
          nameHint: J.normalizeText(element.getAttribute("name"), 120),
          idHint: J.normalizeText(element.getAttribute("id"), 120),
          controlKind: control.kind,
          controlAdapterId: controlAdapter.id,
          options: optionsFor(element),
          required: element.required || element.getAttribute("aria-required") === "true",
          visible: isVisible(element),
          enabled: Boolean(control.enabled),
          ...safeCurrentState(element, controlAdapter)
        });
      }
    }
    const pageFingerprint = await J.sha256([
      location.origin, location.pathname, adapter.id,
      ...fields.map((field) => field.fingerprint)
    ].join("|"));
    return {
      inspectionId: J.randomId("insp"),
      page: {
        origin: `${location.protocol}//${location.host}/`,
        title: J.normalizeText(document.title, 160),
        fingerprint: pageFingerprint,
        adapter: { id: adapter.id, confidence: selected.result.confidence }
      },
      fields,
      createdAt: Date.now()
    };
  };

  J.findRuntimeElement = (runtimeId) => document.querySelector(`[${RUNTIME_ATTR}="${CSS.escape(runtimeId)}"]`);
})();
