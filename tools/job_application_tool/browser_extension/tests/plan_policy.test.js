"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

vm.runInThisContext(fs.readFileSync(path.resolve(__dirname, "..", "plan_policy.js"), "utf8"));
const validate = globalThis.ZhaoxiPlanPolicy.validate;

const plan = {
  expiresAt: 5000, tabId: 7, sessionId: "session_a",
  pageFingerprint: "page_a", profileRevision: 3
};
const state = { state: "ready" };
const context = { tabId: 7, sessionId: "session_a", pageFingerprint: "page_a", profileRevision: 3 };

test("valid immutable plan binding passes", () => assert.equal(validate(plan, state, context, 1000).ok, true));
test("expired plan fails", () => assert.equal(validate(plan, state, context, 6000).code, "plan_expired"));
test("different tab or session fails", () => {
  assert.equal(validate(plan, state, { ...context, tabId: 8 }, 1000).code, "page_changed");
  assert.equal(validate(plan, state, { ...context, sessionId: "session_b" }, 1000).code, "page_changed");
});
test("page fingerprint change fails", () => assert.equal(validate(plan, state, { ...context, pageFingerprint: "page_b" }, 1000).code, "page_changed"));
test("profile revision change fails", () => assert.equal(validate(plan, state, { ...context, profileRevision: 4 }, 1000).code, "profile_revision_changed"));
test("consumed plan cannot replay", () => assert.equal(validate(plan, { state: "completed" }, context, 1000).code, "plan_not_ready"));
