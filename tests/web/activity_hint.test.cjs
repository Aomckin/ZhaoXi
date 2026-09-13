const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8');
function setup(){
  let id=0;const timers=new Map();
  const context=vm.createContext({activity:{textContent:''},
    setTimeout:(fn,ms)=>{assert.equal(ms,3000);timers.set(++id,fn);return id},
    clearTimeout:id=>timers.delete(id),
  });
  vm.runInContext(html.slice(html.indexOf('let activityHintTimer='),html.indexOf('function escapeHtml(')),context);
  return {context,timers,fire(){const callbacks=[...timers.values()];timers.clear();callbacks.forEach(fn=>fn())}};
}
test('temporary voice hint disappears after three seconds',()=>{
  const s=setup();s.context.showActivityHint('Voice 未启用或配置不可用。');
  assert.match(s.context.activity.textContent,/Voice/);
  s.fire();assert.equal(s.context.activity.textContent,'');
});
test('an old hint timeout cannot erase a newer ongoing status',()=>{
  const s=setup();s.context.showActivityHint('Voice 未启用');
  s.context.activity.textContent='正在思考…';s.fire();
  assert.equal(s.context.activity.textContent,'正在思考…');
});
test('repeated hints restart their three-second lifetime',()=>{
  const s=setup();s.context.showActivityHint('提示');const previous=[...s.timers.keys()][0];
  s.context.showActivityHint('提示');
  assert.equal(s.timers.size,1);assert(!s.timers.has(previous));
  s.fire();assert.equal(s.context.activity.textContent,'');
});
