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

test('sidebar keeps the concrete event sequence while the composer shows one characterful stage',()=>{
  const s=setup();
  assert.equal(s.context.beginActionTrace(),'request-1');
  assert.equal(s.nodes['#actionTrace'].open,false);
  assert.match(s.activity.textContent,/^理解 · 耳朵/);
  s.emit('request_started','request','running','正在处理请求…');
  s.emit('model_step_started','model','running','正在思考下一步…',{step_id:1});
  s.emit('model_step_finished','model','success','已确定下一步',{step_id:1});
  s.emit('model_step_started','model','running','正在思考下一步…',{step_id:2});
  assert.equal(s.list.children.length,4);
  assert.equal(s.list.children[3].textContent,'第2轮 · 正在思考下一步…');
  assert.match(s.activity.textContent,/^理解 · 耳朵/);
  s.emit('memory_search_started','memory_search','running','正在检索相关记忆…');
  assert.match(s.activity.textContent,/^检索 · 顺着线索/);
  s.emit('tool_call_started','tool_execution','running','正在添加日程…',{
    tool_call_id:'call-private',invocation_id:'invoke-private',tool_name:'agenda_add',
  });
  assert.match(s.activity.textContent,/^行动 · 伸爪/);
  s.emit('tool_call_succeeded','tool_execution','success','已添加日程',{
    tool_call_id:'call-private',invocation_id:'invoke-private',tool_name:'agenda_add',
  });
  s.emit('response_generation_started','response_generation','running','正在整理回复…');
  assert.match(s.activity.textContent,/^整理 · 把结果叼回来/);
  s.emit('task_completed','task','success','本次任务已完成');
  assert.equal(s.list.children.at(-1).textContent,'本次任务已完成');
  assert.equal(s.nodes['#actionTraceSummary'].textContent,'行动记录 · 已完成');
  assert.equal(s.activity.textContent,'完成 · 好啦，事情办妥了汪。');
  assert.doesNotMatch(s.activity.textContent,/call-private|invoke-private|步骤|Token|第2轮/);
  assert.match(s.nodes['#actionTraceDebug'].textContent,/call-private/);
});

test('token details remain in the sidebar and never appear above the input',()=>{
  const s=setup();s.context.beginActionTrace();
  s.emit('model_step_failed','model','failed','本次请求 Token 预算已耗尽',{
    step_id:3,error_code:'token_budget_exhausted',metadata:{remaining_tokens:0},
  });
  assert.match(s.activity.textContent,/^整理 · /);
  assert.doesNotMatch(s.activity.textContent,/Token|第3轮/);
  assert.equal(s.list.children[0].textContent,'第3轮 · 本次请求 Token 预算已耗尽');
  assert.match(s.nodes['#actionTraceDebug'].textContent,/remaining_tokens/);
  s.emit('task_completed','task','success','已完成的操作均已保留',{
    metadata:{task_status:'completed',response_status:'failed'},
  });
  assert.match(s.activity.textContent,/^完成 · /);
  assert.equal(s.nodes['#actionTraceSummary'].textContent,'行动记录 · 回复未完成');
});
