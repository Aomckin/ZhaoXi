(() => {
  "use strict";
  const J = globalThis.ZhaoxiJobApplication;

  const REVIEW_COLORS = {
    filled: "#16a34a", needs_review: "#f59e0b", sensitive_manual: "#dc2626",
    declaration_manual: "#7c3aed", unsupported: "#64748b", failed: "#e11d48",
    existing_value_preserved: "#2563eb", blocked: "#991b1b"
  };

  const clearHighlights = () => {
    for (const element of document.querySelectorAll("[data-zhaoxi-ja-review]")) {
      element.style.removeProperty("outline");
      element.style.removeProperty("outline-offset");
      element.removeAttribute("data-zhaoxi-ja-review");
    }
  };

  const highlight = (item, group) => {
    const element = J.findRuntimeElement(item.fieldRuntimeId);
    if (!element) return;
    element.dataset.zhaoxiJaReview = group;
    element.style.setProperty("outline", `2px solid ${REVIEW_COLORS[group] || "#f59e0b"}`, "important");
    element.style.setProperty("outline-offset", "2px", "important");
  };

  const renderReview = (review) => {
    document.getElementById("zhaoxi-job-application-review")?.remove();
    clearHighlights();
    const host = document.createElement("aside");
    host.id = "zhaoxi-job-application-review";
    host.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;width:340px;max-height:70vh;overflow:auto;background:#fffdf7;color:#202124;border:1px solid #ded6c8;border-radius:14px;box-shadow:0 16px 48px #0003;padding:14px;font:13px/1.5 system-ui";
    const heading = document.createElement("strong");
    heading.textContent = "朝汐 · 网申复核";
    host.appendChild(heading);
    const note = document.createElement("p");
    note.textContent = "请检查填写结果。敏感字段、声明、附件和最终提交必须由你手动完成。";
    host.appendChild(note);
    for (const [group, items] of Object.entries(review.groups || {})) {
      if (!items.length) continue;
      items.forEach((item) => highlight(item, group));
      const section = document.createElement("section");
      const title = document.createElement("b");
      title.textContent = `${group} (${items.length})`;
      section.appendChild(title);
      const list = document.createElement("ul");
      for (const item of items.slice(0, 30)) {
        const li = document.createElement("li");
        const locate = document.createElement("button");
        locate.type = "button";
        locate.textContent = item.fieldLabel || "未命名字段";
        locate.style.cssText = "border:0;background:transparent;color:inherit;text-align:left;padding:2px;cursor:pointer";
        locate.addEventListener("click", () => {
          const element = J.findRuntimeElement(item.fieldRuntimeId);
          element?.scrollIntoView({ behavior: "smooth", block: "center" });
          element?.focus?.({ preventScroll: true });
        });
        li.appendChild(locate);
        list.appendChild(li);
      }
      section.appendChild(list);
      host.appendChild(section);
    }
    const rescan = document.createElement("button");
    rescan.type = "button";
    rescan.textContent = "重新扫描";
    rescan.addEventListener("click", async () => {
      rescan.disabled = true;
      try { await chrome.runtime.sendMessage({ type: "JA_CONTENT_RESCAN" }); }
      finally { rescan.disabled = false; }
    });
    host.appendChild(rescan);
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "关闭";
    close.addEventListener("click", () => { host.remove(); clearHighlights(); });
    host.appendChild(close);
    document.documentElement.appendChild(host);
  };

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    (async () => {
      if (message.type === "JA_PING") return { ready: true };
      if (message.type === "JA_SCAN") return await J.scanPage();
      if (message.type === "JA_BUILD_LOCAL_PLAN") return J.buildLocalPlan(message.inspection, message.profileCatalog || []);
      if (message.type === "JA_APPLY") return await J.applyPlanCandidates(message.candidates || [], message.valuesByPath || {});
      if (message.type === "JA_SHOW_REVIEW") {
        renderReview(message.review || {});
        return { shown: true };
      }
      throw new Error("unsupported_content_message");
    })().then((data) => sendResponse({ ok: true, data }), (error) => sendResponse({ ok: false, error: String(error?.message || error) }));
    return true;
  });
})();
