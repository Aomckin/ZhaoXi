// Run tool_control_smoke_server.py first. This only talks to the isolated test Core.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');
const fs = require('node:fs');
(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1500, height: 1000}});
    const errors = []; page.on('pageerror', error => errors.push(error.message));
    await page.goto('http://127.0.0.1:18762/desktop-entry?token=tool-ui-test');
    await page.locator('#sideToggle').click();
    await page.locator('.maintenance > summary').click();
    await page.locator('#toolDebugPanel > summary').click();
    const group = page.locator('details[data-group="job_application"]');
    await group.locator('summary').click();
    const enabled = page.getByRole('checkbox', {name: 'job_application_preview 启用', exact: true});
    const forced = page.getByRole('checkbox', {name: 'job_application_preview Force Expose · 每轮携带', exact: true});
    assert.equal(await enabled.isChecked(), false);
    async function change(action) {
      const response = page.waitForResponse(r => r.url().endsWith('/api/debug/tools/control') && r.request().method() === 'POST');
      await action(); const result = await response; assert.equal(result.status(), 200);
      await page.waitForFunction(() => !document.getElementById('resetTools').disabled);
      return result.json();
    }
    let result = await change(() => enabled.check());
    assert.equal(result.tools.find(t => t.name === 'job_application_preview').enabled, true);
    result = await change(() => forced.check());
    assert.equal(result.tools.find(t => t.name === 'job_application_preview').exposed, true);
    await page.reload();
    await page.locator('#sideToggle').click();
    await page.locator('.maintenance > summary').click();
    await page.locator('#toolDebugPanel > summary').click();
    await group.locator('summary').click();
    assert.equal(await enabled.isChecked(), true);
    assert.equal(await forced.isChecked(), true);
    result = await change(() => group.getByRole('button', {name: '停用整组', exact: true}).click());
    assert.equal(result.tools.find(t => t.name === 'job_application_preview').exposed, false);
    result = await change(() => group.getByRole('button', {name: '组恢复默认', exact: true}).click());
    assert.equal(result.tools.find(t => t.name === 'job_application_preview').force_expose, false);
    assert.equal(result.tools.find(t => t.name === 'job_application_preview').enabled, false);
    await change(() => enabled.check());
    await change(() => group.getByRole('button', {name: '恢复默认', exact: true}).click());
    await change(() => enabled.check());
    await change(() => page.locator('#resetTools').click());
    assert.equal(await enabled.isChecked(), false);
    const output = path.resolve(__dirname, '../../docs/screenshots/v1.2.2');
    fs.mkdirSync(output, {recursive: true});
    await page.locator('#toolControls').scrollIntoViewIfNeeded();
    await page.screenshot({path: path.join(output, 'tool-control.png')});
    assert.deepEqual(errors, []);
    console.log('Tool UI: enable, disable group, force expose, reload, three reset scopes passed');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode = 1;});
