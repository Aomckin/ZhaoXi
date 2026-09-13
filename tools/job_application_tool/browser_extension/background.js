"use strict";

importScripts("plan_policy.js");

const PROTOCOL_VERSION = 1;
const NATIVE_HOST = "com.zhaoxi.job_application";
const EXTENSION_VERSION = chrome.runtime.getManifest().version;
const PROFILE_KEY = "jobApplication:profiles";
const SESSION_KEY = "jobApplication:activeSession";
const INSPECTION_PREFIX = "jobApplication:inspection:";
const PLAN_PREFIX = "jobApplication:plan:";
const PLAN_STATE_PREFIX = "jobApplication:planState:";
const PLAN_TTL_MS = 10 * 60 * 1000;
const INSPECTION_TTL_MS = 5 * 60 * 1000;
const ALLOWED_TYPES = new Set(["bridge_status", "inspect_page", "build_plan", "apply_safe_fields", "get_review", "get_profile", "update_profile", "end_session", "clear_expired_plans"]);

let nativePort = null;
let reconnectTimer = null;
let lastError = "";
let lastInspectionSummary = null;

const emptyProfile = () => ({
  schemaVersion: 1,
  activeProfileId: "default",
  profiles: {
    default: {
      profileId: "default", revision: 0, name: "默认资料", locale: "zh-CN",
      createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(),
      basic: {}, job_preference: {}, education: [], internships: [],
      work_experiences: [], projects: [], campus_experiences: [], awards: [],
      languages: [], skills: {}, certificates: [], publications: [], patents: [],
      family_members: [], declarations: {}, custom_sections: []
    }
  }
});

const storageArea = () => chrome.storage.session || chrome.storage.local;
const clone = (value) => structuredClone(value);
const now = () => Date.now();

async function ensureProfiles() {
  const stored = await chrome.storage.local.get(PROFILE_KEY);
  if (!stored[PROFILE_KEY]) await chrome.storage.local.set({ [PROFILE_KEY]: emptyProfile() });
}

chrome.runtime.onInstalled.addListener(ensureProfiles);
ensureProfiles().catch(() => {});

function connectNative() {
  if (nativePort) return;
  try {
    nativePort = chrome.runtime.connectNative(NATIVE_HOST);
    lastError = "";
  } catch (error) {
    lastError = `extension_not_connected: ${String(error?.message || error)}`;
    scheduleReconnect();
    return;
  }
  nativePort.onMessage.addListener((message) => {
    handleEnvelope(message).then(
      (data) => nativePort?.postMessage(responseEnvelope(message, true, data)),
      (error) => nativePort?.postMessage(responseEnvelope(message, false, null, error))
    );
  });
  nativePort.onDisconnect.addListener(() => {
    lastError = `extension_not_connected: ${chrome.runtime.lastError?.message || "Native Host disconnected"}`;
    nativePort = null;
    scheduleReconnect();
  });
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connectNative, 5000);
}

function responseEnvelope(request, ok, data, error = null) {
  const code = errorCode(error);
  return {
    protocol_version: PROTOCOL_VERSION,
    request_id: typeof request?.request_id === "string" ? request.request_id : "invalid",
    session_id: typeof request?.session_id === "string" ? request.session_id : "current",
    ok,
    result: ok ? data : null,
    error: ok ? null : {
      code,
      message: String(error?.message || error || "浏览器操作失败。"),
      retryable: ["extension_not_connected", "content_script_unavailable", "timeout"].includes(code)
    }
  };
}

function assertEnvelope(message) {
  const keys = new Set(Object.keys(message || {}));
  const allowed = new Set(["protocol_version", "request_id", "session_id", "type", "payload", "deadline_ms"]);
  if ([...keys].some((key) => !allowed.has(key))) throw new Error("unknown_message_fields");
  if (message?.protocol_version !== PROTOCOL_VERSION) throw new Error("protocol_mismatch");
  if (typeof message?.request_id !== "string" || typeof message?.session_id !== "string") throw new Error("protocol_mismatch");
  if (!ALLOWED_TYPES.has(message?.type)) throw new Error("unsupported_message_type");
  if (!message.payload || Object.getPrototypeOf(message.payload) !== Object.prototype) throw new Error("invalid_payload");
}

