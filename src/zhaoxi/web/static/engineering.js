/* Adapt the existing engineering tools to a lazy dashboard panel. */
(()=>{
 const mode=location.hash.slice(1)||'runtime';
 const sets={memory:['runtimeDebugPanel'],runtime:['runtimeDebugPanel','budgetDebugPanel','decisionDebugPanel'],capability:['toolCabinetPanel','emojiCabinetPanel','emojiDebugPanel','externalSourcesPanel','perceptionPanel'],settings:['recentContextDebugPanel']};
 const allowed=sets[mode]||sets.runtime;
 const panels=[...document.querySelectorAll('.maintenance details[id]')];
 for(const n of panels)if(!allowed.includes(n.id))n.hidden=true;
 document.querySelector('.maintenance').open=true;
 if(mode==='settings'){const outer=[...document.querySelectorAll('.desk-tools>details')].find(n=>n.querySelector('#thinkingMode'));if(outer)outer.open=true;}
 if(mode!=='runtime')document.querySelector('#actionTrace').hidden=true;
 const toast=document.createElement('section');toast.className='receipt';toast.setAttribute('role','status');toast.setAttribute('aria-live','polite');document.querySelector('.desk-content').prepend(toast);
 const original=request;
 request=async function(url,options={}){
  const write=['POST','PUT','PATCH','DELETE'].includes(options.method);
  if(write)toast.textContent='正在执行，请稍候…';
  try{const result=await original(url,options);if(write){toast.replaceChildren();const receipts=result.receipts||(result.receipt?[result.receipt]:[]);if(receipts.length){for(const r of receipts){const title=document.createElement('h3');title.textContent=r.title;const summary=document.createElement('p');summary.textContent=r.summary;toast.append(title,summary)}}else{const p=document.createElement('p');p.textContent='操作已完成。';const d=document.createElement('details'),s=document.createElement('summary'),raw=document.createElement('pre');s.textContent='技术详情';raw.textContent=JSON.stringify(result,null,2);d.append(s,raw);toast.append(p,d)}}return result}catch(e){if(write)toast.textContent='操作失败：'+e.message;throw e}
 };
})();
