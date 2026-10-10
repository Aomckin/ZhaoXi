
const FRONTEND_BUILD_ID='v1.4.8-reliability-20261010',FRONTEND_LOADED_AT=new Date().toISOString();
const shellInertNodes=new Map();
const $=s=>{const found=document.querySelector(s);if(found)return found;
  if(!shellInertNodes.has(s)){const node=document.createElement('div');node.value='';node.checked=false;shellInertNodes.set(s,node)}
  return shellInertNodes.get(s)}, messages=$('#messages'), input=$('#input'), send=$('#send'), mic=$('#mic'), activity=$('#activity'), debug=$('#debug'), voiceReview=$('#voiceReview'), voiceText=$('#voiceText');let busy=false,voiceEnabled=false,voiceRecording=false,speechActive=false,normalRegenerationEnabled=false;
let activeTraceId=null,traceTerminated=false,traceRevision=0;
const retiredTraceIds=new Set();
function resetActionTrace(requestId){
  if(activeTraceId&&activeTraceId!==requestId){retiredTraceIds.add(activeTraceId);if(retiredTraceIds.size>20)retiredTraceIds.delete(retiredTraceIds.values().next().value)}
  activeTraceId=requestId;traceTerminated=false;traceRevision++;
  $('#actionTraceSummary').textContent='行动记录 · 进行中';$('#actionTraceEvents').replaceChildren();$('#actionTraceDebug').textContent='';
  if($('#actionMaintenance'))$('#actionMaintenance').textContent='';if($('#actionRuntimeSummary'))$('#actionRuntimeSummary').textContent='';if($('#actionPlannerStatus'))$('#actionPlannerStatus').textContent='Planner：本轮尚未启用';
}
function beginActionTrace(){const id=crypto.randomUUID();resetActionTrace(id);activity.textContent='理解 · 耳朵竖起来了，先听清你的意思…';return id}
const actionTraceMonitor=()=>document.body?.dataset.traceMonitor==='true';
async function setupActionTrace(){
  if(!document.querySelector('#actionTrace')||busy)return;
  const revision=traceRevision;
  try{
    const data=await request('/api/debug/runtime');
    if(busy||revision!==traceRevision)return; // A newer live event wins over an older HTTP response.
    const live=data.live_action_trace,metrics=data.runtime_metrics||{};
    const snapshot=live?.request_id?live:{request_id:data.request_id||metrics.request_id,events:metrics.timeline||[]};
    if(!snapshot.request_id){$('#actionTraceSummary').textContent='行动记录 · 暂无请求';return}
    if(retiredTraceIds.has(snapshot.request_id))return;
    resetActionTrace(snapshot.request_id);
    for(const event of snapshot.events||[])renderAgentEvent(event,true);
    if(!live?.request_id){renderRuntimeMetrics(metrics);if(metrics.finished_at||['succeeded','failed'].includes(data.response_status))endActionTraceFallback(data.response_status==='failed'?'本次回复未完成':'本次任务已完成',data.response_status==='failed')}
    if(snapshot.maintenance)$('#actionMaintenance').textContent='后台维护：'+snapshot.maintenance.status;
  }catch(e){if(revision===traceRevision&&!activeTraceId)$('#actionTraceSummary').textContent='行动记录 · 读取失败，可刷新重试'}
}
function renderInterimReply(event){
  if(!busy||!event||event.request_id!==activeTraceId||!event.content)return;
  addMessage('assistant',event.content,'interim',[],event.emitted_at);
  activity.textContent='行动 · 正在继续处理…';
}
function appendTraceEvent(message,outcome){const row=document.createElement('li');row.className=outcome||'info';row.textContent=message;$('#actionTraceEvents').append(row)}
function endActionTraceFallback(message,failed=false){if(traceTerminated)return;appendTraceEvent(message,failed?'failed':'success');$('#actionTraceSummary').textContent=failed?'行动记录 · 未完成':'行动记录 · 已完成';traceTerminated=true}
function traceActivity(event){
  const stage=event.stage||'',type=event.event_type||'',outcome=event.outcome||'';
  if(stage==='memory_search')return outcome==='warning'?'检索 · 这条线索没翻到，继续找别的…':'检索 · 顺着线索嗅一嗅…';
  if(stage==='tool_execution')return type==='tool_call_waiting_permission'?'行动 · 等你点头，我就接着动爪…':outcome==='failed'?'行动 · 这一步卡住了，我再想想…':outcome==='success'?'行动 · 这一爪办好啦，继续往下…':'行动 · 伸爪处理这件事…';
  if(stage==='response_generation'||stage==='recovery')return outcome==='failed'?'整理 · 回复卡住了，我会跟你说清楚…':'整理 · 把结果叼回来理顺…';
  if(stage==='model'&&outcome==='failed')return '整理 · 这回有点卡住了，我会说明白…';
  return '理解 · 耳朵竖起来了，先听清你的意思…';
}
function acknowledgeReply(data,renderStartedAt=null){
  if(!data.request_id||!data.message_id)return;
  const send=()=>{const elapsed=renderStartedAt===null?null:Math.max(0,performance.now()-renderStartedAt);return request('/api/chat/rendered',{method:'POST',body:JSON.stringify({request_id:data.request_id,message_id:data.message_id,first_render_ms:elapsed,fully_rendered_ms:elapsed})}).catch(()=>{})};
  if(typeof requestAnimationFrame==='function')requestAnimationFrame(()=>requestAnimationFrame(send));else void send();
}
function renderMemoryCandidates(items){
  const node=$('#runtimeMemoryCandidates');if(!node)return;
  if(!items?.length){node.textContent='本轮没有 Memory 候选';return}
  const score=value=>Number.isFinite(value)?Number(value).toFixed(4):'—';
  node.textContent=items.map(item=>[
    `#${item.rank} · ${item.kind||'memory'} · ${item.status||'unknown'}${item.cluster?` · ${item.cluster}`:''}`,
    item.content||'（无正文）',
    `Final ${score(item.final_score)} · Context ${score(item.contextual_relevance)} · Text ${score(item.text_score)} · Semantic ${score(item.semantic_score)}`,
    `Graph ${score(item.graph_score)} · Time ${score(item.time_score)} · Activation ${score(item.activation_score)} · Importance ${score(item.importance_score)}`,
    `Why: ${(item.why_selected||[]).join('、')||'—'}`,
  ].join('\n')).join('\n\n');
}
function renderRuntimeMetrics(m){
  const node=$('#actionRuntimeSummary');if(!node)return;
  const ms=value=>Number.isFinite(value)?`${value.toFixed(2)} ms`:'未记录';
  const stages={routing_ms:'路由',memory_retrieval_ms:'记忆检索',decision_ms:'决策',planner_ms:'规划',workflow_ms:'工作流',tool_ms_total:'工具合计',response_generation_ms:'回复生成',auto_memory_ms:'记忆整理',current_cognition_ms:'近期状态',other_ms:'其他'};
  const lane={fast:'FAST / 轻量对话',standard:'STANDARD / 标准',deep:'DEEP / 深度'}[m.runtime_lane]||m.runtime_lane||'未标记';
  node.textContent=[`运行通道 ${lane} · 来源 ${m.route_source||'未记录'}`,
    `前台模型 ${m.foreground_llm_calls||0} · 后台模型 ${m.background_llm_calls||0} · Router ${m.router_llm_calls||0} · Agent ${m.agent_llm_calls||0} · Planner ${m.planner_llm_calls||0}`,
    `记忆检索 ${m.memory_search_count||0} · 工具轮次 ${m.tool_rounds||0} · 目录检查 ${m.catalog_inspections||0}`,
    ...[m.fast_gate_reason?`Fast Gate：${m.fast_gate_reason}`:null,m.escalation_reason?`升级：${m.escalation_reason}`:null,m.extra_round_reason?`额外轮次：${m.extra_round_reason}`:null].filter(Boolean),
    ...(m.fast_escalation_count?[`FAST → STANDARD ${m.fast_escalation_count} 次 · 能力 ${m.fast_escalation_kind||'未记录'}`]:[]),
    ...(m.fast_gate_version?[`Fast Gate ${m.fast_gate_version} · ${m.fast_gate_decision} · FAST 分数 ${m.fast_score} · HEAVY 分数 ${m.heavy_score}`,
      `FAST 依据：${(m.fast_positive_evidence||[]).join('、')||'无'}`,
      `HEAVY 依据：${(m.heavy_evidence||[]).join('、')||'无'}`,
      ...Object.entries(m.fast_gate_signals||{}).map(([key,value])=>`信号 ${key}：${JSON.stringify(value)}`),
      `Router required ${!!m.router_required} · override ${!!m.router_override} · final ${m.router_final_lane||'—'} · 回到 FAST ${m.router_to_fast_count||0}`]:[]),
    `总耗时 ${ms(m.total_ms)} · 首次回复 ${ms(m.ttfr_ms)}`,
    ...Object.entries(stages).map(([key,label])=>`${label}：${ms(m[key])}`),
    ...(m.llm_calls||[]).map(c=>`模型 #${c.index} · ${c.owner} / ${c.stage}：${ms(c.duration_ms)}`),
    ...(m.tool_calls||[]).map(c=>`工具 ${c.tool_name}：${ms(c.duration_ms)}`)].join('\n');
  const planner=$('#actionPlannerStatus');if(planner)planner.textContent=m.planner_used?'Planner：本轮已启用':'Planner：本轮未启用（普通 Agent 执行）';
}
function renderAgentEvent(event,replay=false){
  if(!event?.request_id)return;
  if(event.request_id!==activeTraceId){
    if(replay||retiredTraceIds.has(event.request_id)||busy&&!actionTraceMonitor())return;
    if(activeTraceId&&!['runtime_started','request_started'].includes(event.event_type))return;
    resetActionTrace(event.request_id);
  }
  traceRevision++;
  const type=event.event_type||'',outcome=event.outcome||'info';
  $('#actionTraceDebug').textContent+=`${event.timestamp||''} ${type} ${JSON.stringify(event)}\n`;
  if(event.stage==='context')return;
  const meta=event.metadata||{};
  const duration=Number.isFinite(meta.duration_ms)?` · ${meta.duration_ms.toFixed(2)} ms`:'';
  const identity=type.startsWith('llm_call_')?` · ${meta.owner||'agent'} #${meta.index||''}`:event.tool_name?` · ${event.tool_name}`:'';
  appendTraceEvent((event.display_message||type)+identity+duration,outcome);
  if(event.stage==='planner'){
    const planner=$('#actionPlannerStatus');if(planner)planner.textContent='Planner：'+event.display_message;
    if(type==='planner_plan_created'||type==='planner_replanned')for(const step of meta.steps||[])appendTraceEvent(step.description+' · '+step.status,'info');
  }
  if(meta.runtime_metrics)renderRuntimeMetrics(meta.runtime_metrics);
  if(event.stage==='task'||type.startsWith('task_')){
    const state=event.metadata||{};
    if(state.response_status==='failed'){
      $('#actionTraceSummary').textContent='行动记录 · 回复未完成';traceTerminated=true;
    }else if(state.task_status==='failed'){
      $('#actionTraceSummary').textContent='行动记录 · 未完成';traceTerminated=true;
    }else if(state.task_status==='partial'){
      $('#actionTraceSummary').textContent='行动记录 · 部分完成';traceTerminated=true;
    }else if(state.task_status==='waiting_for_permission'){
      $('#actionTraceSummary').textContent='行动记录 · 等待确认';traceTerminated=true;
    }
    if(!replay&&busy)activity.textContent='整理 · 快弄好啦…';
  }else if(!replay&&busy&&event.stage!=='token_budget'&&event.stage!=='context')activity.textContent=traceActivity(event);
  if(type==='runtime_finished'&&!traceTerminated){$('#actionTraceSummary').textContent=outcome==='failed'?'行动记录 · 未完成':'行动记录 · 已完成';traceTerminated=true;}
}
let activityHintTimer=null;
function showActivityHint(text){
  clearTimeout(activityHintTimer);
  activity.textContent=text;
  activityHintTimer=setTimeout(()=>{
    // A newer recording/thinking status must not be erased by an old hint.
    if(activity.textContent===text)activity.textContent='';
    activityHintTimer=null;
  },3000);
}
function escapeHtml(v){const d=document.createElement('div');d.textContent=v??'';return d.innerHTML}
function markdown(v){return escapeHtml(v).replace(/\*\*(.+?)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\n/g,'<br>')}
// Split presentation only: keep the original reply intact in Core/session history.
let displayTimezone='Asia/Shanghai';
function formatTime(value){return value?new Intl.DateTimeFormat('zh-CN',{timeZone:displayTimezone,year:'numeric',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value)):''}
function addMessageBubble(role,content,kind='',images=[],timestamp=null,group=null){ $('#empty')?.remove();const row=document.createElement('div'),imageOnly=images.length>0&&!String(content||'').trim()&&kind!=='system';row.className=`row ${role} ${kind}${imageOnly?' image-only-row':''}${role==='assistant'&&kind!=='system'&&isActionSegment(content)?' stage-direction':''}`;row.innerHTML=imageOnly?`<div class="image-only"><time class="message-time">${escapeHtml(formatTime(timestamp||new Date().toISOString()))}</time></div>`:`<div class="bubble">${kind==='system'?'<div class="badge">系统消息</div>':''}${markdown(content)}<time class="message-time">${escapeHtml(formatTime(timestamp||new Date().toISOString()))}</time></div>`;const container=row.querySelector(imageOnly?'.image-only':'.bubble');if(!imageOnly&&role==='assistant'&&kind!=='system'&&voiceEnabled&&String(content||'').trim()){const b=document.createElement('button');b.className='speak';b.textContent='朗读';b.onclick=()=>speakText(content,b);container.append(b)}for(const src of images){if(!/^data:image\/(png|jpeg|webp);base64,/.test(src)&&!/^\/api\/expression\/emoji\/[A-Za-z0-9_-]+$/.test(src))continue;const historyImage=historyLoading,image=document.createElement('img');image.className='attachment';image.alt=role==='user'?'用户发送的图片':'朝汐发送的图片';image.src=src;image.onload=()=>{if(!historyImage)messages.scrollTop=messages.scrollHeight};image.onclick=()=>window.open(src,'_blank','noopener');container.insertBefore(image,container.querySelector('time'))}if(group){if(!group.element){group.element=document.createElement('div');group.element.className='message-group';messages.append(group.element)}group.element.append(row)}else messages.append(row);messages.scrollTop=messages.scrollHeight;return row }
function attachRegenerate(group,messageId,debugOnly=true){
  if(!group?.element||!messageId)return;
  const button=document.createElement('button');button.type='button';button.className='regenerate';button.textContent='🔄';button.title='重新生成这条回复';button.setAttribute('aria-label','重新生成这条回复');
  if(debugOnly){button.classList.add('normal-regenerate');button.hidden=!normalRegenerationEnabled}
  button.onclick=()=>regenerateReply(messageId,group.element);group.element.append(button);
}
async function regenerateReply(messageId,oldGroup){
  if(busy||pendingInput.length){showActivityHint('请等当前消息处理完成');return}
  busy=true;$('#clear').disabled=true;document.querySelectorAll('.regenerate').forEach(item=>item.disabled=true);activity.textContent='正在重新生成…';const requestId=beginActionTrace();
  try{
    const data=await request('/api/chat/regenerate',{method:'POST',body:JSON.stringify({message_id:messageId,request_id:requestId})}),renderStartedAt=performance.now();
    oldGroup.remove();await (data.output_messages?.length?renderResponse(data):sendReply(data.content,data.timestamp,data.message_id,true));
    acknowledgeReply(data,renderStartedAt);
    if(data.permission)permissionCard(data.permission);
    debug.textContent=JSON.stringify(data.activity,null,2);void setupDiagnostics();endActionTraceFallback('本次任务已完成');
  }catch(e){showActivityHint(e.message);endActionTraceFallback(e.message,true)}
  finally{document.querySelectorAll('.regenerate').forEach(item=>item.disabled=false);finishTurn();input.focus()}
}
function permissionCard(p){const box=document.createElement('div');box.className='permission';box.innerHTML=`<h3>朝汐想执行</h3><div>${escapeHtml(p.action)}</div><p>权限：${escapeHtml(p.permission.toUpperCase())}</p><p>范围：${escapeHtml(p.resource_scope)}</p><div class="actions"><button class="allow">允许</button><button class="deny">拒绝</button></div>`;messages.append(box);box.querySelector('.allow').onclick=()=>resolve(p.confirmation_id,'approve',box);box.querySelector('.deny').onclick=()=>resolve(p.confirmation_id,'deny',box);messages.scrollTop=messages.scrollHeight}
async function request(url,options={}){const r=await fetch(url,{headers:{'Content-Type':'application/json'},...options});const data=await r.json();if(!r.ok)throw new Error(data.detail||'请求失败');return data}
async function acknowledgeEmojiTrace(traceId,rendered){if(!traceId)return;try{await request('/api/debug/emoji/trace/ack',{method:'POST',body:JSON.stringify({trace_id:traceId,received:true,rendered:!!rendered})})}catch{}}
let INPUT_MERGE_MS=15000;
let pendingInput=[], inputTimer=null;
function addRetryableError(content,requestId){
  const rows=addMessage('assistant',content);
  const group={element:rows[0]?.parentElement};
  void request('/api/session').then(data=>{
    const target=[...(data.messages||[])].reverse().find(item=>item.role==='user'&&item.request_id===requestId);
    if(target?.message_id)attachRegenerate(group,target.message_id,false);
  }).catch(()=>{});
}
function recallInput(item){
  const index=pendingInput.indexOf(item);if(index<0)return;
  pendingInput.splice(index,1);item.row.remove();
  if(!pendingInput.length){clearTimeout(inputTimer);inputTimer=null}
  $('#clear').disabled=busy||imagesReading||pendingInput.length>0;
  if(!busy)activity.textContent=pendingInput.length?'等待合并连续消息…':'';
}
let draftImages=[], imagesReading=false;
const MAX_IMAGES=20, MAX_IMAGE_BYTES=100*1024*1024;
function renderImagePreview(){
  const box=$('#imagePreview');box.replaceChildren();
  draftImages.forEach((src,index)=>{
    const figure=document.createElement('figure'),image=document.createElement('img'),remove=document.createElement('button');
    image.src=src;image.alt=`待发送图片 ${index+1}`;remove.textContent='×';remove.setAttribute('aria-label',`移除图片 ${index+1}`);
    remove.onclick=()=>{draftImages.splice(index,1);renderImagePreview()};figure.append(image,remove);box.append(figure);
  });
}
async function selectImages(files){
  if(imagesReading)return;
  const selected=Array.from(files);
  if(draftImages.length+selected.length>MAX_IMAGES){showActivityHint('每次最多20张图片');return}
  if(selected.some(f=>!['image/png','image/jpeg','image/webp'].includes(f.type)||f.size>MAX_IMAGE_BYTES)){
    showActivityHint('请选择 PNG、JPEG、WebP 图片，每张不超过100MB');return;
  }
  imagesReading=true;$('#clear').disabled=true;send.disabled=true;$('#attachImage').disabled=true;
  try{
    const loaded=[];
    for(const file of selected)loaded.push(await new Promise((resolve,reject)=>{
      const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('图片读取失败，请重新选择'));reader.readAsDataURL(file);
    }));
    draftImages.push(...loaded);renderImagePreview();
  }catch(e){showActivityHint(e.message)}
  finally{imagesReading=false;send.disabled=false;$('#attachImage').disabled=false;$('#clear').disabled=busy||pendingInput.length>0}
}
function submit(){
  const text=input.value.trim();if(imagesReading||(!text&&!draftImages.length))return;
  const queuedImages=pendingInput.reduce((sum,item)=>sum+item.images.length,0);
  if(queuedImages+draftImages.length>MAX_IMAGES){showActivityHint('本次合并消息最多20张图片，请等待发送后再添加');return}
  if(pendingInput.map(item=>item.text).concat(text).join('\n\n').length>20000){showActivityHint('本次合并文字不能超过20000字，请等待发送后再补充');return}
  const images=draftImages;draftImages=[];renderImagePreview();
  input.value='';
  const row=addMessage('user',text,'',images)[0];
  const recall=document.createElement('button');recall.className='recall';recall.textContent='撤回';
  recall.type='button';recall.setAttribute('aria-label','撤回这条待发送消息');
  const item={text,images,row,recall,timestamp:new Date().toISOString()};pendingInput.push(item);
  recall.onclick=()=>recallInput(item);row.querySelector('.bubble,.image-only').append(recall);
  $('#clear').disabled=true;
  clearTimeout(inputTimer);
  inputTimer=setTimeout(()=>{inputTimer=null;flushInput()},INPUT_MERGE_MS);
  if(!busy)activity.textContent='等待合并连续消息…';
  input.focus();
}
function finishTurn(){
  busy=false;send.disabled=imagesReading;
  $('#clear').disabled=imagesReading||pendingInput.length>0;
  activity.textContent=pendingInput.length?'等待处理连续消息…':'';
  if(typeof setupRecentContextBoard==='function')void setupRecentContextBoard();
  if(pendingInput.length&&inputTimer===null)void flushInput();
  else if(!pendingInput.length)void drainDeliveries();
}
async function flushInput(){
  if(busy||!pendingInput.length||inputTimer!==null)return;
  const text=pendingInput.map(item=>item.text).filter(Boolean).join('\n\n');
  const images=pendingInput.flatMap(item=>item.images);
  const display_parts=pendingInput.map(item=>({text:item.text,image_count:item.images.length,timestamp:item.timestamp}));
  pendingInput.forEach(item=>item.recall.remove());pendingInput=[];
  busy=true;$('#clear').disabled=true;activity.textContent='正在处理…';const requestId=beginActionTrace();
  try{
    const data=await request('/api/chat',{method:'POST',body:JSON.stringify({message:text,images,display_parts,request_id:requestId})}),renderStartedAt=performance.now();
    await (data.output_messages?.length?renderResponse(data):sendReply(data.content,data.timestamp,data.message_id));
    acknowledgeReply(data,renderStartedAt);
    if(data.permission)permissionCard(data.permission);
    debug.textContent=JSON.stringify(data.activity,null,2);void setupDiagnostics();endActionTraceFallback('本次任务已完成');
  }catch(e){endActionTraceFallback(e.message,true);addRetryableError(e.message,requestId)}
  finally{finishTurn();input.focus()}
}
async function resolve(id,action,box){if(busy)return;busy=true;$('#clear').disabled=true;box.querySelectorAll('button').forEach(b=>b.disabled=true);activity.textContent=action==='approve'?'正在执行已允许的操作…':'正在处理拒绝…';const requestId=beginActionTrace();try{const data=await request(`/api/permission/${id}/${action}?request_id=${encodeURIComponent(requestId)}`,{method:'POST'}),renderStartedAt=performance.now();box.remove();await (data.output_messages?.length?renderResponse(data):sendReply(data.content,data.timestamp,data.message_id));acknowledgeReply(data,renderStartedAt);if(data.permission)permissionCard(data.permission);debug.textContent=JSON.stringify(data.activity,null,2);void setupDiagnostics();endActionTraceFallback('本次任务已完成')}catch(e){endActionTraceFallback(e.message,true);addMessage('assistant',e.message)}finally{finishTurn()}}
async function setupVoice(){try{const v=await request('/api/voice/status');voiceEnabled=!!v.enabled;mic.style.display=voiceEnabled?'block':'none'}catch(e){voiceEnabled=false}}
async function toggleVoice(){if(busy)return;mic.disabled=true;try{if(!voiceRecording){await request('/api/voice/record/start',{method:'POST'});voiceRecording=true;mic.classList.add('recording');mic.textContent='■';activity.textContent='正在录音… 点击方块停止'}else{activity.textContent='正在识别…';const data=await request('/api/voice/record/stop',{method:'POST'});voiceRecording=false;mic.classList.remove('recording');mic.textContent='●';voiceText.value=data.text||'';voiceReview.style.display='block';activity.textContent='请检查识别结果'}}catch(e){voiceRecording=false;mic.classList.remove('recording');mic.textContent='●';showActivityHint(e.message)}finally{mic.disabled=false}}
async function confirmVoice(){const text=voiceText.value.trim();if(!text||busy)return;busy=true;$('#clear').disabled=true;voiceReview.style.display='none';addMessage('user',text);activity.textContent='正在思考…';try{const data=await request('/api/voice/transcript/confirm',{method:'POST',body:JSON.stringify({text})}),renderStartedAt=performance.now();await (data.output_messages?.length?renderResponse(data):sendReply(data.content,data.timestamp,data.message_id));acknowledgeReply(data,renderStartedAt);if(data.permission)permissionCard(data.permission);debug.textContent=JSON.stringify(data.activity,null,2);void setupDiagnostics()}catch(e){addMessage('assistant',e.message)}finally{finishTurn();input.focus()}}
async function cancelVoice(){await request('/api/voice/cancel',{method:'POST'});voiceRecording=false;mic.classList.remove('recording');mic.textContent='●';voiceReview.style.display='none';voiceText.value='';activity.textContent=''}
async function speakText(text,button){try{if(speechActive){await request('/api/voice/speak/stop',{method:'POST'});speechActive=false;button.textContent='朗读'}else{await request('/api/voice/speak',{method:'POST',body:JSON.stringify({text})});speechActive=true;button.textContent='停止朗读'}}catch(e){showActivityHint(e.message)}}
$('#attachImage').onclick=()=>$('#imageFiles').click();
$('#imageFiles').onchange=async e=>{await selectImages(e.target.files);e.target.value=''};
input.addEventListener('paste',e=>{const files=Array.from(e.clipboardData?.files||[]);if(files.length){e.preventDefault();void selectImages(files)}});
send.onclick=submit;input.onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();submit()}};input.oninput=()=>{input.style.height='auto';input.style.height=Math.min(input.scrollHeight,150)+'px'};
mic.onclick=toggleVoice;$('#voiceConfirm').onclick=confirmVoice;$('#voiceCancel').onclick=cancelVoice;$('#voiceRetry').onclick=async()=>{await cancelVoice();await toggleVoice()};
$('#clear').onclick=async()=>{if(busy||imagesReading||pendingInput.length)return;await request('/api/session',{method:'DELETE'});draftImages=[];renderImagePreview();messages.innerHTML='<div id="empty" class="empty"><b>会话已清空。</b>重新开始吧。</div>';debug.textContent='Session cleared'};
const seenDeliveries=new Set(), deliveryQueue=[];let historyReady=false;
async function restore(){try{const data=await request('/api/session');displayTimezone=data.timezone||displayTimezone;for(const m of data.messages){if([...messages.querySelectorAll('[data-message-id]')].some(n=>n.dataset.messageId===m.message_id))continue;if(m.delivery_id)seenDeliveries.add(m.delivery_id);if(m.kind==='system')continue;if(m.role==='user'&&m.display_parts?.length){let offset=0;for(const p of m.display_parts){addMessage('user',p.text,'',(m.images||[]).slice(offset,offset+p.image_count),p.timestamp,m.message_id);offset+=p.image_count}}else await renderMessage(m)}const p=await request('/api/proactive');p.deliveries.filter(d=>['delivered','acknowledged'].includes(d.status)).reverse().forEach(d=>showNotice(d))}catch(e){$('#connection').textContent='Core 暂时不可用'}finally{historyReady=true;void drainDeliveries()}}
let historyCursor=null, historyLoading=false;
function historyButton(){
  if(document.getElementById('olderHistory'))return;
  const button=document.createElement('button');button.id='olderHistory';button.textContent='加载更早的消息';
  button.onclick=loadOlderHistory;messages.prepend(button);
}
async function loadOlderHistory(){
  if(historyLoading||busy)return;
  const button=document.getElementById('olderHistory');if(!button)return;
  historyLoading=true;button.disabled=true;
  const height=messages.scrollHeight,top=messages.scrollTop,existing=new Set(messages.children);
  try{
    const data=await request('/api/session/history'+(historyCursor?'?before='+encodeURIComponent(historyCursor):''));
    currentReplyDisplayGroup=null;
    for(const message of data.messages){
      if([...messages.querySelectorAll('[data-message-id]')].some(n=>n.dataset.messageId===message.message_id))continue;
      await renderMessage({...message,regeneratable:false});
    }
    const fragment=document.createDocumentFragment();
    for(const node of [...messages.children])if(!existing.has(node))fragment.append(node);
    button.after(fragment);currentReplyDisplayGroup=null;
    historyCursor=data.before;if(!data.has_more)button.remove();
    messages.scrollTop=top+messages.scrollHeight-height;
  }catch(error){showActivityHint('历史消息暂时无法加载：'+error.message)}finally{historyLoading=false;button.disabled=false}
}
async function openReply(id){
  if(busy){showActivityHint('当前回复结束后打开消息…');setTimeout(()=>openReply(id),500);return}
  if(!historyReady){setTimeout(()=>openReply(id),100);return}
  let target=[...messages.querySelectorAll('[data-message-id]')].find(n=>n.dataset.messageId===id);
  if(!target){await restore();target=[...messages.querySelectorAll('[data-message-id]')].find(n=>n.dataset.messageId===id)}
  while(!target&&document.getElementById('olderHistory')){
    const cursor=historyCursor;await loadOlderHistory();
    target=[...messages.querySelectorAll('[data-message-id]')].find(n=>n.dataset.messageId===id);
    if(cursor===historyCursor)break;
  }
  if(target)target.scrollIntoView({block:'center',behavior:'smooth'});
  else showActivityHint('这条回复当前不可用，可查看历史消息。');
}
function interactionBadgeView(state){
  if(state==='ACTIVE')return {label:'活跃 · 还在聊呢',className:'active',title:'当前对话仍在持续'};
  if(state==='SEMI_ACTIVE')return {label:'半活跃 · 就在附近',className:'semi-active',title:'朝汐醒着，在附近'};
  if(state==='IDLE')return {label:'休憩 · 安静待着',className:'idle',title:'朝汐安静待着'};
  if(state==='SLEEP')return {label:'睡眠 · 安静休息',className:'idle',title:'朝汐休息中'};
  if(state==='AWAY')return {label:'离开 · 暂时不在',className:'away',title:'暂时不在'};
  return null;
}
function renderInteractionBadge(presence){
  const badge=$('#interactionBadge'),view=interactionBadgeView(presence?.interaction_state);
  const anchor=document.querySelector('.character-anchor');if(anchor)anchor.dataset.state=view?String(presence.interaction_state).toLowerCase():'unknown';
  if(typeof window!=='undefined'&&typeof window.setCharacterAvatarState==='function')window.setCharacterAvatarState(presence?.interaction_state);
  if(!view){badge.hidden=true;badge.className='interaction-badge';badge.textContent='';badge.removeAttribute('title');badge.removeAttribute('aria-label');return}
  badge.hidden=false;badge.className=`interaction-badge ${view.className}`;badge.textContent=view.label;badge.title=view.title;badge.setAttribute('aria-label',`当前互动状态：${view.label}`);
}
let setupNoticeShown=false;
async function setupDiagnostics(){try{const data=await request('/api/diagnostics');debug.textContent=JSON.stringify(data,null,2);renderInteractionBadge(data.presence);renderPresenceActivity(data.presence_activity);renderDebugPresenceControls(data.presence);if(data.startup&&data.startup.status!=='ready'){const model=data.startup.checks?.model||{},needsConfiguration=data.startup.status==='needs_configuration';$('#connection').textContent=needsConfiguration?'需要完成首次配置':'Core 启动失败';input.placeholder=needsConfiguration?'完成配置后即可和朝汐对话':'请处理启动错误后重启 Core';if(!setupNoticeShown){addMessage('assistant',needsConfiguration?`朝汐尚未完成启动配置。${model.action||'请运行 python main.py --doctor 查看具体问题。'}`:`Core 启动失败：${data.startup.checks?.runtime?.message||'请查看启动诊断。'}`);setupNoticeShown=true}}else{$('#connection').textContent='本地 Core 已连接'}}catch(e){renderInteractionBadge(null);$('#connection').textContent='启动诊断不可用'}if(document.querySelector("#runtimeDebugPanel")?.open)await refreshRuntimeDebug()}
const agendaTypeNames={event:'约定',window:'时间窗口',deadline:'截止',focus:'主线',expectation:'期待'};
const cognitionSectionNames={active_thread:'还挂着',recent_change:'刚变化',unresolved:'需要留意'};
function deskText(tag,value,className=''){const node=document.createElement(tag);node.textContent=value;if(className)node.className=className;return node}
function deskDateParts(value){const parts=new Intl.DateTimeFormat('en-GB',{timeZone:displayTimezone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(value));return Object.fromEntries(parts.map(part=>[part.type,part.value]))}
function deskDateKey(value){const part=deskDateParts(value);return `${part.year}-${part.month}-${part.day}`}
function deskDayTitle(key,today){const day=new Date(`${key}T12:00:00Z`),tomorrow=new Date(`${today}T12:00:00Z`);tomorrow.setUTCDate(tomorrow.getUTCDate()+1);const prefix=key===today?'今天 · ':key===tomorrow.toISOString().slice(0,10)?'明天 · ':'';return `${prefix}${Number(key.slice(5,7))}/${key.slice(8)} 周${'日一二三四五六'[day.getUTCDay()]}`}
function agendaWhen(item){return item.due_at||item.start_at||null}
function agendaDateKey(item,today){if(item.type==='focus'&&!agendaWhen(item))return item.scope==='today'?(item.created_at?deskDateKey(item.created_at):today):'undated';const when=agendaWhen(item);return when?deskDateKey(when):null}
function agendaMarker(){return deskText('div','现在','agenda-now')}
function agendaTitleKey(title){return String(title||'').replace(/[（(][^）)]{1,16}[）)]/g,'').replace(/^作为[^\s]{1,8}参加\s*/,'').replace(/^参加\s*/,'').replace(/[\s，,。.!！?？]/g,'').toLowerCase()}
function linkedAgendaWindow(event,windowItem){return event.type==='event'&&windowItem.type==='window'&&!!event.start_at&&!!windowItem.start_at&&new Date(event.start_at).getTime()===new Date(windowItem.start_at).getTime()&&agendaTitleKey(event.title).length>=5&&agendaTitleKey(event.title)===agendaTitleKey(windowItem.title)}
function renderAgendaTimeline(items,error,now=new Date()){
  const box=$('#agendaTimeline');box.replaceChildren();
  if(error||!Array.isArray(items)){box.append(deskText('p','日程暂时无法读取，请稍后再试。','desk-empty'));return}
  const today=deskDateKey(now),cutoff=new Date(now.getTime()-2*86400000);
  const visible=items.filter(item=>!['cancelled','rescheduled'].includes(item.status)&&(!['done','missed'].includes(item.status)||new Date(item.end_at||agendaWhen(item)||item.updated_at||item.created_at||0)>=cutoff));
  if(!visible.length){box.append(deskText('p','眼下没有日程。','desk-empty'));return}
  const groups=new Map();for(const item of visible){const key=agendaDateKey(item,today)||'undated';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item)}
  for(const key of [...groups.keys()].sort()){
    const group=document.createElement('section');group.className='agenda-day';group.append(deskText('h4',key==='undated'?'近期':deskDayTitle(key,today),'agenda-date'));
    const dayItems=groups.get(key),focus=dayItems.filter(item=>item.type==='focus'),timed=dayItems.filter(item=>item.type!=='focus').sort((a,b)=>new Date(agendaWhen(a)||0)-new Date(agendaWhen(b)||0)||(a.type===b.type?0:a.type==='event'?-1:b.type==='event'?1:0));
    for(const item of focus){const row=document.createElement('article');row.className='agenda-focus';row.append(deskText('span','■ '+(item.scope==='today'?'今日主线':'近期主线'),'agenda-kind'),deskText('p',item.title));if(item.note){const detail=document.createElement('details');detail.append(deskText('summary','详情'),deskText('p',item.note));row.append(detail)}group.append(row)}
    const list=document.createElement('div');list.className='agenda-line';let marked=false;const grouped=new Set();
    for(const item of timed){if(grouped.has(item))continue;const linked=item.type==='event'?timed.find(other=>!grouped.has(other)&&linkedAgendaWindow(item,other)):null;if(linked)grouped.add(linked);
      const when=agendaWhen(item),past=when&&new Date(linked?.end_at||item.end_at||when)<now;if(key===today&&!marked&&(!when||new Date(when)>=now)){list.append(agendaMarker());marked=true}
      const row=document.createElement('article');row.className=`agenda-entry agenda-${item.type}${past||['done','missed'].includes(item.status)?' is-past':''}`;
      const time=when?deskDateParts(when):null;row.append(deskText('span',time?`${time.hour}:${time.minute}`:item.condition||'有余力时','agenda-time'),deskText('span',item.status==='done'?'✓':({event:'●',window:'◆',deadline:'▲',expectation:'○'}[item.type]||'●'),'agenda-node'));
      const body=document.createElement('div');body.className='agenda-entry-body';const until=item.type==='window'&&item.end_at?deskDateParts(item.end_at):null;body.append(deskText('p',item.title,'agenda-title'),deskText('span',`${agendaTypeNames[item.type]||'日程'}${until?` · 至 ${until.hour}:${until.minute}`:''}${item.status==='missed'?' · 已错过':item.status==='active'?' · 进行中':''}`,'agenda-kind'));
      if(linked){const detail=document.createElement('details'),until=linked.end_at?deskDateParts(linked.end_at):null;detail.append(deskText('summary',`另有时间窗口${until?` · 至 ${until.hour}:${until.minute}`:''}`),deskText('p',linked.title));if(linked.note)detail.append(deskText('p',linked.note));body.append(detail)}
      if(item.note){const detail=document.createElement('details');detail.append(deskText('summary','详情'),deskText('p',item.note));body.append(detail)}row.append(body);list.append(row)}
    if(key===today&&!marked)list.append(agendaMarker());group.append(list);box.append(group)
  }
}
function renderCurrentCognition(memory,error){const box=$('#currentCognition');box.replaceChildren();const paper=document.createElement('article');paper.className='memory-paper';box.append(paper);
  if(error){paper.append(deskText('p','近期状态暂时无法读取，请稍后再试。'));return}
  const sections=memory?.sections||{},overview=String(memory?.overview||'').trim(),hasSections=Object.values(sections).some(values=>Array.isArray(values)&&values.length);
  paper.append(deskText('p',overview||(!hasSections?'近期状态正在形成中。':''),'memory-overview'));
  for(const [key,label] of Object.entries(cognitionSectionNames)){const values=sections[key];if(!Array.isArray(values)||!values.length)continue;const section=document.createElement('section'),list=document.createElement('ul');section.className='memory-section';section.append(deskText('h4',label));for(const value of values)list.append(deskText('li',value));section.append(list);paper.append(section)}
  if(memory?.updated_at)paper.append(deskText('small',`更新于 ${formatTime(memory.updated_at)}`,'memory-updated'))
}
function renderPresenceActivity(presence){renderPresenceActivity.last=presence;const el=$('#presenceActivity');if(el){const recent=renderPresenceActivity.recent;el.textContent=recent&&Date.now()<recent.until&&!presence?.current_activity&&presence?.current_presence!=='ACTIVE'?recent.summary:presence?.status||'';el.hidden=!el.textContent;}if(presence?.current_presence==='SLEEP')renderInteractionBadge({interaction_state:'SLEEP'})}
function renderRecentActivityReceipt(receipt){if(receipt?.trigger!=='AUTO'||!['SUCCESS','NO_CHANGE','FAILED','CANCELLED'].includes(receipt.status))return;renderPresenceActivity.recent={summary:receipt.summary,until:Date.now()+4000};renderPresenceActivity(renderPresenceActivity.last);setTimeout(()=>renderPresenceActivity(renderPresenceActivity.last),4100)}
async function setupRecentContextBoard(){try{const data=await request('/api/recent-context');renderPresenceActivity(data.presence);renderAgendaTimeline(data.agenda,data.errors?.agenda);renderCurrentCognition(data.current_cognition,data.errors?.current_cognition)}catch{renderAgendaTimeline([],true);renderCurrentCognition(null,true)}}
window.refreshDeskContext=setupRecentContextBoard;
async function setupEmojiDebug(){try{
  const [data,trace,diagnostics]=await Promise.all([request('/api/debug/emoji'),request('/api/debug/emoji/trace'),request('/api/diagnostics')]);
  $('#emojiToggle').checked=!!data.enabled;$('#emojiDebug').textContent=JSON.stringify({...data,trace,frontend_build_id:FRONTEND_BUILD_ID,frontend_loaded_at:FRONTEND_LOADED_AT,core_version:diagnostics.version,core_started_at:diagnostics.core_started_at},null,2)
}catch(e){$('#emojiDebug').textContent=e.message}}
$('#emojiToggle').onchange=async e=>{const data=await request('/api/debug/emoji',{method:'POST',body:JSON.stringify({enabled:e.target.checked})});$('#emojiDebug').textContent=JSON.stringify(data,null,2)};
$('#emojiReload').onclick=async()=>{const data=await request('/api/debug/emoji',{method:'POST',body:JSON.stringify({reload:true})});$('#emojiDebug').textContent=JSON.stringify(data,null,2)};
$('#emojiTest').onclick=async()=>{const data=await request('/api/debug/emoji',{method:'POST',body:JSON.stringify({intent:$('#emojiIntent').value})});$('#emojiDebug').textContent=JSON.stringify(data,null,2)};
async function runEmojiHealth(path){const data=await request(path,{method:'POST'});const messages=data.messages||data.output_messages||[];for(const message of messages)await renderMessage(message);if(messages.some(message=>message.source==='emoji'))await acknowledgeEmojiTrace(data.trace_id||data.trace?.trace_id,true);await setupEmojiDebug()}
$('#emojiDirectTest').onclick=()=>runEmojiHealth('/api/debug/emoji/direct');$('#emojiModelTest').onclick=()=>runEmojiHealth('/api/debug/emoji/model');
$('#emojiDebugPanel').addEventListener('toggle',event=>{if(event.target.open)void setupEmojiDebug()});
async function setupRecentContextDebug(){try{renderRecentContext(await request('/api/debug/recent-context'))}catch(e){$('#recentContextDebug').textContent=e.message}}
function renderRecentContext(data){$('#agendaContextToggle').checked=!!data.agenda_enabled;$('#recentContextDebug').textContent=JSON.stringify(data,null,2)}
async function updateRecentContext(body){try{renderRecentContext(await request('/api/debug/recent-context',{method:'POST',body:JSON.stringify(body)}))}catch(e){$('#recentContextDebug').textContent=e.message;await setupRecentContextDebug()}}
$('#agendaContextToggle').onchange=e=>updateRecentContext({agenda_enabled:e.target.checked});$('#recentContextRefresh').onclick=setupRecentContextDebug;
$('#recentContextDebugPanel').addEventListener('toggle',event=>{if(event.target.open)void setupRecentContextDebug()});
async function perceptionAction(path, method='GET'){try{$('#perceptionDebug').textContent=JSON.stringify(await request(path,{method}),null,2)}catch(e){$('#perceptionDebug').textContent=e.message}}
$('#perceptionPanel').addEventListener('toggle',event=>{if(event.target.open)void perceptionAction('/api/perception/inspect')});
$('#perceptionRefresh').onclick=()=>perceptionAction('/api/perception/inspect');
$('#perceptionRecent').onclick=()=>perceptionAction('/api/perception/recent');
$('#perceptionFlush').onclick=()=>perceptionAction('/api/perception/flush','POST');
$('#perceptionClear').onclick=()=>perceptionAction('/api/perception/clear-expired','POST');
async function refreshExternalSources(){
  const panel=$('#externalSourcesList');
  try{
    const sources=await request('/api/external-sources');
    panel.replaceChildren();
    if(!sources.length){panel.textContent='未安装外部信息源';return}
    for(const source of sources){
      const row=document.createElement('div');
      const heading=document.createElement('p');
      heading.textContent=source.name+' ('+source.plugin_id+') · '+source.status;
      row.append(heading);
      for(const action of ['enable','disable','restart']){
        const button=document.createElement('button');
        button.type='button';button.textContent=action;
        button.onclick=async()=>{await request('/api/external-sources/'+encodeURIComponent(source.plugin_id)+'/'+action,{method:'POST'});await refreshExternalSources()};
        row.append(button)
      }
      const details=document.createElement('pre');details.className='debug';
      details.textContent=JSON.stringify(source,null,2);row.append(details);panel.append(row)
    }
  }catch(error){panel.textContent=error.message}
}
$('#externalSourcesPanel').addEventListener('toggle',event=>{if(event.target.open)void refreshExternalSources()});
$('#externalSourcesRefresh').onclick=()=>refreshExternalSources();
$('#perceptionSessions').onclick=()=>perceptionAction('/api/perception/sessions');
$('#perceptionEvents').onclick=()=>perceptionAction('/api/perception/self-events');
$('#perceptionPending').onclick=()=>perceptionAction('/api/perception/process-pending','POST');
$('#perceptionLedgerClear').onclick=()=>perceptionAction('/api/perception/clear-ledger','POST');
$('#perceptionImage').onclick=()=>perceptionAction('/api/perception/resolve-last-image','POST');
$('#perceptionExpression').onclick=()=>perceptionAction('/api/perception/expression');
async function cognitiveStreamAction(path){try{$('#cognitiveStreamDebug').textContent=JSON.stringify(await request(path),null,2)}catch(e){$('#cognitiveStreamDebug').textContent=e.message}}
$('#cognitiveStreamPanel').addEventListener('toggle',event=>{if(event.target.open)void cognitiveStreamAction('/api/debug/cognitive-stream')});
$('#cognitiveStreamRefresh').onclick=()=>cognitiveStreamAction('/api/debug/cognitive-stream');
$('#cognitiveStreamApply').onclick=()=>{const value=$('#cognitiveStreamFilter').value.trim();const kind=$('#cognitiveStreamFilterKind').value;void cognitiveStreamAction('/api/debug/cognitive-stream'+(value?'?'+kind+'='+encodeURIComponent(value):''))};
$('#cognitiveAttentionRun').onclick=()=>{const value=$('#cognitiveAttentionQuery').value.trim();if(value)void cognitiveStreamAction('/api/debug/cognitive-stream/attention?query='+encodeURIComponent(value))};
$('#cognitiveSessionRun').onclick=()=>{const value=$('#cognitiveStreamFilter').value.trim()||'local';void cognitiveStreamAction('/api/debug/cognitive-stream/session?session='+encodeURIComponent(value))};
async function refreshInternalActivity(){try{$('#internalActivityDebug').textContent=JSON.stringify(await request('/api/debug/internal-activity'),null,2)}catch(e){$('#internalActivityDebug').textContent=e.message}}
$('#internalActivityRefresh').onclick=refreshInternalActivity;
$('#internalActivityPanel').addEventListener('toggle',event=>{if(event.target.open)void refreshInternalActivity()});
document.querySelectorAll('.runInternalActivity').forEach(button=>button.onclick=async()=>{button.disabled=true;try{$('#internalActivityDebug').textContent=JSON.stringify(await request('/api/debug/internal-activity',{method:'POST',body:JSON.stringify({activity:button.dataset.activity,confirm_social_write:button.dataset.activity==='social_wander'&&window.confirm('允许本次调试在授权群发言吗？仍会检查隐私、冷却和每日限额。取消则只看不说。')})}),null,2)}catch(e){$('#internalActivityDebug').textContent=e.message}finally{button.disabled=false}});
async function setupBudgetDebug(){if(!$('#budgetDebug'))return;try{$('#budgetDebug').textContent=JSON.stringify(await request('/api/debug/budget-context'),null,2)}catch(e){$('#budgetDebug').textContent=e.message}}
$('#budgetDebugRefresh').onclick=setupBudgetDebug;
$('#budgetDebugPanel').addEventListener('toggle',event=>{if(event.target.open)void setupBudgetDebug()});
let pendingDeliveryTimer=null;
async function openDelivery(id){clearTimeout(pendingDeliveryTimer);if(busy||pendingInput.length){activity.textContent='当前回复结束后打开系统消息…';pendingDeliveryTimer=setTimeout(()=>openDelivery(id),500);return}try{await request('/api/proactive/'+encodeURIComponent(id)+'/activate',{method:'POST'});const data=await request('/api/session');displayTimezone=data.timezone||displayTimezone;historyCursor=null;messages.replaceChildren();historyButton();data.messages.forEach(m=>{if(m.delivery_id)seenDeliveries.add(m.delivery_id);if(m.kind==='system')return;if(m.role==='user'&&m.display_parts?.length){let offset=0;for(const p of m.display_parts){addMessage('user',p.text,'',(m.images||[]).slice(offset,offset+p.image_count),p.timestamp);offset+=p.image_count}}else void renderMessage(m)});debug.textContent=JSON.stringify(await request('/api/proactive/'+encodeURIComponent(id)+'/inspect'),null,2);const n=document.getElementById('notice-'+id);if(n)n.querySelector('.badge').textContent='已读';input.focus()}catch(e){showActivityHint('暂时无法打开系统消息，请稍后重试')}}
function showNotice(d){showProactiveNote(d);if(d.kind!=='system'&&!String(d.event_type||'').startsWith('system.'))return;if(!['delivered','acknowledged'].includes(d.status)||document.getElementById('notice-'+d.delivery_id))return;const n=document.createElement('button');n.id='notice-'+d.delivery_id;n.className='notice';n.style.cssText='display:block;width:100%;text-align:left';n.innerHTML=`<div class="badge">${d.status==='acknowledged'?'已读':'未读'}</div><div>${markdown(d.content)}</div><small>${escapeHtml(formatTime(d.delivered_at||d.available_at))}</small>`;n.onclick=()=>openDelivery(d.delivery_id);$('#notices').querySelector('.sub')?.remove();$('#notices').prepend(n);while($('#notices').children.length>100)$('#notices').lastElementChild.remove()}
function receiveDelivery(d){
  showProactiveNote(d);
  if(d.kind==='system'||String(d.event_type||'').startsWith('system.')){showNotice(d);return}
  if(!['delivered','acknowledged'].includes(d.status)||seenDeliveries.has(d.delivery_id)||deliveryQueue.some(x=>x.delivery_id===d.delivery_id))return;
  deliveryQueue.push(d);void drainDeliveries();
}
async function drainDeliveries(){
  if(!historyReady||busy||pendingInput.length)return;
  while(deliveryQueue.length){
    const d=deliveryQueue.shift();if(seenDeliveries.has(d.delivery_id))continue;
    busy=true;$('#clear').disabled=true;seenDeliveries.add(d.delivery_id);
    try{await sendReply(d.content,d.delivered_at||d.available_at)}finally{finishTurn()}
    if(busy||pendingInput.length)return;
  }
}
let replyIntervalMs=5000;
function applySettings(event,persist=false){
  INPUT_MERGE_MS=Number($('#mergeRange').value)*1000;
  replyIntervalMs=Number($('#replyRange').value)*1000;
  $('#mergeValue').textContent=INPUT_MERGE_MS?`${INPUT_MERGE_MS/1000} 秒`:'关闭';
  $('#replyValue').textContent=replyIntervalMs?`${replyIntervalMs/1000}–${replyIntervalMs/500} 秒`:'立即';
  const externalDebounce=Number($('#externalDebounceRange').value);
  const externalReply=Number($('#externalReplyRange').value);
  $('#externalDebounceValue').textContent=externalDebounce?`${externalDebounce} 秒`:'关闭';
  $('#externalReplyValue').textContent=externalReply?`${externalReply.toFixed(1)} 秒`:'立即';
  try{localStorage.setItem('zhaoxiTiming',JSON.stringify([INPUT_MERGE_MS/1000,replyIntervalMs/1000]))}catch{}
  if(persist){const key=INTERFACE_SETTING_KEYS[event?.target?.id];if(key){const node=event.target,value=node.type==='checkbox'?node.checked:Number(node.value);void request('/api/settings/interface',{method:'PATCH',body:JSON.stringify({[key]:value})}).then(applyInterfaceSettings).catch(()=>{$('#pokeStatus').textContent='界面设置保存失败';void setupInterfaceSettings()})}}
  if(event?.target===$('#mergeRange')&&inputTimer!==null){clearTimeout(inputTimer);inputTimer=setTimeout(()=>{inputTimer=null;flushInput()},INPUT_MERGE_MS)}
}
const INTERFACE_SETTING_KEYS={mergeRange:'input_merge_seconds',replyRange:'reply_interval_seconds',externalDebounceRange:'external_input_debounce_seconds',externalReplyRange:'external_reply_interval_seconds',longWaitToggle:'long_wait_enabled',forceFastChatToggle:'force_fast_chat',forceNonFastChatToggle:'force_non_fast_chat',allowMultiModelCallsToggle:'allow_multi_model_calls',regenerateDebugToggle:'show_normal_regenerate'};
function renderNormalRegeneration(enabled){normalRegenerationEnabled=!!enabled;$('#regenerateDebugToggle').checked=normalRegenerationEnabled;document.querySelectorAll('.normal-regenerate').forEach(button=>button.hidden=!normalRegenerationEnabled)}
const BUDGET_SETTING_KEYS={tokenBaseBudget:'base_budget',tokenHardLimit:'hard_limit',tokenFinalizationReserve:'finalization_reserve',plannerExtensionLimit:'planner_extension_limit'};
let budgetSettingsDirty=false;
function applyBudgetSettings(saved){
  if(!$('#budgetSettingsForm')||budgetSettingsDirty)return;
  for(const [id,key] of Object.entries(BUDGET_SETTING_KEYS))$('#'+id).value=saved[key];
  $('#budgetSettingsFields').disabled=false;
}
async function setupBudgetSettings(){if(!$('#budgetSettingsForm'))return;try{applyBudgetSettings(await request('/api/settings/budget'))}catch(e){$('#budgetSettingsStatus').textContent='预算读取失败：'+e.message}}
if($('#budgetSettingsForm')){
$('#budgetSettingsForm').oninput=()=>{budgetSettingsDirty=true;$('#budgetSettingsStatus').textContent='有未保存的预算修改'};
$('#budgetSettingsForm').onsubmit=async e=>{
  e.preventDefault();const values=Object.fromEntries(Object.entries(BUDGET_SETTING_KEYS).map(([id,key])=>[key,Number($('#'+id).value)]));
  if(values.hard_limit<values.base_budget||values.finalization_reserve>=values.base_budget){$('#budgetSettingsStatus').textContent='总硬上限不能小于基础预算，收尾预留必须小于基础预算';return}
  $('#budgetSettingsFields').disabled=true;
  try{const saved=await request('/api/settings/budget',{method:'PUT',body:JSON.stringify(values)});budgetSettingsDirty=false;applyBudgetSettings(saved);$('#budgetSettingsStatus').textContent='预算已保存，下一次请求生效';void setupBudgetDebug()}
  catch(e){$('#budgetSettingsStatus').textContent='预算保存失败：'+e.message}
  finally{$('#budgetSettingsFields').disabled=false}
};
$('#resetBudgetSettings').onclick=async()=>{
  $('#budgetSettingsFields').disabled=true;
  try{const saved=await request('/api/settings/budget',{method:'DELETE'});budgetSettingsDirty=false;applyBudgetSettings(saved);$('#budgetSettingsStatus').textContent='已恢复配置默认预算，下一次请求生效';void setupBudgetDebug()}
  catch(e){$('#budgetSettingsStatus').textContent='预算恢复失败：'+e.message}
  finally{$('#budgetSettingsFields').disabled=false}
};
}
function applyInterfaceSettings(saved){
  $('#mergeRange').value=saved.input_merge_seconds;$('#replyRange').value=saved.reply_interval_seconds;
  $('#externalDebounceRange').value=saved.external_input_debounce_seconds??5;$('#externalReplyRange').value=saved.external_reply_interval_seconds??0.5;
  $('#longWaitToggle').checked=!!saved.long_wait_enabled;$('#forceFastChatToggle').checked=!!saved.force_fast_chat;
  $('#forceNonFastChatToggle').checked=!!saved.force_non_fast_chat;$('#allowMultiModelCallsToggle').checked=!!saved.allow_multi_model_calls;
  renderNormalRegeneration(saved.show_normal_regenerate);
  if(saved.request_budget)applyBudgetSettings(saved.request_budget);else void setupBudgetSettings();
  for(const id of ['longWaitToggle','forceFastChatToggle','forceNonFastChatToggle','allowMultiModelCallsToggle','regenerateDebugToggle'])$('#'+id).disabled=false;
  applySettings();
}
async function setupInterfaceSettings(){
  try{applyInterfaceSettings(await request('/api/settings/interface'))}
  catch{try{const saved=JSON.parse(localStorage.getItem('zhaoxiTiming'));if(Array.isArray(saved)&&saved.length===2&&saved.every(Number.isFinite)){ $('#mergeRange').value=Math.max(0,Math.min(30,saved[0]));$('#replyRange').value=Math.max(0,Math.min(15,saved[1]))}}catch{}applySettings()}
}
$('#mergeRange').oninput=applySettings;$('#replyRange').oninput=applySettings;$('#externalDebounceRange').oninput=applySettings;$('#externalReplyRange').oninput=applySettings;
for(const id of Object.keys(INTERFACE_SETTING_KEYS))$('#'+id).onchange=e=>{if(id==='regenerateDebugToggle')renderNormalRegeneration(e.target.checked);applySettings(e,true)};
applySettings();
function renderDebugPresenceControls(presence){document.querySelectorAll('.forcePresence').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.state===presence?.debug_forced_state)));const label={ACTIVE:'活跃',SEMI_ACTIVE:'半活跃',AWAY:'离开',IDLE:'发呆',SLEEP:'睡眠'}[presence?.debug_forced_state];$('#presenceDebugStatus').textContent=label?`当前强制：${label}；再次点击恢复自动判断`:'自动判断中；点击按钮强制状态'}
document.querySelectorAll('.forcePresence').forEach(button=>button.onclick=async()=>{const state=button.getAttribute('aria-pressed')==='true'?null:button.dataset.state;button.disabled=true;try{const presence=await request('/api/debug/presence',{method:'POST',body:JSON.stringify({state})});renderInteractionBadge(presence);renderDebugPresenceControls(presence)}catch(e){$('#presenceDebugStatus').textContent=e.message}finally{button.disabled=false}});
$('#poke').onclick=async()=>{if(busy||pendingInput.length){$('#pokeStatus').textContent='请等当前消息处理完成';return}$('#poke').disabled=true;try{const r=await request('/api/proactive/active/poke',{method:'POST'});$('#pokeStatus').textContent=r.delivered?'已投递':r.trace?.model_diagnostics?.provider_error_code||r.trace?.model_error||r.trace?.gate_reason||'本次选择沉默';void setupDiagnostics()}catch(e){$('#pokeStatus').textContent=e.message}finally{$('#poke').disabled=false}};
$('#restartCore').onclick=async()=>{
  if(busy||pendingInput.length){$('#pokeStatus').textContent='请等当前消息处理完成';return}
  if(!confirm('确定要重启 Core 吗？当前会话会保留。'))return;
  const button=$('#restartCore');button.disabled=true;$('#poke').disabled=true;
  $('#pokeStatus').textContent='正在重启 Core…';$('#connection').textContent='Core 正在重启…';
  try{await request('/api/core/restart',{method:'POST'})}catch(e){
    // The server can close just after accepting the request. Polling below
    // distinguishes that expected disconnect from a rejected restart.
    if(!String(e.message).includes('fetch')){$('#pokeStatus').textContent=e.message;button.disabled=false;$('#poke').disabled=false;return}
  }
  const deadline=Date.now()+30000;
  while(Date.now()<deadline){
    await new Promise(resolve=>setTimeout(resolve,500));
    try{const response=await fetch('/api/health',{cache:'no-store'});if(response.ok){location.reload();return}}catch{}
  }
  $('#pokeStatus').textContent='重启超时，请从托盘重新打开朝汐';button.disabled=false;$('#poke').disabled=false;
};
const THINKING_STATUS={off:'由服务端默认决定',disabled:'已关闭思考',enabled:'已开启思考'};let savedThinkingMode='off';
async function setupThinking(){try{const s=await request('/api/settings/thinking');const select=$('#thinkingMode');savedThinkingMode=s.mode;select.value=s.mode;select.disabled=false;$('#thinkingStatus').textContent=THINKING_STATUS[s.mode]||''}catch{$('#thinkingStatus').textContent='读取失败'}}
$('#thinkingMode').onchange=async()=>{const select=$('#thinkingMode');select.disabled=true;try{await request('/api/settings/thinking',{method:'PUT',body:JSON.stringify({mode:select.value})});await setupThinking()}catch(e){select.value=savedThinkingMode;select.disabled=false;$('#thinkingStatus').textContent=e.message}};
async function start(){const token=new URLSearchParams(location.hash.slice(1)).get('token')||'';if(token){const boot=await fetch('/api/bootstrap',{method:'POST',headers:{'X-Zhaoxi-Token':token}});history.replaceState(null,'',location.pathname+location.search);if(!boot.ok)throw new Error('Desktop 会话初始化失败')}const es=new EventSource('/api/events');es.onmessage=e=>{const data=JSON.parse(e.data);if(data.type==='agent_event')renderAgentEvent(data.event);if(data.type==='interim_reply')renderInterimReply(data);if(data.type==='maintenance_status'&&data.request_id===activeTraceId){const node=$('#actionMaintenance');if(node)node.textContent='后台维护：'+data.status;}if(data.type==='activity'&&(!busy||!activeTraceId))activity.textContent=data.label||'';if(data.type==='presence_activity')renderPresenceActivity(data.presence);if(data.type==='activity_finished')renderRecentActivityReceipt(data.receipt);if(data.type==='interface_settings')applyInterfaceSettings(data.settings);if(data.type==='proactive')receiveDelivery(data.delivery)};es.onerror=()=>{$('#connection').textContent='事件通道正在重连…'};es.onopen=()=>{$('#connection').textContent='事件通道已连接，正在检查 Core…';void setupDiagnostics();void setupActionTrace()};await setupInterfaceSettings();if(document.querySelector("#thinkingMode"))await setupThinking();await setupVoice();await restore();historyButton();const pendingDelivery=sessionStorage.getItem("zhaoxiPendingDelivery");if(pendingDelivery){sessionStorage.removeItem("zhaoxiPendingDelivery");await openDelivery(pendingDelivery)}await setupDiagnostics();await setupRecentContextBoard();await setupActionTrace();setInterval(()=>{void setupDiagnostics();void setupRecentContextBoard();void setupInterfaceSettings();void setupActionTrace()},30000);input.focus()};window.addEventListener('focus',()=>{void setupInterfaceSettings();void setupActionTrace()});start().catch(()=>{$('#connection').textContent='Desktop 会话初始化失败'});
async function refreshRuntimeDebug(){
  try{
    const data=await request('/api/debug/runtime'),m=data.runtime_metrics||{};
    $('#runtimeSummary').textContent=m.request_id?[
      `Request ID: ${m.request_id}`,`Trace ID: ${m.trace_id}`,`Route: ${m.route||'—'}`,
      `Total: ${m.total_ms} ms · TTFR: ${m.ttfr_ms} ms · Final: ${m.final_response_ms} ms`,
      `Routing: ${m.routing_ms} ms · Memory: ${m.memory_retrieval_ms} ms · Planner: ${m.planner_ms} ms`,
      `Tools: ${m.tool_ms_total} ms · AutoMemory: ${m.auto_memory_ms} ms · Other: ${m.other_ms} ms`,
      `LLM Calls: ${m.llm_call_count} · Tool Calls: ${m.tool_call_count} · Memory Hits: ${m.memory_hits} · Candidates: ${(m.memory_candidates||[]).length}`,
      `Planner Used: ${m.planner_used} · Decision Used: ${m.decision_used} · Interim Replies: ${m.interim_replies}`
    ].join('\n'):'暂无请求指标';
    renderMemoryCandidates(m.memory_candidates||[]);
    const list=$('#runtimeTimeline');list.replaceChildren();
    const start=Date.parse(m.started_at||'');
    for(const event of m.timeline||[]){
      const row=document.createElement('li'),offset=(Date.parse(event.timestamp||'')-start)/1000;
      row.textContent=`${Number.isFinite(offset)?offset.toFixed(1)+'s':'?'} · ${event.event_type||''} · ${event.display_message||''}`;
      list.append(row)
    }
    $('#runtimeDebug').textContent=JSON.stringify(data,null,2);
  }catch(e){$('#runtimeSummary').textContent=e.message}
}
$('#runtimeDebugPanel').addEventListener('toggle',event=>{if(event.target.open)void refreshRuntimeDebug()});
$('#runtimeDebugRefresh').onclick=refreshRuntimeDebug;
let socialTracePage=null, socialTraceMode='read', socialTraceKey=null;
async function loadSocialTrace(next=false,mode='read'){
 const ref=$('#socialTraceRef').value.trim(), statement=$('#socialTraceStatement').value.trim();
 const params=new URLSearchParams();
 if(mode==='read'){
  if(!ref)return;
  params.set('reference',ref);if(statement)params.set('statement_id',statement);
 }else{
  for(const [key,id] of [['query','socialTraceQuery'],['group_id','socialTraceGroup'],['since','socialTraceSince'],['until','socialTraceUntil']]){
   const value=$('#'+id).value.trim();if(value)params.set(key,value);
  }
  if(!params.toString())return;
 }
 const key=mode+':'+params.toString();
 if(next&&socialTracePage&&socialTraceKey===key){params.set('offset',socialTracePage.next_offset);params.set('text_offset',socialTracePage.next_text_offset||0)}
 try{const data=await request('/api/debug/cognitive-stream/social-trace?'+params.toString());socialTracePage=data;socialTraceMode=mode;socialTraceKey=key;$('#socialTraceOutput').textContent=JSON.stringify(data,null,2);$('#socialTraceNext').disabled=data.next_offset==null}
 catch(e){socialTracePage=null;$('#socialTraceNext').disabled=true;$('#socialTraceOutput').textContent=e.message}
}
$('#socialTraceRun').onclick=()=>loadSocialTrace();
$('#socialTraceSearch').onclick=()=>loadSocialTrace(false,'search');
$('#socialTraceNext').onclick=()=>loadSocialTrace(true,socialTraceMode);
$('#provenanceInspectorRun').onclick=async()=>{
  const output=$('#provenanceInspectorOutput');
  try{const data=await request('/api/debug/provenance');output.textContent=JSON.stringify(data,null,2)}
  catch(e){output.textContent=e.message}
};

