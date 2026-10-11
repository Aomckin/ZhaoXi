// Isolated real-DOM acceptance for the image-only session restore contract.
const {chromium}=require(process.env.ZHAOXI_PLAYWRIGHT||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const shell=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/shell.js'),'utf8');
const renderer=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/reply-renderer.js'),'utf8');
const bubble=shell.split('\n').filter(line=>line.startsWith('function addMessageBubble(')).join('\n');
const restore=shell.split('\n').filter(line=>line.startsWith('async function restore(')).join('\n');
const png='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9S8AAAAASUVORK5CYII=';
const fixture={messages:[{role:'user',text:'',type:'image',images:[png],timestamp:'2026-10-08T11:28:48Z'}]};
const script=`
const $=selector=>document.querySelector(selector),messages=$('#messages');
let voiceEnabled=false,displayTimezone='Asia/Shanghai',historyReady=false,historyLoading=false;
const seenDeliveries=new Set(),drainDeliveries=async()=>{},showNotice=()=>{};
function escapeHtml(value){const node=document.createElement('div');node.textContent=value??'';return node.innerHTML}
function markdown(value){return escapeHtml(value)}
function formatTime(value){return new Date(value).toISOString()}
async function request(url){return url==='/api/session'?${JSON.stringify(fixture)}:{deliveries:[]}}
${renderer}
${bubble}
${restore}
restore();`;
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage(),errors=[],checks=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',route=>route.fulfill({contentType:'text/html',body:
    `<html><body><div id="messages"></div><div id="connection"></div><script>${script}</script></body></html>`}));
  await page.goto('http://image-only.test/');
  for(let pass=0;pass<2;pass++){
   await page.waitForFunction(()=>historyReady);
   assert.equal(await page.locator('.row.user.image-only-row').count(),1);
   assert.equal(await page.locator('.row.user .bubble').count(),0);
   assert.equal(await page.locator('.row.user img.attachment').count(),1);
   assert.equal(await page.locator('.row.user .message-time').count(),1);
   assert.ok(!(await page.locator('#messages').innerText()).includes('请查看这些图片。'));
   checks.push(pass?'reload keeps image and timestamp without text bubble':'restore uses image-only DOM');
   if(!pass)await page.reload();
  }
  assert.deepEqual(errors,[]);checks.push('no browser script errors');
  const output=process.env.ZHAOXI_TEST_OUTPUT||'.pytest_cache/image-only-reload-acceptance.json';
  fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify({checks,errors},null,2));
  console.log(JSON.stringify({checks,errors}));
 }finally{await browser.close()}
})().catch(error=>{console.error(error);process.exitCode=1});
