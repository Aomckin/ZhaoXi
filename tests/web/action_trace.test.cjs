const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

const html=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8');
const source=html.slice(html.indexOf('let activeTraceId='),html.indexOf('let activityHintTimer='));

function setup(){
  const list={children:[],append(row){this.children.push(row)},replaceChildren(){this.children=[]}};
  const nodes={
    '#actionTrace':{open:false},'#actionTraceSummary':{textContent:''},
    '#actionTraceEvents':list,'#actionTraceDebug':{textContent:''},
  };
  const activity={textContent:''};
  const context=vm.createContext({
    $:selector=>nodes[selector],activity,crypto:{randomUUID:()=> 'request-1'},
    document:{createElement:()=>({className:'',textContent:'',remove(){
      const index=list.children.indexOf(this);if(index>=0)list.children.splice(index,1);
    }})},
  });
  vm.runInContext(source,context);
  const emit=(event_type,stage,outcome,display_message,extra={})=>context.renderAgentEvent({
    request_id:'request-1',event_type,stage,outcome,display_message,
    timestamp:'2026-09-23T00:00:00Z',...extra,
  });
  return {context,nodes,list,activity,emit};
}

test('user stages replace model rounds and raw fields stay in sidebar Debug',()=>{
  const s=setup();
  assert.equal(s.context.beginActionTrace(),'request-1');
  assert.equal(s.nodes['#actionTrace'].open,false);
  s.emit('request_started','request','running','正在处理请求…');
  s.emit('model_step_started','model','running','正在思考下一步…',{step_id:1});
  s.emit('model_step_finished','model','success','已确定下一步',{step_id:1});
  s.emit('model_step_started','model','running','正在思考下一步…',{step_id:2});
  assert.equal(s.list.children.length,1);
  assert.match(s.activity.textContent,/^理解 · /);
  s.emit('tool_call_started','tool_execution','running','正在添加日程…',{
    tool_call_id:'call-private',invocation_id:'invoke-private',tool_name:'agenda_add',
  });
  s.emit('tool_call_succeeded','tool_execution','success','已添加日程',{
    tool_call_id:'call-private',invocation_id:'invoke-private',tool_name:'agenda_add',
  });
  s.emit('response_generation_started','response_generation','running','正在整理回复…');
  s.emit('task_completed','task','success','本次任务已完成');
  assert.deepEqual(s.list.children.map(row=>row.textContent),[
    '理解 · 已理解请求','行动 · 已添加日程','整理 · 已完成整理','完成 · 本次任务已完成',
  ]);
  assert.equal(s.nodes['#actionTraceSummary'].textContent,'行动记录 · 已完成');
  assert.doesNotMatch(s.list.children.map(row=>row.textContent).join(''),/call-private|invoke-private|步骤|Token/);
  assert.match(s.nodes['#actionTraceDebug'].textContent,/call-private/);
  assert.match(s.nodes['#actionTraceDebug'].textContent,/"step_id":2/);
});

test('token budget details do not leak into the main action line',()=>{
  const s=setup();s.context.beginActionTrace();
  s.emit('model_step_failed','model','failed','本次请求 Token 预算已耗尽',{
    error_code:'token_budget_exhausted',metadata:{remaining_tokens:0},
  });
  assert.equal(s.activity.textContent,'整理 · 回复生成遇到问题');
  assert.equal(s.list.children[0].textContent,'整理 · 回复生成遇到问题');
  assert.match(s.nodes['#actionTraceDebug'].textContent,/Token/);
  assert.match(s.nodes['#actionTraceDebug'].textContent,/remaining_tokens/);
  s.emit('task_completed','task','success','已完成的操作均已保留',{
    metadata:{task_status:'completed',response_status:'failed'},
  });
  assert.equal(s.activity.textContent,'完成 · 操作已保留，回复未完成');
  assert.equal(s.nodes['#actionTraceSummary'].textContent,'行动记录 · 回复未完成');
});