$('#memoryInspectorRun').onclick=async()=>{
  const query=$('#memoryInspectorQuery').value.trim();if(!query)return;
  const output=$('#memoryInspectorOutput');output.replaceChildren();
  try{
    const memoryId=$('#memoryInspectorId').value.trim();
    const data=await request('/api/debug/memory-retrieval?query='+encodeURIComponent(query)+'&retrieval_mode='+encodeURIComponent($('#memoryInspectorMode').value)+(memoryId?'&memory_id='+encodeURIComponent(memoryId):''));
    const details=document.createElement('pre');details.textContent=JSON.stringify({retrieval_mode:data.retrieval_mode,status_filter:data.status_filter,cluster_candidates:data.cluster_candidates,cluster_diversity:data.cluster_diversity,embedding_status:data.embedding_status,embedding_error:data.embedding_error,requested_memory:data.requested_memory,excluded:data.excluded,candidate_count:data.candidate_count},null,2);output.append(details);
    if(!data.candidates.length){output.append(document.createTextNode('没有找到候选记忆'));return}
    for(const item of data.candidates){
      const block=document.createElement('pre');block.textContent=[
        `ID: ${item.memory_id}`,item.content,
        `Write: ${item.decision||'未记录'} · Why written: ${item.reason||'未记录'}`,
        `Evidence: ${JSON.stringify({source_event_id:item.source_event_id,source_message_id:item.source_message_id,evidence_reference:item.evidence_reference,refs:item.evidence_refs,scope:item.evidence_scope,provenance:item.evidence_provenance})}`,
        `Lifecycle: ${item.lifecycle_reason||'未记录'} · Cluster: ${item.cluster_reason||'未记录'}`,
        `Heat history: ${JSON.stringify(item.activation_history||[])}`,
        `Final: ${item.final_score} · Context: ${item.contextual_relevance} · Text: ${item.text_score} · Semantic: ${item.semantic_score}`,
        `Graph: ${item.graph_score} · Time: ${item.time_score} · Activation: ${item.activation_score} · Importance: ${item.importance_score}`,
        `Status: ${item.status} · Importance: ${item.importance} · Activation: ${item.activation}`,
        `Mode: ${item.retrieval_mode} · Sources: ${(item.candidate_source||[]).join(", ")} · Cluster rank: ${item.cluster_rank}`,
        `Why: ${(item.why_selected||[]).join('、')}`
      ].join('\n');output.append(block)
    }
  }catch(e){output.textContent=e.message}
};
$('#memoryClusterInspectorRun').onclick=async()=>{try{$('#memoryMaintenanceOutput').textContent=JSON.stringify(await request('/api/debug/memory-clusters'),null,2)}catch(e){$('#memoryMaintenanceOutput').textContent=e.message}};
$('#databaseInspectorRun').onclick=async()=>{try{$('#memoryMaintenanceOutput').textContent=JSON.stringify(await request('/api/debug/database-maintenance'),null,2)}catch(e){$('#memoryMaintenanceOutput').textContent=e.message}};
function renderDecisionDebug(data){
 const target=$('#decisionDebugOutput');target.replaceChildren();
 const legacy=data.decision_mode==='legacy';$('#decisionLegacyControls').hidden=!legacy;
 const text=value=>{const p=document.createElement('p');p.textContent=value;target.append(p)};
 const sources={current_input:'当前表达',current_image:'本轮图片',agenda:'Agenda',current_cognition:'Current Cognition',memory:'Memory',principles:'Decision Principles',choice_history:'Choice History',tool:'实际工具资料'};
 if(legacy){text('当前使用 Legacy 决策链。')}else{
  const protocol=data.reply_protocol,failed=protocol?.status==='failed';
  if(failed)text('本轮回复未能交付：'+protocol.error_code+'。请重试本轮消息。');
  else if(protocol&&['invalid','missing'].includes(protocol.awareness))text('本轮正文已生成，但没有有效的生活判断记录。');
  const row=data.latest;
  if(row){text((protocol&&(failed||protocol.mode!==row.mode)?'上次已完成的判断：':'这次朝汐建议：')+(row.agent_recommendation||'整理事实与价值冲突'));text('模式：'+row.mode);
   if(row.predicted_user_choice)text('推测你更可能选择：'+row.predicted_user_choice);
   text('本轮参考：'+((row.context_sources||[]).map(s=>sources[s]||s).join('、')||'当前对话'));
   if(row.principle_ids?.length)text('参考原则：'+row.principle_ids.join('、'));
   text(row.guard_flags?.length?'行动边界：'+row.guard_flags.join('、'):'本次判断没有行动 Guard 命中。');
  }else text('还没有生活判断记录。正常对话后刷新即可，查看不会调用模型。');
  if(data.choice_history?.length){text('最近选择（历史只作弱证据）：');const list=document.createElement('ul');
   for(const row of data.choice_history){const li=document.createElement('li');li.textContent=row.mode+' · '+(row.suggestion||row.summary)+(row.user_final_choice?' → 最终：'+row.user_final_choice:'')+(row.overridden?'（已接受覆盖）':'')+(row.outcome?' · 结果：'+row.outcome:'');list.append(li)}target.append(list)}
  if(data.guard_events?.length){text('最近行动边界：');for(const event of data.guard_events)text(event.tool+' · '+event.flags.join('、')+' · '+event.status)}
 }
 const details=document.createElement('details'),summary=document.createElement('summary'),raw=document.createElement('pre');
 summary.textContent='技术详情';raw.textContent=JSON.stringify(data,null,2);details.append(summary,raw);target.append(details);
}
async function refreshDecisionDebug(){try{renderDecisionDebug(await request('/api/debug/decision'))}catch(e){$('#decisionDebugOutput').textContent=e.message}}
$('#decisionDebugPanel').addEventListener('toggle',event=>{if(event.target.open)void refreshDecisionDebug()});
$('#decisionDebugRefresh').onclick=refreshDecisionDebug;
$('#decisionDebugEvaluate').onclick=async()=>{const message=$('#decisionDebugInput').value.trim();if(!message)return;try{$('#decisionDebugOutput').textContent=JSON.stringify(await request('/api/debug/decision',{method:'POST',body:JSON.stringify({message,forced_level:$('#decisionDebugLevel').value||null})}),null,2)}catch(e){$('#decisionDebugOutput').textContent=e.message}};
