"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
for (const file of ["namespace.js", "field_catalog.js", "safety_policy.js"]) {
  vm.runInThisContext(fs.readFileSync(path.join(root, file), "utf8"), { filename: file });
}
const J = globalThis.ZhaoxiJobApplication;

const baseField = {
  label: "姓名", section: "基本信息", placeholder: "", nameHint: "name", idHint: "name",
  controlKind: "text", hasCurrentValue: false, enabled: true, visible: true
};

test("high-confidence standard fields can be planned for autofill", () => {
  const definition = J.FIELD_CATALOG.find((item) => item.key === "basic.full_name");
  assert.equal(J.decideCandidate({ field: baseField, definition, confidence: 0.96 }).decision, "auto_fill");
});

test("existing values are preserved", () => {
  const definition = J.FIELD_CATALOG.find((item) => item.key === "basic.full_name");
  assert.equal(J.decideCandidate({ field: { ...baseField, hasCurrentValue: true }, definition, confidence: 0.99 }).decision, "preserve_existing");
});

test("sensitive and declaration fields are always manual", () => {
  const political = J.FIELD_CATALOG.find((item) => item.key === "basic.political_status");
  assert.equal(J.decideCandidate({ field: { ...baseField, label: "政治面貌" }, definition: political, confidence: 0.99 }).decision, "manual_sensitive");
  assert.equal(J.decideCandidate({ field: { ...baseField, label: "本人声明以上信息真实" }, definition: null, confidence: 0.99 }).decision, "manual_declaration");
});

test("submission and file controls are permanently blocked", () => {
  assert.equal(J.decideCandidate({ field: { ...baseField, label: "提交申请", controlKind: "submit" }, definition: null, confidence: 0.99 }).decision, "blocked");
  assert.equal(J.decideCandidate({ field: { ...baseField, label: "上传简历", controlKind: "file" }, definition: null, confidence: 0.99 }).decision, "blocked");
});
