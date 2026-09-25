const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

const html=readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8');
const source=html.slice(html.indexOf('const agendaTypeNames='),html.indexOf('async function setupEmojiDebug()'));

function element(tag='div'){return {tag,textContent:'',className:'',children:[],append(...items){this.children.push(...items)},replaceChildren(){this.children=[]}}}
function flatten(node){return [node,...node.children.flatMap(flatten)]}
function setup(response){
  const agenda=element(),memory=element();
  const context=vm.createContext({
    $:selector=>({'#agendaTimeline':agenda,'#currentCognition':memory})[selector],
    document:{createElement:element},window:{},request:async()=>response,
    Intl,Date,formatTime:value=>value.slice(0,16),displayTimezone:'Asia/Shanghai',
  });
  vm.runInContext(source,context);
  return {context,agenda,memory};
}

test('timeline groups and sorts items, keeps distinct records and a now marker',()=>{
  const s=setup();
  s.context.renderAgendaTimeline([
    {type:'event',title:'下午大会',start_at:'2026-09-24T13:00:00+08:00',status:'planned',note:'观众身份参加'},
    {type:'window',title:'上午宣讲',start_at:'2026-09-24T09:00:00+08:00',end_at:'2026-09-24T10:00:00+08:00',status:'done'},
    {type:'event',title:'作为观众参加下午大会',start_at:'2026-09-24T13:00:00+08:00',status:'planned'},
    {type:'focus',title:'秋招与项目整理',scope:'today',status:'active'},
    {type:'deadline',title:'网申截止',due_at:'2026-09-25T23:59:00+08:00',status:'planned'},
  ],null,new Date('2026-09-24T12:00:00+08:00'));
  const nodes=flatten(s.agenda),titles=nodes.filter(n=>n.className==='agenda-title').map(n=>n.textContent);
  assert.deepEqual(titles,['上午宣讲','下午大会','作为观众参加下午大会','网申截止']);
  assert.equal(nodes.filter(n=>n.className==='agenda-now').length,1);
  assert.ok(nodes.some(n=>n.className==='agenda-focus'));
  assert.ok(nodes.some(n=>n.className.includes('agenda-deadline')));
  assert.ok(nodes.some(n=>n.className.includes('is-past')));
  assert.ok(nodes.some(n=>n.tag==='details'));
  assert.match(nodes.filter(n=>n.className==='agenda-date')[0].textContent,/今天/);
  assert.match(nodes.filter(n=>n.className==='agenda-date')[1].textContent,/明天/);
});

test('same-time event and matching window share one visual node without losing either title',()=>{
  const s=setup();
  s.context.renderAgendaTimeline([
    {id:'event',type:'event',title:'AI+创新产业大会（观众）',start_at:'2026-09-24T13:00:00+08:00',status:'planned'},
    {id:'window',type:'window',title:'作为观众参加 AI+创新产业大会',start_at:'2026-09-24T13:00:00+08:00',end_at:'2026-09-24T18:00:00+08:00',status:'planned'},
    {id:'other',type:'window',title:'不同的活动',start_at:'2026-09-24T13:00:00+08:00',status:'planned'},
  ],null,new Date('2026-09-24T12:00:00+08:00'));
  const nodes=flatten(s.agenda);
  assert.equal(nodes.filter(n=>n.className.includes('agenda-entry ')).length,2);
  assert.ok(nodes.some(n=>n.tag==='p'&&n.textContent==='作为观众参加 AI+创新产业大会'));
  assert.ok(nodes.some(n=>n.className==='agenda-title'&&n.textContent==='不同的活动'));
});

test('current cognition uses one paper, hides absent sections and uses text-only content',async()=>{
  const s=setup({agenda:[],current_cognition:{overview:'最近持续开发 Zhaoxi',sections:{active_context:['秋招'],recent_change:['<script>alert(1)</script>']},updated_at:'2026-09-24T09:00:00+08:00'},errors:{}});
  await s.context.setupRecentContextBoard();
  assert.equal(s.memory.children.length,1);
  const nodes=flatten(s.memory);
  assert.ok(nodes.some(n=>n.className==='memory-overview'&&n.textContent==='最近持续开发 Zhaoxi'));
  assert.ok(nodes.some(n=>n.tag==='li'&&n.textContent==='<script>alert(1)</script>'));
  assert.equal(nodes.filter(n=>n.className==='memory-section').length,2);
  assert.match(html,/Agenda \/ Current Cognition Debug/);
  assert.doesNotMatch(html,/workingNoteCards|Working Notes Context/);
});

test('independent failures and first-run empty state',async()=>{
  const s=setup({agenda:[],current_cognition:{overview:'仍在参与秋招',sections:{}},errors:{agenda:'暂时无法读取。'}});
  await s.context.setupRecentContextBoard();
  assert.match(flatten(s.agenda)[1].textContent,/无法读取/);
  assert.equal(flatten(s.memory).find(n=>n.className==='memory-overview').textContent,'仍在参与秋招');
  s.context.renderCurrentCognition(null,null);
  assert.match(flatten(s.memory).find(n=>n.className==='memory-overview').textContent,/正在形成/);
  s.context.renderCurrentCognition(null,true);
  assert.match(flatten(s.memory)[2].textContent,/无法读取/);
});