async function handleEnvelope(message) {
  assertEnvelope(message);
  switch (message.type) {
    case "bridge_status": return getBridgeStatus();
    case "inspect_page": return inspectPage(message.payload);
    case "build_plan": return buildPlan(message.payload);
    case "apply_safe_fields": return applySafeFields(message.payload);
    case "get_review": return getReview(message.payload);
    case "get_profile": return getProfile(message.payload);
    case "update_profile": return updateProfile(message.payload);
    case "end_session": return endSession();
    case "clear_expired_plans": return clearExpiredPlans();
    default: throw new Error("unsupported_message_type");
  }
}

async function targetTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) throw new Error("no_active_supported_tab");
  return tab;
}

function cleanPageUrl(rawUrl) {
  const url = new URL(rawUrl);
  return { origin: url.origin, pathname: url.pathname, cleanUrl: `${url.origin}${url.pathname}` };
}

async function getSession() {
  const stored = await storageArea().get(SESSION_KEY);
  return stored[SESSION_KEY] || null;
}

async function requireActiveSession() {
  const tab = await targetTab();
  const session = await getSession();
  if (!session || session.tabId !== tab.id) throw new Error("permission_denied: 请先在当前页面点击扩展图标并选择启用并扫描。");
  if (!tab.url) throw new Error("permission_denied: 当前页授权已失效，请重新点击扩展图标。");
  const current = cleanPageUrl(tab.url);
  if (current.origin !== session.origin || current.pathname !== session.pathname) {
    await invalidateSession(session, "navigation_changed");
    throw new Error("page_changed");
  }
  return { tab, session };
}

async function sendToTab(tabId, message) {
  try {
    const response = await chrome.tabs.sendMessage(tabId, message);
    if (!response?.ok) throw new Error(response?.error || "content_request_failed");
    return response.data;
  } catch (error) {
    if (!String(error).includes("Receiving end does not exist")) throw error;
    try { await injectContentScript(tabId); }
    catch (injectionError) { throw new Error(`content_script_unavailable: ${String(injectionError?.message || injectionError)}`); }
    const response = await chrome.tabs.sendMessage(tabId, message);
    if (!response?.ok) throw new Error(response?.error || "content_request_failed");
    return response.data;
  }
}

async function injectContentScript(tabId) {
  await chrome.scripting.executeScript({
    target: { tabId },
    files: [
      "namespace.js", "field_catalog.js", "safety_policy.js",
      "adapters/page_adapters.js", "adapters/control_adapters.js",
      "scanner.js", "orchestrator.js", "content.js"
    ]
  });
}

async function ensureContentScript(tabId) {
  try {
    await sendToTab(tabId, { type: "JA_PING" });
  } catch (error) {
    throw new Error(`content_script_unavailable: ${String(error?.message || error)}`);
  }
}

async function inspectPage(payload) {
  rejectUnknown(payload, ["include_options"]);
  const { tab, session } = await requireActiveSession();
  if (!/^https?:/i.test(tab.url || session.cleanUrl || "")) throw new Error("no_active_supported_tab");
  const inspection = await sendToTab(tab.id, { type: "JA_SCAN", includeOptions: payload.include_options !== false });
  const stored = { ...inspection, tabId: tab.id, sessionId: session.sessionId, expiresAt: now() + INSPECTION_TTL_MS };
  await storageArea().set({ [`${INSPECTION_PREFIX}${inspection.inspectionId}`]: stored });
  lastInspectionSummary = { adapter: inspection.page.adapter.id, fieldCount: inspection.fields.length, at: now() };
  const { profile } = await getActiveProfile();
  return sanitizeInspection(stored, createProfileRedactor(profile));
}

async function loadProfiles() {
  await ensureProfiles();
  const stored = await chrome.storage.local.get(PROFILE_KEY);
  return stored[PROFILE_KEY];
}

async function getActiveProfile(requestedId = null) {
  const store = await loadProfiles();
  const profileId = requestedId || store.activeProfileId;
  const profile = store.profiles?.[profileId];
  if (!profile) throw new Error("profile_not_found");
  return { store, profileId, profile };
}

