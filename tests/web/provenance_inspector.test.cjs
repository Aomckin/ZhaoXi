const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8');
const start=html.indexOf("$('#provenanceInspectorRun').onclick=");
const code=html.slice(start,html.indexOf("$('#memoryInspectorRun').onclick=",start));
function setup(response){
 const elements=new Map(),calls=[];
 const $=key=>{if(!elements.has(key))elements.set(key,{textContent:'',set innerHTML(x){throw Error('unsafe HTML')}});return elements.get(key)};
 vm.runInNewContext(code,{$,JSON,request:async url=>{calls.push(url);if(response instanceof Error)throw response;return response}});
 return {$,calls};
}
test('Source Inspector shows scope, unknown, plugin and literal labels',async()=>{
 const ui=setup({items:[{context_relation:'unknown',source_plugin:'future',timeline_scope:'current_trigger',rendered_source_label:'<img onerror=x>'}],legacy_shadow:['old'],rendered:['new']});
 await ui.$('#provenanceInspectorRun').onclick();
 assert.deepEqual(ui.calls,['/api/debug/provenance']);
 const text=ui.$('#provenanceInspectorOutput').textContent;
 for(const word of ['unknown','future','current_trigger','<img onerror=x>','old','new'])assert.ok(text.includes(word));
});
test('Source Inspector renders empty results and error',async()=>{
 let ui=setup({items:[]});await ui.$('#provenanceInspectorRun').onclick();assert.match(ui.$('#provenanceInspectorOutput').textContent,/\[\]/);
 ui=setup(new Error('unavailable'));await ui.$('#provenanceInspectorRun').onclick();assert.equal(ui.$('#provenanceInspectorOutput').textContent,'unavailable');
});
