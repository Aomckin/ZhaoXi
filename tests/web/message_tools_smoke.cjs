// Real browser interaction acceptance; no Core or production session.
const {chromium}=require(process.env.ZHAOXI_PLAYWRIGHT||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const dir=path.join(__dirname,'../../src/zhaoxi/web/static');
const bubble=fs.readFileSync(path.join(dir,'shell.js'),'utf8').split('\n').find(line=>line.startsWith('function addMessageBubble('));
const tools=fs.readFileSync(path.join(dir,'message-tools.js'),'utf8');
const css=fs.readFileSync(path.join(dir,'message-tools.css'),'utf8');
const renderer=fs.readFileSync(path.join(dir,'reply-renderer.js'),'utf8');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1000,height:760}});
  await context.grantPermissions(['clipboard-read','clipboard-write']);
  const page=await context.newPage(),errors=[],popups=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('popup',p=>popups.push(p));
  await page.route('**/*',route=>route.fulfill({contentType:'text/html',body:`<!doctype html><meta charset="utf-8"><style>${css}.row{margin:10px}.attachment{max-width:180px;max-height:120px}.bubble{background:#eee;padding:12px}</style><div id="messages"></div><textarea id="input"></textarea><div id="imagePreview"></div><div id="activity"></div><script>
const $=s=>document.querySelector(s),messages=$('#messages'),input=$('#input');
let voiceEnabled=false,historyLoading=false,imagesReading=false,draftImages=[];const MAX_IMAGES=20;
async function openReply(){}
function showActivityHint(text){$('#activity').textContent=text}
function formatTime(value){return '2026/10/11 01:00'}
function renderImagePreview(){$('#imagePreview').textContent=draftImages.length+' pictures'}
function markdown(v){const d=document.createElement('div');d.textContent=v??'';return d.innerHTML}
const escapeHtml=markdown;
${tools}
${renderer}
${bubble}
const canvas=document.createElement('canvas');canvas.width=1200;canvas.height=1800;const g=canvas.getContext('2d');g.fillStyle='#82aaa0';g.fillRect(0,0,1200,1800);g.fillStyle='white';g.font='80px sans-serif';g.fillText('Image viewer',180,200);
window.fixtureImage=canvas.toDataURL('image/png');
addMessage('assistant','朝汐：**先看看**这张图\\n第二行','',[fixtureImage],'2026-10-11T01:00:00+08:00','source-assistant');
addMessage('user','','',[fixtureImage],'2026-10-11T01:01:00+08:00','source-user');
</script>`}));
  await page.goto('http://localhost:18799/');
  assert.deepEqual(errors,[]);
  await page.locator('.row.assistant .attachment').click();
  assert.equal(await page.locator('#imageViewer').evaluate(e=>e.open),true);
  assert.equal(popups.length,0);
  await page.waitForFunction(()=>document.querySelector('.viewer-stage img').naturalWidth>0);
  assert.deepEqual(errors,[]);
  const fit=await page.locator('.viewer-scale').textContent();

  await page.getByRole('button',{name:'放大',exact:true}).click();
  assert.notEqual(await page.locator('.viewer-scale').textContent(),fit);
  await page.getByRole('button',{name:'原始大小',exact:true}).click();assert.equal(await page.locator('.viewer-scale').textContent(),'100%');
  await page.locator('.viewer-stage').hover();await page.mouse.wheel(0,-120);assert.notEqual(await page.locator('.viewer-scale').textContent(),'100%');
  const transform=await page.locator('.viewer-stage img').evaluate(e=>e.style.transform);
  await page.mouse.move(450,350);await page.mouse.down();await page.mouse.move(500,400);await page.mouse.up();
  assert.notEqual(await page.locator('.viewer-stage img').evaluate(e=>e.style.transform),transform);
  await page.getByRole('button',{name:'适应窗口',exact:true}).click();
  await page.screenshot({path:'.pytest_cache/message-viewer.png'});
  await page.keyboard.press('Escape');assert.equal(await page.locator('#imageViewer').evaluate(e=>e.open),false);
  await page.locator('.row.assistant').click({button:'right'});await page.getByRole('menuitem',{name:'复制文字',exact:true}).click();
  assert.equal((await page.evaluate(()=>navigator.clipboard.readText())).replace(/\r\n/g,'\n'),'朝汐：**先看看**这张图\n第二行');
  await page.evaluate(()=>{Object.defineProperty(navigator.clipboard,'writeText',{configurable:true,value:async()=>{throw new Error('fixture unavailable')}})});
  await page.locator('.row.assistant').click({button:'right'});await page.getByRole('menuitem',{name:'复制文字',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#activity').textContent==='文字已复制');
  assert.equal((await page.evaluate(()=>navigator.clipboard.readText())).replace(/\r\n/g,'\n'),'朝汐：**先看看**这张图\n第二行');
  await page.evaluate(()=>{delete navigator.clipboard.writeText;input.value='继续解释';});
  await page.locator('.row.assistant').click({button:'right'});await page.getByRole('menuitem',{name:'引用消息',exact:true}).click();
  assert.equal(await page.locator('#input').inputValue(),'继续解释');
  assert.equal(await page.locator('#draftReference').isVisible(),true);
  assert.ok((await page.locator('#draftReference').innerText()).includes('先看看'));
  assert.equal(await page.evaluate(()=>draftImages.length),0);
  await page.locator('#draftReference .reference-link').click();
  assert.equal(await page.locator('[data-message-id="source-assistant"]').evaluate(e=>e.classList.contains('reference-highlight')),true);
  await page.getByRole('button',{name:'取消引用',exact:true}).click();assert.equal(await page.locator('#draftReference').isVisible(),false);
  await page.locator('.row.user .attachment').click({button:'right'});await page.getByRole('menuitem',{name:'复制图片',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('#activity').textContent==='图片已复制');
  assert.ok(await page.evaluate(async()=> (await navigator.clipboard.read()).some(item=>item.types.includes('image/png'))));
  await page.locator('.row.user').focus();await page.keyboard.press('Shift+F10');assert.equal(await page.locator('#messageMenu').isVisible(),true);
  await page.getByRole('menuitem',{name:'引用消息',exact:true}).click();
  assert.equal(await page.locator('#input').inputValue(),'继续解释');assert.equal(await page.evaluate(()=>draftImages.length),0);
  const reference=await page.evaluate(()=>window.MessageTools.takeReference());assert.equal(reference.message_id,'source-user');
  await page.evaluate(reference=>{addMessage('user','我的回复','',[],null,'referencing-user',false,true,null,reference)},reference);
  await page.locator('[data-message-id="referencing-user"] .reference-link').click();
  assert.equal(await page.locator('[data-message-id="source-user"]').evaluate(e=>e.classList.contains('reference-highlight')),true);
  await page.locator('.row.assistant').click({button:'right'});await page.locator('#input').click();assert.equal(await page.locator('#messageMenu').isVisible(),false);
  assert.deepEqual(errors,[]);console.log('PASS: viewer zoom/pan/fit/close, no popup, copy text/image, read-only linked quote cards, unchanged composer/images, cancel, locate source, keyboard menu, outside dismissal');
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
