const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8');
const source=html.slice(html.indexOf('const INPUT_MERGE_MS='),html.indexOf('async function resolve('));
function setup(){
  let id=0;const timers=new Map(),requests=[],payloads=[],bubbles=[],clear={replaceChildren(){},append(){}};
  const context=vm.createContext({busy:false,send:{},input:{value:'',focus(){}},activity:{},debug:{},
    $:()=>clear,document:{createElement:()=>({append(){},setAttribute(){}})},addMessage:(...args)=>bubbles.push(args),permissionCard(){},
    setTimeout:(fn,ms)=>{assert.equal(ms,2000);timers.set(++id,fn);return id},clearTimeout:id=>timers.delete(id),
    request:async(url,options)=>{payloads.push(JSON.parse(options.body));requests.push(JSON.parse(options.body).message);return {content:'回复'}},
    sendReply:async()=>{},setupCapabilities:async()=>{},
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
  assert.deepEqual(s.payloads,[{message:'看看这是什么',images:['data:image/png;base64,AAAA']}]);
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
