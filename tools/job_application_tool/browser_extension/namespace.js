(() => {
  "use strict";
  const root = globalThis.ZhaoxiJobApplication || {};
  root.PROTOCOL = "zhaoxi.job-application.native";
  root.PROTOCOL_VERSION = 1;
  root.CONTROL_SELECTOR = [
    "input:not([type='hidden'])",
    "textarea",
    "select",
    "[contenteditable='true']",
    "[contenteditable='plaintext-only']",
    "[role='combobox']"
  ].join(",");
  root.normalizeText = (value, max = 240) => String(value || "")
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, max);
  root.normalizeKey = (value) => root.normalizeText(value, 160)
    .toLowerCase()
    .replace(/[\s:：*＊()（）【】\[\]_.\-/\\]/g, "");
  root.randomId = (prefix) => `${prefix}_${crypto.randomUUID().replace(/-/g, "")}`;
  root.sha256 = async (value) => {
    const bytes = new TextEncoder().encode(String(value));
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return `sha256:${Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("")}`;
  };
  globalThis.ZhaoxiJobApplication = root;
})();
