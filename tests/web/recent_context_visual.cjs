// Isolated layout smoke test. Set NODE_PATH to the bundled Playwright packages.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');

const assets=path.resolve(__dirname,'../../src/zhaoxi/web/static');
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try{
    for(const width of [1600,420]){
      const page=await browser.newPage({viewport:{width,height:800},reducedMotion:'reduce'});
      const errors=[];page.on('pageerror',error=>errors.push(error.message));
      await page.route('http://zhaoxi.test/**',route=>{
        const url=new URL(route.request().url());
        if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(assets,'index.html'))});
        if(url.pathname.startsWith('/static/')){
          const asset=path.join(assets,path.basename(url.pathname));
          return route.fulfill({contentType:asset.endsWith('.css')?'text/css':asset.endsWith('.js')?'text/javascript':'image/webp',body:fs.readFileSync(asset)});
        }
        if(url.pathname==='/api/events')return route.fulfill({contentType:'text/event-stream',body:': fixture\n\n'});
        if(url.pathname==='/api/recent-context')return route.fulfill({json:{agenda:[
          {id:'a',type:'event',title:'AI+创新产业大会（观众）',start_at:'2026-09-24T13:00:00+08:00',status:'planned',note:'提前确认路线'},
          {id:'a-window',type:'window',title:'作为观众参加 AI+创新产业大会',start_at:'2026-09-24T13:00:00+08:00',end_at:'2026-09-24T18:00:00+08:00',status:'planned'},
          {id:'b',type:'deadline',title:'网申截止',due_at:'2026-09-26T23:59:00+08:00',status:'planned'}],
          current_cognition:{overview:'近期仍在参与秋招，同时开发 Zhaoxi。',sections:{active_context:['秋招'],active_thread:['Zhaoxi v1.2.6']},updated_at:'2026-09-24T12:00:00+08:00'},errors:{}}});
        const fixture={'/api/settings/interface':{input_merge_seconds:15,reply_interval_seconds:5},'/api/settings/thinking':{mode:'off'},'/api/voice/status':{enabled:false},'/api/session':{messages:[],timezone:'Asia/Shanghai'},'/api/proactive':{deliveries:[]},'/api/diagnostics':{presence:{},startup:{status:'ready'}}};
        return route.fulfill({json:fixture[url.pathname]||{}});
      });
      await page.goto('http://zhaoxi.test/');
      await page.evaluate(()=>desktopShellState({mode:'main',topmost:false}));
      const handle=await page.locator('#sideToggle').boundingBox();
      assert.ok(handle.y>=36,`desk handle overlaps desktop chrome at ${width}px`);
      await page.locator('#sideToggle').click();
      await page.locator('.agenda-entry').first().waitFor();
      await page.waitForTimeout(350); // opening refresh and board transition settle
      assert.equal(await page.locator('.agenda-day').count(),2);
      assert.equal(await page.locator('.agenda-entry').count(),2);
      assert.equal(await page.locator('.agenda-entry details').count(),2);
      assert.equal(await page.locator('.agenda-entry details').first().evaluate(el=>getComputedStyle(el).backgroundColor),'rgba(0, 0, 0, 0)');
      assert.equal(await page.locator('.agenda-entry details').first().evaluate(el=>getComputedStyle(el).borderTopStyle),'none');
      assert.equal(await page.locator('.agenda-entry details summary').first().evaluate(el=>getComputedStyle(el).display),'inline');
      assert.equal(await page.locator('.memory-paper').count(),1);
      assert.equal(await page.locator('#desk').evaluate(el=>getComputedStyle(el).overflow),'hidden');
      assert.equal(await page.locator('.desk-content').evaluate(el=>getComputedStyle(el).overflowY),'auto');
      const board=await page.locator('#desk').boundingBox();
      assert.ok(board.x>=0&&board.x+board.width<=width,`board outside ${width}px viewport`);
      assert.deepEqual(errors,[]);
      await page.close();
    }
  }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
