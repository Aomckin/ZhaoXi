const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../../src/zhaoxi/web/static/index.html'),'utf8');
const source=html.slice(html.indexOf('function receiveDelivery('),html.indexOf('let replyIntervalMs='));
test('live proactive replies use normal reply queue and deduplicate restored deliveries',async()=>{
 const sent=[],notices=[];
 const c=vm.createContext({seenDeliveries:new Set(['old']),deliveryQueue:[],historyReady:true,busy:true,pendingInput:[],$:()=>({}),showNotice:d=>notices.push(d),sendReply:async(text)=>sent.push(text),finishTurn:()=>{c.busy=false}});
 vm.runInContext(source,c);
 const d={delivery_id:'new',status:'delivered',content:'hello'};
 c.receiveDelivery(d);c.receiveDelivery(d);c.receiveDelivery({...d,delivery_id:'old'});
 assert.equal(sent.length,0);assert.equal(c.deliveryQueue.length,1);
 c.busy=false;await c.drainDeliveries();assert.deepEqual(sent,['hello']);
 c.receiveDelivery(d);assert.equal(sent.length,1);
 c.receiveDelivery({...d,delivery_id:'sys',event_type:'system.warning'});assert.equal(notices.length,1);
});
test('sidebar suggestions and system messages have native collapse controls',()=>{
 assert.match(html,/<details open><summary>可以这样找我<\/summary>/);
 assert.match(html,/<details open><summary>系统消息<\/summary>/);
 assert.doesNotMatch(html,/class="badge">主动消息/);
});
