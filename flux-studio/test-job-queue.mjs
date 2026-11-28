import test from 'node:test';
import assert from 'node:assert/strict';
import {createJobQueue,WAITING_AFTER_MS} from './job-queue.js';
import {waitForJob} from './api-client.js';

const PNG='data:image/png;base64,iVBORw0KGgo=';
const record=(fields={})=>({id:'j1',status:'queued',step:0,total:0,phase:'',error:'',result:null,result_meta:{},cancel_requested:false,...fields});

test('submit uploads each image once and sends references, not bytes',async()=>{
 const sent=[],uploads=[];
 const queue=createJobQueue({newKey:()=>'key',projectId:()=>'p1',api:{
  uploadAsset:async(bytes,type)=>{uploads.push(type);return 'a'.repeat(64);},
  createJob:async body=>{sent.push(body);return record();}}});
 assert.deepEqual(await queue.submit({mode:'multi',image:PNG,references:[{image:PNG,role:'style'}]}),{job:'j1'});
 await queue.submit({mode:'generate',image:null,prompt:'x'});
 const ref=`asset:${'a'.repeat(64)}`;
 assert.deepEqual(uploads,['image/png']);
 assert.deepEqual(sent[0],{idempotency_key:'key',project_id:'p1',inputs:{mode:'multi',image:ref,references:[{image:ref,role:'style'}]}});
 assert.deepEqual(sent[1].inputs,{mode:'generate',prompt:'x'});
});

test('a job is followed to its image',async()=>{
 const states=[record(),record({status:'running',phase:'model'}),record({status:'running',step:2,total:4}),record({status:'succeeded',result:'sha',result_meta:{width:1,seed:7}})];
 const seen=[];
 const queue=createJobQueue({api:{job:async()=>states.shift(),downloadAsset:async()=>({bytes:Uint8Array.of(1,2).buffer,type:'image/png'})}});
 const result=await waitForJob('j1',queue.status,{onProgress:job=>seen.push(job.state),sleep:async()=>{}});
 assert.deepEqual(seen,['queued','loading','running','complete']);
 assert.deepEqual(result,{width:1,seed:7,image:'data:image/png;base64,AQI='});
});

test('a long queue says so, and an unknown job stops the wait',async()=>{
 let now=0;
 const queue=createJobQueue({clock:()=>now,api:{job:async id=>{if(id==='gone')throw Object.assign(Error('x'),{status:404});return record();}}});
 assert.equal((await queue.status('j1')).job.waiting,false);
 now=WAITING_AFTER_MS;
 assert.equal((await queue.status('j1')).job.waiting,true);
 assert.deepEqual(await queue.status('gone'),{job:null});
});

test('cancel reports whether the server took it',async()=>{
 let answer=record({status:'cancelled'});
 const queue=createJobQueue({api:{cancelJob:async()=>answer}});
 assert.deepEqual(await queue.cancel('j1'),{cancelled:true});
 answer=record({status:'succeeded'});
 assert.deepEqual(await queue.cancel('j1'),{cancelled:false});
});
