// Run with: node --test tests/web/reply_segments.test.cjs
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const html=readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8');
const source=html.slice(html.indexOf('function splitReply('),html.indexOf('function addMessageBubble('));
const calls=[];
const context=vm.createContext({addMessageBubble:(...args)=>calls.push(args)});
vm.runInContext(source,context);
const split=text=>Array.from(context.splitReply(text));

test('blank lines produce separate paragraphs; single newline is preserved',()=>{
  assert.deepEqual(split('第一段。\n仍是第一段。\n\n第二段！\n\n第三段✨'),['第一段。\n仍是第一段。','第二段！','第三段✨']);
});
test('normalizes Windows newlines and ignores empty paragraphs',()=>{
  assert.deepEqual(split(' \r\n第一段\r\n \t\r\n\r\n第二段\r\n'),['第一段','第二段']);
  assert.deepEqual(split(' \n\n'),[]);
  assert.deepEqual(split(null),[]);
});
test('fenced code retains blank lines, including longer and unclosed fences',()=>{
  for(const fence of ['```','~~~~','````']){
    const code=`${fence}python\na = 1\n\nb = 2\n${fence}`;
    assert.deepEqual(split(`说明\n\n${code}\n\n结束`),['说明',code,'结束']);
  }
  assert.deepEqual(split('```\na\n\nb'),['```\na\n\nb']);
});
test('assistant replies render separately, user and proactive messages stay intact',()=>{
  calls.length=0;
  context.addMessage('assistant','一\n\n二');
  context.addMessage('user','一\n\n二');
  context.addMessage('assistant','一\n\n二','system');
  assert.deepEqual(calls.map(args=>args.slice(0,3)),[['assistant','一',''],['assistant','二',''],['user','一\n\n二',''],['assistant','一\n\n二','system']]);
});
test('formatting and literal HTML are unchanged before safe rendering',()=>{
  assert.deepEqual(split('**你好**\n\n<script>alert(1)</script>'),['**你好**','<script>alert(1)</script>']);
});

test('live replies wait a random 5–10 seconds between bubbles, never before the first',async()=>{
  const scheduled=[], displayed=[];
  const fakeMath=Object.create(Math);
  let random=0;
  fakeMath.random=()=>random;
  const paced=vm.createContext({
    activity:{textContent:''}, Math:fakeMath,
    setTimeout:(callback,delay)=>scheduled.push({callback,delay}),
    addMessageBubble:(...args)=>displayed.push(args),
  });
  vm.runInContext(source,paced);
  const done=paced.sendReply('一\n\n二\n\n三');
  assert.equal(displayed.length,1);
  assert.equal(scheduled[0].delay,5000);
  random=0.999999;
  scheduled[0].callback();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(displayed.length,2);
  assert.equal(scheduled[1].delay,10000);
  scheduled[1].callback();
  await done;
  assert.equal(displayed.length,3);
  assert.equal(scheduled.length,2);
});

test('single-segment live reply has no delay',async()=>{
  const timer=()=>assert.fail('unexpected timer');
  const displayed=[];
  const paced=vm.createContext({setTimeout:timer,addMessageBubble:(...args)=>displayed.push(args)});
  vm.runInContext(source,paced);
  await paced.sendReply('你好');
  assert.equal(displayed.length,1);
});


test('alternating action lines form segments without requiring blank lines',()=>{
 assert.deepEqual(split('（尾巴摇了摇。）\n正文\n（顿了两秒。）\n正文\n（耳朵转了转。）\n正文'),['（尾巴摇了摇。）','正文','（顿了两秒。）','正文','（耳朵转了转。）','正文']);
 assert.equal(context.isActionSegment('我今天用了 VS Code（主要是在改朝汐）。'),false);
 assert.equal(context.isActionSegment('  (nods)  '),true);
 assert.deepEqual(split('```\n（代码内容）\n```'),['```\n（代码内容）\n```']);
});
test('tool-query notice reuses the stage-direction segment renderer',()=>{
 const notice='（提醒：这次没有实际调用工具，回复未经工具核验。）';
 assert.deepEqual(split(`正常回复。\n\n${notice}`),['正常回复。',notice]);
 assert.equal(context.isActionSegment(notice),true);
});
test('degraded-response notices reuse the stage-direction segment renderer',()=>{
 for(const notice of [
  '（提醒：模型服务暂时不可用，这段回复可能不完整；已完成的工具操作已保留。）',
  '（提醒：工具步骤已达到本轮上限，回复可能不完整；已完成的操作已保留。）',
 ]){
  assert.deepEqual(split(`已有结果。\n\n${notice}`),['已有结果。',notice]);
  assert.equal(context.isActionSegment(notice),true);
 }
});
test('one assistant turn shares a group, separate turns never share it',()=>{
 calls.length=0;context.addMessage('assistant','（点头。）\n你好');context.addMessage('assistant','下一轮');
 assert.equal(calls[0][5],calls[1][5]);assert.notEqual(calls[1][5],calls[2][5]);
});
