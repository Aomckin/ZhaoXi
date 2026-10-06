const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const shell=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/shell.js'),'utf8');
const source=shell.slice(shell.indexOf('async function setupDiagnostics()'),shell.indexOf('async function ',shell.indexOf('async function setupDiagnostics()')+1));
function setup(startup){
 const connection={textContent:''},messages=[];
 const context=vm.createContext({
  request:async()=>({startup}),debug:{},input:{},setupNoticeShown:false,
  $:()=>connection,document:{querySelector:()=>null},
  renderInteractionBadge:()=>{},renderPresenceActivity:()=>{},renderDebugPresenceControls:()=>{},
  addMessage:(role,text)=>messages.push(text),
 });
 vm.runInContext(source,context);
 return {context,connection,messages};
}
test('configured model does not hide Core initialization failure',async()=>{
 const s=setup({status:'blocked',checks:{model:{ok:true},runtime:{message:'数据健康检查失败：internal_activity'}}});
 await s.context.setupDiagnostics();
 assert.equal(s.connection.textContent,'Core 启动失败');
 assert.match(s.messages[0],/internal_activity/);
 await s.context.setupDiagnostics();
 assert.equal(s.messages.length,1);
});
test('first-run setup and healthy Core have distinct status',async()=>{
 const s=setup({status:'needs_configuration',checks:{model:{action:'填写 API Key'}}});
 await s.context.setupDiagnostics();
 assert.equal(s.connection.textContent,'需要完成首次配置');
 assert.match(s.messages[0],/填写 API Key/);
 const ready=setup(null);
 await ready.context.setupDiagnostics();
 assert.equal(ready.connection.textContent,'本地 Core 已连接');
 assert.equal(ready.messages.length,0);
});
