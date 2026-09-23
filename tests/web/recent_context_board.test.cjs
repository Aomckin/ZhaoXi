const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');

const html=readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8');
const source=html.slice(html.indexOf('const agendaTypeNames='),html.indexOf('async function setupEmojiDebug()'));

function element(){return {textContent:'',className:'',children:[],append(...items){this.children.push(...items)},replaceChildren(){this.children=[]}}}
function setup(response){
  const agenda=element(),notes=element();
  const context=vm.createContext({
    $:selector=>({'#agendaCards':agenda,'#workingNoteCards':notes})[selector],
    document:{createElement:element},window:{},request:async()=>response,
    formatTime:date=>date.slice(0,16),
  });
  vm.runInContext(source,context);
  return {context,agenda,notes};
}

test('sidebar renders Agenda and Working Notes as separate paper cards with text-only content',async()=>{
  const s=setup({agenda:[{type:'deadline',title:'下午交稿',due_at:'2026-09-23T16:00:00',status:'planned'}],working_notes:[{type:'hypothesis',topic:'进度',content:'<script>alert(1)</script>',confidence:'tentative'}],errors:{}});
  await s.context.setupRecentContextBoard();
  assert.equal(s.agenda.children[0].children[1].textContent,'下午交稿');
  assert.match(s.agenda.children[0].children[2].textContent,/2026-09-23T16:00/);
  assert.equal(s.notes.children[0].children[1].textContent,'<script>alert(1)</script>');
  assert.match(s.notes.children[0].children[2].textContent,/暂定/);
  assert.match(html,/id="emojiDebugPanel"[^>]*><summary>表情包系统 Debug/);
  assert.match(html,/id="recentContextDebugPanel"[^>]*><summary>Agenda \/ Working Notes Debug/);
});

test('one failed module does not hide the other sidebar cards',async()=>{
  const s=setup({agenda:[],working_notes:[{type:'todo',topic:'写提纲',content:'列三点',confidence:'working'}],errors:{agenda:'暂时无法读取。'}});
  await s.context.setupRecentContextBoard();
  assert.match(s.agenda.children[0].children[0].textContent,/稍后/);
  assert.equal(s.notes.children[0].children[1].textContent,'列三点');
});
