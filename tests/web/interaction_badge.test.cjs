// Run with: node --test tests/web/interaction_badge.test.cjs
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

const html=readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8');
const source=html.slice(html.indexOf('function interactionBadgeView('),html.indexOf('let setupNoticeShown='));

function createBadge(){
  const attributes={};
  return {
    hidden:true,className:'interaction-badge',textContent:'',title:'',attributes,
    setAttribute:(name,value)=>{attributes[name]=value},
    removeAttribute:name=>{delete attributes[name]},
  };
}

function render(state){
  const badge=createBadge();
  const context=vm.createContext({$:()=>badge});
  vm.runInContext(source,context);
  context.renderInteractionBadge(state===undefined?null:{interaction_state:state});
  return badge;
}

test('ACTIVE and SEMI_ACTIVE render compact localized badges',()=>{
  const active=render('ACTIVE');
  assert.equal(active.hidden,false);
  assert.equal(active.textContent,'活跃');
  assert.equal(active.className,'interaction-badge active');
  assert.equal(active.attributes['aria-label'],'当前互动状态：活跃');

  const semiActive=render('SEMI_ACTIVE');
  assert.equal(semiActive.hidden,false);
  assert.equal(semiActive.textContent,'半活跃');
  assert.equal(semiActive.className,'interaction-badge semi-active');
  assert.equal(semiActive.attributes['aria-label'],'当前互动状态：半活跃');
});

test('other and unavailable states keep the badge hidden',()=>{
  for(const state of ['IDLE','AWAY',undefined]){
    const badge=render(state);
    assert.equal(badge.hidden,true);
    assert.equal(badge.textContent,'');
    assert.equal(badge.className,'interaction-badge');
  }
});
