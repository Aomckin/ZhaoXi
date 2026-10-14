// Real pointer interaction regression; run against dashboard_smoke_server.py.
const assert = require('node:assert/strict');
async function checkEngineeringPanels(page) {
  const checks = [];
  const modes = {
    memory: ['runtimeDebugPanel'],
    runtime: ['runtimeDebugPanel', 'budgetDebugPanel', 'decisionDebugPanel', 'debugPanel'],
    capability: ['toolCabinetPanel', 'emojiCabinetPanel', 'emojiDebugPanel', 'externalSourcesPanel', 'perceptionPanel'],
    settings: ['recentContextDebugPanel', 'debugPanel'],
  };
  for (const [mode, panels] of Object.entries(modes)) {
    await page.goto('http://127.0.0.1:18765/dashboard#' + mode);
    if (mode === 'memory') await page.getByText('记忆检索检查器与维护诊断', {exact: true}).click();
    const frame = page.frameLocator('iframe');
    await frame.locator('#' + panels[0]).waitFor();
    assert.equal(await frame.locator('#desk').evaluate(n => getComputedStyle(n).pointerEvents), 'auto');
    assert.equal(await frame.locator('#desk').evaluate(n => n.inert), false);
    // Use actual clicks (no force/evaluate click), including nested disclosures.
    let count = 0;
    for (const detail of await frame.locator('.desk-tools details').all()) {
      const summary = detail.locator(':scope > summary');
      if (!await summary.isVisible()) continue;
      if (await detail.evaluate(n => n.open)) {
        await summary.click({timeout: 3000});
        assert.equal(await detail.evaluate(n => n.open), false);
      }
      await summary.click({timeout: 3000});
      assert.equal(await detail.evaluate(n => n.open), true);
      count++;
    }
    for (const id of panels) assert.equal(await frame.locator('#' + id).evaluate(n => n.open), true);
    assert.ok(count >= panels.length + 3);
    // A safe refresh must reach the domain API after pointer interaction.
    const button = mode === 'capability' ? '#perceptionRefresh' : mode === 'settings' ? '#recentContextRefresh' : '#runtimeDebugRefresh';
    const endpoint = mode === 'capability' ? '/api/perception/inspect' : mode === 'settings' ? '/api/debug/recent-context' : '/api/debug/runtime';
    const response = page.waitForResponse(r => r.request().method() === 'GET' && new URL(r.url()).pathname === endpoint && r.frame().parentFrame());
    await frame.locator(button).click({timeout: 3000});
    const refreshStatus = (await response).status();
    assert.ok([200, 409].includes(refreshStatus), mode + ': ' + endpoint + ' returned ' + refreshStatus);
    if (refreshStatus === 409) {
      assert.equal(mode, 'settings'); // Fixture has no recent-context service.
      await frame.locator('#recentContextDebug').getByText('Context Builder 尚未就绪。', {exact: false}).waitFor();
    }
    if (mode === 'memory') {
      const query = frame.locator('#memoryInspectorQuery');
      await query.fill('test pointer and keyboard focus');
      assert.equal(await query.inputValue(), 'test pointer and keyboard focus');
      assert.equal(await query.evaluate(n => document.activeElement === n), true);
      await page.screenshot({path: '.zhaoxi/v145-engineering-clickable.png', fullPage: true});
    }
    checks.push({mode, disclosures_clicked: count, refresh_status: refreshStatus});
  }
  return checks;
}
module.exports = {checkEngineeringPanels};
if (require.main === module) {
  const {chromium} = require(process.env.ZHAOXI_PLAYWRIGHT || 'playwright');
  (async () => {
    const browser = await chromium.launch({channel: 'msedge', headless: true});
    try {
      const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      await page.goto('http://127.0.0.1:18765/desktop-entry?token=dashboard-ui-test');
      const checks = await checkEngineeringPanels(page);
      assert.deepEqual(errors, []);
      const evidence = {checks, errors};
      require('node:fs').writeFileSync('.zhaoxi/v145-engineering-click-acceptance.json', JSON.stringify(evidence, null, 2));
      console.log(JSON.stringify(evidence));
    } finally {await browser.close();}
  })().catch(e => {console.error(e); process.exitCode = 1;});
}
