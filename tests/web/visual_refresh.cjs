// Isolated browser acceptance; never calls a running Core.
// NODE_PATH must contain playwright. Uses the installed Microsoft Edge.
const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'../..'),assets=path.join(root,'src/zhaoxi/web/static');
const output=path.join(root,'docs/screenshots/v1.2-phase3');
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
    '/api/suggestions':{suggestions:['和我聊聊今天吧','一起整理一下思绪','看看今天的安排'],timezone:'Asia/Shanghai'},
    '/api/session':{messages:[{role:'user',content:'今天终于忙完了，想过来坐一会儿。',timestamp:'2026-09-12T09:18:00Z'},{role:'assistant',content:action,timestamp:'2026-09-12T09:19:00Z'}]},
    '/api/proactive':{deliveries:notes},'/api/diagnostics':{presence:{interaction_state:'ACTIVE'},startup:{status:'ready'}},
   };
   return route.fulfill({json:fixture[url.pathname]||{}});
  });
  await page.goto('http://zhaoxi.test/');
  await page.locator('#proactiveNotes [data-delivery]').waitFor({state:'attached'});
  await page.waitForFunction(()=>document.querySelector('#characterAvatar').naturalWidth===512);
  assert.equal(await page.locator('#desk').getAttribute('aria-hidden'),'true');
  assert.equal(await page.locator('#desk').evaluate(el=>el.inert),true);
  assert.equal(await page.locator('#deskUnread').isVisible(),true);
  assert.match(await page.locator('#sideToggle').getAttribute('aria-label'),/未读/);
  assert.equal(requests.filter(p=>p.endsWith('/activate')).length,0);
  assert.equal(await page.locator('.stage-direction').count(),3);
  const group=await page.locator('.message-group').innerHTML();
  await page.screenshot({path:path.join(output,'desktop.png')});
  const before=await page.locator('#messages').boundingBox();
  await page.locator('#sideToggle').click();
  await page.waitForFunction(()=>document.querySelector('#deskUnread').hidden);
  assert.deepEqual(await page.locator('#messages').boundingBox(),before);
  assert.equal(requests.filter(p=>p.endsWith('/activate')).length,1);
  assert.equal(await page.locator('.message-group').innerHTML(),group);
  assert.equal(await page.locator('.maintenance').getAttribute('open'),null);
  await page.screenshot({path:path.join(output,'deskboard-open.png')});
  await page.locator('.prompt-card').first().click();
  assert.equal(await page.locator('#input').inputValue(),'和我聊聊今天吧');
  await page.locator('.maintenance > summary').click();await page.getByText('Debug',{exact:true}).click();
  await page.locator('#restartCore').scrollIntoViewIfNeeded();assert.equal(await page.locator('#restartCore').isVisible(),true);
  await page.screenshot({path:path.join(output,'maintenance.png')});
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#sideToggle').getAttribute('aria-expanded'),'false');
  assert.equal(await page.locator('#sideToggle').evaluate(el=>el===document.activeElement),true);
  await page.reload();await page.locator('.message-group').waitFor();
  assert.equal(await page.locator('#deskUnread').isVisible(),false);
  // Live delivery renders in chat, adds a note, and does not open the board.
  const live={delivery_id:'live-note',status:'delivered',content:'新留言：我就在附近。',delivered_at:'2026-09-12T09:21:00Z'};notes.unshift(live);
  await page.evaluate(d=>{receiveDelivery(d);receiveDelivery(d)},live);
  await page.waitForFunction(()=>document.querySelector('#messages').textContent.includes('新留言'));
  assert.equal(await page.locator('#desk').getAttribute('aria-hidden'),'true');
  assert.equal(await page.locator('#proactiveNotes [data-delivery]').count(),2);
  assert.equal(await page.locator('.message-group').count(),2);
  assert.equal(await page.locator('#deskUnread').isVisible(),true);
  // Failed persistence must not clear the unread indicator or reset a draft.
  failAck=true;await page.locator('#input').fill('还没发送的草稿');await page.locator('#sideToggle').click();
  await page.waitForFunction(()=>document.querySelector('#noteReadStatus').textContent.includes('暂未保存'));
  assert.equal(await page.locator('#deskUnread').isVisible(),true);
  await page.locator('#deskClose').click();failAck=false;await page.locator('#sideToggle').click();
  await page.waitForFunction(()=>document.querySelector('#deskUnread').hidden);
  assert.equal(await page.locator('#input').inputValue(),'还没发送的草稿');
  await page.locator('#deskClose').click();
  // An offscreen second note is not acknowledged until it is scrolled into view.
  await page.evaluate(()=>{
   document.querySelector('#proactiveNotes').replaceChildren();
   showProactiveNote({delivery_id:'offscreen',status:'delivered',content:'下面的一张纸条'});
   showProactiveNote({delivery_id:'long-note',status:'delivered',content:('很长的留言，慢慢看。\n').repeat(70)});
  });
  const readCount=requests.filter(p=>p.endsWith('/activate')).length;
  await page.locator('#sideToggle').click();
  await page.waitForFunction(()=>!document.querySelector('#note-long-note .note-unread'));
  assert.equal(requests.filter(p=>p.endsWith('/activate')).length,readCount+1);
  assert.equal(await page.locator('#note-offscreen .note-unread').count(),1);
  await page.locator('#note-offscreen').scrollIntoViewIfNeeded();
  await page.waitForFunction(()=>!document.querySelector('#note-offscreen .note-unread'));
  await page.locator('#deskClose').click();
  await page.reload();await page.locator('.message-group').waitFor();
  // Viewport changes never resize the conversation when the board opens.
  for(const [width,height] of [[1920,1080],[2560,1440],[3840,2160],[1600,900],[1366,768],[720,520],[390,844],[320,568]]){
   await page.setViewportSize({width,height});
   const chat=await page.locator('#messages').boundingBox(),tray=await page.locator('.composer').boundingBox(),anchor=await page.locator('.character-anchor').boundingBox(),send=await page.locator('#send').boundingBox();
   assert.ok(Math.abs(chat.x-tray.x)<1&&Math.abs(chat.width-tray.width)<1);
   assert.ok(tray.y-(chat.y+chat.height)>=15&&tray.y-(chat.y+chat.height)<=22);
   assert.ok(Math.abs(anchor.x-chat.x)<1&&chat.y-anchor.y-anchor.height<=14);
   assert.ok(send.x>=0&&send.x+send.width<=width&&send.y+send.height<=height);
   assert.ok(chat.height>=140);assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
   await page.screenshot({path:path.join(output,`scene-${width}x${height}.png`)});
   await page.locator('#sideToggle').click();
   assert.deepEqual(await page.locator('#messages').boundingBox(),chat);
   const board=await page.locator('#desk').boundingBox();assert.ok(board.y>=0&&board.y+board.height<=height&&board.width<=width);
   if(width===390)await page.screenshot({path:path.join(output,'mobile-board.png')});
   await page.locator('#deskClose').click();
  }
  // Long chat keeps its own scroll area and the action parser is unchanged.
  await page.evaluate(()=>{for(let i=0;i<80;i++)addMessage('assistant','长聊天 '+i+'\n\n（轻轻点头。）');addMessage('user','我今天用了 VS Code（主要是在改朝汐）。')});
  assert.equal(await page.locator('.user.stage-direction').count(),0);
  assert.ok(await page.locator('#messages').evaluate(el=>el.scrollHeight>el.clientHeight));
  for(const state of ['ACTIVE','SEMI_ACTIVE','IDLE','AWAY']){await page.evaluate(s=>renderInteractionBadge({interaction_state:s}),state);assert.equal(await page.locator('.character-anchor').getAttribute('data-state'),state.toLowerCase())}
  // Check the real animation path as well as reduced motion.
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.locator('#sideToggle').click();
  assert.match(await page.locator('#desk').evaluate(el=>getComputedStyle(el).transitionDuration),/0\.28s/);
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('#desk')).transform==='matrix(1, 0, 0, 1, 0, 0)');
  await page.locator('#deskClose').click();
  await page.waitForFunction(()=>getComputedStyle(document.querySelector('#desk')).visibility==='hidden');
  await page.emulateMedia({reducedMotion:'reduce'});
  // Missing dedicated avatar falls back to 汐, never a character sheet crop.
  missingAvatar=true;await page.reload();await page.locator('.message-group').waitFor();
  await page.waitForFunction(()=>document.querySelector('#characterAvatar').hidden);
  assert.equal(await page.locator('#avatarFallback').isVisible(),true);
  assert.equal(await page.locator('.character-portrait').evaluate(el=>getComputedStyle(el).backgroundImage),'none');
  await page.screenshot({path:path.join(output,'avatar-fallback.png')});
  assert.deepEqual(errors,[]);
  // A separate DPR 2 page checks actual image pixels against a 140px avatar.
  const highDpi=await browser.newPage({viewport:{width:1600,height:900},deviceScaleFactor:2});
  await highDpi.setContent('<img style="width:140px;height:140px" src="data:image/webp;base64,'+fs.readFileSync(path.join(assets,'avatar-default.webp')).toString('base64')+'">');
  await highDpi.waitForFunction(()=>document.querySelector('img').naturalWidth===512);
  assert.ok(await highDpi.locator('img').evaluate(el=>el.naturalWidth>=el.clientWidth*devicePixelRatio));await highDpi.close();
  console.log('Phase 3 browser acceptance passed: 8 sizes, overlay, read persistence/failure/visibility, live delivery, avatar/fallback/DPR2, prompts, debug, long chat.');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
