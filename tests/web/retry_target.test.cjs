const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../src/zhaoxi/web/static/shell.js'),'utf8');
const code=source.slice(source.indexOf('function addRetryableError('),source.indexOf('function recallInput('));
async function bindings(messages){
  const calls=[];
  const context={addMessage:()=>[{parentElement:{}}],request:async()=>({messages}),
    attachRegenerate:(_group,id,debug)=>calls.push({id,debug})};
  vm.createContext(context);vm.runInContext(code,context);
  context.addRetryableError('fixture HTTP 400','current-request');
  await new Promise(resolve=>setImmediate(resolve));return calls;
}
test('failed bubble targets its accepted request instead of trailing heartbeat',async()=>{
 assert.deepEqual(await bindings([
  {role:'user',message_id:'current-user',request_id:'current-request'},
  {role:'assistant',message_id:'beat',delivery_id:'beat-fixture'},
 ]),[{id:'current-user',debug:false}]);
});
test('missing failed request never binds an older user or assistant',async()=>{
 assert.deepEqual(await bindings([
  {role:'user',message_id:'old-user',request_id:'old-request'},
  {role:'assistant',message_id:'beat',delivery_id:'beat-fixture'},
 ]),[]);
});
