const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const html=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8');
const code=html.slice(html.indexOf("$('#memoryInspectorRun').onclick="),html.indexOf('async function refreshDecisionDebug'));
function setup(response){
  const elements=new Map(),calls=[];
  const element=()=>({value:'',textContent:'',children:[],replaceChildren(){this.children=[]},append(child){this.children.push(child)},set innerHTML(value){throw Error('unsafe HTML sink')}});
  const $=id=>{if(!elements.has(id))elements.set(id,element());return elements.get(id)};
  const context={$,encodeURIComponent,JSON,document:{createElement:element,createTextNode:text=>({textContent:text})},request:async url=>{calls.push(url);if(response instanceof Error)throw response;return response}};
  vm.runInNewContext(code,context);
  $('#memoryInspectorQuery').value=' QQ 接入 & <script> ';
  $('#memoryInspectorId').value='forbidden&id';
  return {$,calls};
}
for(const mode of ['ASSOCIATIVE','EXPLICIT_RECALL','BROAD_SEARCH']){
 test(`Inspector submits ${mode}, explains evidence and keeps content literal`,async()=>{
  const fixture={retrieval_mode:mode,embedding_status:'available',requested_memory:{why:{why_excluded:'status filter'}},
    candidates:[{memory_id:'id',content:'<img src=x onerror=alert(1)>',reason:'trusted fact',evidence_refs:['event'],activation_history:[{reason:'decay'}],candidate_source:['semantic'],why_selected:['query match'],retrieval_mode:mode}]};
  const {$,calls}=setup(fixture);$('#memoryInspectorMode').value=mode;
  await $('#memoryInspectorRun').onclick();
  assert.ok(calls[0].includes(`retrieval_mode=${mode}`));
  assert.ok(calls[0].includes('memory_id=forbidden%26id'));
  const texts=$('#memoryInspectorOutput').children.map(x=>x.textContent).join('\n');
  assert.match(texts,/status filter/);assert.match(texts,/trusted fact/);assert.match(texts,/event/);assert.match(texts,/<img src=x onerror=alert\(1\)>/);
 });
}
test('Inspector clears stale results, distinguishes empty results and errors',async()=>{
 let ui=setup({candidates:[]});ui.$('#memoryInspectorOutput').children.push({textContent:'stale'});
 await ui.$('#memoryInspectorRun').onclick();
 assert.equal(ui.$('#memoryInspectorOutput').children.length,2);
 ui=setup(new Error('service unavailable'));
 await ui.$('#memoryInspectorRun').onclick();assert.equal(ui.$('#memoryInspectorOutput').textContent,'service unavailable');
});
test('Cluster and database Inspector buttons fetch the correct diagnostics',async()=>{
 const ui=setup({last_vacuum:'now'});
 await ui.$('#memoryClusterInspectorRun').onclick();await ui.$('#databaseInspectorRun').onclick();
 assert.deepEqual(ui.calls,['/api/debug/memory-clusters','/api/debug/database-maintenance']);
 assert.match(ui.$('#memoryMaintenanceOutput').textContent,/last_vacuum/);
});