function canonicalCatalog() {
  // Kept in the service worker to avoid transferring browser Profile values to
  // the content script during inspection. The content script owns equivalent
  // labels for local matching.
  return null;
}

function valueAtPath(profile, path) {
  if (!path || path.includes("*") || path.startsWith("prohibited.")) return "";
  const parts = path.replace(/\[(\d+)\]/g, ".$1").replace(/\[\]/g, ".0").split(".");
  let value = profile;
  for (const part of parts) {
    if (value == null) return "";
    value = value[part];
  }
  if (Array.isArray(value)) {
    const selected = value.find((item) => item?.is_default) || value[0];
    if (selected && typeof selected === "object" && "value" in selected) return selected.value;
    return value.filter((item) => typeof item !== "object").join(", ");
  }
  if (value && typeof value === "object" && "value" in value) return value.value;
  return value == null ? "" : String(value);
}

function flattenProfilePaths(profile) {
  const paths = [];
  const walk = (value, prefix) => {
    if (Array.isArray(value)) {
      if (value.some((item) => item && typeof item === "object" && "value" in item)) {
        paths.push({ path: prefix, hasValue: Boolean(valueAtPath(profile, prefix)) });
        return;
      }
      value.forEach((item, index) => walk(item, `${prefix}[${index}]`));
      return;
    }
    if (value && typeof value === "object" && !("value" in value)) {
      for (const [key, child] of Object.entries(value)) walk(child, prefix ? `${prefix}.${key}` : key);
      return;
    }
    paths.push({ path: prefix, hasValue: Boolean(valueAtPath(profile, prefix)) });
  };
  for (const [key, value] of Object.entries(profile)) {
    if (!["profileId", "revision", "name", "locale", "createdAt", "updatedAt"].includes(key)) walk(value, key);
  }
  return paths;
}

async function loadInspection(inspectionId) {
  const key = `${INSPECTION_PREFIX}${inspectionId}`;
  const result = await storageArea().get(key);
  const inspection = result[key];
  if (!inspection || inspection.expiresAt < now()) throw new Error("inspection_expired");
  return inspection;
}

async function buildPlan(payload) {
  rejectUnknown(payload, ["inspection_id", "profile_id", "allow_ai_mapping"]);
  const inspection = await loadInspection(payload.inspection_id);
  const { tab: activeTab, session } = await requireActiveSession();
  if (inspection.tabId !== activeTab.id || inspection.sessionId !== session.sessionId) throw new Error("inspection_expired");
  const { profileId, profile } = await getActiveProfile(payload.profile_id);
  const profileCatalog = flattenProfilePaths(profile);
  const candidates = await sendToTab(inspection.tabId, {
    type: "JA_BUILD_LOCAL_PLAN",
    inspection,
    profileCatalog
  }).catch(async (error) => {
    // Older content instance: reinject once through the standard scan path.
    await sendToTab(inspection.tabId, { type: "JA_SCAN" });
    throw error;
  });
  const planId = `jap_${crypto.randomUUID().replace(/-/g, "")}`;
  const plan = {
    planId,
    createdAt: now(), expiresAt: now() + PLAN_TTL_MS,
    tabId: inspection.tabId,
    sessionId: inspection.sessionId,
    pageFingerprint: inspection.page.fingerprint,
    profileId, profileRevision: profile.revision,
    inspectionId: inspection.inspectionId,
    adapter: inspection.page.adapter,
    candidates,
    ai: { requested: Boolean(payload.allow_ai_mapping), attempted: false, status: "local_only_v0.1" }
  };
  await storageArea().set({
    [`${PLAN_PREFIX}${planId}`]: plan,
    [`${PLAN_STATE_PREFIX}${planId}`]: { state: "ready", result: null }
  });
  return planPublicSummary(plan, { state: "ready" });
}

