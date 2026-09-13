"use strict";

const byId = (id) => document.getElementById(id);

async function send(type) {
  return await chrome.runtime.sendMessage({ type });
}

function render(status) {
  byId("bridge").textContent = status.extension_connected ? "已连接" : "未连接";
  byId("page").textContent = status.page?.title || status.last_error || "尚未启用";
  byId("adapter").textContent = status.current_adapter || "—";
  byId("controls").textContent = (status.control_adapters || []).join(", ") || "—";
  byId("session").textContent = status.active_session || "—";
  byId("fields").textContent = String(status.fields_discovered || 0);
  byId("error").textContent = status.last_error || "";
}

async function refresh() {
  const response = await send("JA_POPUP_STATUS");
  if (response?.ok) render(response.data);
}

byId("enable").addEventListener("click", async () => {
  byId("error").textContent = "";
  const response = await send("JA_POPUP_ENABLE");
  if (!response?.ok) byId("error").textContent = response?.error || "启用失败";
  await refresh();
});

byId("reconnect").addEventListener("click", async () => {
  await send("JA_POPUP_RECONNECT");
  await new Promise((resolve) => setTimeout(resolve, 250));
  await refresh();
});

refresh().catch((error) => { byId("error").textContent = String(error); });
