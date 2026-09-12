(() => {
  "use strict";
  const J = globalThis.ZhaoxiJobApplication;

  const renderReview = (review) => {
    document.getElementById("zhaoxi-job-application-review")?.remove();
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
      const section = document.createElement("section");
      const title = document.createElement("b");
      title.textContent = `${group} (${items.length})`;
      section.appendChild(title);
      const list = document.createElement("ul");
      for (const item of items.slice(0, 30)) {
        const li = document.createElement("li");
        li.textContent = item.fieldLabel || "未命名字段";
        list.appendChild(li);
      }
      section.appendChild(list);
      host.appendChild(section);
    }
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "关闭";
    close.addEventListener("click", () => host.remove());
    host.appendChild(close);
    document.documentElement.appendChild(host);
  };

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    (async () => {
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
