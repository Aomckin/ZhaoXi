const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');

const assets=path.join(__dirname,'../../src/zhaoxi/web/static');
const html=readFileSync(path.join(assets,'index.html'),'utf8');
const config=html.match(/<script id="characterConfig" type="application\/json">(.*?)<\/script>/)[1];
const script=readFileSync(path.join(assets,'deskboard.js'),'utf8');
const avatarSource=script.slice(script.indexOf('const avatar = document.querySelector'));

test('presence states select the matching portrait and retain the active fallback',()=>{
  const avatar={hidden:true,src:'',getAttribute(name){return name==='src'?this.src:null}};
  const fallback={hidden:false};
  const context=vm.createContext({window:{},document:{querySelector(selector){
    return {'#characterAvatar':avatar,'#avatarFallback':fallback,'#characterConfig':{textContent:config}}[selector];
  }}});
  vm.runInContext(avatarSource,context);
  assert.equal(avatar.src,'/static/avatar-default.webp');
  for(const [state,expected] of Object.entries({
    ACTIVE:'/static/avatar-default.webp',
    SEMI_ACTIVE:'/static/avatar-daydream.png',
    IDLE:'/static/avatar-nap.png',
    AWAY:'/static/avatar-nap.png',
  })){
    context.window.setCharacterAvatarState(state);
    assert.equal(avatar.src,expected);
  }
  avatar.onerror();
  assert.equal(avatar.src,'/static/avatar-default.webp');
  avatar.onerror();
  assert.equal(avatar.hidden,true);
  assert.equal(fallback.hidden,false);
});
