const {chromium}=require(process.env.ZHAOXI_PLAYWRIGHT||'playwright');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});
try{const page=await browser.newPage(),errors=[],checks=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(process.env.ZHAOXI_TEST_BASE_URL||'http://127.0.0.1:18768/');
 await page.locator('.bubble').filter({hasText:'after original'}).waitFor();
 assert.equal(await page.locator('.message-group').count(),1);
 assert.equal(await page.locator('.message-group .row').count(),2);checks.push('saved unresolved emoji text shares one reply group');
 await page.evaluate(()=>{renderNormalRegeneration(true);replyIntervalMs=0});
 await page.locator('.normal-regenerate').click();
 await page.locator('.bubble').filter({hasText:'after retry 1'}).waitFor();
 await page.locator('.bubble').filter({hasText:'last paragraph'}).waitFor();
 assert.equal(await page.locator('.bubble').filter({hasText:'before original'}).count(),0);
 assert.equal(await page.locator('.message-group').count(),1);
 assert.equal(await page.locator('.message-group .row').count(),4);
 assert.equal(await page.locator('.message-group .regenerate').count(),1);checks.push('regeneration replaces whole text emoji text response');
 await page.reload();await page.locator('.bubble').filter({hasText:'last paragraph'}).waitFor();
 assert.equal(await page.locator('.message-group').count(),1);
 assert.equal(await page.locator('.message-group .row').count(),4);checks.push('reload preserves group and image ordering');
 await page.evaluate(async()=>{messages.replaceChildren();await renderResponse({message_id:'last-image',output_messages:[
   {role:'assistant',text:'image-final fixture',id:'before-image',reply_group_id:'image-final'},
   {role:'assistant',text:'',images:['/api/expression/emoji/fixture'],id:'last-image',reply_group_id:'image-final'},
 ]})});
 assert.equal(await page.locator('.message-group').count(),1);
 assert.equal(await page.locator('.message-group .regenerate').count(),1);checks.push('image-only tail has whole-reply retry button');
 assert.deepEqual(errors,[]);checks.push('no browser script errors');
 const output=process.env.ZHAOXI_TEST_OUTPUT||'.pytest_cache/reply-group-browser-acceptance.json';fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify({checks,errors},null,2));console.log(JSON.stringify({checks,errors}));
}finally{await browser.close()}})().catch(e=>{console.error(e);process.exitCode=1});
