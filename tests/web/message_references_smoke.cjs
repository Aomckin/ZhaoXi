// Real Desktop page with isolated API fixtures; no production model or history.
const {chromium}=require(process.env.ZHAOXI_PLAYWRIGHT||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const assets=path.join(__dirname,'../../src/zhaoxi/web/static');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1400,height:1000}}),errors=[],payloads=[];
  page.on('pageerror',e=>errors.push(e.message));
  const timestamp='2026-10-11T01:00:00Z';
  const original={message_id:'old-source',role:'user',content:'第一段\n\n真正要引用的第二段',images:[],timestamp,
   display_parts:[{text:'第一段',image_count:0,timestamp},{text:'真正要引用的第二段',image_count:0,timestamp}]};
  const view={message_id:'old-source',part_index:1,role:'user',text:'真正要引用的第二段',image_count:0,timestamp};
  const source={message_id:'source-assistant',role:'assistant',content:'下午去 A201 吗？',timestamp};
  let history=[source,{message_id:'past-reference',role:'user',content:'关于那条消息',timestamp,images:[],
   references:[view],display_parts:[{text:'关于那条消息',image_count:0,timestamp,reference:{message_id:'old-source',part_index:1}}]}];
  await page.route('http://127.0.0.1:18798/**',async route=>{
   const url=new URL(route.request().url());
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(assets,'index.html'))});
   if(url.pathname.startsWith('/static/'))return route.fulfill({contentType:url.pathname.endsWith('.js')?'text/javascript':url.pathname.endsWith('.css')?'text/css':'image/webp',body:fs.readFileSync(path.join(assets,path.basename(url.pathname)))});
   if(url.pathname==='/api/events')return route.fulfill({contentType:'text/event-stream',body:': fixture\n\n'});
   if(url.pathname==='/api/session/history')return route.fulfill({json:{messages:[original],has_more:false,before:original.message_id}});
   if(url.pathname==='/api/chat'){
    const payload=route.request().postDataJSON();payloads.push(payload);
    const reference={message_id:source.message_id,part_index:null,role:'assistant',text:source.content,image_count:0,timestamp};
    history.push({message_id:payload.message_id,role:'user',content:payload.message,images:payload.images,timestamp,display_parts:payload.display_parts,references:[reference]});
    const reply={message_id:'live-reply',id:'live-reply',role:'assistant',content:'记下了，待会儿见。',timestamp};history.push(reply);
    return route.fulfill({json:{content:reply.content,message_id:reply.message_id,timestamp,request_id:payload.request_id,output_messages:[reply],activity:{}}});
   }
   const fixtures={'/api/session':{messages:history},'/api/proactive':{deliveries:[]},'/api/settings/interface':{input_merge_seconds:15,reply_interval_seconds:0},'/api/settings/thinking':{mode:'off'},'/api/voice/status':{enabled:false},'/api/diagnostics':{presence:{interaction_state:'ACTIVE'},startup:{status:'ready'}}};
   return route.fulfill({json:fixtures[url.pathname]||{}});
  });
  await page.addInitScript(()=>{window.pywebview={api:{command:async(action,value)=>{const state={mode:document.documentElement.dataset.windowMode||'main',topmost:false};if(action==='mode')state.mode=value;window.desktopShellState?.(state);return state}}};});
  await page.goto('http://127.0.0.1:18798/');
  await page.waitForFunction(()=>document.querySelector('[data-message-id="past-reference"] .reference-link'));
  await page.evaluate(()=>window.dispatchEvent(new Event('pywebviewready')));
  // Original is outside restored recent messages: clicking loads and locates the exact part.
  await page.locator('[data-message-id="past-reference"] .reference-link').click();
  await page.waitForFunction(()=>document.querySelector('[data-message-id="old-source"][data-message-part-index="1"]')?.classList.contains('reference-highlight'));
  await page.locator('[data-message-id="source-assistant"]').click({button:'right'});
  await page.getByRole('menuitem',{name:'引用消息',exact:true}).click();
  await page.locator('#input').fill('我会提前十分钟到。');
  assert.equal(await page.locator('#draftReference').isVisible(),true);
  assert.equal(await page.locator('#draftReference textarea').count(),0);
  await page.screenshot({path:'.pytest_cache/message-reference-composer.png'});
  await page.locator('#send').click();
  await page.locator('#input').fill('谢谢提醒');await page.locator('#send').click();
  await page.evaluate(async()=>{clearTimeout(inputTimer);inputTimer=null;await flushInput()});
  assert.equal(payloads.length,1);
  assert.equal(payloads[0].message,'我会提前十分钟到。\n\n谢谢提醒');
  assert.deepEqual(payloads[0].images,[]);
  assert.deepEqual(payloads[0].display_parts[0].reference,{message_id:'source-assistant',part_index:null});
  assert.equal(payloads[0].display_parts[1].reference,null);
  assert.ok(!JSON.stringify(payloads[0]).includes(source.content));
  assert.equal(await page.locator('[data-message-id="live-reply"]').count(),1);
  const newId=payloads[0].message_id;
  assert.equal(await page.locator(`[data-message-id="${newId}"] .message-reference`).count(),1);
  await page.reload();
  await page.waitForFunction(id=>document.querySelector(`[data-message-id="${id}"] .reference-link`),newId);
  assert.equal(await page.locator(`[data-message-id="${newId}"] .message-reference`).count(),1);
  assert.equal(await page.locator(`[data-message-id="${newId}"][data-message-part-index="1"] .message-reference`).count(),0);
  await page.locator(`[data-message-id="${newId}"] .reference-link`).click();
  await page.waitForFunction(()=>document.querySelector('[data-message-id="source-assistant"]')?.classList.contains('reference-highlight'));
  // Companion uses the same original identity and opens the main window on navigation.
  await page.evaluate(async()=>{await window.pywebview.api.command('state');desktopShellState({mode:'companion',topmost:false})});
  await page.locator('#currentConversation article[data-role="assistant"]').click({button:'right'});
  await page.getByRole('menuitem',{name:'引用消息',exact:true}).click();
  assert.equal(await page.locator('#input').inputValue(),'');
  assert.ok((await page.locator('#draftReference').innerText()).includes('记下了'));
  await page.locator('#draftReference .reference-link').click();
  await page.waitForFunction(()=>document.documentElement.dataset.windowMode==='main');
  await page.waitForFunction(()=>document.querySelector('[data-message-id="live-reply"]')?.classList.contains('reference-highlight'));
  assert.deepEqual(errors,[]);
  console.log('PASS: original history/part navigation, read-only composer, ID-only request, merged inputs, live reply IDs, refresh persistence, companion references/main-window navigation');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
