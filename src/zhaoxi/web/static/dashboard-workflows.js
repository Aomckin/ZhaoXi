import {el,api,send,button,card,raw,time} from './dashboard-common.js';
export async function workflows(root){
  root.append(el('h1','工作流'),el('p','这里展示实际注册流程和执行记录。演示流程不代表日用覆盖；保存定义不会自动执行。'));
  const data=await api('/api/workflows');
  async function edit(definition){
    const box=card('流程定义'),text=el('textarea');text.rows=18;text.style.width='100%';text.value=definition?JSON.stringify(definition,null,2):'';text.setAttribute('aria-label','Workflow JSON');
    box.append(text,button('保存定义',async()=>{const value=JSON.parse(text.value);await send('/api/workflows/'+encodeURIComponent(value.id),value,'PUT');root.replaceChildren();await workflows(root)}));root.append(box)
  }
  root.append(button('新增流程',()=>edit()));
  for(const d of data.definitions){
    const c=card(d.name);c.append(el('p',d.description),el('p',`${d.id} · v${d.version} · ${d.enabled?'启用':'禁用'} · ${d.available?'依赖可用':'当前不可执行'}`),raw(d));
    c.append(button(d.enabled?'停用':'启用',async()=>{const value=await api('/api/workflows/'+encodeURIComponent(d.id));value.enabled=!value.enabled;await send('/api/workflows/'+encodeURIComponent(d.id),value,'PUT');root.replaceChildren();await workflows(root)}),button('编辑',async()=>edit(await api('/api/workflows/'+encodeURIComponent(d.id)))),button('从目录移除',async()=>{if(!window.confirm('移除此流程？既有执行快照保留，安装包文件不会修改。'))return;await api('/api/workflows/'+encodeURIComponent(d.id),{method:'DELETE'});root.replaceChildren();await workflows(root)}));root.append(c)
  }
  if(!data.definitions.length)root.append(el('p','尚无已注册流程。'));
  root.append(el('h2','最近执行'));for(const run of data.runs)root.append(el('p',`${run.workflow_id} · ${run.status} · ${time(run.updated_at)}`),raw(run));
}
