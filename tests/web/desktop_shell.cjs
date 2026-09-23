// Isolated browser acceptance; never calls a running Core.
// NODE_PATH must contain playwright. Uses the installed Microsoft Edge.
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),assets=path.join(root,'src/zhaoxi/web/static');
const output=path.join(root,'docs/screenshots/v1.2.1');
const action='（尾巴轻轻摇了摇。）\n今天也辛苦啦。要在这里坐一会儿吗？\n（顿了两秒。）\n窗外的麦田被风吹得沙沙响。\n（耳朵转了转。）\n你的话，我在听。';
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:900},reducedMotion:'reduce'});
  const errors=[],requests=[];let failAck=false,missingAvatar=false;
  const notes=[{delivery_id:'preview-note',status:'delivered',content:'忙完之后，记得喝口水呀。\n我就在这里。',delivered_at:'2026-09-12T09:20:00Z'}];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('http://zhaoxi.test/**',async route=>{
   const url=new URL(route.request().url());requests.push(url.pathname);
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(assets,'index.html'))});
   if(url.pathname.startsWith('/static/')){
    if(missingAvatar&&url.pathname.endsWith('avatar-default.webp'))return route.fulfill({status:404,body:''});
    const type=url.pathname.endsWith('.css')?'text/css':url.pathname.endsWith('.js')?'text/javascript':'image/webp';
    return route.fulfill({contentType:type,body:fs.readFileSync(path.join(assets,path.basename(url.pathname)))});
   }
   if(url.pathname.endsWith('/activate')){
    if(failAck)return route.fulfill({status:503,json:{detail:'fixture failure'}});
    const id=decodeURIComponent(url.pathname.split('/').at(-2));const note=notes.find(n=>n.delivery_id===id);if(note)note.status='acknowledged';
    return route.fulfill({json:{status:'acknowledged',delivery_id:id}});
   }
   if(url.pathname==='/api/events')return route.fulfill({contentType:'text/event-stream',body:': fixture\n\n'});
   const fixture={
    '/api/settings/interface':{input_merge_seconds:15,reply_interval_seconds:0},'/api/settings/thinking':{mode:'off'},'/api/voice/status':{enabled:false},
    '/api/session':{messages:[{role:'user',content:'今天终于忙完了，想过来坐一会儿。',timestamp:'2026-09-12T09:18:00Z'},{role:'assistant',content:action,timestamp:'2026-09-12T09:19:00Z'}]},
    '/api/proactive':{deliveries:notes},'/api/diagnostics':{presence:{interaction_state:'ACTIVE'},startup:{status:'ready'}},
   };
   return route.fulfill({json:fixture[url.pathname]||{}});
  });
  await page.addInitScript(() => {
    window.nativeCommands = [];
    window.pywebview = {api:{command:async (action,value) => {
      window.nativeCommands.push([action,value]);
      const state = {mode:document.documentElement.dataset.windowMode || 'main',topmost:false};
      if(action === 'mode') state.mode = value;
      if(action === 'maximize' && state.mode === 'companion') state.mode = 'main';
      window.desktopShellState?.(state); return state;
    }}};
  });
  await page.goto('http://zhaoxi.test/');
  await page.waitForFunction(() => document.querySelectorAll('#messages .row').length > 1);
  await page.evaluate(() => window.dispatchEvent(new Event('pywebviewready')));
  await page.evaluate(() => {
    window.originalInput = document.querySelector('#input');
    window.originalMessages = document.querySelector('#messages');
    window.originalRow = document.querySelector('#messages .row');
    document.querySelector('#input').value = '草稿不丢';
    for(let i=0;i<30;i++){addMessage('user','旧用户 '+i);addMessage('assistant','旧历史 '+i);}
    addMessage('user','最近的问题');
    addMessage('user','', '',['data:image/png;base64,AAAA']);
    addMessage('assistant','最新回复'.repeat(400));
  });
  const sessionLoads = requests.filter(p=>p==='/api/session').length;
  for(let i=0;i<20;i++){
    await page.evaluate(() => desktopShellState({mode:'companion',topmost:false}));
    await page.evaluate(() => desktopShellState({mode:'main',topmost:false}));
  }
  assert.equal(requests.filter(p=>p==='/api/session').length,sessionLoads);
  assert(await page.evaluate(() => originalInput===document.querySelector('#input') && originalMessages===document.querySelector('#messages') && originalRow.isConnected));
  assert.equal(await page.inputValue('#input'),'草稿不丢');
  await page.screenshot({path:path.join(output,'main.png')});
  await page.evaluate(() => desktopShellState({mode:'companion',topmost:false}));
  for(const [width,height] of [[390,480],[300,320],[420,540],[600,700]]){
    await page.setViewportSize({width,height});
    const bounds = await page.locator('#input').boundingBox();
    assert(bounds.y>=0 && bounds.y+bounds.height<=height-25, JSON.stringify({width,height,bounds}));
    assert.equal(await page.locator('#messages').isVisible(),false);
    assert.equal(await page.locator('.character-anchor').isVisible(),false);
    assert.equal(await page.locator('#companionHeader').count(),0);
    assert((await page.locator('.composer').boundingBox()).height <= 50);
    assert.equal(await page.locator('#attachImage').isVisible(),false);
    assert((await page.locator('#currentConversation p').first().boundingBox()).height >= 19);
    assert.equal(await page.locator('#currentConversation article').count(),2);
    assert((await page.locator('#currentConversation').innerText()).includes('[图片]'));
    assert(!(await page.locator('#currentConversation').innerText()).includes('旧历史'));
    assert.equal(await page.locator('#currentConversation').evaluate(el=>getComputedStyle(el).overflowY),'hidden');
    await page.screenshot({path:path.join(output,`companion-${width}x${height}.png`)});
  }
  await page.locator('#windowTitle').dblclick();
  assert.equal(await page.locator('html').getAttribute('data-window-mode'),'main');
  assert.equal(errors.length,0,errors.join('\n'));
  console.log('Desktop layout: 20 roundtrips, identity/draft/history, latest turn, four sizes, double-click passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
