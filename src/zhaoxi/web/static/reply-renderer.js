// Reply grouping, segmentation and pacing. DOM construction is supplied by shell.js.
function splitReply(content){
  const segments=[], lines=String(content??'').replace(/\r\n?/g,'\n').split('\n');
  let paragraph=[], fence=null;
  const flush=()=>{const text=paragraph.join('\n').trim();if(text)segments.push(text);paragraph=[]};
  for(const line of lines){
    const marker=line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/);
    if(marker){
      if(!fence)fence={char:marker[1][0],length:marker[1].length};
      else if(marker[1][0]===fence.char&&marker[1].length>=fence.length&&!marker[2].trim())fence=null;
      paragraph.push(line);
    }else if(!fence&&isActionSegment(line)){flush();segments.push(line.trim())}
    else if(!fence&&!line.trim())flush();
    else paragraph.push(line);
  }
  flush();return segments;
}
function isActionSegment(text){
  const value=String(text??'').trim();
  return /^(（[^\r\n]*）|\([^\r\n]*\))$/.test(value);
}
let currentReplyDisplayGroup=null;
function replyDisplayGroup(message){
  const key=message.role==='assistant'&&message.kind!=='system'?message.reply_group_id:null;
  if(!key){currentReplyDisplayGroup=null;return null}
  if(currentReplyDisplayGroup?.key!==key)currentReplyDisplayGroup={key};
  return currentReplyDisplayGroup;
}
function addMessage(role,content,kind='',images=[],timestamp=null,messageId=null,regeneratable=false,debugOnly=true,replyGroup=null,reference=null){
  const splitParts=role==='assistant'&&kind!=='system'?splitReply(content):[content];
  const parts=splitParts.length?splitParts:(images.length?['']:[]);
  const group=role==='assistant'&&kind!=='system'?(replyGroup||{}):null;
  if(group&&regeneratable&&messageId)document.querySelectorAll('.regenerate').forEach(item=>item.remove());
  const rows=parts.map(part=>addMessageBubble(role,part,kind,images,timestamp,group));
  for(const row of rows){if(messageId)row.dataset.messageId=messageId;if(reference)window.MessageTools?.attachReference(row,reference)}
  if(group&&regeneratable)attachRegenerate(group,messageId,debugOnly);
  return rows;
}
// New replies are paced across the whole visible response; session restoration
// continues to use addMessage directly and never replays delays.
function waitReplySegment(pacing){
  let waiting=null;
  if(pacing.shown>0){
    const base=typeof replyIntervalMs==='undefined'?5000:replyIntervalMs;
    if(base>0){
      activity.textContent='整理 · 我慢慢把话说完呀…';
      waiting=new Promise(resolve=>setTimeout(resolve,base+Math.floor(Math.random()*(base+1))));
    }
  }
  pacing.shown+=1;
  return waiting;
}
async function sendReply(content,timestamp=null,messageId=null,regeneratable=true,pacing=null,replyGroup=null){
  const parts=splitReply(content),group=replyGroup||{},sequence=pacing||{shown:0};
  if(regeneratable&&messageId)document.querySelectorAll('.regenerate').forEach(item=>item.remove());
  for(const part of parts){
    const waiting=waitReplySegment(sequence);if(waiting)await waiting;
    const row=addMessageBubble('assistant',part,'',[],timestamp,group);
    if(messageId)row.dataset.messageId=messageId;
  }
  if(regeneratable&&messageId)attachRegenerate(group,messageId,true);
  return group.element;
}
async function renderResponse(data){
  const output=data.output_messages||[];
  if(!output.length)return sendReply(data.content,data.timestamp,data.message_id);
  const pacing={shown:0};let last=null;
  for(const item of output)last=await renderMessage(item,{paced:true,latestMessageId:data.message_id,pacing});
  if(output.some(item=>item.source==='emoji'))void acknowledgeEmojiTrace(data.trace_id,true);
  return last;
}
function renderUserParts(message){
  let offset=0,first=null;
  for(const [index,part] of message.display_parts.entries()){
    const reference=part.reference?(message.references||[]).find(r=>r.message_id===part.reference.message_id&&r.part_index===part.reference.part_index):null;
    const rows=addMessage('user',part.text,'',(message.images||[]).slice(offset,offset+part.image_count),part.timestamp,message.message_id,false,true,null,reference);
    rows.forEach(row=>row.dataset.messagePartIndex=index);first=first||rows[0];offset+=part.image_count;
  }
  return first;
}
async function renderMessage(message,{paced=false,latestMessageId=null,pacing=null}={}){
  if(message.role==='user'&&message.display_parts?.length)return renderUserParts(message);
  const content=message.text??message.content??'',images=message.images||[],id=message.id||message.message_id||null;
  const group=replyDisplayGroup(message);
  if(id&&message.kind!=='system'&&['user','assistant'].includes(message.role))document.querySelectorAll('.regenerate').forEach(item=>item.remove());
  if(paced&&message.role==='assistant'){
    if(content.trim())return sendReply(content,message.timestamp,id,id===latestMessageId,pacing,group);
    const waiting=waitReplySegment(pacing||{shown:0});if(waiting)await waiting;
  }
  return addMessage(message.role,content,message.kind==='system'?'system':'',images,message.timestamp,id,paced?!!id&&id===latestMessageId:!!message.regeneratable,true,group,message.references?.[0])[0]||null;
}
