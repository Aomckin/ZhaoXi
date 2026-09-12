(() => {
  "use strict";
  const J = globalThis.ZhaoxiJobApplication;

  const dispatch = (element) => {
    for (const type of ["input", "change", "blur"]) element.dispatchEvent(new Event(type, { bubbles: true }));
  };
  const nativeSetter = (element, value) => {
    const prototype = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(prototype, "value")?.set;
    if (!setter) return false;
    setter.call(element, String(value));
    dispatch(element);
    return true;
  };
  const optionMatch = (label, value) => {
    const left = J.normalizeKey(label);
    const right = J.normalizeKey(value);
    return Boolean(left && right && (left === right || left.includes(right) || right.includes(left)));
  };
  const visible = (element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  };

  const nativeAdapter = {
    id: "native-control", version: "0.1.0", priority: 10,
    match(element) {
      return element.matches("input,textarea,select,[contenteditable='true'],[contenteditable='plaintext-only']") ? 0.9 : 0;
    },
    describe(element) {
      const tag = element.tagName.toLowerCase();
      const type = (element.getAttribute("type") || "text").toLowerCase();
      let kind = tag === "select" ? "select" : tag === "textarea" ? "textarea" : type;
      if (element.hasAttribute("contenteditable")) kind = "contenteditable";
      if (["submit", "button", "reset", "image", "file"].includes(type)) kind = type;
      return { kind, enabled: !element.disabled && !element.readOnly };
    },
    read(element) {
      if (element instanceof HTMLInputElement && ["checkbox", "radio"].includes(element.type)) return element.checked ? element.value || "true" : "";
      return element.value ?? element.textContent ?? "";
    },
    async fill(element, value) {
      if (element instanceof HTMLSelectElement) {
        const option = Array.from(element.options).find((item) => optionMatch(item.textContent, value) || optionMatch(item.value, value));
        if (!option) return { ok: false, code: "option_not_found" };
        element.value = option.value;
        dispatch(element);
        return { ok: true };
      }
      if (element instanceof HTMLInputElement && ["checkbox", "radio"].includes(element.type)) {
        if (!optionMatch(element.value || element.parentElement?.textContent, value)) return { ok: false, code: "choice_mismatch" };
        element.click();
        return { ok: element.checked };
      }
      if (element.hasAttribute("contenteditable")) {
        element.textContent = String(value);
        dispatch(element);
        return { ok: true };
      }
      return { ok: nativeSetter(element, value) };
    },
    async verify(element, expected) {
      const actual = this.read(element);
      return { ok: optionMatch(actual, expected), actualPresent: Boolean(String(actual || "").trim()) };
    }
  };

  const libraryAdapter = (id, rootSelector, optionSelector, priority) => ({
    id, version: "0.1.0", priority,
    match(element) { return element.closest(rootSelector) ? 0.96 : 0; },
    describe(element) {
      const root = element.closest(rootSelector);
      const role = element.getAttribute("role") || root?.getAttribute("role");
      return { kind: role === "combobox" || /select|cascader|picker/i.test(root?.className || "") ? "combobox" : nativeAdapter.describe(element).kind, enabled: !element.disabled };
    },
    read: nativeAdapter.read.bind(nativeAdapter),
    async fill(element, value) {
      const description = this.describe(element);
      if (description.kind !== "combobox") return nativeAdapter.fill(element, value);
      const trigger = element.closest(rootSelector)?.querySelector("input,[role='combobox']") || element;
      trigger.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
      trigger.click();
      await new Promise((resolve) => setTimeout(resolve, 80));
      const options = Array.from(document.querySelectorAll(optionSelector)).filter(visible);
      const option = options.find((item) => optionMatch(item.textContent, value));
      if (!option) return { ok: false, code: "option_not_found" };
      option.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
      option.click();
      await new Promise((resolve) => setTimeout(resolve, 40));
      return { ok: true };
    },
    verify: nativeAdapter.verify.bind(nativeAdapter)
  });

  J.CONTROL_ADAPTERS = [
    libraryAdapter("ant-design-control", ".ant-form-item,.ant-select,.ant-picker,.ant-cascader-picker", ".ant-select-item-option,.ant-cascader-menu-item,[role='option']", 30),
    libraryAdapter("element-control", ".el-form-item,.el-select,.el-date-editor,.el-cascader", ".el-select-dropdown__item,.el-cascader-node,[role='option']", 20),
    nativeAdapter
  ];

  J.selectControlAdapter = (element) => J.CONTROL_ADAPTERS
    .map((adapter) => ({ adapter, score: adapter.match(element) }))
    .filter(({ score }) => score > 0)
    .sort((left, right) => right.score - left.score || right.adapter.priority - left.adapter.priority)[0]?.adapter || null;
})();
