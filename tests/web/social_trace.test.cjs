const {test}=require('node:test');
const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8');
const code=html.slice(html.indexOf('let socialTracePage=null;'),html.indexOf("$('#provenanceInspectorRun').onclick="));
function setup(responses){const elements=new Map(),urls=[];const $=key=>{if(!elements.has(key))elements.set(key,{value:'',disabled:false,textContent:'',set innerHTML(x){throw Error('unsafe HTML')}});return elements.get(key)};
 vm.runInNewContext(code,{$,JSON,URLSearchParams,request:async url=>{urls.push(url);const data=responses.shift();if(data instanceof Error)throw data;return data}});return {$,urls};}
test('social trace encodes references, shows literal raw text and pages',async()=>{
 const ui=setup([{reference:'qq:group:A:1&other',statement_id:'s1',records:[{content:'<img onerror=x>'}],next_offset:0,next_text_offset:200},{records:[],next_offset:null}]);
 ui.$('#socialTraceRef').value='qq:group:A:1&other';ui.$('#socialTraceStatement').value='s1';
 await ui.$('#socialTraceRun').onclick();assert.match(ui.urls[0],/reference=qq%3Agroup%3AA%3A1%26other/);assert.ok(ui.$('#socialTraceOutput').textContent.includes('<img onerror=x>'));assert.equal(ui.$('#socialTraceNext').disabled,false);
 await ui.$('#socialTraceNext').onclick();assert.match(ui.urls[1],/offset=0&text_offset=200/);assert.equal(ui.$('#socialTraceNext').disabled,true);
});
test('empty trace input makes no request and errors disable pagination',async()=>{
 const ui=setup([new Error('unavailable')]);await ui.$('#socialTraceRun').onclick();assert.equal(ui.urls.length,0);
 ui.$('#socialTraceRef').value='missing';await ui.$('#socialTraceRun').onclick();assert.equal(ui.$('#socialTraceOutput').textContent,'unavailable');assert.equal(ui.$('#socialTraceNext').disabled,true);
});
