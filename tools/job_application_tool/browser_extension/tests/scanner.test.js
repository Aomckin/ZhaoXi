"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { JSDOM } = require("jsdom");

const root = path.resolve(__dirname, "..");
const scripts = [
  "namespace.js", "field_catalog.js", "safety_policy.js",
  "adapters/page_adapters.js", "adapters/control_adapters.js", "scanner.js", "orchestrator.js"
];

function runtime(html, url = "https://jobs.example.test/apply?token=secret#step") {
  const dom = new JSDOM(html, { url, runScripts: "outside-only", pretendToBeVisual: true });
  dom.window.Element.prototype.getBoundingClientRect = function () {
    if (this.hidden || this.style?.display === "none") return { width: 0, height: 0, top: 0, left: 0, right: 0, bottom: 0 };
    return { width: 120, height: 32, top: 0, left: 0, right: 120, bottom: 32 };
  };
  for (const file of scripts) dom.window.eval(fs.readFileSync(path.join(root, file), "utf8"));
  let sequence = 0;
  dom.window.ZhaoxiJobApplication.sha256 = async (value) => `sha256:test-${++sequence}-${String(value).length}`;
  return dom.window.ZhaoxiJobApplication;
}

test("generic scanner includes supported controls and excludes unsafe/noisy controls", async () => {
  const J = runtime(`
    <form><h2>基本信息</h2>
      <label>姓名<input name="name"></label>
      <label>简介<textarea></textarea></label>
      <label>学历<select><option>本科</option></select></label>
      <label>性别<input type="radio" value="男"></label>
      <label>接受调剂<input type="checkbox" value="是"></label>
      <label>出生日期<input type="date"></label>
      <div contenteditable="true" aria-label="个人优势"></div>
      <input type="hidden"><input type="file"><input type="submit">
      <input type="password" name="password"><input type="search" placeholder="搜索职位、公司">
      <input name="captcha" placeholder="验证码">
    </form>`);
  const inspection = await J.scanPage();
  const kinds = inspection.fields.map((field) => field.controlKind);
  assert.ok(kinds.includes("text"));
  assert.ok(kinds.includes("textarea"));
  assert.ok(kinds.includes("select"));
  assert.ok(kinds.includes("radio"));
  assert.ok(kinds.includes("checkbox"));
  assert.ok(kinds.includes("date"));
  assert.ok(kinds.includes("contenteditable"));
  assert.equal(inspection.fields.some((field) => /captcha|password|搜索职位/.test(field.label + field.placeholder + field.nameHint)), false);
  assert.equal(inspection.page.url, "https://jobs.example.test/apply");
});

test("Ant Design and Element controls use their dedicated adapters", async () => {
  const J = runtime(`
    <form>
      <div class="ant-form-item"><label>意向城市</label><div class="ant-select"><input role="combobox"></div></div>
      <div class="el-form-item"><label>学历</label><div class="el-select"><input role="combobox"></div></div>
    </form>`);
  const inspection = await J.scanPage();
  assert.deepEqual(new Set(inspection.fields.map((field) => field.controlAdapterId)), new Set(["ant-design-control", "element-control"]));
});

test("repeat context makes repeated education fields distinct", async () => {
  const J = runtime(`
    <form><h2>教育经历</h2>
      <div class="experience-item"><h3>教育经历 1</h3><label>学校<input name="school"></label></div>
      <div class="experience-item"><h3>教育经历 2</h3><label>学校<input name="school"></label></div>
    </form>`);
  const inspection = await J.scanPage();
  assert.deepEqual(Array.from(inspection.fields, (field) => Number(field.repeatContext.index)), [0, 1]);
  assert.notEqual(inspection.fields[0].fingerprint, inspection.fields[1].fingerprint);
});

test("mapper binds repeated education and project fields to matching profile indexes", async () => {
  const J = runtime(`
    <form>
      <section><h2>教育经历</h2>
        <div class="experience-item"><h3>教育经历 1</h3><label>学校<input></label></div>
        <div class="experience-item"><h3>教育经历 2</h3><label>学校<input></label></div>
      </section>
      <section><h2>项目经历</h2>
        <div class="record-item"><h3>项目经历 1</h3><label>项目名称<input></label></div>
      </section>
    </form>`);
  const inspection = await J.scanPage();
  const profileCatalog = [
    { path: "education[0].school", hasValue: true },
    { path: "education[1].school", hasValue: true },
    { path: "projects[0].name", hasValue: true }
  ];
  const plan = J.buildLocalPlan(inspection, profileCatalog);
  assert.deepEqual(Array.from(plan, (candidate) => candidate.profilePath), [
    "education[0].school", "education[1].school", "projects[0].name"
  ]);
});
