const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

const html=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8');
const source=html.slice(html.indexOf('let activeTraceId='),html.indexOf('let activityHintTimer='));
test('the live action list is visible in the side panel',()=>{
  const summary=html.indexOf('id="actionTraceSummary"');
  const list=html.indexOf('id="actionTraceEvents"');
  const debug=html.indexOf('id="runtimeDebugPanel"');
  assert.ok(summary>=0&&list>summary&&list<debug);
  assert.equal(html.split('id="actionTraceEvents"').length-1,1);
});


function setup(){
  const list={children:[],append(row){this.children.push(row)},replaceChildren(){this.children=[]}};
  const nodes={
    '#actionTrace':{open:false},'#actionTraceSummary':{textContent:''},
    '#actionTraceEvents':list,'#actionTraceDebug':{textContent:''},
    '#actionRuntimeSummary':{textContent:''},'#actionPlannerStatus':{textContent:''},
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

test('side panel keeps the concrete event sequence while the composer shows one characterful stage',()=>{
  const s=setup();
  assert.equal(s.context.beginActionTrace(),'request-1');
  assert.equal(s.nodes['#actionTraceSummary'].textContent,'行动记录 · 进行中');
  assert.match(s.activity.textContent,/^理解 · 耳朵/);
  s.emit('request_started','request','running','正在处理请求…');
  s.emit('model_step_started','model','running','正在思考下一步…',{step_id:1});
  s.emit('model_step_finished','model','success','已确定下一步',{step_id:1});
  s.emit('model_step_started','model','running','正在思考下一步…',{step_id:2});
  assert.equal(s.list.children.length,4);
  assert.equal(s.list.children[3].textContent,'正在思考下一步…');
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
  assert.equal(s.nodes['#actionTraceSummary'].textContent,'行动记录 · 进行中');
  s.context.endActionTraceFallback('本次任务已完成');
  assert.equal(s.nodes['#actionTraceSummary'].textContent,'行动记录 · 已完成');
  assert.doesNotMatch(s.activity.textContent,/call-private|invoke-private|步骤|Token|第2轮/);
  assert.match(s.nodes['#actionTraceDebug'].textContent,/call-private/);
});

test('token details remain in Debug and never appear above the input',()=>{
  const s=setup();s.context.beginActionTrace();
  s.emit('model_step_failed','model','failed','本次请求 Token 预算已耗尽',{
    step_id:3,error_code:'token_budget_exhausted',metadata:{remaining_tokens:0},
  });
  assert.match(s.activity.textContent,/^整理 · /);
  assert.doesNotMatch(s.activity.textContent,/Token|第3轮/);
  assert.equal(s.list.children[0].textContent,'本次请求 Token 预算已耗尽');
  assert.match(s.nodes['#actionTraceDebug'].textContent,/remaining_tokens/);
  s.emit('task_completed','task','success','已完成的操作均已保留',{
    metadata:{task_status:'completed',response_status:'failed'},
  });
  assert.equal(s.nodes['#actionTraceSummary'].textContent,'行动记录 · 回复未完成');
  s.context.endActionTraceFallback('本次任务未完成',true);
  assert.equal(s.nodes['#actionTraceSummary'].textContent,'行动记录 · 回复未完成');
});

test('budget requests appear in Debug while context estimates stay in raw events',()=>{
  const s=setup();s.context.beginActionTrace();
  const before=s.activity.textContent;
  s.emit('budget_extension_requested','token_budget','info','已申请额外预算',{metadata:{requested_extra:3000}});
  assert.equal(s.list.children.at(-1).textContent,'已申请额外预算');
  assert.equal(s.activity.textContent,before);
  s.emit('context_measured','context','info','已测量本轮上下文',{metadata:{estimated:{tool_schema:120}}});
  assert.equal(s.list.children.length,1);
  assert.match(s.nodes['#actionTraceDebug'].textContent,/tool_schema/);
  assert.doesNotMatch(s.activity.textContent,/3000|120/);
});

test('runtime observatory renders actual memory candidate score components',()=>{
  const node={textContent:''};
  const context=vm.createContext({
    $:selector=>selector==='#runtimeMemoryCandidates'?node:null,
    activity:{textContent:''},crypto:{randomUUID:()=> 'request-1'},
    document:{createElement:()=>({})},
  });
  vm.runInContext(source,context);
  context.renderMemoryCandidates([{
    rank:1,kind:'semantic',status:'active',cluster:'开发习惯',content:'晚间开发效率更高',
    final_score:0.91,contextual_relevance:0.82,text_score:0.73,semantic_score:0.64,
    graph_score:0.12,time_score:0.55,activation_score:0.44,importance_score:0.66,
    why_selected:['embedding=0.640'],
  }]);
  assert.match(node.textContent,/晚间开发效率更高/);
  assert.match(node.textContent,/Final 0.9100/);
  assert.match(node.textContent,/Semantic 0.6400/);
  assert.match(node.textContent,/Graph 0.1200/);
  assert.match(node.textContent,/embedding=0.640/);
});

test('live calls show duration and final metrics distinguish ordinary agent execution',()=>{
  const s=setup();s.context.beginActionTrace();
  s.emit('llm_call_finished','model','success','模型调用已结束',{metadata:{index:2,owner:'agent',duration_ms:1234.56}});
  assert.match(s.list.children.at(-1).textContent,/agent #2.*1234.56 ms/);
  s.emit('runtime_metrics_finalized','metrics','success','运行指标已汇总',{metadata:{runtime_metrics:{total_ms:2000,ttfr_ms:1000,planner_used:false,runtime_lane:'fast',route_source:'fast_gate',foreground_llm_calls:1,background_llm_calls:0,router_llm_calls:0,agent_llm_calls:1,planner_llm_calls:0,memory_search_count:0,tool_rounds:0,catalog_inspections:0,fast_gate_reason:'safe_conversation',llm_calls:[],tool_calls:[]}}});
  assert.match(s.nodes['#actionRuntimeSummary'].textContent,/FAST \/ 轻量对话/);
  assert.match(s.nodes['#actionRuntimeSummary'].textContent,/前台模型 1.*Router 0/);
  assert.match(s.nodes['#actionRuntimeSummary'].textContent,/Fast Gate：safe_conversation/);
  assert.match(s.nodes['#actionRuntimeSummary'].textContent,/2000.00 ms/);
  assert.match(s.nodes['#actionPlannerStatus'].textContent,/普通 Agent/);
});


test('Fast Gate 2 observatory explains votes and router fallback as text',()=>{
  const s=setup();
  s.context.renderRuntimeMetrics({fast_gate_version:2,fast_gate_decision:'AMBIGUOUS',
    fast_score:0.8,heavy_score:0.5,fast_positive_evidence:['recent_context_sufficient'],
    heavy_evidence:['resource_reference_confidence'],
    fast_gate_signals:{conversation_likeness:0.8,resource_reference_confidence:0.5,signal_errors:['<script>example</script>']},
    router_required:true,router_override:true,router_final_lane:'fast_chat',router_to_fast_count:1});
  const node=s.nodes['#actionRuntimeSummary'];
  assert.match(node.textContent,/Fast Gate 2 · AMBIGUOUS · FAST 分数 0.8 · HEAVY 分数 0.5/);
  assert.match(node.textContent,/FAST 依据：recent_context_sufficient/);
  assert.match(node.textContent,/HEAVY 依据：resource_reference_confidence/);
  assert.match(node.textContent,/信号 conversation_likeness：0.8/);
  assert.match(node.textContent,/Router required true · override true · final fast_chat · 回到 FAST 1/);
  assert.match(node.textContent,/<script>example<\/script>/);
  assert.equal(node.innerHTML,undefined);
});


test('Debug shows the single capability upgrade without rendering a draft',()=>{
  const s=setup();
  s.context.renderRuntimeMetrics({runtime_lane:'standard',route_source:'fast_escalation',
    escalation_reason:'fast_requires_recall',fast_escalation_count:1,fast_escalation_kind:'recall'});
  const text=s.nodes['#actionRuntimeSummary'].textContent;
  assert.match(text,/STANDARD \/ 标准/);
  assert.match(text,/FAST → STANDARD 1 次 · 能力 recall/);
  assert.match(text,/升级：fast_requires_recall/);
});
