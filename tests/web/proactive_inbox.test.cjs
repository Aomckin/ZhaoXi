const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8')+fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/shell.js'),'utf8');
const source=html.slice(html.indexOf('let pendingDeliveryTimer='),html.indexOf('let replyIntervalMs='));
function setup(){
  const nodes=new Map(),requests=[],rendered=[],timers=[];
  const notices={children:[],querySelector(){return null},prepend(n){nodes.set(n.id,n);this.children.unshift(n)}};
  const context=vm.createContext({historyButton:()=>{},historyCursor:null,historyReady:true,deliveryQueue:[],finishTurn(){context.busy=false},sendReply:(...args)=>rendered.push(['fallback',...args]),showProactiveNote:()=>{},seenDeliveries:new Set(),busy:false,pendingInput:[],activity:{},debug:{},displayTimezone:'Asia/Shanghai',clearTimeout(){},setTimeout(fn){timers.push(fn)},
    document:{getElementById:id=>nodes.get(id),createElement:()=>({style:{},querySelector:()=>({textContent:''})})},
    $:selector=>selector==='#clear'?{}:notices,markdown:s=>s,escapeHtml:s=>s,formatTime:s=>s,input:{focus(){}},
    messages:{replaceChildren(){rendered.length=0}},addMessage:(...args)=>rendered.push(args),renderMessage:(m,options)=>rendered.push([m.role,m.content,m.message_id,options]),
    request:async(url,options)=>{requests.push({url,options});return url==='/api/session'?{messages:[{role:'assistant',content:'主动上下文'}]}:{}},
  });
  vm.runInContext(source,context);
  return {context,requests,rendered,notices,timers};
}
test('inbox deduplicates notices and click activates durable context',async()=>{
  const s=setup();const d={kind:'system',delivery_id:'a:b',status:'delivered',content:'休息一下',available_at:'2026-09-05T04:00:00Z'};
  s.context.showNotice(d);s.context.showNotice(d);
  assert.equal(s.notices.children.length,1);
  await s.notices.children[0].onclick();
  assert.equal(s.requests[0].url,'/api/proactive/a%3Ab/activate');
  assert.equal(s.requests[0].options.method,'POST');
  assert.equal(s.rendered[0][1],'主动上下文');
  assert.equal(s.requests[2].url,'/api/proactive/a%3Ab/inspect');
  assert.equal(s.context.debug.textContent,'{}');
});
test('suppressed and deferred deliveries do not appear in inbox',()=>{
  const s=setup();s.context.showNotice({delivery_id:'x',status:'deferred'});
  s.context.showNotice({delivery_id:'y',status:'suppressed'});
  assert.equal(s.notices.children.length,0);
});
test('opening while a reply is being rendered waits without erasing it',async()=>{
  const s=setup();s.context.busy=true;await s.context.openDelivery('a');
  assert.equal(s.requests.length,0);assert.equal(s.timers.length,1);
  s.context.busy=false;await s.timers[0]();
  assert.equal(s.requests[0].url,'/api/proactive/a/activate');
});


test('opening a notice preserves unsent messages until the queue is cleared',async()=>{
  const s=setup();s.context.pendingInput.push({text:'待发送'});
  await s.context.openDelivery('notice');assert.equal(s.requests.length,0);
  assert.equal(s.timers.length,1);s.context.pendingInput.length=0;
  await s.timers[0]();assert.ok(s.requests.length>0);
});

const live={delivery_id:'beat-live',kind:'assistant',status:'delivered',content:'第一段\n\n第二段',delivered_at:'2026-10-11T09:13:58Z'};
test('live initiative resolves stored identity by delivery ID and never enables regenerate',async()=>{
  const s=setup();s.context.request=async()=>({messages:[{role:'assistant',content:live.content,message_id:'unrelated',delivery_id:'other'},{role:'assistant',content:live.content,message_id:'stored-beat',delivery_id:live.delivery_id}]});
  s.context.deliveryQueue.push(live);await s.context.drainDeliveries();
  assert.equal(s.rendered.length,1);assert.equal(s.rendered[0][2],'stored-beat');assert.equal(s.rendered[0][3].paced,true);assert.equal(s.rendered[0][3].latestMessageId,undefined);
  s.context.deliveryQueue.push(live);await s.context.drainDeliveries();assert.equal(s.rendered.length,1);
});
test('session read outage preserves delivered text without inventing a source ID',async()=>{
  const s=setup();s.context.request=async()=>{throw Error('offline')};s.context.deliveryQueue.push(live);await s.context.drainDeliveries();
  assert.deepEqual(s.rendered[0],['fallback',live.content,live.delivered_at,null,false]);assert.equal(s.context.busy,false);
});
test('pending input delays initiative identity lookup until the turn can render',async()=>{
  const s=setup();s.context.pendingInput.push({text:'未发出'});s.context.deliveryQueue.push(live);await s.context.drainDeliveries();assert.equal(s.requests.length,0);assert.equal(s.rendered.length,0);
});
