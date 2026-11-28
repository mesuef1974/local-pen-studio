// Django's double-submit token: the readable cookie set at sign-in, echoed in a header.
export function csrfHeader(cookies=globalThis.document?.cookie??''){
 const token=/(?:^|;\s*)masar_csrftoken=([A-Za-z0-9]+)/.exec(cookies)?.[1];
 return token?{'X-CSRFToken':token}:{};
}

// One deadline covers response headers, JSON body and retries, not just fetch().
export async function requestJson(path,body,{fetchImpl=globalThis.fetch,timeoutMs=195000,retryDelay=ms=>new Promise(resolve=>setTimeout(resolve,ms))}={}){
 const controller=new AbortController();let timer;
 const timeout=new Promise((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(Error('انتهت مهلة الاتصال بالمعالجة المحلية. استُعيد التحكم بالواجهة؛ قد تستمر العملية على الخادم حتى تنتهي مهلتها.'));},timeoutMs);});
 const work=(async()=>{const payload=JSON.stringify(body);for(let attempt=0;;attempt++){
  if(controller.signal.aborted)throw Error('انتهت مهلة الاتصال.');
  const response=await fetchImpl(path,{method:'POST',headers:{'Content-Type':'application/json',...csrfHeader()},body:payload,signal:controller.signal});
  let result;try{result=await response.json();}catch(error){if(controller.signal.aborted)throw error;throw Error('وصل رد غير مكتمل من الخادم المحلي. أعد المحاولة.',{cause:error});}
  if(!result||typeof result!=='object')throw Error('رد المعالجة المحلية غير صالح.');
  if(response.status===429&&attempt<4){await retryDelay(Math.min(2000,300*2**attempt));continue;}
  if(!response.ok||result.error)throw Error(result.error||'تعذرت المعالجة المحلية.');return result;
 }})();
 try{return await Promise.race([work,timeout]);}finally{clearTimeout(timer);}
}

// What the local worker is doing right now, from the phase the server reports. No invented progress.
export function phaseText(job){
 if(!job)return 'توليد الصورة على جهازك';
 if(job.cancelling)return 'جارٍ إلغاء التوليد…';
 if(job.state==='running'&&job.total>0)return job.step>0?`الرسم · الخطوة ${job.step} من ${job.total}`:'بدء الرسم…';
 if(job.phase==='model')return 'تحميل النموذج إلى الذاكرة · أول طلب يأخذ نحو نصف دقيقة';
 if(job.phase==='prompt')return 'قراءة الوصف وتجهيز الصور…';
 if(job.state==='queued'&&job.waiting)return 'ما زال الطلب في الطابور · تأكد أن عامل التوليد يعمل (start-masar.ps1)';
 return job.state==='queued'?'الطلب في طابور التوليد…':'تجهيز التوليد على جهازك…';
}

export async function waitForJob(id,status,{onProgress=()=>{},onConnection=()=>{},clock=Date.now,sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms)),timeoutMs=1260000}={}){
 const started=clock();
 for(;;){
  if(clock()-started>=timeoutMs)throw Error('انتهت مهلة متابعة التوليد. تحقق من اتصال الخادم المحلي قبل إعادة المحاولة.');
  let state;try{state=await status(id);}catch{onConnection(false);await sleep(3000);continue;}
  onConnection(true);const job=state.job;
  if(!job||job.id!==id)throw Error('تعذر العثور على مهمة التوليد الحالية. أعد المحاولة.');
  onProgress(job);
  if(job.state==='cancelled'){const stopped=Error('أُلغي التوليد.');stopped.cancelled=true;throw stopped;}
  if(job.state==='failed')throw Error(job.error||'تعذر توليد الصورة. جرّب دقة أقل.');
  if(job.state==='complete'){if(!job.result?.image)throw Error('اكتمل الطلب دون صورة صالحة.');return job.result;}
  await sleep(1000);
 }
}
