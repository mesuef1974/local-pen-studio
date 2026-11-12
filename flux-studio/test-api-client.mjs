import test from 'node:test';
import assert from 'node:assert/strict';
import {requestJson,waitForJob,phaseText} from './api-client.js';
test('a cancelled job ends the wait with a marked error, never a result',async()=>{
 await assert.rejects(waitForJob('a',async()=>({job:{id:'a',state:'cancelled',result:{image:'late'}}})),error=>error.cancelled===true&&/أُلغي/.test(error.message));
});
test('phase text follows the reported phase and never invents steps',()=>{
 assert.match(phaseText({state:'queued',step:0,total:0}),/إرسال/);
 assert.match(phaseText({state:'loading',phase:'model'}),/تحميل النموذج/);
 assert.match(phaseText({state:'loading',phase:'prompt'}),/الوصف/);
 assert.match(phaseText({state:'running',phase:'draw',step:0,total:4}),/بدء الرسم/);
 assert.match(phaseText({state:'running',phase:'draw',step:3,total:4}),/3 من 4/);
 assert.match(phaseText({state:'running',step:3,total:4,cancelling:true}),/إلغاء/);
 assert.doesNotMatch(phaseText({state:'loading'}),/\d/);
 assert.ok(phaseText(null));
});
const response=(result,status=200)=>({status,ok:status===200,json:async()=>result});
test('successful request retains payload and returns result',async()=>{
 let seen;const result=await requestJson('/api/background',{image:'test'},{fetchImpl:async(path,options)=>{seen={path,options};return response({image:'cutout'});}});
 assert.equal(result.image,'cutout');assert.equal(seen.path,'/api/background');assert.deepEqual(JSON.parse(seen.options.body),{image:'test'});assert.ok(seen.options.signal);
});
test('unresponsive connection cannot leave caller pending indefinitely',async()=>{
 let signal;await assert.rejects(requestJson('/api/background',{}, {timeoutMs:15,fetchImpl:async(_,options)=>{signal=options.signal;return new Promise(()=>{});}}),/مهلة/);assert.equal(signal.aborted,true);
});
test('deadline also covers an unresponsive response body',async()=>{
 await assert.rejects(requestJson('/api/prepare',{}, {timeoutMs:15,fetchImpl:async()=>({ok:true,status:200,json:()=>new Promise(()=>{})})}),/مهلة/);
});
test('busy retries are bounded and server error remains visible',async()=>{
 let count=0;await assert.rejects(requestJson('/api/background',{}, {fetchImpl:async()=>{count++;return response({error:'هناك معالجة أخرى'},429);},retryDelay:async()=>{}}),/معالجة أخرى/);assert.equal(count,5);
});
test('invalid JSON yields actionable failure and following request can succeed',async()=>{
 await assert.rejects(requestJson('/api/background',{}, {fetchImpl:async()=>({json:async()=>{throw Error('invalid');}})}),/غير مكتمل/);
 assert.deepEqual(await requestJson('/api/background',{}, {fetchImpl:async()=>response({image:'ready'})}),{image:'ready'});
});
test('generation polling reconnects without mixing jobs or inventing progress',async()=>{
 let now=0,calls=0;const connection=[],steps=[];
 const result=await waitForJob('a',async()=>{calls++;if(calls===1)throw Error('offline');return {job:{id:'a',state:calls===2?'running':'complete',step:calls===2?1:4,result:{image:'raw'}}};},{clock:()=>now,sleep:async ms=>{now+=ms;},onConnection:v=>connection.push(v),onProgress:j=>steps.push(j.step)});
 assert.equal(result.image,'raw');assert.deepEqual(connection,[false,true,true]);assert.deepEqual(steps,[1,4]);
});
test('continuous generation disconnects and stuck running jobs have a finite deadline',async()=>{
 for(const offline of [true,false]){let now=0;await assert.rejects(waitForJob('a',async()=>{if(offline)throw Error('offline');return {job:{id:'a',state:'loading'}};},{timeoutMs:4000,clock:()=>now,sleep:async ms=>{now+=ms;}}),/مهلة/);}
});
test('failed, missing and incomplete generation results cannot be approved',async()=>{
 for(const job of [null,{id:'other',state:'complete',result:{image:'wrong'}},{id:'a',state:'failed',error:'GPU failed'},{id:'a',state:'complete',result:{}}])await assert.rejects(waitForJob('a',async()=>({job})));
});
