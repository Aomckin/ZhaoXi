const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const common=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/dashboard-common.js'),'utf8');
const script=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/dashboard.js'),'utf8');
const page=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8');
test('living page has dashboard entry and engineering controls have moved',()=>{assert.match(page,/href="\/dashboard"/);for(const id of ['runtimeDebugPanel','toolCabinetPanel','internalActivityPanel','actionTrace'])assert.ok(!page.includes('id="'+id+'"'))});
test('manual receipt is rendered before awaiting the runtime and technical details stay folded',()=>{assert.ok(common.indexOf("summary:'正在处理，请稍候。'")<common.indexOf("await send('/api/internal-activity/"));assert.match(common,/el\('details'\)/);assert.doesNotMatch(common,/innerHTML/)});
test('overview polls only its own bounded API and engineering iframe loads on demand',()=>{assert.match(script,/if\(loaders\[view\]\)/);assert.match(script,/frame.src='\/static\/engineering.html#'\+view/);assert.doesNotMatch(script,/memory-retrieval|memory-clusters/)});

const vm=require('node:vm');
function node(tag='div'){return {tag,textContent:'',className:'',dataset:{},children:[],append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items}}}
function setup(){const feedback=node(),error=node();const ctx=vm.createContext({document:{createElement:node,querySelector:s=>s==='#feedback'?feedback:error},window:{confirm:()=>false},fetch:()=>{throw Error('unexpected request')}});vm.runInContext(common.replace(/export /g,''),ctx);return {ctx,feedback}}
for(const status of ['SUCCESS','NO_CHANGE','SKIPPED','BLOCKED','FAILED','CANCELLED'])test('receipt '+status+' exposes summary with raw data folded and literal',()=>{const {ctx}=setup();const r=ctx.receiptCard({status,title:'<img src=x>',summary:'明确反馈',raw_payload:{secret:'secondary'}});assert.equal(r.children[0].textContent,'<img src=x>');assert.equal(r.children[1].textContent,'明确反馈');const details=r.children.find(n=>n.tag==='details');assert.ok(details);assert.ok(!details.open)});
test('run immediately shows running then consumes structured final receipt',async()=>{const {ctx,feedback}=setup();let finish;ctx.fetch=()=>new Promise(resolve=>finish=()=>resolve({ok:true,json:async()=>({receipt:{status:'NO_CHANGE',title:'完成',summary:'无需调整',raw_payload:{}}})}));const task=ctx.runActivity('cognition_gardening','整理认知');assert.equal(feedback.children[0].dataset.status,'RUNNING');finish();await task;assert.equal(feedback.children[0].dataset.status,'NO_CHANGE');assert.equal(feedback.children[0].children[1].textContent,'无需调整')});
test('declining social confirmation performs no request',async()=>{const {ctx,feedback}=setup();await ctx.runActivity('social_wander','发言',true);assert.equal(feedback.children.length,0)});
