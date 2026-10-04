const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/shell.js'),'utf8');
const page=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/engineering.html'),'utf8');
function node(tag){return {tag,children:[],hidden:false,textContent:'',append(...items){this.children.push(...items)},replaceChildren(...items){this.children=items}}}
function setup(){const nodes={'#decisionDebugOutput':node('div'),'#decisionLegacyControls':node('p')};
 const context=vm.createContext({document:{createElement:node},$:id=>nodes[id]});
 vm.runInContext(source.slice(source.indexOf('function renderDecisionDebug('),source.indexOf('async function refreshDecisionDebug')),context);
 return {context,nodes}}
function text(n){return [n.textContent,...n.children.map(text)].join(' ')}
test('Decision 2 debug reads human explanations and keeps raw details folded and literal',()=>{
 const {context,nodes}=setup();
 context.renderDecisionDebug({decision_mode:'agency',latest:{mode:'ADVISE',agent_recommendation:'<img src=x>',predicted_user_choice:'继续项目',context_sources:['agenda','current_cognition'],principle_ids:['career'],guard_flags:[]},
 choice_history:[{mode:'PICK',suggestion:'两瓶',user_final_choice:'三瓶',overridden:true}],guard_events:[{tool:'payment',flags:['external_action'],status:'require_confirmation'}]});
 const output=nodes['#decisionDebugOutput'];
 assert.match(text(output),/这次朝汐建议：<img src=x>/);assert.match(text(output),/模式：ADVISE/);
 assert.match(text(output),/Agenda、Current Cognition/);assert.match(text(output),/已接受覆盖/);
 assert.match(text(output),/payment/);assert.ok(nodes['#decisionLegacyControls'].hidden);
 const details=output.children.find(n=>n.tag==='details');assert.ok(details);assert.ok(!details.open);
 assert.doesNotMatch(source.slice(source.indexOf('function renderDecisionDebug('),source.indexOf('async function refreshDecisionDebug')),/innerHTML/);
});
test('empty agency observation requires no test model and legacy exposes rollback controls',()=>{
 const {context,nodes}=setup();context.renderDecisionDebug({decision_mode:'agency',latest:null,choice_history:[]});
 assert.match(text(nodes['#decisionDebugOutput']),/查看不会调用模型/);
 context.renderDecisionDebug({decision_mode:'legacy'});assert.equal(nodes['#decisionLegacyControls'].hidden,false);
});
test('engineering has Decision 2 panel and hides independent classifier controls until legacy is selected',()=>{
 assert.match(page,/Decision 2.0 · 生活判断/);assert.match(page,/id="decisionLegacyControls" hidden/);
 assert.match(source,/refreshDecisionDebug\(\).*renderDecisionDebug\(await request\('\/api\/debug\/decision'\)\)/);
});


test('failed delivery is visible and previous advice is not presented as this turn',()=>{
 const {context,nodes}=setup();context.renderDecisionDebug({decision_mode:'agency',
 reply_protocol:{status:'failed',error_code:'empty_model_reply'},
 latest:{mode:'ADVISE',agent_recommendation:'旧建议',context_sources:['current_image']}});
 assert.match(text(nodes['#decisionDebugOutput']),/本轮回复未能交付：empty_model_reply/);
 assert.match(text(nodes['#decisionDebugOutput']),/上次已完成的判断：旧建议/);
 assert.match(text(nodes['#decisionDebugOutput']),/本轮图片/);
 assert.doesNotMatch(text(nodes['#decisionDebugOutput']),/这次朝汐建议：/);
});

test('valid body without awareness explains the missing decision record',()=>{
 const {context,nodes}=setup();context.renderDecisionDebug({decision_mode:'agency',
 reply_protocol:{status:'decoded',awareness:'invalid'},latest:null});
 assert.match(text(nodes['#decisionDebugOutput']),/正文已生成，但没有有效的生活判断记录/);
});
