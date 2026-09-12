(() => {
  "use strict";
  const J = globalThis.ZhaoxiJobApplication;

  const visible = (element) => {
    if (!(element instanceof Element)) return false;
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  };

  const labelFor = (element, selectors = "label,[class*='label'],[class*='Label']") => {
    const id = element.getAttribute("id");
    if (id) {
      const explicit = document.querySelector(`label[for="${CSS.escape(id)}"]`);
      if (explicit) return J.normalizeText(explicit.textContent, 120);
    }
    const container = element.closest(".form-item,.ant-form-item,.el-form-item,[class*='form-item'],[class*='field'],[class*='Field']");
    const found = container?.querySelector(selectors);
    return J.normalizeText(found?.textContent || element.getAttribute("aria-label") || element.getAttribute("placeholder"), 120);
  };

  const sectionFor = (element, selectors) => {
    let current = element.parentElement;
    for (let depth = 0; current && depth < 8; depth += 1, current = current.parentElement) {
      const heading = current.querySelector(`:scope > ${selectors}`);
      const text = J.normalizeText(heading?.textContent, 100);
      if (text) return text;
    }
    return "";
  };

  const makeAdapter = ({ id, domains = [], indicators = [], confidence, labelSelectors, sectionSelectors }) => ({
    id,
    version: "0.1.0",
    match(context) {
      const domainMatch = domains.some((pattern) => pattern.test(context.hostname));
      const indicatorCount = indicators.filter((selector) => document.querySelector(selector)).length;
      if (!domainMatch && indicatorCount === 0) return { matched: false, confidence: 0 };
      return { matched: true, confidence: Math.min(0.99, confidence + indicatorCount * 0.01) };
    },
    scanRoots(doc) {
      const forms = Array.from(doc.querySelectorAll("form")).filter(visible);
      return forms.length ? forms : [doc.documentElement];
    },
    extractFieldContext(element) {
      const container = element.closest(".form-item,.ant-form-item,.el-form-item,[class*='form-item'],[class*='field'],[class*='Field']");
      return {
        label: labelFor(element, labelSelectors),
        section: sectionFor(element, sectionSelectors),
        nearbyText: J.normalizeText(container?.textContent, 240),
        repeatContext: null
      };
    }
  });

  const commonSections = "h1,h2,h3,h4,[class*='section-title'],[class*='module-title'],[class*='block-title']";
  J.PAGE_ADAPTERS = [
    makeAdapter({
      id: "moka-page",
      domains: [/(?:^|\.)(?:mokahr|moka)\.com$/i],
      indicators: [".ant-form-item", "[class*='questionnaire']", "[class*='schema-form']"],
      confidence: 0.92,
      labelSelectors: ".ant-form-item-label,label,[class*='field-label'],[class*='question-title']",
      sectionSelectors: `.ant-card-head-title,${commonSections}`
    }),
    makeAdapter({
      id: "beisen-page",
      domains: [/(?:^|\.)beisen\.com$/i, /(?:^|\.)italentx?\.(?:cn|com)$/i, /(?:^|\.)career\.naura\.com$/i],
      indicators: [".form-item--phoenix", ".phoenix-select", "[class*='resume-form']", "[class*='bs-']"],
      confidence: 0.94,
      labelSelectors: ".form-item__text,.form-item__title,.el-form-item__label,.ant-form-item-label,label",
      sectionSelectors: `.form-part-head,.head-title,${commonSections}`
    }),
    makeAdapter({
      id: "feishu-page",
      domains: [/(?:^|\.)jobs\.feishu\.cn$/i],
      indicators: [".ud-formily-item", "[data-form-field-id]", "[class*='applyFormModuleWrapper']"],
      confidence: 0.93,
      labelSelectors: ".ud-formily-item-label-content,label,[data-form-field-i18n-name],[class*='label']",
      sectionSelectors: `.applyFormModuleWrapper-text,${commonSections}`
    })
  ];

  J.GENERIC_PAGE_ADAPTER = makeAdapter({
    id: "generic-page",
    indicators: ["form", "input", "textarea", "select"],
    confidence: 0.55,
    labelSelectors: "label,[class*='label'],[class*='Label']",
    sectionSelectors: commonSections
  });

  J.selectPageAdapter = () => {
    const context = { hostname: location.hostname, url: location.href };
    const matches = J.PAGE_ADAPTERS
      .map((adapter) => ({ adapter, result: adapter.match(context) }))
      .filter(({ result }) => result.matched)
      .sort((left, right) => right.result.confidence - left.result.confidence);
    return matches[0] || { adapter: J.GENERIC_PAGE_ADAPTER, result: { matched: true, confidence: 0.55 } };
  };
})();
