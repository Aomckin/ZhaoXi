const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8');
const source=html.slice(html.indexOf('let INPUT_MERGE_MS='),html.indexOf('async function resolve('));
function setup(){
  let id=0;const timers=new Map(),requests=[],payloads=[],bubbles=[],clear={replaceChildren(){},append(){}};
  const node=()=>({removed:false,append(){},setAttribute(){},remove(){this.removed=true},querySelector(){return this}});
  const context=vm.createContext({busy:false,send:{},input:{value:'',focus(){}},activity:{},debug:{},
    $:()=>clear,document:{createElement:node},addMessage:(...args)=>{bubbles.push(args);return [node()]},permissionCard(){},
    setTimeout:(fn,ms)=>{assert.equal(ms,15000);timers.set(++id,fn);return id},clearTimeout:id=>timers.delete(id),
    request:async(url,options)=>{payloads.push(JSON.parse(options.body));requests.push(JSON.parse(options.body).message);return {content:'回复'}},
    sendReply:async()=>{},drainDeliveries:async()=>{},setupCapabilities:async()=>{},setupDiagnostics:async()=>{},
  });
  vm.runInContext(source,context);
  return {context,requests,payloads,bubbles,clear,timers,
    submit:text=>{context.input.value=text;context.submit()},
    fire:async()=>{const callbacks=[...timers.values()];timers.clear();callbacks.forEach(fn=>fn());for(let i=0;i<8;i++)await Promise.resolve()},
  };
}
test('rapid sends reset timer and merge in order into one request',async()=>{
  const s=setup();s.submit('第一条');s.submit('第二条');
  assert.equal(s.requests.length,0);assert.equal(s.timers.size,1);
  assert.equal(s.bubbles.length,2);await s.fire();
  assert.deepEqual(s.requests,['第一条\n\n第二条']);assert.equal(s.clear.disabled,false);
});
test('inputs during a paced reply queue without overlapping requests',async()=>{
  const s=setup();let finish;
  s.context.sendReply=()=>new Promise(resolve=>{finish=resolve});
  s.submit('第一轮');await s.fire();
  s.submit('第二轮');s.submit('补充');await s.fire();
  assert.deepEqual(s.requests,['第一轮']);
  s.context.sendReply=async()=>{};finish();
  for(let i=0;i<12;i++)await Promise.resolve();
  assert.deepEqual(s.requests,['第一轮','第二轮\n\n补充']);
});
test('reply completion does not shorten a pending debounce window',async()=>{
  const s=setup();s.context.busy=true;s.submit('补充');s.context.finishTurn();
  assert.equal(s.requests.length,0);await s.fire();assert.deepEqual(s.requests,['补充']);
});
test('empty input is ignored; errors release busy state without automatic retries',async()=>{
  const s=setup();s.submit('  ');assert.equal(s.timers.size,0);
  s.context.request=async()=>{throw Error('离线')};s.submit('你好');await s.fire();
  assert.equal(s.context.busy,false);assert.equal(s.clear.disabled,false);
  assert.deepEqual(s.bubbles.at(-1),['assistant','离线']);assert.equal(s.timers.size,0);
});

test('image-only and following text merge without losing the image',async()=>{
  const s=setup();vm.runInContext("draftImages=['data:image/png;base64,AAAA']",s.context);
  s.submit('');s.submit('看看这是什么');await s.fire();
  assert.equal(s.payloads[0].message,'看看这是什么');
  assert.deepEqual(s.payloads[0].images,['data:image/png;base64,AAAA']);
  assert.deepEqual(s.payloads[0].display_parts.map(p=>[p.text,p.image_count]),[['',1],['看看这是什么',0]]);
});
test('twenty images accepted and twenty-first stays in draft',async()=>{
  const s=setup();vm.runInContext("draftImages=Array(20).fill('data:image/png;base64,AAAA')",s.context);s.submit('');
  vm.runInContext("draftImages=['data:image/png;base64,BBBB']",s.context);s.submit('');
  assert.match(s.context.activity.textContent,/最多20张/);await s.fire();
  assert.equal(s.payloads[0].images.length,20);assert.equal(vm.runInContext('draftImages.length',s.context),1);
});
test('file selection permits 100MB and rejects larger files',async()=>{
  const s=setup();s.context.FileReader=class {readAsDataURL(){this.result='data:image/png;base64,AAAA';this.onload()}};
  await s.context.selectImages([{type:'image/png',size:100*1024*1024}]);
  assert.equal(vm.runInContext('draftImages.length',s.context),1);
  await s.context.selectImages([{type:'image/png',size:100*1024*1024+1}]);
  assert.match(s.context.activity.textContent,/100MB/);
  assert.equal(vm.runInContext('draftImages.length',s.context),1);
});


test('recall removes only the selected message and its images from the batch',async()=>{
  const s=setup();s.submit('保留');
  vm.runInContext("draftImages=['data:image/png;base64,AAAA']",s.context);s.submit('撤回');
  const item=vm.runInContext('pendingInput[1]',s.context);item.recall.onclick();
  assert.equal(item.row.removed,true);assert.equal(s.timers.size,1);
  await s.fire();assert.equal(s.payloads[0].message,'保留');assert.deepEqual(s.payloads[0].images,[]);
  assert.deepEqual(s.payloads[0].display_parts.map(p=>p.text),['保留']);
});

test('recalling the last pending message cancels submission',async()=>{
  const s=setup();s.submit('撤回');vm.runInContext('pendingInput[0].recall.onclick()',s.context);
  assert.equal(s.timers.size,0);assert.equal(s.clear.disabled,false);
  await s.fire();assert.deepEqual(s.requests,[]);
});

test('recall disappears at dispatch and cannot cancel an uploaded message',async()=>{
  const s=setup();s.submit('发送');const item=vm.runInContext('pendingInput[0]',s.context);
  await s.fire();assert.equal(item.recall.removed,true);
  item.recall.onclick();assert.equal(item.row.removed,false);assert.deepEqual(s.requests,['发送']);
});

test('queued input can be recalled while the previous reply is busy',async()=>{
  const s=setup();s.context.busy=true;s.submit('排队');await s.fire();
  vm.runInContext('pendingInput[0].recall.onclick()',s.context);s.context.finishTurn();
  await s.fire();assert.deepEqual(s.requests,[]);
});
