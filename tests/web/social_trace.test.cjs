const {test}=require('node:test');
const assert=require('node:assert/strict');const fs=require('node:fs');const vm=require('node:vm');const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8');
const code=html.slice(html.indexOf('let socialTracePage=null'),html.indexOf("$('#provenanceInspectorRun').onclick="));
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

test('search filters are encoded and changing filters restarts pagination',async()=>{
 const ui=setup([{records:[{reference:'qq:group:A:1',content:'<b>原文</b>'}],next_offset:2,next_text_offset:10},{records:[],next_offset:null}]);
 ui.$('#socialTraceQuery').value='关键词&条件';ui.$('#socialTraceGroup').value='A';ui.$('#socialTraceSince').value='2026-10-01T00:00:00+08:00';
 await ui.$('#socialTraceSearch').onclick();assert.match(ui.urls[0],/query=/);assert.match(ui.urls[0],/group_id=A/);assert.ok(ui.urls[0].includes('%2B08%3A00'));assert.ok(!ui.urls[0].includes('reference='));
 assert.ok(ui.$('#socialTraceOutput').textContent.includes('<b>原文</b>'));
 ui.$('#socialTraceGroup').value='B';await ui.$('#socialTraceNext').onclick();assert.match(ui.urls[1],/group_id=B/);assert.ok(!ui.urls[1].includes('offset='));
});
test('search next page preserves conditions and text cursor',async()=>{
 const ui=setup([{records:[],next_offset:3,next_text_offset:400},{records:[],next_offset:null}]);ui.$('#socialTraceGroup').value='A';
 await ui.$('#socialTraceSearch').onclick();await ui.$('#socialTraceNext').onclick();assert.match(ui.urls[1],/group_id=A&offset=3&text_offset=400/);
});
