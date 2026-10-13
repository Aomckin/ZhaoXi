const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

const html=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/engineering.html'),'utf8')+fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/shell.js'),'utf8');
const source=html.slice(html.indexOf('let activeTraceId='),html.indexOf('let activityHintTimer='));
test('the live action list is available in dashboard engineering',()=>{
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
    '#actionRuntimeSummary':{textContent:''},'#actionPlannerStatus':{textContent:''},'#actionMaintenance':{textContent:''},
    '#actionTokenSummary':{textContent:''},'#actionContextBreakdown':{children:[],append(row){this.children.push(row)},replaceChildren(){this.children=[]}},'#actionModelCalls':{children:[],append(row){this.children.push(row)},replaceChildren(){this.children=[]}},
  };
  const activity={textContent:''};
  const context=vm.createContext({
    $:selector=>nodes[selector],activity,busy:true,crypto:{randomUUID:()=> 'request-1'},
    document:{createElement:()=>({className:'',textContent:'',children:[],append(...items){this.children.push(...items)},remove(){
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


test('observer adopts desktop requests, ignores retired events and completes without its own POST',()=>{
  const s=setup();s.context.busy=false;s.context.document.body={dataset:{traceMonitor:'true'}};
  s.emit('runtime_started','runtime','running','请求一开始');
  s.emit('tool_call_succeeded','tool_execution','success','工具已完成');
  assert.equal(s.list.children.length,2);
  s.emit('runtime_started','runtime','running','请求二开始',{request_id:'request-2'});
  s.emit('tool_call_succeeded','tool_execution','success','旧请求晚到的事件');
  s.emit('request_started','request','running','旧请求晚到的启动');
  assert.deepEqual(s.list.children.map(n=>n.textContent),['请求二开始']);
  s.emit('runtime_finished','runtime','success','请求二完成',{request_id:'request-2'});
  assert.equal(s.nodes['#actionTraceSummary'].textContent,'行动记录 · 已完成');
  assert.equal(s.activity.textContent,'');
});

test('busy chat keeps its own trace and does not adopt another request',()=>{
  const s=setup();s.context.beginActionTrace();
  s.emit('runtime_started','runtime','running','别的请求',{request_id:'request-2'});
  assert.equal(s.list.children.length,0);
  s.emit('tool_call_started','tool_execution','running','当前请求');
  assert.equal(s.list.children[0].textContent,'当前请求');
});

test('snapshot restores an in-flight trace and metrics without changing composer text',async()=>{
  const s=setup();s.context.busy=false;
  s.context.document.querySelector=()=>({});
  s.activity.textContent='正在录音';
  s.context.request=async()=>({live_action_trace:{request_id:'request-live',events:[
    {request_id:'request-live',event_type:'runtime_started',stage:'runtime',outcome:'running',display_message:'运行中'},
    {request_id:'request-live',event_type:'llm_call_finished',stage:'model',outcome:'success',display_message:'模型完成',metadata:{owner:'agent',index:1,duration_ms:123}},
  ],maintenance:{status:'running'}}});
  await s.context.setupActionTrace();
  assert.equal(s.list.children.length,2);assert.match(s.list.children[1].textContent,/123.00 ms/);
  assert.equal(s.nodes['#actionTraceSummary'].textContent,'行动记录 · 进行中');
  assert.equal(s.activity.textContent,'正在录音');
});

test('late HTTP snapshot cannot overwrite a newer live request',async()=>{
  const s=setup();s.context.busy=false;s.context.document.querySelector=()=>({});
  let resolve;s.context.request=()=>new Promise(r=>{resolve=r});
  const pending=s.context.setupActionTrace();
  s.emit('runtime_started','runtime','running','新请求开始',{request_id:'request-new'});
  resolve({live_action_trace:{request_id:'request-old',events:[]}});
  await pending;
  assert.deepEqual(s.list.children.map(n=>n.textContent),['新请求开始']);
});


test('existing completed runtime timeline is restored when the live cache is empty',async()=>{
  const s=setup();s.context.busy=false;s.context.document.querySelector=()=>({});
  s.context.request=async()=>({request_id:'prior',response_status:'succeeded',
    live_action_trace:{request_id:null,events:[]},runtime_metrics:{request_id:'prior',total_ms:42,
      finished_at:'2026-10-03T10:00:00Z',timeline:[
        {request_id:'prior',event_type:'tool_call_succeeded',stage:'tool_execution',outcome:'success',display_message:'已有工具结果'},
      ]}});
  await s.context.setupActionTrace();
  assert.equal(s.list.children[0].textContent,'已有工具结果');
  assert.equal(s.nodes['#actionTraceSummary'].textContent,'行动记录 · 已完成');
  assert.match(s.nodes['#actionRuntimeSummary'].textContent,/42.00 ms/);
});


for(const [status,title] of [['failed','行动记录 · 未完成'],['partial','行动记录 · 部分完成']]){
 test(`task ${status} is retained when its explanation succeeds`,()=>{
  const s=setup();s.context.beginActionTrace();
  s.emit('task_'+status,'task',status==='failed'?'failed':'warning','如实说明任务结果',{
   metadata:{task_status:status,response_status:'succeeded'},
  });
  s.emit('runtime_finished','runtime','success','运行已结束');
  s.context.endActionTraceFallback('回复已交付');
  assert.equal(s.nodes['#actionTraceSummary'].textContent,title);
 });
}


test('per-call tokens and known request total are accurate and replay-safe',()=>{
  const s=setup();s.context.beginActionTrace();
  const first={index:1,model:'synthetic-model',owner:'planner',stage:'planning',prompt_tokens:12,output_tokens:5,total_tokens:17,reply_kind:'process',process_text:'先核对日程 <script>never execute</script>'};
  s.emit('llm_call_finished','model','success','模型调用已结束',{metadata:first});
  s.emit('llm_call_finished','model','success','模型调用已结束',{metadata:first});
  assert.equal(s.nodes['#actionModelCalls'].children.length,1);
  assert.match(s.nodes['#actionTokenSummary'].textContent,/Token 合计 17.*输入 12.*输出 5.*1 次调用/);
  const card=s.nodes['#actionModelCalls'].children[0];
  assert.match(card.children[0].textContent,/synthetic-model.*planner/);
  assert.match(card.children[1].textContent,/Token 17.*输入 12.*输出 5/);
  assert.equal(card.children[2].children[1].textContent,first.process_text);
  assert.equal(card.children[2].children[1].innerHTML,undefined);
  s.emit('llm_call_finished','model','failed','模型调用失败',{metadata:{index:2,prompt_tokens:null,output_tokens:null,total_tokens:null}});
  assert.match(s.nodes['#actionTokenSummary'].textContent,/17（已知）.*1 次用量未返回/);
  assert.match(s.nodes['#actionModelCalls'].children[1].children[1].textContent,/Token 未返回/);
  assert.doesNotMatch(s.activity.textContent,/Token|never execute/);
});

test('final call remains counted but its body is not repeated; new requests clear old calls',()=>{
  const s=setup();s.context.beginActionTrace();
  s.emit('llm_call_finished','model','success','模型调用已结束',{metadata:{index:1,prompt_tokens:0,output_tokens:0,total_tokens:0,process_text:'最终回复正文'}});
  s.emit('llm_reply_committed','model','success','本次模型调用用于最终回复',{metadata:{index:1,final_reply:true}});
  const card=s.nodes['#actionModelCalls'].children[0];
  assert.equal(card.children.length,2);
  assert.match(card.children[0].textContent,/最终回复/);
  assert.match(s.nodes['#actionTokenSummary'].textContent,/Token 合计 0/);
  s.context.resetActionTrace('request-2');
  assert.equal(s.nodes['#actionModelCalls'].children.length,0);
  assert.match(s.nodes['#actionTokenSummary'].textContent,/等待模型返回用量/);
});

test('final runtime snapshot restores all call bodies and authoritative token totals',()=>{
  const s=setup();s.context.beginActionTrace();
  s.context.renderRuntimeMetrics({llm_calls:[
    {index:1,model:'first',prompt_tokens:10,output_tokens:2,total_tokens:12,reply_kind:'process',process_text:'公开的规划说明'},
    {index:2,model:'final',prompt_tokens:20,output_tokens:3,total_tokens:23,process_text:'不重复显示',final_reply:true},
  ],token_usage:{call_count:2,input_tokens:30,output_tokens:5,total_tokens:35}});
  assert.match(s.nodes['#actionTokenSummary'].textContent,/Token 合计 35.*输入 30.*输出 5.*2 次调用/);
  assert.equal(s.nodes['#actionModelCalls'].children[0].children[2].children[1].textContent,'公开的规划说明');
  assert.equal(s.nodes['#actionModelCalls'].children[1].children.length,2);
});


test('eight-way context breakdown survives replay and snapshots without altering actual tokens',()=>{
  const s=setup();s.context.beginActionTrace();
  const context_breakdown=Object.fromEntries(['system','persona','tool_schemas','timeline','tool_results','images','memory','cognition'].map(key=>[key,{chars:key==='images'?1200:400,estimated_tokens:key==='images'?null:100,...(key==='images'?{count:1,tokens:null}:{})}]));
  const call={index:1,prompt_tokens:900,output_tokens:20,total_tokens:920,context_breakdown};
  s.emit('llm_call_finished','model','success','done',{metadata:call});
  s.emit('llm_call_finished','model','success','done',{metadata:call});
  let table=s.nodes['#actionContextBreakdown'].children[1];
  assert.equal(table.children.length,8);
  assert.equal(table.children[0].children[0].textContent,'System');
  assert.match(table.children[0].children[1].textContent,/100 Token.*400 字符/);
  assert.match(table.children[5].children[1].textContent,/1 张次.*1,200.*图片 Token 未返回/);
  s.context.renderRuntimeMetrics({llm_calls:[call,{...call,index:2}],token_usage:{call_count:2,input_tokens:1800,output_tokens:40,total_tokens:1840}});
  table=s.nodes['#actionContextBreakdown'].children[1];
  assert.match(table.children[0].children[1].textContent,/200 Token.*800 字符/);
  assert.match(s.nodes['#actionTokenSummary'].textContent,/输入 1,800/);
  assert.match(s.nodes['#actionModelCalls'].children[0].children[2].textContent,/非 API 实际分项/);
  s.emit('llm_call_finished','model','success','known image tokens',{metadata:{...call,index:2,context_breakdown:{...context_breakdown,images:{chars:1200,count:1,tokens:7}}}});
  assert.match(s.nodes['#actionContextBreakdown'].children[1].children[5].children[1].textContent,/图片 Token 7（已知部分）/);
  s.emit('llm_call_finished','model','success','reported zero',{metadata:{...call,index:1,context_breakdown:{...context_breakdown,images:{chars:261216,count:8,tokens:0}}}});
  assert.match(s.nodes['#actionModelCalls'].children[0].children[3].children[5].children[1].textContent,/8 张次.*261,216.*图片 Token 0（接口报告）/);
  s.context.resetActionTrace('next');assert.equal(s.nodes['#actionContextBreakdown'].children.length,0);
});


test('approved process replies render on chat even for an observing idle main window, once per sequence',()=>{
  const s=setup(),chat=[];s.context.addMessage=(...args)=>chat.push(args);
  s.context.busy=false;s.context.beginActionTrace();
  const event={request_id:'request-1',sequence:1,content:'我先核对一下时间。',emitted_at:'2026-10-13T02:00:00Z'};
  s.context.renderInterimReply(event);s.context.renderInterimReply(event);
  assert.equal(chat.length,1);assert.equal(chat[0][0],'assistant');assert.equal(chat[0][2],'interim');
  s.context.renderInterimReply({...event,request_id:'old'});assert.equal(chat.length,1);
  s.emit('runtime_finished','runtime','success','done');s.context.renderInterimReply({...event,sequence:2});assert.equal(chat.length,1);
  s.context.resetActionTrace('request-2');s.context.renderInterimReply({...event,request_id:'request-2'});assert.equal(chat.length,2);
});

test('the engineering monitor never creates chat bubbles from process events',()=>{
  const s=setup(),chat=[];s.context.addMessage=(...args)=>chat.push(args);
  s.context.document.body={dataset:{traceMonitor:'true'}};s.context.beginActionTrace();
  s.context.renderInterimReply({request_id:'request-1',sequence:1,content:'natural process'});
  assert.equal(chat.length,0);
});
