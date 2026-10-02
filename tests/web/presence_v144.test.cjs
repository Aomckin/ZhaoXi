const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8');

test('natural activity text clears on completion and never renders HTML',()=>{
  const el={textContent:'',hidden:true};
  const ctx=vm.createContext({$:()=>el,renderInteractionBadge:()=>{}});
  vm.runInContext(html.slice(html.indexOf('function renderPresenceActivity('),html.indexOf('async function setupRecentContextBoard(')),ctx);
  ctx.renderPresenceActivity({status:'在翻旧日记',current_presence:'SEMI_ACTIVE'});
  assert.equal(el.textContent,'在翻旧日记');assert.equal(el.hidden,false);
  ctx.renderPresenceActivity({status:null,current_presence:'ACTIVE'});
  assert.equal(el.textContent,'');assert.equal(el.hidden,true);
  ctx.renderPresenceActivity({status:'<img src=x>',current_presence:'IDLE'});
  assert.equal(el.textContent,'<img src=x>');
});

for(const confirmation of [false,true]){
  test('manual social write sends explicit confirmation '+confirmation,async()=>{
    const button={disabled:false,dataset:{activity:'social_wander'}},debug={textContent:''},requests=[];
    const ctx=vm.createContext({document:{querySelectorAll:()=>[button]},$:()=>debug,
      window:{confirm:()=>confirmation},request:async(url,options)=>{requests.push(JSON.parse(options.body));return {}}});
    vm.runInContext(html.slice(html.indexOf("document.querySelectorAll('.runInternalActivity')"),html.indexOf('async function setupBudgetDebug(')),ctx);
    await button.onclick();
    assert.equal(requests[0].confirm_social_write,confirmation);
    assert.equal(button.disabled,false);
  });
}
