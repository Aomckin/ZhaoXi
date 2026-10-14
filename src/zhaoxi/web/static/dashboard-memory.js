import {el,api,button,card,raw,time} from './dashboard-common.js';

const statuses={active:'活跃',cold:'冷却',dormant:'休眠',archived:'归档',forgotten:'已遗忘',superseded:'已替代'};
const kinds={episodic:'经历',semantic:'知识',state:'状态',intent:'意图',relationship:'关系'};
const score=value=>Number(value||0).toFixed(3);

export async function memory(root){
 const data=await api('/api/dashboard/memory');
 root.append(el('h1','记忆'),button('刷新记忆',async()=>{const next=el('div');await memory(next);root.replaceChildren(...next.childNodes)}));
 const counts=card('记忆库总览'),d=data.diagnostics;
 counts.append(el('p',`${d.total} 条记忆 · ${data.clusters.filter(c=>c.active).length} 个活跃簇 · ${d.unclustered} 条未聚类`));
 counts.append(el('p',Object.entries(d.by_status).map(([key,value])=>`${statuses[key]||key} ${value}`).join(' · ')));
 counts.append(raw(d));root.append(counts);
 const recall=card('当前本地对话 · 最近完成请求的记忆候选'),r=data.retrieval;
 if(!r)recall.append(el('p','当前会话暂无可用请求快照。完成一轮对话后刷新此页；重启 Core 会清空候选快照。','muted'));
 else{
  recall.append(el('p',`${time(r.started_at)} · 本地预取 ${r.preload_count} 次 · 工具检索 ${r.tool_search_count} 次`),el('small',`会话 ${r.session_id} · 请求 ${r.request_id}`));
  recall.append(el('p','仅展示本轮实际注入或工具返回的候选，最多 20 条；不使用后台或手动检查器的检索结果。','muted'));
  if(!r.candidates.length)recall.append(el('p','本轮没有记录到相关记忆候选。'));
  for(const item of r.candidates){
   const row=el('article',undefined,'list-item');
   row.append(el('strong',`#${item.rank} · ${kinds[item.kind]||item.kind} · ${statuses[item.status]||item.status}`),el('span',{preload:'首轮预取',tool:'工具检索',recall:'相关记忆'}[item.retrieval_source]||'相关记忆','tag'),el('p',item.content));
   if(item.cluster)row.append(el('p','记忆簇：'+item.cluster));
   row.append(el('p',`相关性 ${score(item.contextual_relevance)} · 综合评分 ${score(item.final_score)}`),raw(item));recall.append(row);
  }
 }
 root.append(recall);
 const clusters=card('记忆簇总览'),filters=el('div',undefined,'actions'),query=el('input'),state=el('select'),list=el('div'),count=el('p',undefined,'muted');
 query.type='search';query.placeholder='搜索主题、摘要、标签或人物';query.setAttribute('aria-label','搜索记忆簇');
 for(const [value,label] of [['active','活跃簇'],['all','全部簇'],['inactive','已合并或停用']]){const option=el('option',label);option.value=value;state.append(option)}
 state.setAttribute('aria-label','记忆簇状态');filters.append(query,state);clusters.append(filters,count,list);root.append(clusters);
 const ordered=[...data.clusters].sort((a,b)=>b.updated_at.localeCompare(a.updated_at));let limit=20;
 function renderClusters(){
  list.replaceChildren();const needle=query.value.trim().toLocaleLowerCase();
  const rows=ordered.filter(c=>(state.value==='all'||c.active===(state.value==='active'))&&[c.topic,c.summary,...c.tags,...c.entities].join(' ').toLocaleLowerCase().includes(needle));
  count.textContent=`共 ${rows.length} 个簇，已显示 ${Math.min(limit,rows.length)} 个`;
  if(!rows.length)list.append(el('p','没有符合条件的记忆簇。'));
  for(const c of rows.slice(0,limit)){
   const row=el('article',undefined,'list-item');row.append(el('strong',c.topic),el('span',`${c.member_count} 条`,'tag'));
   if(!c.active)row.append(el('span','已合并或停用','tag'));
   if(c.summary)row.append(el('p',c.summary));
   if(c.tags.length)row.append(el('p','标签：'+c.tags.slice(0,8).join('、')+(c.tags.length>8?' 等 '+c.tags.length+' 个':'')));
   row.append(el('small',`活跃度 ${score(c.activation)} · 重要度 ${score(c.importance)} · 更新于 ${time(c.updated_at)}`),raw(c));list.append(row);
  }
  if(rows.length>limit)list.append(button('加载更多记忆簇',()=>{limit+=20;renderClusters()}));
 }
 query.oninput=state.onchange=()=>{limit=20;renderClusters()};renderClusters();
 const engineering=el('details');engineering.append(el('summary','记忆检索检查器与维护诊断'));
 engineering.addEventListener('toggle',()=>{if(engineering.open&&!engineering.querySelector('iframe')){const frame=el('iframe');frame.title='记忆工程详情';frame.src='/static/engineering.html#memory';engineering.append(frame)}});
 root.append(engineering);
}