async function loadPlan(planId) {
  const planKey = `${PLAN_PREFIX}${planId}`;
  const stateKey = `${PLAN_STATE_PREFIX}${planId}`;
  const stored = await storageArea().get([planKey, stateKey]);
  const plan = stored[planKey];
  const state = stored[stateKey];
  if (!plan || !state) throw new Error("plan_not_found");
  if (plan.expiresAt < now()) {
    await storageArea().set({ [stateKey]: { ...state, state: "expired" } });
    throw new Error("plan_expired");
  }
  return { plan, state, stateKey };
}

async function applySafeFields(payload) {
  rejectUnknown(payload, ["plan_id", "expected_page_fingerprint", "expected_profile_revision"]);
  const { plan, state, stateKey } = await loadPlan(payload.plan_id);
  const { tab: activeTab, session } = await requireActiveSession();
  const { profile } = await getActiveProfile(plan.profileId);
  const binding = globalThis.ZhaoxiPlanPolicy.validate(plan, state, {
    tabId: activeTab.id,
    sessionId: session.sessionId,
    pageFingerprint: payload.expected_page_fingerprint,
    profileRevision: payload.expected_profile_revision
  });
  if (!binding.ok) {
    await storageArea().set({ [stateKey]: { state: "invalidated", result: { reason: binding.code } } });
    throw new Error(binding.code);
  }
  if (profile.revision !== plan.profileRevision) throw new Error("profile_revision_changed");

  const rescanned = await sendToTab(plan.tabId, { type: "JA_SCAN" });
  if (rescanned.page.fingerprint !== plan.pageFingerprint) {
    await storageArea().set({ [stateKey]: { state: "invalidated", result: { reason: "page_changed" } } });
    throw new Error("page_changed");
  }
  const currentByFingerprint = new Map(rescanned.fields.map((field) => [field.fingerprint, field]));
  const executable = [];
  for (const candidate of plan.candidates) {
    if (candidate.decision !== "auto_fill") continue;
    const current = currentByFingerprint.get(candidate.fieldFingerprint);
    if (!current || current.hasCurrentValue || !current.enabled || !current.visible) continue;
    if (["sensitive", "declaration", "prohibited"].includes(candidate.risk)) continue;
    if (candidate.confidence < 0.85) continue;
    executable.push({ ...candidate, fieldRuntimeId: current.runtimeId });
  }
  await storageArea().set({ [stateKey]: { state: "consuming", result: null } });
  const valuesByPath = Object.fromEntries(executable.map((candidate) => [candidate.profilePath, valueAtPath(profile, candidate.profilePath)]));
  let results;
  try {
    results = await sendToTab(plan.tabId, { type: "JA_APPLY", candidates: executable, valuesByPath });
  } catch (error) {
    await storageArea().set({ [stateKey]: { state: "consuming", result: { interrupted: true } } });
    throw error;
  }
  const result = {
    completedAt: now(),
    attempted: executable.length,
    filled: results.filter((item) => item.status === "filled").length,
    failed: results.filter((item) => item.status !== "filled").length,
    results,
    finalAction: "review_and_submit_manually"
  };
  await storageArea().set({ [stateKey]: { state: "completed", result } });
  return result;
}

function reviewFor(plan, state) {
  const groups = {
    filled: [], needs_review: [], sensitive_manual: [], declaration_manual: [],
    existing_value_preserved: [], unsupported: [], blocked: [], failed: []
  };
  const resultById = new Map((state.result?.results || []).map((item) => [item.candidateId, item]));
  for (const candidate of plan.candidates) {
    const execution = resultById.get(candidate.candidateId);
    if (execution?.status === "filled") groups.filled.push(candidate);
    else if (execution) groups.failed.push(candidate);
    else if (candidate.decision === "manual_sensitive") groups.sensitive_manual.push(candidate);
    else if (candidate.decision === "manual_declaration") groups.declaration_manual.push(candidate);
    else if (candidate.decision === "existing_value_preserved") groups.existing_value_preserved.push(candidate);
    else if (candidate.decision === "blocked") groups.blocked.push(candidate);
    else if (candidate.decision === "unsupported") groups.unsupported.push(candidate);
    else groups.needs_review.push(candidate);
  }
  return { planId: plan.planId, state: state.state, groups, finalAction: "review_and_submit_manually" };
}

