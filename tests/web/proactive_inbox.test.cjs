const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8');
const source=html.slice(html.indexOf('let pendingDeliveryTimer='),html.indexOf('async function start()'));
function setup(){
  const nodes=new Map(),requests=[],rendered=[],timers=[];
  const notices={children:[],querySelector(){return null},prepend(n){nodes.set(n.id,n);this.children.unshift(n)}};
  const context=vm.createContext({busy:false,activity:{},debug:{},setupCapabilities:async()=>{},clearTimeout(){},setTimeout(fn){timers.push(fn)},
    document:{getElementById:id=>nodes.get(id),createElement:()=>({style:{},querySelector:()=>({textContent:''})})},
    $:()=>notices,markdown:s=>s,escapeHtml:s=>s,formatTime:s=>s,input:{focus(){}},
    messages:{replaceChildren(){rendered.length=0}},addMessage:(...args)=>rendered.push(args),
    request:async(url,options)=>{requests.push({url,options});return url==='/api/session'?{messages:[{role:'assistant',content:'主动上下文'}]}:{}},
  });
  vm.runInContext(source,context);
  return {context,requests,rendered,notices,timers};
}
test('inbox deduplicates notices and click activates durable context',async()=>{
  const s=setup();const d={delivery_id:'a:b',status:'delivered',content:'休息一下',available_at:'2026-09-05T04:00:00Z'};
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
