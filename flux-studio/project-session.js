// One open project: its server revision, and a draft in this browser so a reload loses nothing.
// The unbound work (the store's default key) is never written here; it stays as the backup of an import.
import {toState,fromState} from './project-state.js';

export const draftKey=id=>`project:${id}`;
const fingerprint=snapshot=>JSON.stringify({...snapshot,pendingGeneration:null});

export function createProjectSession({api,store,id}){
 const uploaded=new Map();let revision=0,saved=null;
 return {
  id,title:'',
  // Resolves to {snapshot|null, unsaved, offline?}. useServer() decides when the project changed under an unsaved draft.
  async open({useServer=()=>true}={}){
   const draft=await store.load(draftKey(id));
   let project;
   try{project=await api.project(id);}
   catch(error){
    if(!draft||!(error.status===0||error.status>=500))throw error;
    revision=draft.revision;return {snapshot:draft.snapshot,unsaved:draft.unsaved,offline:true};
   }
   this.title=project.title;
   if(draft&&(draft.revision===project.revision||(draft.unsaved&&!useServer()))){
    revision=draft.revision;saved=draft.unsaved?null:fingerprint(draft.snapshot);
    return {snapshot:draft.snapshot,unsaved:draft.unsaved};
   }
   const snapshot=await fromState(project.state,sha=>api.downloadAsset(sha),uploaded);
   revision=project.revision;saved=snapshot&&fingerprint(snapshot);
   if(draft)await store.clear(draftKey(id));
   return {snapshot,unsaved:false};
  },
  // The page rewrites some values while restoring, so it says what the clean state looks like once applied.
  markClean(snapshot){saved=fingerprint(snapshot);},
  async keep(snapshot){
   const unsaved=fingerprint(snapshot)!==saved;
   await store.save({revision,unsaved,snapshot},draftKey(id));
   return unsaved;
  },
  async push(snapshot){
   const send=async()=>api.saveState(id,revision,await toState(snapshot,(bytes,type)=>api.uploadAsset(bytes,type),uploaded));
   let project;
   // The remembered uploads can be another account's after signing in again: send the images once more.
   try{project=await send();}catch(error){if(error.code!=='unknown_asset')throw error;uploaded.clear();project=await send();}
   revision=project.revision;saved=fingerprint(snapshot);
  },
 };
}

// Copy the unbound work into a new project, once per account. Safe to repeat after a failure.
// `existing` lists the account's project ids, so an import that was deleted since can be made again.
export async function importWork({api,store,userId,title,existing}){
 const snapshot=await store.load();
 if(snapshot?.version!==1)throw Error('لا يوجد عمل محفوظ في هذا المتصفح.');
 const key=`import:${userId}`;let record=await store.load(key);
 if(record?.projectId&&(!existing||existing.includes(record.projectId)))return record.projectId;
 record={clientKey:record?.clientKey??crypto.randomUUID()};
 await store.save(record,key);
 let project;
 try{project=await api.createProject(title,record.clientKey);}
 catch(error){
  if(error.code!=='project_deleted')throw error;
  record={clientKey:crypto.randomUUID()};await store.save(record,key);
  project=await api.createProject(title,record.clientKey);
 }
 // A revision above zero means an earlier attempt was saved and only its reply was lost.
 if(project.revision===0)await api.saveState(project.id,0,await toState(snapshot,(bytes,type)=>api.uploadAsset(bytes,type)));
 await store.save({...record,projectId:project.id},key);
 return project.id;
}