async function getReview(payload) {
  rejectUnknown(payload, ["plan_id", "show_overlay"]);
  const { plan, state } = await loadPlan(payload.plan_id);
  const review = reviewFor(plan, state);
  if (payload.show_overlay !== false) {
    const { tab, session } = await requireActiveSession();
    if (tab.id !== plan.tabId || session.sessionId !== plan.sessionId) throw new Error("page_changed");
    await sendToTab(plan.tabId, { type: "JA_SHOW_REVIEW", review });
  }
  return review;
}

function sensitivePath(path) {
  return /sensitive|family_members|declarations|identity|health|political_status|marital_status|hukou|student_origin|salary/i.test(path);
}

function mask(value, path) {
  if (!value) return "";
  if (sensitivePath(path)) return "已保存";
  const text = String(value);
  if (/phone/i.test(path)) return text.length >= 7 ? `${text.slice(0, 3)}****${text.slice(-4)}` : "已保存";
  if (/email/i.test(path)) {
    const [name, domain] = text.split("@");
    return domain ? `${name.slice(0, 2)}***@${domain}` : "已保存";
  }
  return text.length > 80 ? `${text.slice(0, 80)}…` : text;
}

function profileView(profile, mode, section) {
  const metadata = flattenProfilePaths(profile).map(({ path, hasValue }) => ({
    path, has_value: hasValue,
    masked_value: hasValue ? mask(valueAtPath(profile, path), path) : "",
    sensitivity: sensitivePath(path) ? "sensitive" : /phone|email/i.test(path) ? "contact" : "personal"
  }));
  if (mode === "field_metadata") return metadata;
  if (mode === "section") return metadata.filter((item) => item.path === section || item.path.startsWith(`${section}.`) || item.path.startsWith(`${section}[]`));
  return {
    profile_id: profile.profileId, revision: profile.revision, name: profile.name,
    locale: profile.locale, populated_fields: metadata.filter((item) => item.has_value).length,
    sections: [...new Set(metadata.map((item) => item.path.split(/[.[]/, 1)[0]))]
  };
}

async function getProfile(payload) {
  rejectUnknown(payload, ["profile_id", "mode", "section"]);
  const { profile } = await getActiveProfile(payload.profile_id);
  return profileView(profile, payload.mode || "summary", payload.section || "");
}

function setPath(target, path, value) {
  const parts = path.split(".");
  if (parts.some((part) => !/^[A-Za-z0-9_]+$/.test(part) || ["__proto__", "prototype", "constructor"].includes(part))) throw new Error("unsafe_profile_path");
  let cursor = target;
  for (const part of parts.slice(0, -1)) {
    if (!cursor[part] || typeof cursor[part] !== "object" || Array.isArray(cursor[part])) cursor[part] = {};
    cursor = cursor[part];
  }
  cursor[parts.at(-1)] = value;
}

async function updateProfile(payload) {
  rejectUnknown(payload, ["profile_id", "expected_revision", "patches"]);
  const { store, profileId, profile } = await getActiveProfile(payload.profile_id);
  if (profile.revision !== payload.expected_revision) throw new Error("profile_revision_mismatch");
  if (!Array.isArray(payload.patches) || payload.patches.length < 1 || payload.patches.length > 50) throw new Error("invalid_patches");
  const updated = clone(profile);
  for (const patch of payload.patches) {
    rejectUnknown(patch, ["path", "value"]);
    setPath(updated, patch.path, patch.value);
  }
  updated.revision += 1;
  updated.updatedAt = new Date().toISOString();
  store.profiles[profileId] = updated;
  await chrome.storage.local.set({ [PROFILE_KEY]: store });
  await invalidatePlansForProfile(profileId);
  return { profile_id: profileId, revision: updated.revision, updated_paths: payload.patches.map((patch) => patch.path) };
}

async function invalidatePlansForProfile(profileId) {
  const all = await storageArea().get(null);
  const updates = {};
  for (const [key, plan] of Object.entries(all)) {
    if (!key.startsWith(PLAN_PREFIX) || plan?.profileId !== profileId) continue;
    const stateKey = `${PLAN_STATE_PREFIX}${plan.planId}`;
    if (all[stateKey]?.state === "ready") updates[stateKey] = { state: "invalidated", result: { reason: "profile_changed" } };
  }
  if (Object.keys(updates).length) await storageArea().set(updates);
}

function collectKnownValues(value, output = []) {
  if (Array.isArray(value)) {
    for (const item of value) collectKnownValues(item, output);
  } else if (value && typeof value === "object") {
    for (const [key, child] of Object.entries(value)) {
      if (!["profileId", "revision", "createdAt", "updatedAt", "id"].includes(key)) collectKnownValues(child, output);
    }
  } else if (typeof value === "string" && value.trim().length >= 2) {
    output.push(value.trim());
  }
  return output;
}

function createProfileRedactor(profile) {
  const known = [...new Set(collectKnownValues(profile))].sort((left, right) => right.length - left.length).slice(0, 160);
  return (value) => {
    let text = String(value || "");
    for (const item of known) text = text.split(item).join("【已有值已隐藏】");
    return text
      .replace(/[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}/g, "【邮箱已隐藏】")
      .replace(/\b(?:\d{11}|\d{15,18}[Xx]?)\b/g, "【号码已隐藏】")
      .slice(0, 180);
  };
}

function sanitizeInspection(inspection, redact = (value) => String(value || "").slice(0, 180)) {
  return {
    inspection_id: inspection.inspectionId,
    page: { ...inspection.page, title: redact(inspection.page.title) },
    fields: inspection.fields.map((field) => ({
      field_id: field.runtimeId, fingerprint: field.fingerprint, label: redact(field.label),
      section: redact(field.section), control_kind: field.controlKind,
      control_adapter: field.controlAdapterId, required: field.required,
      has_current_value: field.hasCurrentValue, enabled: field.enabled, visible: field.visible,
      option_labels: field.options?.map((option) => redact(option.label))
    })),
    expires_at: new Date(inspection.expiresAt).toISOString()
  };
}

function planPublicSummary(plan, state) {
  const summary = plan.candidates.reduce((out, candidate) => {
    out[candidate.decision] = (out[candidate.decision] || 0) + 1;
    out.total += 1;
    return out;
  }, { total: 0 });
  return {
    plan_id: plan.planId,
    state: state.state,
    page_fingerprint: plan.pageFingerprint,
    profile_id: plan.profileId,
    profile_revision: plan.profileRevision,
    expires_at: new Date(plan.expiresAt).toISOString(),
    summary,
    ai: plan.ai,
    final_action: "review_and_submit_manually"
  };
}

function rejectUnknown(value, allowedKeys) {
  if (!value || Object.getPrototypeOf(value) !== Object.prototype) throw new Error("invalid_payload");
  const allowed = new Set(allowedKeys);
  if (Object.keys(value).some((key) => !allowed.has(key))) throw new Error("unknown_payload_fields");
}

function errorCode(error) {
  const text = String(error?.code || error?.message || error || "browser_request_failed");
  const prefix = text.split(":", 1)[0];
  const known = new Set([
    "browser_bridge_unavailable", "extension_not_connected", "no_active_supported_tab",
    "content_script_unavailable", "page_changed", "inspection_expired", "plan_expired",
    "profile_revision_changed", "profile_revision_mismatch", "unsafe_field",
    "unsupported_control", "write_verification_failed", "permission_denied",
    "protocol_mismatch", "timeout", "plan_not_found", "plan_not_ready", "profile_not_found"
  ]);
  return known.has(prefix) ? (prefix === "profile_revision_mismatch" ? "profile_revision_changed" : prefix) : "browser_request_failed";
}

async function enableCurrentTab() {
  const tab = await targetTab();
  if (!tab.url || !/^https?:/i.test(tab.url)) throw new Error("no_active_supported_tab");
  await ensureContentScript(tab.id);
  const inspection = await sendToTab(tab.id, { type: "JA_SCAN", includeOptions: true });
  const cleaned = cleanPageUrl(tab.url);
  const session = {
    sessionId: `session_${crypto.randomUUID().replace(/-/g, "")}`,
    tabId: tab.id,
    origin: cleaned.origin,
    pathname: cleaned.pathname,
    cleanUrl: cleaned.cleanUrl,
    title: inspection.page.title,
    pageFingerprint: inspection.page.fingerprint,
    createdAt: now(),
    lastSeenAt: now()
  };
  await storageArea().set({ [SESSION_KEY]: session });
  lastInspectionSummary = { adapter: inspection.page.adapter.id, fieldCount: inspection.fields.length, at: now() };
  lastError = "";
  return { session_id: session.sessionId, page: inspection.page, fields_discovered: inspection.fields.length };
}

async function getBridgeStatus() {
  const session = await getSession();
  return {
    extension_connected: Boolean(nativePort),
    browser: /Edg\//.test(navigator.userAgent) ? "Edge" : "Chrome",
    extension_version: EXTENSION_VERSION,
    protocol_version: PROTOCOL_VERSION,
    active_session: session?.sessionId || null,
    current_adapter: lastInspectionSummary?.adapter || null,
    fields_discovered: lastInspectionSummary?.fieldCount || 0,
    last_inspection: lastInspectionSummary?.at || null,
    last_error: lastError,
    page: session ? { origin: session.origin, pathname: session.pathname, title: session.title || "已启用页面" } : null,
    control_adapters: ["native-html", "ant-design", "element-ui"]
  };
}

async function endSession() {
  const session = await getSession();
  if (session) await invalidateSession(session, "session_ended");
  await storageArea().remove(SESSION_KEY);
  return { ended: true };
}

async function rescanCurrentSession() {
  const { tab, session } = await requireActiveSession();
  const inspection = await sendToTab(tab.id, { type: "JA_SCAN", includeOptions: true });
  await invalidateSession(session, "manual_rescan");
  const updated = { ...session, pageFingerprint: inspection.page.fingerprint, lastSeenAt: now() };
  await storageArea().set({ [SESSION_KEY]: updated });
  lastInspectionSummary = { adapter: inspection.page.adapter.id, fieldCount: inspection.fields.length, at: now() };
  return { page: inspection.page, fields_discovered: inspection.fields.length };
}

async function invalidateSession(session, reason) {
  const all = await storageArea().get(null);
  const updates = {};
  for (const [key, plan] of Object.entries(all)) {
    if (!key.startsWith(PLAN_PREFIX) || plan?.sessionId !== session.sessionId) continue;
    const stateKey = `${PLAN_STATE_PREFIX}${plan.planId}`;
    if (all[stateKey]?.state === "ready") updates[stateKey] = { state: "invalidated", result: { reason } };
  }
  if (Object.keys(updates).length) await storageArea().set(updates);
}

async function clearExpiredPlans() {
  const all = await storageArea().get(null);
  const remove = [];
  for (const [key, value] of Object.entries(all)) {
    if ((key.startsWith(PLAN_PREFIX) || key.startsWith(INSPECTION_PREFIX)) && value?.expiresAt < now()) {
      remove.push(key);
      if (key.startsWith(PLAN_PREFIX)) remove.push(`${PLAN_STATE_PREFIX}${value.planId}`);
    }
    if (key.startsWith(PLAN_STATE_PREFIX)) {
      const planId = key.slice(PLAN_STATE_PREFIX.length);
      if (!all[`${PLAN_PREFIX}${planId}`]) remove.push(key);
    }
  }
  if (remove.length) await storageArea().remove(remove);
  return { removed: remove.length };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    if (message?.type === "JA_POPUP_STATUS") return await getBridgeStatus();
    if (message?.type === "JA_POPUP_ENABLE") return await enableCurrentTab();
    if (message?.type === "JA_POPUP_RECONNECT") {
      nativePort?.disconnect();
      nativePort = null;
      connectNative();
      return await getBridgeStatus();
    }
    if (message?.type === "JA_CONTENT_RESCAN") return await rescanCurrentSession();
    throw new Error("unsupported_popup_message");
  })().then(
    (data) => sendResponse({ ok: true, data }),
    (error) => { lastError = String(error?.message || error); sendResponse({ ok: false, error: lastError }); }
  );
  return true;
});

connectNative();
