// Generation through the account server's job record; the job worker runs it. Speaks the shape waitForJob reads.
import {decode,encode} from './project-state.js';

const STATES={succeeded:'complete',failed:'failed',cancelled:'cancelled'};
export const WAITING_AFTER_MS=15000;

export function createJobQueue({api,projectId=()=>null,newKey=()=>crypto.randomUUID(),clock=Date.now}){
 const uploaded=new Map(),queuedSince=new Map();
 const reference=async url=>{
  if(!uploaded.has(url)){const {bytes,type}=decode(url);uploaded.set(url,await api.uploadAsset(bytes,type));}
  return `asset:${uploaded.get(url)}`;
 };
 return {
  async submit(payload){
   const inputs={...payload};
   if(inputs.image)inputs.image=await reference(inputs.image);else delete inputs.image;
   if(inputs.references){const list=[];for(const item of inputs.references)list.push({...item,image:await reference(item.image)});inputs.references=list;}
   const job=await api.createJob({inputs,idempotency_key:newKey(),project_id:projectId()||null});
   return {job:job.id};
  },
  async status(id){
   let job;
   // A job this account cannot see will never finish; anything else is retried by the caller.
   try{job=await api.job(id);}
   catch(error){if(error.status===404||error.status===422)return {job:null};if(error.status===401)return {job:{id,state:'failed',error:'انتهت الجلسة. سجّل الدخول من «مشاريعي»؛ الطلب محفوظ في سجل التوليد.'}};throw error;}
   const state=STATES[job.status]??(job.status==='queued'?'queued':job.total>0?'running':'loading');
   if(state!=='queued')queuedSince.delete(id);else if(!queuedSince.has(id))queuedSince.set(id,clock());
   const view={id,state,step:job.step,total:job.total,phase:job.phase,error:job.error,waiting:state==='queued'&&clock()-queuedSince.get(id)>=WAITING_AFTER_MS};
   if(state==='complete')view.result={...job.result_meta,image:encode(await api.downloadAsset(job.result))};
   return {job:view};
  },
  async cancel(id){
   const job=await api.cancelJob(id);
   return {cancelled:job.cancel_requested||job.status==='cancelled'};
  },
 };
}
