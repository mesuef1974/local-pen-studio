// One deadline covers response headers, JSON body and retries, not just fetch().
export async function requestJson(path,body,{fetchImpl=globalThis.fetch,timeoutMs=195000,retryDelay=ms=>new Promise(resolve=>setTimeout(resolve,ms))}={}){
 const controller=new AbortController();let timer;
 const timeout=new Promise((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(Error('انتهت مهلة الاتصال بالمعالجة المحلية. استُعيد التحكم بالواجهة؛ قد تستمر العملية على الخادم حتى تنتهي مهلتها.'));},timeoutMs);});
 const work=(async()=>{const payload=JSON.stringify(body);for(let attempt=0;;attempt++){
  if(controller.signal.aborted)throw Error('انتهت مهلة الاتصال.');
  const response=await fetchImpl(path,{method:'POST',headers:{'Content-Type':'application/json'},body:payload,signal:controller.signal});
  let result;try{result=await response.json();}catch(error){if(controller.signal.aborted)throw error;throw Error('وصل رد غير مكتمل من الخادم المحلي. أعد المحاولة.');}
  if(!result||typeof result!=='object')throw Error('رد المعالجة المحلية غير صالح.');
  if(response.status===429&&attempt<4){await retryDelay(Math.min(2000,300*2**attempt));continue;}
  if(!response.ok||result.error)throw Error(result.error||'تعذرت المعالجة المحلية.');return result;
 }})();
 try{return await Promise.race([work,timeout]);}finally{clearTimeout(timer);}
}

export async function waitForJob(id,status,{onProgress=()=>{},onConnection=()=>{},clock=Date.now,sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms)),timeoutMs=1260000}={}){
 const started=clock();
 for(;;){
  if(clock()-started>=timeoutMs)throw Error('انتهت مهلة متابعة التوليد. تحقق من اتصال الخادم المحلي قبل إعادة المحاولة.');
  let state;try{state=await status(id);}catch{onConnection(false);await sleep(3000);continue;}
  onConnection(true);const job=state.job;
  if(!job||job.id!==id)throw Error('تعذر العثور على مهمة التوليد الحالية. أعد المحاولة.');
  onProgress(job);
  if(job.state==='failed')throw Error(job.error||'تعذر توليد الصورة. جرّب دقة أقل.');
  if(job.state==='complete'){if(!job.result?.image)throw Error('اكتمل الطلب دون صورة صالحة.');return job.result;}
  await sleep(1000);
 }
}
