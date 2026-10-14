import {$,el,clearError,showError,showReceipt,api,statusCard} from './dashboard-common.js';
import {workflows} from './dashboard-workflows.js';
import {overview} from './dashboard-overview.js';
import {presence} from './dashboard-presence.js';
import {activity,budgetForm} from './dashboard-activity.js';
import {decision} from './dashboard-decision.js';
import {cognition} from './dashboard-cognition.js';
import {memory} from './dashboard-memory.js';
let current='overview',generation=0;
const loaders={overview,presence,activity,cognition,decision,workflows,memory};
async function render(view){current=view;const version=++generation;clearError();for(const n of document.querySelectorAll('nav button')){if(n.dataset.view===view)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current')}const fragment=el("div");$('#view').replaceChildren(el('p','正在读取…'));try{if(loaders[view])await loaders[view](fragment);else{fragment.append(el('h1',{memory:'记忆检查',runtime:'运行观测',capability:'能力与社交',settings:'设置'}[view]));if(view==='capability')await budgetForm(fragment,true);const frame=el('iframe');frame.title='工程详情';frame.src='/static/engineering.html#'+view;fragment.append(el('p','工程工具按需加载；展开检查器后读取详细数据。','muted'),frame)}if(version===generation)$('#view').replaceChildren(fragment)}catch(e){if(version===generation){$('#view').replaceChildren();showError(e.message)}}updateCountdowns();}
function updateCountdowns(){for(const node of document.querySelectorAll('[data-until]')){const remaining=Math.max(0,Math.ceil((new Date(node.dataset.until)-Date.now())/1000));node.textContent=`约 ${remaining} 秒后进入${node.dataset.next}`}}
for(const n of document.querySelectorAll('nav button'))n.onclick=()=>{location.hash=n.dataset.view};
window.addEventListener('hashchange',()=>render(location.hash.slice(1)||'overview'));
const events=new EventSource('/api/events');events.onmessage=e=>{try{const data=JSON.parse(e.data);if(['activity_started','activity_finished'].includes(data.type)&&data.receipt.trigger!=='AUTO')showReceipt(data.receipt)}catch{}};
setInterval(updateCountdowns,1000);
setInterval(async()=>{if(current==='presence'&&!document.hidden){try{const p=await api('/api/presence/status');const node=$('.presence-live');if(node)node.replaceWith(statusCard(p));updateCountdowns()}catch(e){showError(e.message)}}},3000);
setInterval(()=>{if(current==='overview'&&!document.hidden)void render('overview')},10000);
void render(location.hash.slice(1)||'overview');

$('#openDesktop').onclick=async()=>{try{await api('/api/dashboard/open-desktop',{method:'POST'});clearError()}catch(e){showError(e.message)}};
