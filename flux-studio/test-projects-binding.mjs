import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {toState,fromState} from './project-state.js';
import {createProjectSession,importWork,draftKey} from './project-session.js';

const png='data:image/png;base64,'+Buffer.from('\x89PNG-one').toString('base64');
const jpg='data:image/jpeg;base64,'+Buffer.from('jpeg-two').toString('base64');
const sample=()=>({version:1,flow:{source:png,original:jpg,outputs:[{image:png},null,null]},candidate:{requestKey:JSON.stringify({references:[{image:jpg,role:'x'}]})},pendingGeneration:{job:'1',source:png},fields:[['genPrompt','حصان']]});

function fakeServer(){
 const assets=new Map(),projects=new Map(),keys=new Map(),calls=[];let next=0;
 const fail=(status,code)=>{throw Object.assign(Error(code),{status,code});};
 return {assets,projects,calls,
  uploadAsset:async(bytes,type)=>{const sha=createHash('sha256').update(bytes).digest('hex');calls.push('upload');assets.set(sha,{bytes,type});return sha;},
  downloadAsset:async sha=>assets.get(sha)??fail(404,'not_found'),
  createProject:async(title,key)=>{if(keys.has(key)){const p=projects.get(keys.get(key));return p?{...p}:fail(409,'project_deleted');}const p={id:`p${++next}`,title,revision:0,state:{}};projects.set(p.id,p);keys.set(key,p.id);return {...p};},
  project:async id=>projects.has(id)?structuredClone(projects.get(id)):fail(404,'not_found'),
  saveState:async(id,revision,state)=>{const p=projects.get(id);assert.ok(!JSON.stringify(state).includes('data:image/'));if(revision!==p.revision)fail(409,'stale_revision');p.state=structuredClone(state);p.revision++;return {...p};},
 };
}
function fakeStore(){const data=new Map();return {data,load:async(key='current')=>structuredClone(data.get(key)),save:async(value,key='current')=>{data.set(key,structuredClone(value));},clear:async(key='current')=>{data.delete(key);}};}

test('a snapshot becomes a state without inline images and comes back byte for byte',async()=>{
 const server=fakeServer(),snapshot=sample();
 const state=await toState(snapshot,server.uploadAsset);
 assert.ok(!JSON.stringify(state).includes('data:image/'));
 assert.equal(server.calls.length,2,'each distinct image is uploaded once');
 assert.equal(state.pendingGeneration,null);
 assert.equal(snapshot.flow.source,png,'the input is not modified');
 assert.deepEqual(await fromState(state,server.downloadAsset),{...snapshot,pendingGeneration:null});
});

test('a new project has no snapshot, and an image the server cannot take is refused',async()=>{
 assert.equal(await fromState({},async()=>assert.fail()),null);
 await assert.rejects(toState({version:1,a:'data:image/svg+xml,<svg/>'},fakeServer().uploadAsset),/PNG/);
});

test('save then open elsewhere gives the same work; an unsaved draft survives a reload',async()=>{
 const api=fakeServer(),store=fakeStore(),{id}=await api.createProject('a','k');
 const first=createProjectSession({api,store,id});
 assert.equal((await first.open()).snapshot,null);
 await first.push(sample());
 assert.equal(await first.keep(sample()),false);
 const other=createProjectSession({api,store:fakeStore(),id});
 assert.equal((await other.open()).snapshot.flow.source,png);
 const edited={...sample(),fields:[['genPrompt','جمل']]};
 assert.equal(await first.keep(edited),true);
 const reload=await createProjectSession({api,store,id}).open();
 assert.deepEqual([reload.unsaved,reload.snapshot.fields[0][1]],[true,'جمل']);
 assert.equal(store.data.has('current'),false,'the unbound work is never touched');
});

test('when the project moved on, the user chooses; a stale draft cannot overwrite it',async()=>{
 const api=fakeServer(),store=fakeStore(),{id}=await api.createProject('a','k');
 await api.saveState(id,0,{version:1,from:'server'});
 const draft={revision:0,unsaved:true,snapshot:{version:1,from:'draft'}};
 await store.save(draft,draftKey(id));
 const mine=createProjectSession({api,store,id});
 assert.equal((await mine.open({useServer:()=>false})).snapshot.from,'draft');
 await assert.rejects(mine.push(draft.snapshot),{code:'stale_revision'});
 assert.equal((await createProjectSession({api,store,id}).open({useServer:()=>true})).snapshot.from,'server');
});

test('with the account server away the draft opens; a deleted project does not',async()=>{
 const store=fakeStore();await store.save({revision:1,unsaved:true,snapshot:{version:1}},draftKey('x'));
 const failing=(status,code)=>({project:async()=>{throw Object.assign(Error(code),{status,code});}});
 assert.equal((await createProjectSession({api:failing(503,'accounts_unavailable'),store,id:'x'}).open()).offline,true);
 await assert.rejects(createProjectSession({api:failing(404,'not_found'),store,id:'x'}).open(),{code:'not_found'});
});

test('the browser work is imported once and stays in the browser',async()=>{
 const api=fakeServer(),store=fakeStore();await store.save(sample());
 const args={api,store,userId:7,title:'عملي'};
 const lost={...args,api:{...api,saveState:async()=>{throw Error('offline');}}};
 await assert.rejects(importWork(lost));
 const id=await importWork(args);
 assert.equal(await importWork(args),id);
 assert.equal(api.projects.size,1);
 assert.equal(api.projects.get(id).revision,1);
 assert.deepEqual(await store.load(),sample());
 api.projects.delete(id);
 assert.notEqual(await importWork({...args,existing:[]}),id,'a deleted import can be made again');
});
