import test from 'node:test';
import assert from 'node:assert/strict';
import {createApi,ApiError} from './account-api.js';

const reply=(status,data)=>({status,ok:status<300,json:async()=>{if(data===undefined)throw Error('empty');return data;}});
const fake=(...replies)=>{const calls=[];return {calls,api:createApi(async(path,options)=>{calls.push({path,options});return replies.shift();})};};

test('a write fetches a fresh CSRF token and sends it',async()=>{
 const {api,calls}=fake(reply(200,{csrf_token:'t'}),reply(201,{id:'p'}));
 assert.deepEqual(await api.createProject('x','k'),{id:'p'});
 assert.equal(calls[0].path,'/api/auth/csrf');
 assert.equal(calls[1].options.headers['X-CSRFToken'],'t');
 assert.deepEqual(JSON.parse(calls[1].options.body),{title:'x',client_key:'k'});
});

test('204 is an empty success and ids cannot add path segments',async()=>{
 const {api,calls}=fake(reply(200,{csrf_token:'t'}),reply(204));
 assert.equal(await api.deleteProject('a/b'),null);
 assert.equal(calls[1].path,'/api/projects/a%2Fb/delete');
});

test('server errors keep status, code and a readable message',async()=>{
 for(const [body,message] of [[{detail:'رسالة',code:'c'},'رسالة'],[{detail:[{msg:'x'}]},'تعذر تنفيذ الطلب.'],[{error:'مرفوض'},'مرفوض']]){
  const {api}=fake(reply(400,body));
  await assert.rejects(api.me(),error=>error instanceof ApiError&&error.status===400&&error.message===message);
 }
 await assert.rejects(fake(reply(502)).api.me(),{code:'bad_reply'});
 await assert.rejects(createApi(async()=>{throw Error('down');}).me(),{code:'offline'});
});
